"""Record that the Board asked to upgrade one known managed app.

The sentence is "An upgrade was asked." The note under it is not a goal
and it is not a command. The image is not upgraded. The container is not
restarted. A catalog upgrade does not turn a new tool on. A tool stays
off until the Board accepts that name. Accepting one name does not
accept another, and it does not accept that name for another app.

An adopted app is not upgraded. Pulling, starting, stopping, and calling
are not this record. Refusing the upgrade does not stop qBittorrent's
swarm.

The Board is the only actor. Chat cannot record one or accept a name,
and that refusal leaves the row and an accepted name. The family role
is blocked. A second record keeps the first note and the first tool
list. A credential-shaped name, tool, or note is not stored, including
a percent-encoded or plus-encoded copy. "The password is kept outside
the machine" can be a note. A tool list that is not a list of names
does not clear the list.

confirmed=true is ignored. apply_upgrade returns catalog_install_closed.
This module does not create an approval, does not read the draft wires,
does not open a socket, and does not pull an image. Friday's ask path
does not call it.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from urllib.parse import unquote_plus

from memoryd.store import credential_shape
from netpolicy.paths import CORE_NAMES

SAID = "An upgrade was asked."
_ID = re.compile(r"[a-z][a-z0-9-]{0,63}\Z")
_TOOL = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")
_NOTE_LIMIT = 1200
_TOOL_CAP = 8


@dataclass(frozen=True)
class Decision:
    outcome: str
    reason: str
    app_id: str = ""
    said: str = ""
    note: str = ""
    tools: tuple[str, ...] = ()
    on: tuple[str, ...] = ()
    kept: bool = False
    tools_on: bool = False
    upgraded: bool = False
    restarted: bool = False
    pulled: bool = False
    started: bool = False
    stopped: bool = False
    called: bool = False
    performed: bool = False
    applied: bool = False
    swarm_stopped: bool = False


class Book:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.rows: dict[str, dict] = {}
        self.accepted: dict[str, tuple[str, ...]] = {}

    def __repr__(self) -> str:
        return "Book()"


def record_upgrade(
    book: Book,
    *,
    app_id: object,
    actor: object,
    wire_level: object = "known",
    mark: object = None,
    note: object = "",
    tools: object = (),
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
    offered, reason = _tools(tools)
    if reason == "credential":
        return _quiet(reason)
    if reason:
        return _leave(book, name, reason, refused=True)
    if _family(actor):
        return _leave(book, name, "family_blocked")
    if _chat(actor):
        return _leave(book, name, "chat_cannot")
    if actor != "board":
        return _leave(book, name, "actor_cannot")
    with book._lock:
        row = book.rows.get(name)
        if row is not None:
            return _from(book, name, row, "already")
        stored = {"said": SAID, "note": cleaned, "tools": offered}
        book.rows[name] = stored
        book.accepted[name] = ()
        return _from(book, name, stored, "not_upgraded")


def accept_tool(
    book: Book,
    *,
    app_id: object,
    tool: object,
    actor: object,
    wire_level: object = "known",
    mark: object = None,
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
    picked, reason = _one_tool(tool)
    if reason:
        return _quiet(reason)
    if _family(actor):
        return _leave(book, name, "family_blocked")
    if _chat(actor):
        return _leave(book, name, "chat_cannot")
    if actor != "board":
        return _leave(book, name, "actor_cannot")
    with book._lock:
        row = book.rows.get(name)
        if row is None:
            return _quiet("no_upgrade")
        offered = row["tools"]
        current = book.accepted.get(name, ())
        if picked not in offered:
            return _from(book, name, row, "not_offered", outcome="refused")
        if picked in current:
            return _from(book, name, row, "already", outcome="accepted")
        nxt = tuple(item for item in offered if item in current or item == picked)
        book.accepted[name] = nxt
        return _from(book, name, row, "owner_accepted", outcome="accepted")


def shown(book: Book, app_id: object) -> Decision:
    name, reason = _app(app_id)
    if reason:
        return _quiet(reason)
    with book._lock:
        row = book.rows.get(name)
        if row is None:
            return _quiet("no_upgrade")
        return _from(book, name, row, "not_upgraded")


def apply_upgrade(
    book: Book,
    app_id: object = "",
    *,
    confirmed: bool = False,
) -> Decision:
    """Refuse the install. Leave the row and any accepted name in place."""
    del confirmed
    name, reason = _app(app_id) if app_id != "" else ("", "")
    if app_id != "" and reason:
        return Decision("refused", "catalog_install_closed", applied=False, upgraded=False)
    with book._lock:
        row = book.rows.get(name) if name else None
        if row is None:
            return Decision("refused", "catalog_install_closed", applied=False, upgraded=False)
        found = _from(book, name, row, "catalog_install_closed", outcome="refused")
    return Decision(
        "refused",
        "catalog_install_closed",
        app_id=found.app_id,
        said=found.said,
        note=found.note,
        tools=found.tools,
        on=found.on,
        kept=True,
        tools_on=False,
        upgraded=False,
        restarted=False,
        pulled=False,
        started=False,
        stopped=False,
        called=False,
        performed=False,
        applied=False,
        swarm_stopped=False,
    )


def _from(
    book: Book,
    app_id: str,
    row: dict,
    reason: str,
    *,
    outcome: str = "recorded",
) -> Decision:
    offered = row["tools"]
    on = tuple(item for item in offered if item in book.accepted.get(app_id, ()))
    return Decision(
        outcome,
        reason,
        app_id=app_id,
        said=row["said"],
        note=row["note"],
        tools=offered,
        on=on,
        kept=True,
        tools_on=bool(on),
        upgraded=False,
        restarted=False,
        pulled=False,
        started=False,
        stopped=False,
        called=False,
        performed=False,
        applied=False,
        swarm_stopped=False,
    )


def _leave(book: Book, app_id: str, reason: str, *, refused: bool = False) -> Decision:
    with book._lock:
        row = book.rows.get(app_id)
        if row is None:
            return _quiet(reason)
        return _from(book, app_id, row, reason, outcome="refused" if refused else "recorded")


def _quiet(reason: str) -> Decision:
    return Decision("refused", reason)


def _family(actor: object) -> bool:
    return isinstance(actor, str) and actor.strip().casefold() == "family"


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


def _tools(value: object) -> tuple[tuple[str, ...] | None, str]:
    if value is None:
        return (), ""
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        return None, "tool_list"
    names: list[str] = []
    for item in value:
        picked, reason = _one_tool(item)
        if reason:
            return None, "tool_list" if reason == "tool_name" else reason
        if picked not in names:
            names.append(picked)
    if len(names) > _TOOL_CAP:
        return None, "tool_list"
    return tuple(names), ""


def _one_tool(value: object) -> tuple[str, str]:
    if not isinstance(value, str) or value == "" or value != value.strip() or "\n" in value or "\r" in value:
        return "", "tool_name"
    if _hidden(value):
        return "", "credential"
    if _TOOL.fullmatch(value) is None:
        return "", "tool_name"
    return value, ""


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
