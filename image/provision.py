"""Local setup page. It binds to 127.0.0.1 and does not install or read memory."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from image import VERSION
from image.setup import Store

MAX_BODY = 32 * 1024


def header(headers, name: str) -> str:
    if headers is None:
        return ""
    getter = getattr(headers, "get", None)
    if getter is None:
        return ""
    return (getter(name) or "").strip()


def handle(store: Store, method: str, path: str, headers, body: bytes, *, local: bool) -> tuple[int, str]:
    del method
    if not local:
        return 403, "refused\nnot_local\n"
    route = urlsplit(path).path
    try:
        text = body.decode() if body else ""
    except UnicodeDecodeError:
        return 400, "refused\nbody\n"
    fields = {key: values[0] for key, values in parse_qs(text, keep_blank_values=True).items()}
    # The confirmed flag is parsed so it is not a mistake, and then dropped.
    fields.pop("confirmed", None)
    action = fields.get("action", "")
    if route == "/provision":
        if store.provision_state == "complete":
            return 404, "provision_closed\n"
        token = header(headers, "Friday-Provision")
        if not store.provision_token or not token or not _same(token, store.provision_token):
            return 401, "unauthenticated\n"
        if action in {"install", "uninstall", "grant", "memory", "recall", "recover"}:
            return _closed(store, route, action)
        return _provision(store, action, fields)
    if not _board_ok(store, headers):
        return 401, "unauthenticated\n"
    if route in {"/install", "/memory", "/grant"} or action in {
        "install",
        "uninstall",
        "grant",
        "memory",
        "recall",
        "recover",
    }:
        return _closed(store, route, action)
    return 200, f"Friday {VERSION} test image. The Board is not in this image.\n" + store.status_text()


def _same(left: str, right: str) -> bool:
    from image.setup import same

    return same(left, right)


def _board_ok(store: Store, headers) -> bool:
    presented = header(headers, "Friday-Board")
    return bool(presented) and _same(presented, store.board_password)


def _closed(store: Store, route: str, action: str) -> tuple[int, str]:
    del store
    if route == "/install" or action in {"install", "uninstall"}:
        return 403, "refused\ncatalog_install_closed\n"
    if route == "/grant" or action == "grant":
        return 403, "refused\ngrant_closed\n"
    if route == "/memory" or action in {"memory", "recall"}:
        return 403, "refused\nmemory_unreadable\n"
    if action == "recover":
        return 403, "refused\nconsole_only\n"
    return 403, "refused\nclosed\n"


def _provision(store: Store, action: str, fields: dict) -> tuple[int, str]:
    if action in {"", "status"}:
        return 200, store.status_text()
    if action == "link":
        store.save_link()
        return 200, store.status_text()
    if action == "wifi":
        outcome = store.save_wifi(fields.get("ssid", ""), fields.get("password", ""))
        if outcome.outcome != "ok":
            return 200, outcome.reason + "\n" + store.status_text()
        return 200, store.status_text()
    if action == "server":
        outcome = store.confirm_server()
        return 200, outcome.reason + "\n" + store.status_text()
    if action == "name":
        outcome = store.set_name(fields.get("name", ""))
        return 200, outcome.reason + "\n" + store.status_text()
    if action == "timezone":
        outcome = store.set_timezone(fields.get("timezone", ""))
        return 200, outcome.reason + "\n" + store.status_text()
    if action == "model":
        outcome = store.set_model(
            fields.get("base", ""),
            fields.get("fast", ""),
            fields.get("think", ""),
            fields.get("key", ""),
        )
        return 200, outcome.reason + "\n" + store.status_text()
    if action == "password":
        outcome = store.confirm_password(fields.get("typed", ""), fields.get("again", ""))
        return 200, outcome.reason + "\n" + store.status_text()
    if action == "finish":
        outcome = store.finish()
        return 200, outcome.reason + "\n" + store.status_text()
    return 200, "unknown\n" + store.status_text()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        return

    def do_GET(self) -> None:
        self._go()

    def do_POST(self) -> None:
        self._go()

    def _go(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
        except ValueError:
            length = MAX_BODY + 1
        if length > MAX_BODY:
            self._send(413, "too_large\n")
            return
        body = self.rfile.read(length) if length else b""
        local = self.client_address[0] in {"127.0.0.1", "::1"}
        status, payload = handle(self.server.store, self.command, self.path, self.headers, body, local=local)
        self._send(status, payload)

    def _send(self, status: int, payload: str) -> None:
        data = payload.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def serve(store: Store, port: int = 8080) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.store = store
    return httpd
