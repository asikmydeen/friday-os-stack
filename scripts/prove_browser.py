"""Throwaway checks for the disposable browser session.

page serves one document and counts fetches. hold listens on 5432.
closed exits 0 when postgres cannot be opened. client checks the
session, then exits 0.
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import socket
from urllib.error import HTTPError
from urllib.request import Request, urlopen

SECRET = "vault-secret-marker"
HITS = {"n": 0}


def hold() -> None:
    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("0.0.0.0", 5432))
    server.listen(5)
    while True:
        conn, _addr = server.accept()
        conn.close()


def page() -> None:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args) -> None:
            return

        def do_GET(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0]
            if path == "/count":
                self._send(200, dict(HITS))
                return
            HITS["n"] += 1
            body = "lighthouse"
            if self.headers.get("Authorization") == f"Bearer {SECRET}":
                body = f"lighthouse {SECRET}"
            raw = body.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _send(self, status: int, payload: dict) -> None:
            raw = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()


def closed() -> None:
    import os

    address = sys.argv[2] if len(sys.argv) > 2 and sys.argv[1] == "closed" else os.environ.get("POSTGRES_IP", "")
    for host, port in (("postgres", 5432), (address, 5432)):
        if not host:
            continue
        try:
            socket.create_connection((host, int(port)), 2).close()
        except OSError:
            continue
        raise SystemExit("postgres-open")


def _call(url: str, payload: dict, token: str) -> tuple[int, dict]:
    request = Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Friday-Browser": token},
        method="POST",
    )
    try:
        with urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read())
    except HTTPError as exc:
        return exc.code, json.loads(exc.read())


def client() -> None:
    import os

    browser = os.environ["BROWSER_URL"]
    page_url = os.environ["PAGE_URL"]
    token = os.environ["BROWSER_TOKEN"]
    status, body = _call(
        browser + "/page",
        {
            "action": "read",
            "url": page_url,
            "secret": SECRET,
            "confirmed": True,
            "approval_id": "not-for-the-session",
        },
        token,
    )
    raw = json.dumps(body)
    if status != 200 or body.get("reason") != "page" or "lighthouse" not in body.get("text", ""):
        raise SystemExit("read-failed")
    if SECRET in raw or token in raw or "approval_id" in raw:
        raise SystemExit("read-leaked")
    before = json.loads(urlopen(os.environ["COUNT_URL"], timeout=5).read())
    status, waiting = _call(
        browser + "/page",
        {"action": "pay", "url": page_url, "secret": SECRET, "confirmed": True},
        token,
    )
    after = json.loads(urlopen(os.environ["COUNT_URL"], timeout=5).read())
    if status != 202 or waiting.get("reason") != "approval_required" or waiting.get("started") is not False:
        raise SystemExit("pay-failed")
    if "approval_id" in json.dumps(waiting) or SECRET in json.dumps(waiting) or after != before:
        raise SystemExit("pay-fetched")
    status, denied = _call(browser + "/approvals", {"action": "pay"}, token)
    if status != 404 or denied.get("reason") != "unknown_path":
        raise SystemExit("approval-path")
    closed()
    print("browser-client-ok")


if __name__ == "__main__":
    command = sys.argv[1]
    if command == "hold":
        hold()
    elif command == "page":
        page()
    elif command == "closed":
        closed()
    elif command == "client":
        client()
    else:
        raise SystemExit("usage")
