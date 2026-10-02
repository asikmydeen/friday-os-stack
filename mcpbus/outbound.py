"""Call one granted MCP server. This process cannot approve.

It listens only when OUTBOUND_ENABLED is yes. The caller presents
Friday-Outbound. tools/list returns the granted names the server also
offers. A mutating tools/call waits and is not sent. confirmed=true is
dropped. The process has no Postgres URL and does not create an approval.
"""

from __future__ import annotations

import ipaddress
import json
import os
import socket
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener

from mcpbus.grants import inbound, visible
from mcpbus.server import granted_names
from netpolicy.paths import browser_can_open
from runtime.forward import _RefuseRedirect, listen_host
from runtime.http import header, same

_DROP = {"secret", "token", "password", "qdrant_key", "approval_id"}


def listening(env: dict[str, str]) -> bool:
    return env.get("OUTBOUND_ENABLED") == "yes"


def granted_servers(env: dict[str, str]) -> tuple[str, ...]:
    raw = env.get("GRANTED_SERVERS", "")
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def vet_server(url: str, resolve) -> str | None:
    """A refusal reason, or None when this granted URL may be called."""
    parts = urlsplit((url or "").strip())
    if parts.scheme not in {"http", "https"} or parts.username or parts.password:
        return "url"
    if parts.fragment or not parts.hostname:
        return "url"
    decision = browser_can_open(parts.hostname)
    if decision.outcome != "allowed":
        return decision.reason
    try:
        addresses = list(resolve(parts.hostname))
    except OSError:
        return "unreachable"
    decision = browser_can_open(parts.hostname, addresses)
    if decision.outcome != "allowed":
        return decision.reason
    if _local(parts.hostname, addresses):
        return "loopback"
    return None


def app(env: dict[str, str], rpc, resolve):
    granted = granted_names(env)
    servers = granted_servers(env)

    def handle(method: str, path: str, headers, payload: dict) -> tuple[int, dict]:
        if path == "/health" and method == "GET":
            return 200, {"outcome": "ok", "reason": "health"}
        if not listening(env):
            return 403, {"outcome": "refused", "reason": "outbound_off"}
        token = env.get("OUTBOUND_TOKEN", "")
        presented = header(headers, "Friday-Outbound")
        if not token or not presented or not same(presented, token):
            return 401, {"outcome": "refused", "reason": "unauthenticated"}
        if method != "POST" or path not in {"/tools", "/call"}:
            return 404, {"outcome": "refused", "reason": "unknown_path"}
        payload.pop("confirmed", None)
        server = str(payload.get("server") or "").strip()
        if server not in servers:
            return 403, {"outcome": "refused", "reason": "unknown_server"}
        reason = vet_server(server, resolve)
        if reason == "unreachable":
            return 502, {"outcome": "refused", "reason": "unreachable"}
        if reason is not None:
            return 403, {"outcome": "refused", "reason": reason}
        secret = str(payload.get("secret") or "")
        try:
            listed = rpc(server, secret, "tools/list", {})
        except OSError as exc:
            return 502, {"outcome": "refused", "reason": _rpc_reason(exc)}
        offered = _offered(listed)
        if path == "/tools":
            names = visible(granted, offered)
            return 200, {
                "outcome": "ok",
                "reason": "tools",
                "tools": [{"name": name} for name in names],
            }
        tool = str(payload.get("tool") or "").strip()
        decision = inbound(tool, granted, offered)
        if decision.outcome == "waiting":
            return 202, {"outcome": "waiting", "reason": decision.reason, "started": False}
        if decision.outcome != "allowed":
            return 403, {"outcome": "refused", "reason": decision.reason}
        arguments = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
        arguments = dict(arguments)
        arguments.pop("confirmed", None)
        try:
            result = rpc(server, secret, "tools/call", {"name": tool, "arguments": arguments})
        except OSError as exc:
            return 502, {"outcome": "refused", "reason": _rpc_reason(exc)}
        public = _public(result, secret)
        if secret and secret in json.dumps(public):
            return 502, {"outcome": "refused", "reason": "secret_in_result"}
        return 200, {"outcome": "ok", "reason": "called", "result": public}

    return handle


def default_rpc(url: str, secret: str, method: str, params: dict) -> dict:
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    raw = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if secret:
        headers["Authorization"] = f"Bearer {secret}"
    request = Request(url, data=raw, headers=headers, method="POST")
    opener = build_opener(_RefuseRedirect)
    try:
        with opener.open(request, timeout=20) as response:
            body = json.loads(response.read())
    except OSError as exc:
        if str(exc) == "redirect":
            raise
        raise OSError("unreachable") from None
    except HTTPError as exc:
        raise OSError("unreachable") from exc
    except json.JSONDecodeError as exc:
        raise OSError("unreachable") from exc
    if not isinstance(body, dict):
        raise OSError("unreachable")
    result = body.get("result")
    if not isinstance(result, dict):
        raise OSError("unreachable")
    return result


def _offered(result: dict) -> tuple[str, ...]:
    names = []
    for tool in list(result.get("tools") or []):
        if isinstance(tool, dict) and tool.get("name"):
            names.append(str(tool["name"]))
    return tuple(names)


def _public(result: dict, secret: str) -> dict:
    found = {}
    for key, value in result.items():
        if key in _DROP:
            continue
        if isinstance(value, str):
            if secret:
                value = value.replace(secret, "")
            found[key] = value
        elif isinstance(value, (int, float, bool)) or value is None:
            found[key] = value
    return found


def _local(host: str, addresses: list[str]) -> bool:
    for item in (host, *addresses):
        try:
            address = ipaddress.ip_address(item)
        except ValueError:
            continue
        if address.is_loopback or address.is_unspecified:
            return True
    return False


def _rpc_reason(exc: OSError) -> str:
    if str(exc) == "redirect":
        return "redirect"
    return "unreachable"


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
    if not env.get("OUTBOUND_TOKEN"):
        raise SystemExit("outbound: secrets")
    try:
        host = listen_host(env)
    except OSError as exc:
        raise SystemExit(f"outbound: {exc}") from None
    port = int(env.get("PORT", "8080"))

    def rpc(url: str, secret: str, method: str, params: dict) -> dict:
        return default_rpc(url, secret, method, params)

    serve(app(env, rpc, _resolve), host, port).serve_forever()


if __name__ == "__main__":
    main()
