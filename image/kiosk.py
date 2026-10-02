"""Open setup on the attached monitor, then the Board.

The launcher reads one provisioning token from a mode 0600 file. It
adds Friday-Provision only when the path is /provision. The token is
not placed on the chromium command line and not written into the page.
When the token file is gone and the Board is answering, chromium opens
http://127.0.0.1:8080/ with no provision header. The decision functions
do not open a socket and do not start chromium. main() is the kiosk
service: it listens on 127.0.0.1 only while setup is open, and it does
not install an app.
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit

TOKEN_PATH = Path("/var/lib/kiosk/provision.token")
LISTEN_PORT = 8081
MAX_TOKEN = 256
_HOP = frozenset(
    {
        "host",
        "content-length",
        "connection",
        "keep-alive",
        "proxy-connection",
        "transfer-encoding",
        "friday-provision",
        "te",
        "trailer",
        "upgrade",
    }
)


def read_token(path: Path) -> str:
    """The token, or empty when the file is missing or not one line."""
    if not path.is_file():
        return ""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    if text.endswith("\n"):
        text = text[:-1]
    if text == "" or "\n" in text or "\r" in text or len(text) > MAX_TOKEN:
        return ""
    return text


def place_token(token: str, dest: Path) -> None:
    """Write or remove the kiosk user's copy. An empty token removes it.

    The file is mode 0600. When a local user named kiosk exists, that
    user owns the file. The token is not returned.
    """
    if token == "":
        if dest.is_file() or dest.is_symlink():
            dest.unlink()
        return
    if "\n" in token or "\r" in token or len(token) > MAX_TOKEN:
        raise OSError("token_invalid")
    dest.parent.mkdir(parents=True, exist_ok=True)
    temporary = dest.with_suffix(dest.suffix + ".tmp")
    fd = os.open(temporary, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    try:
        os.write(fd, (token + "\n").encode())
    finally:
        os.close(fd)
    os.chmod(temporary, 0o600)
    os.replace(temporary, dest)
    os.chmod(dest, 0o600)
    try:
        import pwd

        user = pwd.getpwnam("kiosk")
    except KeyError:
        return
    try:
        os.chown(dest, user.pw_uid, user.pw_gid)
    except OSError:
        return


def safe_path(path: str) -> str | None:
    """A path on this host, or None when it could name another host."""
    if not isinstance(path, str) or not path.startswith("/") or path.startswith("//"):
        return None
    if "\\" in path or "\n" in path or "\r" in path or "\x00" in path:
        return None
    parts = urlsplit(path)
    if parts.scheme or parts.netloc:
        return None
    return path


def forwarded_headers(path: str, headers, token: str) -> dict[str, str]:
    """Headers for the setup server. The token is added only for /provision.

    A header the browser already sent under that name is dropped, so the
    page cannot replace the token or send it to another path.
    """
    route = urlsplit(path).path or "/"
    kept: dict[str, str] = {}
    items = headers.items() if hasattr(headers, "items") else ()
    for key, value in items:
        if not isinstance(key, str) or not isinstance(value, str):
            continue
        if key.lower() in _HOP or "\n" in key or "\r" in key or "\n" in value or "\r" in value:
            continue
        kept[key] = value
    if route == "/provision" and token and "\n" not in token and "\r" not in token:
        kept["Friday-Provision"] = token
    return kept


def chromium_command(
    token: str,
    *,
    cage: str = "/usr/bin/cage",
    chromium: str = "/usr/bin/chromium",
    listen_port: int = LISTEN_PORT,
) -> list[str]:
    """The kiosk command. The token is not an argument."""
    if token:
        url = f"http://127.0.0.1:{listen_port}/provision"
    else:
        url = "http://127.0.0.1:8080/"
    argv = [
        cage,
        "--",
        chromium,
        "--kiosk",
        "--no-first-run",
        "--disable-sync",
        "--disable-translate",
        "--noerrdialogs",
        "--ozone-platform=wayland",
        url,
    ]
    if token and any(token in part for part in argv):
        raise OSError("token_on_command_line")
    return argv


def next_screen(token: str, upstream_status: int | None) -> str:
    """setup, board, or wait. A token opens setup. 404 with no token is the Board."""
    if token:
        return "setup"
    if upstream_status == 404:
        return "board"
    return "wait"


def opening(token: str, provision_status: int, root_status: int, root_body: bytes) -> str:
    """What the monitor should open now.

    A token opens setup only after the setup server answers. No token
    opens the Board only when that login page is answering. A refused
    setup probe is not the Board.
    """
    if token and provision_status != 0:
        return "setup"
    if not token and board_ready(root_status, root_body):
        return "board"
    return "wait"


def setup_finished(path: str, payload: bytes) -> bool:
    """True only when /provision itself reports the finished line."""
    if urlsplit(path).path != "/provision":
        return False
    try:
        text = payload.decode()
    except UnicodeDecodeError:
        return False
    return any(line == "Provision: complete" for line in text.splitlines())


def board_ready(status: int, payload: bytes) -> bool:
    """True when the Board login page is what answered, not the setup text."""
    if status != 200:
        return False
    return b"Let Friday speak first" in payload


def serve_proxy(token: str, upstream_port: int, listen_port: int = 0):
    """Forward the kiosk browser to the setup server on this machine.

    The returned server is not started. listen_port 0 asks the OS for a
    free port. The token stays on this process.
    """
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args) -> None:
            return

        def do_GET(self) -> None:
            self._go()

        def do_POST(self) -> None:
            self._go()

        def do_HEAD(self) -> None:
            self._go()

        def _go(self) -> None:
            path = safe_path(self.path)
            if path is None:
                self._send(400, b"refused\n", "text/plain; charset=utf-8")
                return
            try:
                length = int(self.headers.get("Content-Length", "0") or "0")
            except ValueError:
                length = MAX_BODY + 1
            if length > MAX_BODY or length < 0:
                self._send(413, b"too_large\n", "text/plain; charset=utf-8")
                return
            body = self.rfile.read(length) if length else b""
            headers = forwarded_headers(path, self.headers, self.server.token)
            try:
                status, payload, kind = forward(self.command, path, headers, body, self.server.upstream_port)
            except OSError:
                self._send(502, b"unreachable\n", "text/plain; charset=utf-8")
                return
            self._send(status, payload, kind)
            if setup_finished(path, payload):
                self.server.closed = True

        def _send(self, status: int, payload: bytes, kind: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(payload)

    httpd = ThreadingHTTPServer(("127.0.0.1", listen_port), Handler)
    httpd.token = token
    httpd.upstream_port = upstream_port
    httpd.closed = False
    return httpd


def forward(method: str, path: str, headers: dict[str, str], body: bytes, upstream_port: int):
    """One request to 127.0.0.1. The port is the setup server, not a caller URL."""
    import http.client

    connection = http.client.HTTPConnection("127.0.0.1", upstream_port, timeout=30)
    try:
        connection.request(method, path, body=body if body else None, headers=headers)
        response = connection.getresponse()
        payload = response.read()
        kind = response.getheader("Content-Type") or "text/plain; charset=utf-8"
    finally:
        connection.close()
    if kind not in {"text/plain; charset=utf-8", "text/html; charset=utf-8"}:
        kind = "text/plain; charset=utf-8"
    return response.status, payload, kind


MAX_BODY = 32 * 1024


def main() -> None:
    """Run as the kiosk user. Exit 1 when setup is not ready yet."""
    import os
    import time
    import urllib.error
    import urllib.request

    token_path = Path(os.environ.get("FRIDAY_KIOSK_TOKEN", str(TOKEN_PATH)))
    upstream_port = _upstream_port(os.environ.get("FRIDAY_UPSTREAM", "http://127.0.0.1:8080"))
    listen = int(os.environ.get("FRIDAY_KIOSK_PORT", str(LISTEN_PORT)))
    cage = os.environ.get("FRIDAY_CAGE", "/usr/bin/cage")
    browser = os.environ.get("FRIDAY_CHROMIUM", "/usr/bin/chromium")

    def probe(path: str) -> tuple[int, bytes]:
        request = urllib.request.Request(f"http://127.0.0.1:{upstream_port}{path}", method="GET")
        try:
            with urllib.request.urlopen(request, timeout=2) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            try:
                return exc.code, exc.read()
            finally:
                exc.close()
        except OSError:
            return 0, b""

    choice = "wait"
    for _ in range(150):
        token = read_token(token_path)
        provision_status, _provision_body = probe("/provision")
        root_status, root_body = probe("/")
        choice = opening(token, provision_status, root_status, root_body)
        if choice != "wait":
            break
        time.sleep(0.2)
    else:
        raise SystemExit(1)
    if choice == "board":
        os.execv(cage, chromium_command("", cage=cage, chromium=browser))
    httpd = serve_proxy(token, upstream_port, listen)
    import threading

    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    import subprocess

    proc = subprocess.Popen(chromium_command(token, cage=cage, chromium=browser, listen_port=listen))
    while proc.poll() is None and not httpd.closed:
        time.sleep(0.2)
    httpd.shutdown()
    if proc.poll() is None:
        proc.terminate()
    for _ in range(150):
        status, body = probe("/")
        if board_ready(status, body):
            os.execv(cage, chromium_command("", cage=cage, chromium=browser))
        time.sleep(0.2)
    raise SystemExit(1)


def _upstream_port(upstream: str) -> int:
    parts = urlsplit(upstream)
    if parts.scheme not in {"http", ""} or parts.hostname != "127.0.0.1" or parts.path not in {"", "/"}:
        raise SystemExit(1)
    return parts.port or 8080


if __name__ == "__main__":
    main()
