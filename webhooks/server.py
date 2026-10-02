"""HTTP front for receive(). The response never includes the raw body.

With POSTGRES_HOST set, a matching post calls webhook_store. Without
that host the event stays in memory. A database error is the reason
postgres and the body is not repeated. GET /announcements returns the
fixed sentences when Friday-Notify matches. It does not return the
body. The process does not call Friday, does not call the executor,
and does not write an approval. An empty secret rejects every
header, which is the state before any guest app exists.
"""

from __future__ import annotations

import hmac
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from webhooks.queue import PostgresQueue, QueueError
from webhooks.receiver import HEADER, MAX_BODY, MemoryStore, announcements, receive

ROUTES = {"/media": "media", "/arr": "arr"}
STATUSES = {
    "stored": 200,
    "already_stored": 200,
    "header_rejected": 403,
    "ambiguous_secret": 403,
    "method_refused": 405,
    "unknown_route": 404,
    "body_too_large": 413,
    "postgres": 503,
}


def secrets_from_env() -> dict[str, str]:
    return {
        "jellyfin": os.environ.get("WEBHOOK_SECRET_JELLYFIN", ""),
        "radarr": os.environ.get("WEBHOOK_SECRET_RADARR", ""),
        "sonarr": os.environ.get("WEBHOOK_SECRET_SONARR", ""),
    }


def serve(
    store: MemoryStore,
    secrets: dict[str, str],
    host: str,
    port: int,
    notify_token: str = "",
) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args) -> None:
            return

        def do_GET(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0]
            if path == "/health":
                self._send(200, {"outcome": "ok"})
                return
            if path == "/announcements":
                self._announcements()
                return
            self._send(404, {"outcome": "refused", "reason": "unknown_route"})

        def _announcements(self) -> None:
            if not notify_token:
                self._send(503, {"outcome": "refused", "reason": "secrets", "announcements": []})
                return
            presented = self.headers.get("Friday-Notify") or ""
            if not _token_ok(presented, notify_token):
                self._send(401, {"outcome": "refused", "reason": "unauthenticated", "announcements": []})
                return
            try:
                rows = announcements(store)
            except QueueError:
                self._send(503, {"outcome": "refused", "reason": "postgres", "announcements": []})
                return
            self._send(200, {
                "outcome": "ok",
                "reason": "announced",
                "announcements": rows,
                "started": False,
                "sent": False,
            })

        def do_POST(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0]
            route = ROUTES.get(path)
            if route is None:
                self._send(404, {"outcome": "refused", "reason": "unknown_route"})
                return
            length = self.headers.get("Content-Length")
            try:
                size = int(length) if length is not None else 0
            except ValueError:
                size = -1
            if size < 0 or size > MAX_BODY:
                self._send(413, {"outcome": "refused", "reason": "body_too_large"})
                return
            body = self.rfile.read(size) if size else b""
            receipt = receive(
                store,
                method="POST",
                route=route,
                header=self.headers.get(HEADER),
                body=body,
                secrets=secrets,
            )
            payload = {"outcome": receipt.outcome, "reason": receipt.reason}
            if receipt.event_type:
                payload["event_type"] = receipt.event_type
            if receipt.announcement:
                payload["announcement"] = receipt.announcement
            self._send(STATUSES.get(receipt.reason, 400), payload)

        def _send(self, status: int, payload: dict) -> None:
            raw = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    httpd = ThreadingHTTPServer((host, port), Handler)
    return httpd


def open_store(env: dict[str, str] | None = None):
    """Memory when Postgres is unset. Otherwise the webhook_store queue."""
    source = os.environ if env is None else env
    if not source.get("POSTGRES_HOST"):
        return MemoryStore()
    if not source.get("POSTGRES_PASSWORD") or not source.get("POSTGRES_USER"):
        raise SystemExit("webhooks: postgres")
    try:
        queue = PostgresQueue.from_env(source)
    except QueueError as exc:
        raise SystemExit("webhooks: postgres") from exc
    if not _wait_postgres(queue):
        raise SystemExit("webhooks: postgres")
    return queue


def _wait_postgres(queue: PostgresQueue) -> bool:
    deadline = time.time() + 60
    while True:
        if queue.ensure():
            return True
        if time.time() >= deadline:
            return False
        time.sleep(1)


def _token_ok(presented: str, expected: str) -> bool:
    if not presented or not expected:
        return False
    left = presented.encode()
    right = expected.encode()
    if len(left) != len(right):
        return False
    return hmac.compare_digest(left, right)


def main() -> None:
    host = os.environ.get("BIND_HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8080"))
    httpd = serve(
        open_store(),
        secrets_from_env(),
        host,
        port,
        os.environ.get("FRIDAY_NOTIFY_TOKEN", ""),
    )
    httpd.serve_forever()
