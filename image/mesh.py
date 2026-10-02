"""Mesh choice for setup. Nothing here listens or calls Docker.

Leaving the choice unset keeps the Board on this computer. Joining stores
a control URL and a pre-auth key for the client on this box. Creating
stores the URL other devices will use. The phone and laptop keys are
minted later by Headscale, not invented here.
"""

from __future__ import annotations

import ipaddress
import json
import re
from dataclasses import dataclass
from urllib.parse import unquote_plus, urlsplit

from memoryd.store import credential_shape

HEADSCALE_IMAGE = "friday-os-stack/headscale:0.26.1-amd64"
TAILSCALE_IMAGE = "friday-os-stack/tailscale:1.82.5-amd64"
DNS_BASE = "friday.mesh"
USER_NAME = "friday"
LOCAL_PORT = "8443"
BLOCKED_PORTS = frozenset({8080, 11434, 5432, 6333, 8090, 6334})
CORE_HOSTS = frozenset({"postgres", "qdrant", "memory-mcp", "executor"})
_KEY = re.compile(r"[A-Za-z0-9._:-]{10,200}")
_KEY_WHOLE = re.compile(r"[A-Za-z0-9._:-]{10,200}\Z")


@dataclass(frozen=True)
class Choice:
    mode: str
    url: str
    key: str
    port: str
    reason: str


def choose_local() -> Choice:
    return Choice("local", "", "", LOCAL_PORT, "")


def choose_join(url: str, key: str) -> Choice:
    cleaned, reason = _url(url, creating=False)
    if reason:
        return Choice("", "", "", "", reason)
    secret = _key(key)
    if not secret:
        return Choice("", "", "", "", "mesh_key_missing")
    return Choice("join", cleaned, secret, LOCAL_PORT, "")


def choose_create(url: str) -> Choice:
    cleaned, reason = _url(url, creating=True)
    if reason:
        return Choice("", "", "", "", reason)
    port = str(urlsplit(cleaned).port)
    return Choice("create", cleaned, "", port, "")


def images_for(mode: str) -> tuple[str, ...]:
    if mode == "join":
        return (TAILSCALE_IMAGE,)
    if mode == "create":
        return (HEADSCALE_IMAGE, TAILSCALE_IMAGE)
    return ()


def render_headscale_config(server_url: str, port: int) -> str:
    """YAML Headscale can start from. The auth key is not in this file."""
    quoted = json.dumps(server_url)
    return f"""server_url: {quoted}
listen_addr: 0.0.0.0:{port}
metrics_listen_addr: 127.0.0.1:9090
grpc_listen_addr: 127.0.0.1:50443
grpc_allow_insecure: false
noise:
  private_key_path: /var/lib/headscale/noise_private.key
prefixes:
  v4: 100.64.0.0/10
  v6: fd7a:115c:a1e0::/48
  allocation: sequential
derp:
  server:
    enabled: false
  urls:
    - https://controlplane.tailscale.com/derpmap/default
  paths: []
  auto_update_enabled: true
  update_frequency: 24h
disable_check_updates: true
database:
  type: sqlite
  sqlite:
    path: /var/lib/headscale/db.sqlite
    write_ahead_log: true
policy:
  mode: database
dns:
  magic_dns: true
  base_domain: {DNS_BASE}
  override_local_dns: false
  nameservers:
    global:
      - 1.1.1.1
      - 1.0.0.1
logtail:
  enabled: false
unix_socket: /var/run/headscale/headscale.sock
unix_socket_permission: "0770"
"""


def user_create_argv() -> list[str]:
    return [
        "docker",
        "exec",
        "friday-headscale-1",
        "headscale",
        "users",
        "create",
        USER_NAME,
        "--output",
        "json",
    ]


def user_list_argv() -> list[str]:
    return [
        "docker",
        "exec",
        "friday-headscale-1",
        "headscale",
        "users",
        "list",
        "--name",
        USER_NAME,
        "--output",
        "json",
    ]


def preauth_argv(user_id: str) -> list[str]:
    return [
        "docker",
        "exec",
        "friday-headscale-1",
        "headscale",
        "preauthkeys",
        "create",
        "--user",
        user_id,
        "--expiration",
        "168h",
        "--reusable=false",
    ]


