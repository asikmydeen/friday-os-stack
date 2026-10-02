"""Listen for an advisor call and forward it only when the wire allows it.

/health is this process. Any other path is refused unless it is a health
URL copied from a wire. A missing upstream is 502. Nothing here mints an
approval or publishes a host port.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from gateway.proxy import Allow, allows_from_dir, match
from runtime.bind import bind_host


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise OSError("upstream_unavailable")


def open_upstream(request: urllib.request.Request, timeout: float):
    opener = urllib.request.build_opener(_NoRedirect)
    return opener.open(request, timeout=timeout)


def forward(allow: Allow, opener=open_upstream, timeout: float = 5.0) -> tuple[int, bytes]:
    request = urllib.request.Request(
        f"http://{allow.host}:{allow.port}{allow.path}",
        method="GET",
    )
    try:
        with opener(request, timeout) as response:
            return response.status, response.read(32768)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(32768)
    except (urllib.error.URLError, TimeoutError, OSError):
        raise OSError("upstream_unavailable") from None


def serve(allows: tuple[Allow, ...], host: str, port: int, opener=open_upstream) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args) -> None:
            return

        def do_GET(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0]
            if path == "/health":
                self._send(200, b'{"outcome":"ok"}')
                return
            allow = match("GET", path, allows)
            if allow is None:
                self._send(403, b'{"outcome":"refused","reason":"not_allowed"}')
                return
            try:
                status, body = forward(allow, opener)
            except OSError:
                self._send(502, b'{"outcome":"refused","reason":"upstream_unavailable"}')
                return
            self._send(status, body[:32768])

        def do_POST(self) -> None:  # noqa: N802
            self._send(403, b'{"outcome":"refused","reason":"not_allowed"}')

        def _send(self, status: int, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return ThreadingHTTPServer((host, port), Handler)


def main() -> None:
    env = dict(os.environ)
    try:
        host = bind_host(env)
    except OSError as exc:
        raise SystemExit(f"gateway: {exc}") from None
    port = int(env.get("PORT", "8090"))
    wires = Path(env.get("WIRES_DIR", "/wires"))
    allows = allows_from_dir(wires) if wires.is_dir() else ()
    serve(allows, host, port).serve_forever()
