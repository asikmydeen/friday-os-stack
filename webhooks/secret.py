"""Record one generated webhook secret per app.

The Board asks. The name comes back. The value stays in this process.
It is not shown, not written to a file, and not placed on the process
environment. It is not the notify token. A caller-supplied value is
not stored. Chat cannot record one, and that refusal leaves a secret
the Board already recorded.

Jellyfin, Radarr, and Sonarr are the only apps. A second record for
the same app keeps the first value. Radarr and Sonarr do not share a
secret. A 64-character hex value is the generated secret. Any other
credential-shaped draw is not stored. This module does not open a
socket, does not post the webhook, and does not open Postgres.
Friday's ask path does not call it.
"""

from __future__ import annotations

import hmac
import threading
from dataclasses import dataclass

from memoryd.store import credential_shape

APPS = {
    "jellyfin": "WEBHOOK_SECRET_JELLYFIN",
    "radarr": "WEBHOOK_SECRET_RADARR",
    "sonarr": "WEBHOOK_SECRET_SONARR",
}
# Radarr and Sonarr share the /arr route. One secret for both is ambiguous.
PEERS = {
    "jellyfin": (),
    "radarr": ("sonarr",),
    "sonarr": ("radarr",),
}
_HEX = frozenset("0123456789abcdef")


@dataclass(frozen=True)
class Decision:
    outcome: str
    reason: str
    name: str = ""


class Book:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._values: dict[str, str] = {}

    def __repr__(self) -> str:
        return "Book()"


def register(
    book: Book,
    app: object,
    *,
    actor: str,
    rng,
    supplied: object = None,
    notify_token: object = "",
    confirmed: bool = False,
) -> Decision:
    del confirmed
    if actor != "board":
        return Decision("refused", "board_only", name=_name(app))
    name = _name(app)
    if name == "":
        return Decision("refused", "not_a_webhook_app")
    if supplied is not None and supplied != "":
        return Decision("refused", "caller_value", name=name)
    key = str(app)
    notify = notify_token if isinstance(notify_token, str) else ""
    with book._lock:
        if key in book._values:
            return Decision("recorded", "name_only", name=name)
        value = _mint(rng, _blocked(book, key, notify))
        if value is None:
            return Decision("refused", "not_minted", name=name)
        book._values[key] = value
        return Decision("recorded", "name_only", name=name)


def show(book: Book, app: object) -> Decision:
    name = _name(app)
    with book._lock:
        if name == "" or str(app) not in book._values:
            return Decision("refused", "unknown_secret")
    return Decision("refused", "value_hidden", name=name)


def matches(book: Book, app: object, header: object) -> bool:
    if not isinstance(app, str) or not isinstance(header, str):
        return False
    with book._lock:
        secret = book._values.get(app)
    if not isinstance(secret, str) or secret == "" or header == "":
        return False
    try:
        return hmac.compare_digest(secret, header)
    except (TypeError, ValueError):
        return False


def names(book: Book) -> tuple[str, ...]:
    with book._lock:
        held = set(book._values)
    return tuple(APPS[app] for app in ("jellyfin", "radarr", "sonarr") if app in held)


def _name(app: object) -> str:
    if not isinstance(app, str):
        return ""
    return APPS.get(app, "")


def _blocked(book: Book, app: str, notify: str) -> tuple[str, ...]:
    blocked = []
    if notify != "":
        blocked.append(notify)
    for peer in PEERS[app]:
        peer_value = book._values.get(peer, "")
        if isinstance(peer_value, str) and peer_value != "":
            blocked.append(peer_value)
    return tuple(blocked)


def _draw(rng) -> str | None:
    try:
        value = rng.token_hex(32)
    except Exception:
        return None
    if not isinstance(value, str) or value == "" or "\n" in value or "\r" in value:
        return None
    if _generated_hex(value):
        return value
    if credential_shape(value):
        return None
    return value


def _generated_hex(value: str) -> bool:
    return len(value) == 64 and all(char in _HEX for char in value)


def _mint(rng, blocked: tuple[str, ...]) -> str | None:
    first = _draw(rng)
    if first is None:
        return None
    if first not in blocked:
        return first
    second = _draw(rng)
    if second is None or second in blocked:
        return None
    return second
