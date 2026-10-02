"""Record one public name. Do not publish it.

The tunnel stays off. This module does not call Cloudflare, does not
read a token value, and does not open a socket. Each call names one
route. The Board is the only core service that can be named. Friday's
container is not a route. A media player can be recorded after
Cloudflare Access, or after the app's own login when the caller says
the wire already allows that login.

memory-mcp, Qdrant, Postgres, taskrunner, Radarr, Sonarr, Prowlarr,
and qBittorrent are refused. Refusing those names does not stop
qBittorrent's swarm or indexer calls. A later failed check removes the
name even if the caller says a container is still running. A check
that is not exactly true or false leaves the name in place. Chat
cannot add a name or remove one. confirmed=true is ignored. Friday's
ask path does not call this module.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass

from netpolicy.paths import CORE_NAMES

NON_PUBLISHABLE = frozenset({
    "memory-mcp",
    "qdrant",
    "postgres",
    "taskrunner",
    "radarr",
    "sonarr",
    "prowlarr",
    "qbittorrent",
})
NAMED = frozenset({"board", "jellyfin", "plex"})
_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
_SERVICE = re.compile(r"[a-z][a-z0-9-]{0,63}\Z")
_SECRET = re.compile(r"[A-Z][A-Z0-9_]{0,63}\Z")


@dataclass(frozen=True)
class Decision:
    outcome: str
    reason: str
    name: str = ""
    service: str = ""
    started: bool = False
    created: bool = False
    exposed: bool = False
    called_cloudflare: bool = False
    swarm_stopped: bool = False
    token_name: str = ""


@dataclass(frozen=True)
class Route:
    name: str
    service: str
    access: str
    token_name: str = ""


class Book:
    def __init__(self) -> None:
        self.routes: dict[str, Route] = {}

    def __repr__(self) -> str:
        return "Book()"


def add_name(
    book: Book,
    *,
    actor: str,
    name: object,
    service: object,
    access: object = "",
    wire_login_sufficient: bool = False,
    enabled: bool = False,
    token: object = None,
    token_name: str = "",
    confirmed: bool = False,
) -> Decision:
    del confirmed
    if isinstance(name, (list, tuple)) or isinstance(service, (list, tuple)):
        return _closed("one_at_a_time")
    if enabled is not True:
        return _closed("tunnel_off", outcome="off")
    if actor != "board":
        return _closed("actor_cannot_approve")
    if token is not None and token != "":
        return _closed("value_not_stored")
    host = _hostname(name)
    if host is None:
        return _closed("name")
    target = _service(service)
    if target is None:
        return _closed("service")
    if target in NON_PUBLISHABLE:
        return _closed("not_publishable", name=host, service=target)
    if target == "friday":
        return _closed("friday_not_a_route", name=host, service=target)
    if target in CORE_NAMES and target != "board":
        return _closed("board_only", name=host, service=target)
    if target not in NAMED:
        return _closed("route_not_listed", name=host, service=target)
    chosen = _access(access, wire_login_sufficient)
    if chosen is None:
        kind = access.strip().casefold() if isinstance(access, str) else ""
        reason = "login_not_sufficient" if kind == "app_login" else "access_unchecked"
        return _closed(reason, name=host, service=target)
    secret = _token_name(token_name)
    if secret is None:
        return _closed("secret_name", name=host, service=target)
    if host in book.routes:
        kept = book.routes[host]
        return _closed("already_recorded", name=kept.name, service=kept.service, token_name=kept.token_name)
    book.routes[host] = Route(host, target, chosen, secret)
    return _closed("not_started", outcome="recorded", name=host, service=target, token_name=secret)


def recheck(
    book: Book,
    name: object,
    *,
    actor: str,
    access_ok: object,
    container_running: bool = False,
    confirmed: bool = False,
) -> Decision:
    del container_running, confirmed
    host = _hostname(name)
    if host is None or host not in book.routes:
        return _closed("unknown_name", name=host or "")
    route = book.routes[host]
    if actor != "board":
        return _closed("actor_cannot_approve", name=route.name, service=route.service)
    if access_ok is True:
        return _closed(
            "not_started",
            outcome="recorded",
            name=route.name,
            service=route.service,
            token_name=route.token_name,
        )
    if access_ok is False:
        del book.routes[host]
        return _closed("torn_down", outcome="removed", name=route.name, service=route.service)
    return _closed("access_unchecked", name=route.name, service=route.service)


def _closed(
    reason: str,
    *,
    outcome: str = "refused",
    name: str = "",
    service: str = "",
    token_name: str = "",
) -> Decision:
    return Decision(
        outcome,
        reason,
        name=name,
        service=service,
        token_name=token_name,
    )


def _hostname(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip().casefold().rstrip(".")
    if not text or len(text) > 253 or ".." in text or any(mark in text for mark in "/\\:@#? "):
        return None
    labels = text.split(".")
    if any(_LABEL.fullmatch(label) is None for label in labels):
        return None
    try:
        ipaddress.ip_address(text)
    except ValueError:
        return text
    return None


def _service(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip().casefold()
    if _SERVICE.fullmatch(text) is None:
        return None
    return text


def _access(access: object, wire_login_sufficient: object) -> str | None:
    if not isinstance(access, str):
        return None
    kind = access.strip().casefold()
    if kind == "cloudflare_access":
        return "cloudflare_access"
    if kind == "app_login" and wire_login_sufficient is True:
        return "app_login"
    return None


def _token_name(value: object) -> str | None:
    if value == "":
        return ""
    if not isinstance(value, str) or _SECRET.fullmatch(value) is None:
        return None
    return value