def serve_argv() -> list[str]:
    """Publish the Board's local port as HTTP on mesh port 80.

    Headscale 0.26.1 completes this with MagicDNS. The mesh carries the HTTP.
    """
    return [
        "docker",
        "exec",
        "friday-tailscale-1",
        "tailscale",
        "serve",
        "--bg",
        "--http=80",
        "8080",
    ]


def user_id(text: str) -> str:
    """Numeric id for the friday user in Headscale JSON. Empty when it is absent."""
    payload = _json_payload(text)
    if payload is None:
        return ""
    return _friday_id(payload)


def take_key(text: str) -> str:
    """Last key-shaped token in Headscale's text. Empty when the text has none."""
    found = ""
    if not isinstance(text, str):
        return ""
    for match in _KEY.finditer(text):
        token = match.group(0)
        if re.match(r"\d{4}-\d{2}-\d{2}", token):
            continue
        if any(char.isalpha() for char in token):
            found = token
    return found


def _url(raw: str, *, creating: bool) -> tuple[str, str]:
    if not isinstance(raw, str) or len(raw) > 300 or "\n" in raw or "\r" in raw:
        return "", "mesh_url"
    stripped = raw.strip()
    if stripped == "":
        return "", "mesh_url"
    decoded = _unwrap(stripped)
    if credential_shape(stripped) or credential_shape(decoded):
        return "", "mesh_url"
    try:
        parts = urlsplit(decoded)
    except ValueError:
        return "", "mesh_url"
    if parts.scheme.lower() not in {"http", "https"}:
        return "", "mesh_url"
    if parts.username or parts.password or parts.query or parts.fragment:
        return "", "mesh_url"
    if parts.path not in {"", "/"}:
        return "", "mesh_url"
    host = parts.hostname or ""
    if host == "" or host.lower() in CORE_HOSTS:
        return "", "mesh_url"
    try:
        port = parts.port
    except ValueError:
        return "", "mesh_url"
    if creating and (port is None or port in BLOCKED_PORTS):
        return "", "mesh_port"
    if creating and (_loopback(host) or _magic(host)):
        return "", "mesh_url"
    return _normalize(parts), ""


def _key(value: str) -> str:
    if not isinstance(value, str) or "\n" in value or "\r" in value:
        return ""
    if value.strip() != value:
        return ""
    if _KEY_WHOLE.fullmatch(value) is None:
        return ""
    if not any(char.isalpha() for char in value):
        return ""
    return value


def _unwrap(value: str) -> str:
    current = value
    for _ in range(3):
        decoded = unquote_plus(current)
        if decoded == current:
            break
        current = decoded
    return current


def _loopback(host: str) -> bool:
    name = host.lower()
    if name in {"localhost", "127.0.0.1", "0.0.0.0", "::1"}:
        return True
    try:
        address = ipaddress.ip_address(name)
    except ValueError:
        return False
    return bool(address.is_loopback or address.is_unspecified)


def _magic(host: str) -> bool:
    name = host.lower().rstrip(".")
    return name == DNS_BASE or name.endswith("." + DNS_BASE)


def _normalize(parts) -> str:
    host = parts.hostname or ""
    if ":" in host:
        shown = f"[{host.lower()}]"
    else:
        shown = host.lower()
    if parts.port:
        return f"{parts.scheme.lower()}://{shown}:{parts.port}"
    return f"{parts.scheme.lower()}://{shown}"


def _json_payload(text: str):
    if not isinstance(text, str):
        return None
    stripped = text.strip()
    start = -1
    for index, char in enumerate(stripped):
        if char in "{[":
            start = index
            break
    if start < 0:
        return None
    try:
        payload, _end = json.JSONDecoder().raw_decode(stripped[start:])
    except json.JSONDecodeError:
        return None
    return payload


def _friday_id(payload) -> str:
    if isinstance(payload, dict):
        name = payload.get("name", payload.get("Name", ""))
        if name == USER_NAME:
            digits = _digits(payload.get("id", payload.get("Id")))
            if digits:
                return digits
        for value in payload.values():
            if isinstance(value, (dict, list)):
                found = _friday_id(value)
                if found:
                    return found
        return ""
    if isinstance(payload, list):
        for item in payload:
            found = _friday_id(item)
            if found:
                return found
    return ""


def _digits(value) -> str:
    if isinstance(value, bool) or isinstance(value, float):
        return ""
    if isinstance(value, int) and value > 0:
        return str(value)
    if isinstance(value, str) and value.isdigit() and int(value) > 0:
        return str(int(value))
    return ""
