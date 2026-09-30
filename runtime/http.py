"""JSON over HTTP. Tokens are compared in constant time for equal lengths."""

from __future__ import annotations

import hmac
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable
from urllib.parse import urlsplit

MAX_BODY = 32 * 1024

Handler = Callable[[str, str, object, dict], tuple[int, dict]]


def same(left: str, right: str) -> bool:
    raw_left = left.encode()
    raw_right = right.encode()
    if len(raw_left) != len(raw_right):
        return False
    return hmac.compare_digest(raw_left, raw_right)


def header(headers, name: str) -> str:
    if headers is None:
        return ""
    getter = getattr(headers, "get", None)
    if getter is None:
        return ""
    return (getter(name) or "").strip()


def json_bytes(payload: dict) -> bytes:
    return json.dumps(payload, separators=(",", ":")).encode()


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST")

    def log_message(self, fmt: str, *args) -> None:
        return

    def _dispatch(self, method: str) -> None:
        length = int(self.headers.get("Content-Length") or "0")
        if length > MAX_BODY:
            self._send(413, {"outcome": "refused", "reason": "too_large"})
            return
        raw = self.rfile.read(length) if length else b""
        path = urlsplit(self.path).path
        if raw:
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                self._send(400, {"outcome": "refused", "reason": "body"})
                return
            if not isinstance(payload, dict):
                self._send(400, {"outcome": "refused", "reason": "body"})
                return
        else:
            payload = {}
        payload.pop("confirmed", None)
        status, body = self.server.app(method, path, self.headers, payload)  # type: ignore[attr-defined]
        self._send(status, body)

    def _send(self, status: int, body: dict) -> None:
        raw = json_bytes(body)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)


def serve(app: Handler, host: str, port: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), _Handler)
    server.app = app  # type: ignore[attr-defined]
    return server
