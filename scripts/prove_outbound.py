"""Throwaway checks for outbound MCP.

peer answers tools/list and tools/call and counts calls. hold listens
on 5432. closed exits 0 when postgres cannot be opened. client checks
the caller, then exits 0.
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import socket
from urllib.error import HTTPError
from urllib.request import Request, urlopen

SECRET = "vault-secret-marker"
CALLS = {"n": 0}


def hold() -> None:
    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("0.0.0.0", 5432))
    server.listen(5)
    while True:
        conn, _addr = server.accept()
        conn.close()


def peer() -> None:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args) -> None:
            return

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            method = str(payload.get("method") or "")
            if method == "tools/list":
                result = {"tools": [{"name": "status"}, {"name": "send"}, {"name": "qdrant"}]}
            elif method == "tools/call":
                CALLS["n"] += 1
                text = "lighthouse"
                if self.headers.get("Authorization") == f"Bearer {SECRET}":
                    text = f"lighthouse {SECRET}"
                result = {"text": text, "qdrant_key": "marker"}
            else:
                self._send(404, {"error": {"message": "unknown_method"}})
                return
            self._send(200, {"jsonrpc": "2.0", "id": payload.get("id"), "result": result})

        def do_GET(self) -> None:  # noqa: N802
            if self.path.split("?", 1)[0] == "/count":
                self._send(200, dict(CALLS))
                return
            self._send(404, {"reason": "unknown_path"})

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
        headers={"Content-Type": "application/json", "Friday-Outbound": token},
        method="POST",
    )
    try:
        with urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read())
    except HTTPError as exc:
        return exc.code, json.loads(exc.read())


def client() -> None:
    import os

    base = os.environ["OUTBOUND_URL"]
    server = os.environ["SERVER_URL"]
    token = os.environ["OUTBOUND_TOKEN"]
    status, tools = _call(base + "/tools", {"server": server, "secret": SECRET}, token)
    names = [item.get("name") for item in tools.get("tools") or []]
    if status != 200 or names != ["send", "status"]:
        raise SystemExit("tools-failed")
    if SECRET in json.dumps(tools) or "qdrant" in names:
        raise SystemExit("tools-leaked")
    status, body = _call(
        base + "/call",
        {"server": server, "tool": "status", "secret": SECRET, "confirmed": True, "approval_id": "nope"},
        token,
    )
    raw = json.dumps(body)
    if status != 200 or "lighthouse" not in body.get("result", {}).get("text", ""):
        raise SystemExit("call-failed")
    if SECRET in raw or token in raw or "qdrant_key" in raw or "approval_id" in raw:
        raise SystemExit("call-leaked")
    before = json.loads(urlopen(os.environ["COUNT_URL"], timeout=5).read())
    status, waiting = _call(
        base + "/call",
        {"server": server, "tool": "send", "secret": SECRET, "confirmed": True},
        token,
    )
    after = json.loads(urlopen(os.environ["COUNT_URL"], timeout=5).read())
    if status != 202 or waiting.get("reason") != "board_must_approve" or waiting.get("started") is not False:
        raise SystemExit("send-failed")
    if after != before or "approval_id" in json.dumps(waiting):
        raise SystemExit("send-forwarded")
    status, denied = _call(base + "/approvals", {"server": server}, token)
    if status != 404 or denied.get("reason") != "unknown_path":
        raise SystemExit("approval-path")
    closed()
    print("outbound-client-ok")


if __name__ == "__main__":
    command = sys.argv[1]
    if command == "hold":
        hold()
    elif command == "peer":
        peer()
    elif command == "closed":
        closed()
    elif command == "client":
        client()
    else:
        raise SystemExit("usage")
