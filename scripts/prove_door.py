"""Throwaway checks for the messaging door and the inbound MCP listener.

hold listens on 5432. friday answers /ask and /recall. closed exits 0 when
postgres and the executor cannot be opened. client checks the door and the
listener, then exits 0.
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import socket
from urllib.error import HTTPError
from urllib.request import Request, urlopen

MARKER = "qdrant-key-marker"
COUNTS = {"ask": 0, "recall": 0}


def hold() -> None:
    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("0.0.0.0", 5432))
    server.listen(5)
    while True:
        conn, _addr = server.accept()
        conn.close()


def friday() -> None:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args) -> None:
            return

        def do_GET(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0]
            if path == "/health":
                self._send(200, {"outcome": "ok"})
                return
            if path == "/counts":
                self._send(200, dict(COUNTS))
                return
            self._send(404, {"outcome": "refused"})

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or "0")
            raw = self.rfile.read(length) if length else b""
            try:
                payload = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                payload = {}
            path = self.path.split("?", 1)[0]
            if not self.headers.get("Friday-Notify"):
                self._send(401, {"outcome": "refused", "reason": "unauthenticated"})
                return
            if path == "/ask":
                COUNTS["ask"] += 1
                reply = "LEAK" if "confirmed" in payload else "Ready."
                self._send(200, {
                    "outcome": "spoken",
                    "reason": "model",
                    "reply": reply,
                    "role": "friday",
                    "approval_id": "not-for-the-door",
                })
                return
            if path == "/recall":
                COUNTS["recall"] += 1
                self._send(200, {
                    "outcome": "ok",
                    "reason": "recall",
                    "notes": [{
                        "id": "n1",
                        "content": "lighthouse",
                        "qdrant_key": MARKER,
                    }],
                })
                return
            self._send(404, {"outcome": "refused"})

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
    for host, port in (("postgres", 5432), ("executor", 8080), (address, 5432)):
        if not host:
            continue
        try:
            socket.create_connection((host, int(port)), 2).close()
        except OSError:
            continue
        raise SystemExit("postgres-open")


def _call(url: str, payload: dict, header: str, token: str) -> tuple[int, dict]:
    request = Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", header: token},
        method="POST",
    )
    try:
        with urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except HTTPError as exc:
        return exc.code, json.loads(exc.read())


def client() -> None:
    import os

    door = os.environ["DOOR_URL"]
    mcp = os.environ["MCP_URL"]
    friday_url = os.environ["FRIDAY_URL"]
    door_token = os.environ["DOOR_TOKEN"]
    harness = os.environ["MCP_TOKEN"]
    notify = os.environ["FRIDAY_NOTIFY_TOKEN"]
    status, body = _call(
        door + "/turn",
        {"text": "hello", "owner_id": "owner-1", "confirmed": True, "approval_id": "x"},
        "Friday-Door",
        door_token,
    )
    encoded = json.dumps(body)
    if status != 200 or body.get("reply") != "Ready." or "approval_id" in body:
        raise SystemExit("turn-failed")
    if notify in encoded or door_token in encoded or "LEAK" in encoded:
        raise SystemExit("turn-leaked")
    status, denied = _call(door + "/approvals", {"text": "approve"}, "Friday-Door", door_token)
    if status != 404 or denied.get("reason") != "unknown_path":
        raise SystemExit("approval-path")
    status, recalled = _call(
        mcp + "/mcp",
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "recall", "arguments": {"owner_id": "owner-1"}, "confirmed": True},
        },
        "Friday-Harness",
        harness,
    )
    packed = json.dumps(recalled)
    notes = (recalled.get("result") or {}).get("notes")
    if status != 200 or notes != [{"id": "n1", "content": "lighthouse"}] or MARKER in packed:
        raise SystemExit("recall-failed")
    if notify in packed or harness in packed:
        raise SystemExit("recall-leaked")
    before = json.loads(urlopen(friday_url + "/counts", timeout=5).read())
    status, waiting = _call(
        mcp + "/mcp",
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "send", "confirmed": True, "arguments": {"target": "sam@example.com"}},
        },
        "Friday-Harness",
        harness,
    )
    after = json.loads(urlopen(friday_url + "/counts", timeout=5).read())
    result = waiting.get("result") or {}
    if status != 202 or result.get("reason") != "board_must_approve" or result.get("started") is not False:
        raise SystemExit("send-failed")
    if "approval_id" in json.dumps(waiting) or after != before:
        raise SystemExit("send-forwarded")
    closed()
    print("door-client-ok")


if __name__ == "__main__":
    command = sys.argv[1]
    if command == "hold":
        hold()
    elif command == "friday":
        friday()
    elif command == "closed":
        closed()
    elif command == "client":
        client()
    else:
        raise SystemExit("usage")
