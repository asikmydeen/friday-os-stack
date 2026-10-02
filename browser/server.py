"""Fetch one page for the model. This process cannot approve.

It listens only when BROWSER_ENABLED is yes. The caller presents
Friday-Browser. A read returns page text with the vault secret removed.
Send, pay, delete, and publish wait and are not fetched. confirmed=true
is dropped before this handler runs. The process has no executor URL
and no Postgres URL. It does not call note_page, discard, or the broker record.
"""

from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import quote, urlsplit
from urllib.request import Request, build_opener

from browser.session import act
from netpolicy.paths import browser_can_open
from runtime.forward import _RefuseRedirect, listen_host
from runtime.http import header, same

TEXT_LIMIT = 8000


def listening(env: dict[str, str]) -> bool:
    return env.get("BROWSER_ENABLED") == "yes"


def vet(url: str, resolve) -> str | None:
    """A refusal reason, or None when this URL may be fetched."""
    parts = urlsplit((url or "").strip())
    if parts.scheme not in {"http", "https"} or parts.username or parts.password:
        return "url"
    host = parts.hostname or ""
    if not host or parts.fragment:
        return "url"
    decision = browser_can_open(host)
    if decision.outcome != "allowed":
        return decision.reason
    try:
        addresses = list(resolve(host))
    except OSError:
        return "unreachable"
    decision = browser_can_open(host, addresses)
    if decision.outcome != "allowed":
        return decision.reason
    if _local(host, addresses):
        return "loopback"
    return None


def page_request(url: str, secret: str, site_host: str) -> Request:
    """The secret is not placed in the URL. It is sent only to SITE_HOST."""
    parts = urlsplit(url)
    headers = {}
    site = (site_host or "").strip().casefold().rstrip(".")
    host = (parts.hostname or "").casefold().rstrip(".")
    if secret and site and host == site:
        headers["Authorization"] = f"Bearer {secret}"
    return Request(url, headers=headers, method="GET")


def default_fetch(url: str, secret: str, site_host: str = "") -> str:
    request = page_request(url, secret, site_host)
    opener = build_opener(_RefuseRedirect)
    try:
        with opener.open(request, timeout=20) as response:
            raw = response.read(64_000)
    except OSError as exc:
        if str(exc) == "redirect":
            raise
        raise OSError("unreachable") from None
    return raw.decode("utf-8", "replace")


def app(env: dict[str, str], fetch, resolve):
    def handle(method: str, path: str, headers, payload: dict) -> tuple[int, dict]:
        if path == "/health" and method == "GET":
            return 200, {"outcome": "ok", "reason": "health"}
        if not listening(env):
            return 403, {"outcome": "refused", "reason": "browser_off"}
        token = env.get("BROWSER_TOKEN", "")
        presented = header(headers, "Friday-Browser")
        if not token or not presented or not same(presented, token):
            return 401, {"outcome": "refused", "reason": "unauthenticated"}
        if path != "/page" or method != "POST":
            return 404, {"outcome": "refused", "reason": "unknown_path"}
        payload.pop("confirmed", None)
        action = str(payload.get("action") or "").strip()
        secret = str(payload.get("secret") or "")
        decision = act(action, confirmed=True)
        if decision.outcome == "waiting":
            return 202, {"outcome": "waiting", "reason": decision.reason, "started": False}
        if decision.outcome != "allowed":
            return 403, {"outcome": "refused", "reason": decision.reason}
        if action == "draft":
            return 200, {"outcome": "allowed", "reason": "draft", "started": False}
        url = str(payload.get("url") or "").strip()
        reason = vet(url, resolve)
        if reason == "unreachable":
            return 502, {"outcome": "refused", "reason": "unreachable"}
        if reason is not None:
            return 403, {"outcome": "refused", "reason": reason}
        try:
            text = fetch(url, secret)
        except OSError as exc:
            reason = "redirect" if str(exc) == "redirect" else "unreachable"
            return 502, {"outcome": "refused", "reason": reason}
        visible = _visible(text, secret)
        if secret and secret in visible:
            return 502, {"outcome": "refused", "reason": "secret_in_page"}
        return 200, {"outcome": "ok", "reason": "page", "text": visible}

    return handle


def _visible(text: str, secret: str) -> str:
    if secret:
        text = text.replace(secret, "")
        text = text.replace(quote(secret, safe=""), "")
    return text[:TEXT_LIMIT]


def _local(host: str, addresses: list[str]) -> bool:
    for item in (host, *addresses):
        try:
            address = ipaddress.ip_address(item)
        except ValueError:
            continue
        if address.is_loopback or address.is_unspecified:
            return True
    return False


def _resolve(host: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise OSError("unreachable") from exc
    found = []
    for info in infos:
        address = info[4][0]
        if address not in found:
            found.append(address)
    if not found:
        raise OSError("unreachable")
    return found


def main() -> None:
    from runtime.http import serve

    env = dict(os.environ)
    if not listening(env):
        raise SystemExit(0)
    if not env.get("BROWSER_TOKEN"):
        raise SystemExit("browser: secrets")
    try:
        host = listen_host(env)
    except OSError as exc:
        raise SystemExit(f"browser: {exc}") from None
    port = int(env.get("PORT", "8080"))
    site = env.get("SITE_HOST", "")

    def fetch(url: str, secret: str) -> str:
        return default_fetch(url, secret, site)

    serve(app(env, fetch, _resolve), host, port).serve_forever()
