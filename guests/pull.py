"""Record that the Board asked to pull one known managed app.

The sentence is "A pull was asked." The note under it is not a goal
and it is not a command. The image is not pulled. An adopted app is
not pulled. Starting is not this record. Stopping is not this record.

The Board is the only actor. Chat cannot record one, and that refusal
leaves a row already recorded. A second record keeps the first name and
the first note. A credential-shaped name or note is not stored,
including a percent-encoded or plus-encoded copy. "The password is kept
outside the machine" can be a note.

confirmed=true is ignored. This module does not create an approval,
does not start or stop a container, does not open a socket, and does
not pull an image. Friday's ask path does not call it.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from urllib.parse import unquote_plus

from memoryd.store import credential_shape
from netpolicy.paths import CORE_NAMES

SAID = "A pull was asked."
_ID = re.compile(r"[a-z][a-z0-9-]{0,63}\Z")
_NOTE_LIMIT = 1200


@dataclass(frozen=True)
class Decision:
    outcome: str
    reason: str
    app_id: str = ""
    said: str = ""
    note: str = ""
    kept: bool = False
    pulled: bool = False
    started: bool = False
    stopped: bool = False
    performed: bool = False
    called: bool = False


class Book:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.rows: dict[str, dict] = {}

    def __repr__(self) -> str:
        return "Book()"


def record_pull(
    book: Book,
    *,
    app_id: object,
    actor: object,
    wire_level: object = "known",
    mark: object = None,
    note: object = "",
    confirmed: bool = False,
) -> Decision:
    del confirmed
    name, reason = _app(app_id)
    if reason:
        return _quiet(reason)
    if wire_level != "known":
        return _quiet("not_known")
    if mark != "managed":
        return _quiet("not_managed")
    cleaned, reason = _note(note)
    if reason:
        return _quiet(reason)
    if _chat(actor):
        return _kept(book, name, "chat_cannot")
    if actor != "board":
        return _kept(book, name, "actor_cannot")
    with book._lock:
        row = book.rows.get(name)
        if row is not None:
            return _from(name, row, "already")
        stored = {"said": SAID, "note": cleaned}
        book.rows[name] = stored
        return _from(name, stored, "not_pulled")


def shown(book: Book, app_id: object) -> Decision:
    name, reason = _app(app_id)
    if reason:
        return _quiet(reason)
    with book._lock:
        row = book.rows.get(name)
        if row is None:
            return _quiet("no_pull")
        return _from(name, row, "not_pulled")


def _from(app_id: str, row: dict, reason: str) -> Decision:
    return Decision(
        "recorded",
        reason,
        app_id=app_id,
        said=row["said"],
        note=row["note"],
        kept=True,
        pulled=False,
        started=False,
        stopped=False,
        performed=False,
        called=False,
    )


def _kept(book: Book, app_id: str, reason: str) -> Decision:
    with book._lock:
        row = book.rows.get(app_id)
        if row is None:
            return _quiet(reason)
        return _from(app_id, row, reason)


def _quiet(reason: str) -> Decision:
    return Decision("refused", reason)


def _chat(actor: object) -> bool:
    return isinstance(actor, str) and actor.strip().casefold() == "chat"


def _app(value: object) -> tuple[str, str]:
    if not isinstance(value, str) or value == "" or value != value.strip() or "\n" in value or "\r" in value:
        return "", "app_id"
    if _hidden(value):
        return "", "credential"
    if value.casefold() in CORE_NAMES:
        return "", "core_locked"
    if _ID.fullmatch(value) is None:
        return "", "app_id"
    return value, ""


def _note(value: object) -> tuple[str, str]:
    if value is None:
        return "", ""
    if not isinstance(value, str):
        return "", "note_text"
    if value.strip() == "":
        return "", ""
    if _hidden(value):
        return "", "credential"
    flat = " ".join(value.split())
    if _hidden(flat):
        return "", "credential"
    return flat[:_NOTE_LIMIT], ""


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
