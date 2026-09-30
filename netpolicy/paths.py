"""Decide which name may open which port.

An app may open the webhook receiver on port 8080. It may not open a
core service, including the gateway's core listener. The executor may
health-check an app by its Compose DNS name. An advisor reaches an app
only through the gateway on port 8090 when the wire allows that call.
The browser session has a path to the public internet and no path to a
core name.

An adopted URL is refused for a core service name, a link-local address
(that range covers 169.254.169.254), or the host metadata name. A
private LAN address can be an adopted app. The caller supplies any
resolved addresses. This module does not resolve DNS and does not
create Docker networks.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import Sequence

CORE_NAMES = frozenset({
    "friday",
    "board",
    "qdrant",
    "postgres",
    "ollama",
    "memory-mcp",
    "executor",
    "gateway",
})
METADATA_HOST = "metadata.google.internal"
WEBHOOK_PORT = 8080
GATEWAY_PORT = 8090


@dataclass(frozen=True)
class Decision:
    outcome: str
    reason: str


def _whole(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _host(value: str) -> str:
    text = value.strip()
    if "://" in text:
        text = text.split("://", 1)[1]
    text = text.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    if "@" in text:
        text = text.split("@", 1)[1]
    if text.startswith("["):
        end = text.find("]")
        text = text[1:end] if end != -1 else text
    elif text.count(":") == 1 and not _is_address(text):
        text = text.split(":", 1)[0]
    return text.rstrip(".").casefold()


def _is_address(text: str) -> bool:
    try:
        ipaddress.ip_address(text)
    except ValueError:
        return False
    return True


def _address_reason(host: str) -> str | None:
    if host == METADATA_HOST:
        return "metadata"
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if host in CORE_NAMES:
            return "core_closed"
        return None
    if address.is_link_local:
        return "link_local"
    return None


def _resolved_reason(addresses: Sequence[str]) -> str | None:
    for item in addresses:
        reason = _address_reason(_host(item))
        if reason == "link_local":
            return "link_local"
    return None


def app_can_open(host: str, port: int) -> Decision:
    name = _host(host)
    if name == "webhooks" and port == WEBHOOK_PORT and _whole(port):
        return Decision("allowed", "webhook")
    if name == "webhooks":
        return Decision("refused", "not_the_webhook")
    reason = _address_reason(name)
    if reason is not None:
        return Decision("refused", "core_closed" if reason == "core_closed" else reason)
    return Decision("refused", "not_the_webhook")


def executor_can_open(host: str, port: int) -> Decision:
    name = _host(host)
    reason = _address_reason(name)
    if reason is not None or name == "webhooks" or not _whole(port):
        return Decision("refused", "not_an_app")
    return Decision("allowed", "health")


def advisor_can_open(host: str, port: int, *, wire_allows: bool) -> Decision:
    if _host(host) != "gateway" or port != GATEWAY_PORT or not _whole(port):
        return Decision("refused", "not_the_gateway")
    if wire_allows is not True:
        return Decision("refused", "wire_closed")
    return Decision("allowed", "gateway")


def browser_can_open(host: str, resolved: Sequence[str] = ()) -> Decision:
    name = _host(host)
    reason = _address_reason(name) or _resolved_reason(resolved)
    if reason is not None:
        return Decision("refused", reason)
    return Decision("allowed", "internet")


def vet_adopted(host: str, resolved: Sequence[str] = ()) -> Decision:
    name = _host(host)
    reason = _address_reason(name) or _resolved_reason(resolved)
    if reason is not None:
        return Decision("refused", reason)
    return Decision("allowed", "adopted")
