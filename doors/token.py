"""Record one generated secret for the messaging door.

The Board asks. The name DOOR_TOKEN comes back. The value stays in
this process. It is not shown, not written to a file, and not placed
on the process environment. It is not the notify token and it is not
the inbound MCP token. A caller-supplied value is not stored. Chat
cannot record one, and that refusal leaves a secret the Board already
recorded.

A second record keeps the first value. A 64-character lowercase hex
value is the generated secret. Any other credential-shaped draw is
not stored. Recording it does not start the door and does not create
an approval. This module does not open a socket and does not call
Friday. doors/server.py still reads the environment and does not call
this record. Friday's ask path does not call it.
"""

from __future__ import annotations

import hmac
import threading
from dataclasses import dataclass

from memoryd.store import credential_shape

NAME = "DOOR_TOKEN"
KEPT = "The password is kept outside the machine"
_HEX = frozenset("0123456789abcdef")


@dataclass(frozen=True)
class Decision:
    outcome: str
    reason: str
    name: str = ""
    listening: bool = False
    approved: bool = False


class Book:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._value: str | None = None

    def __repr__(self) -> str:
        return "Book()"


def record_token(
    book: Book,
    *,
    actor: str,
    rng,
    supplied: object = None,
    notify_token: object = "",
    mcp_token: object = "",
    confirmed: bool = False,
) -> Decision:
    del confirmed
    held = _held(book)
    if actor != "board":
        return _no("board_only", name=NAME if held else "")
    if held:
        return _keep(supplied)
    reason = _supplied(supplied)
    if reason == "credential":
        return _no("credential")
    if reason:
        return _no(reason, name=NAME)
    blocked = tuple(item for item in (notify_token, mcp_token) if isinstance(item, str) and item != "")
    with book._lock:
        if book._value is not None:
            return _named("recorded", "name_only")
        value = _mint(rng, blocked)
        if value is None:
            return _no("not_minted", name=NAME)
        book._value = value
    return _named("recorded", "name_only")


def show(book: Book) -> Decision:
    if not _held(book):
        return _no("unknown_secret")
    return _named("refused", "value_hidden")


def names(book: Book) -> tuple[str, ...]:
    if not _held(book):
        return ()
    return (NAME,)


def matches(book: Book, header: object) -> bool:
    if not isinstance(header, str) or header == "":
        return False
    with book._lock:
        secret = book._value
    if not isinstance(secret, str) or secret == "":
        return False
    try:
        return hmac.compare_digest(secret, header)
    except (TypeError, ValueError):
        return False


def _held(book: Book) -> bool:
    with book._lock:
        return book._value is not None


def _keep(supplied: object) -> Decision:
    reason = _supplied(supplied)
    if reason == "credential":
        return _named("recorded", "name_only")
    if reason:
        return _named("refused", reason)
    return _named("recorded", "name_only")


def _supplied(value: object) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, str) and value != KEPT and credential_shape(value):
        return "credential"
    return "caller_value"


def _draw(rng) -> str | None:
    try:
        value = rng.token_hex(32)
    except Exception:
        return None
    if not isinstance(value, str) or value == "" or "\n" in value or "\r" in value:
        return None
    if len(value) == 64 and all(char in _HEX for char in value):
        return value
    if credential_shape(value):
        return None
    return value


def _mint(rng, blocked: tuple[str, ...]) -> str | None:
    if rng is None:
        return None
    first = _draw(rng)
    if first is None:
        return None
    if first not in blocked:
        return first
    second = _draw(rng)
    if second is None or second in blocked:
        return None
    return second


def _named(outcome: str, reason: str) -> Decision:
    return Decision(outcome, reason, name=NAME, listening=False, approved=False)


def _no(reason: str, *, name: str = "") -> Decision:
    return Decision("refused", reason, name=name, listening=False, approved=False)
