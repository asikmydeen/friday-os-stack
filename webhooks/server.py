"""HTTP front for receive(). The response never includes the raw body.

The process keeps events in memory. It does not open Postgres, does not
call the executor, and does not write an approval. An empty secret
rejects every header, which is the state before any guest app exists.
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from webhooks.receiver import HEADER, MAX_BODY, MemoryStore, receive

ROUTES = {"/media": "media", "/arr": "arr"}
STATUSES = {
    "stored": 200,
    "already_stored": 200,
    "header_rejected": 403,
    "ambiguous_secret": 403,
    "method_refused": 405,
    "unknown_route": 404,
    "body_too_large": 413,
}


def secrets_from_env() -> dict[str, str]:
    return {
        "jellyfin": os.environ.get("WEBHOOK_SECRET_JELLYFIN", ""),
        "radarr": os.environ.get("WEBHOOK_SECRET_RADARR", ""),
        "sonarr": os.environ.get("WEBHOOK_SECRET_SONARR", ""),
    }


def serve(store: MemoryStore, secrets: dict[str, str], host: str, port: int) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args) -> None:
            return

        def do_GET(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0]
            if path == "/health":
                self._send(200, {"outcome": "ok"})
                return
            self._send(404, {"outcome": "refused", "reason": "unknown_route"})

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


def main() -> None:
    host = os.environ.get("BIND_HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8080"))
    httpd = serve(MemoryStore(), secrets_from_env(), host, port)
    httpd.serve_forever()
