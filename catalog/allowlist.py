"""Allowlist jellyfin. Every other catalog id stays closed.

One fire from the Board adds jellyfin and no other id. A second fire
keeps that same id. Install of an id that is not on the list stays
closed. Install of jellyfin stays closed too: membership is not
permission to start a container. confirmed=true is ignored.

Chat cannot fire it, and that refusal leaves an id already allowlisted.
A credential-shaped id is not stored, including a percent-encoded or
plus-encoded copy. This module does not store a sentence, does not read
the draft wires, does not write catalog/PIN, does not open a file, and
does not start a container. Friday's ask path does not call it.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from urllib.parse import unquote_plus

from memoryd.store import credential_shape

ONLY = "jellyfin"
_ID = re.compile(r"[a-z][a-z0-9-]{0,63}\Z")


@dataclass(frozen=True)
class Decision:
    outcome: str
    reason: str
    app_id: str = ""
    allowlisted: bool = False
    install: str = "refused"
    started: bool = False
    applied: bool = False


class Book:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.ids: set[str] = set()

    def __repr__(self) -> str:
        return "Book()"


def fire(
    book: Book,
    *,
    actor: object,
    app_id: object,
    confirmed: bool = False,
) -> Decision:
    del confirmed
    name, reason = _name(app_id)
    if reason:
        return _quiet(reason)
    if _chat(actor):
        return _leave(book, name, "chat_cannot_allow")
    if actor != "board":
        return _leave(book, name, "actor_cannot_allow")
    if name != ONLY:
        return _leave(book, name, "stays_closed")
    with book._lock:
        book.ids.add(ONLY)
    return _member(name, "allowlisted", "jellyfin")


def install(
    book: Book,
    app_id: object,
    *,
    confirmed: bool = False,
) -> Decision:
    del confirmed
    name, reason = _name(app_id)
    if reason:
        return _quiet(reason)
    if name not in book.ids:
        return _closed(name, allowlisted=False)
    return _closed(name, allowlisted=True)


def _member(name: str, outcome: str, reason: str) -> Decision:
    return Decision(
        outcome,
        reason,
        app_id=name,
        allowlisted=True,
        install="refused",
        started=False,
        applied=False,
    )


def _closed(name: str, *, allowlisted: bool) -> Decision:
    return Decision(
        "refused",
        "catalog_install_closed",
        app_id=name,
        allowlisted=allowlisted,
        install="refused",
        started=False,
        applied=False,
    )


def _leave(book: Book, name: str, reason: str) -> Decision:
    on = name == ONLY and name in book.ids
    return Decision(
        "refused",
        reason,
        app_id=name,
        allowlisted=on,
        install="refused",
        started=False,
        applied=False,
    )


def _quiet(reason: str) -> Decision:
    return Decision("refused", reason)


def _chat(actor: object) -> bool:
    return isinstance(actor, str) and actor.strip().casefold() == "chat"


def _name(value: object) -> tuple[str, str]:
    if not isinstance(value, str):
        return "", "app_id"
    if _hidden(value):
        return "", "credential"
    name = value.strip().casefold()
    if name == "" or _hidden(name) or _ID.fullmatch(name) is None:
        return "", "app_id"
    return name, ""


def _hidden(text: str) -> bool:
    seen = text
    for _ in range(3):
        if credential_shape(" ".join(seen.split())):
            return True
        decoded = unquote_plus(seen)
        if decoded == seen:
            return False
        seen = decoded
    return credential_shape(" ".join(seen.split()))
