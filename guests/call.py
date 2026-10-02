"""Record one API call the Board asked a named advisor to make.

The sentence is "An API call was asked." The note under it is not a
goal and it is not a command. The call is not made. The gateway is not
opened. An adopted app can be recorded the same way. Starting,
stopping, and pulling are not this record.

The named advisor is media for Jellyfin and Plex, fetcher for Radarr,
Sonarr, Prowlarr, qBittorrent, and Bazarr, and home for Home Assistant.
The tool names are the ones those wires already list. This module does
not read the wire files. A tool stays off until the Board accepts that
name. Accepting one name does not accept another, and it does not
accept that name for another app. A new name stays off.

The Board is the only actor. Chat cannot record a call or accept a
name, and that refusal leaves a row and an accepted name. A second
record keeps the first tool and the first note. A credential-shaped
name, advisor, tool, or note is not stored, including a percent-encoded
or plus-encoded copy. "The password is kept outside the machine" can
be a note. Refusing the call does not stop qBittorrent's swarm.

confirmed=true is ignored. This module does not create an approval,
does not open a socket, and does not call the app. Friday's ask path
does not call it.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from urllib.parse import unquote_plus

from memoryd.store import credential_shape
from netpolicy.paths import CORE_NAMES

SAID = "An API call was asked."
_ID = re.compile(r"[a-z][a-z0-9-]{0,63}\Z")
_NOTE_LIMIT = 1200
# Advisor, then the tool names that advisor may use for that one app.
CALLS = {
    "jellyfin": ("media", ("player",)),
    "plex": ("media", ("player",)),
    "radarr": ("fetcher", ("radarr",)),
    "sonarr": ("fetcher", ("sonarr",)),
    "prowlarr": ("fetcher", ("prowlarr",)),
    "qbittorrent": ("fetcher", ("qbittorrent",)),
    "bazarr": ("fetcher", ("bazarr",)),
    "home-assistant": ("home", ("home_status", "home_control")),
}


@dataclass(frozen=True)
class Decision:
    outcome: str
    reason: str
    app_id: str = ""
    advisor: str = ""
    tool: str = ""
    said: str = ""
    note: str = ""
    on: tuple[str, ...] = ()
    kept: bool = False
    tools_on: bool = False
    via: str = ""
    opened: bool = False
    called: bool = False
    sent: bool = False
    started: bool = False
    stopped: bool = False
    pulled: bool = False
    performed: bool = False
    swarm_stopped: bool = False


class Book:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.rows: dict[str, dict] = {}
        self.accepted: dict[str, tuple[str, ...]] = {}

    def __repr__(self) -> str:
        return "Book()"


def accept_tool(
    book: Book,
    *,
    app_id: object,
    advisor: object,
    tool: object,
    actor: object,
    wire_level: object = "known",
    mark: object = None,
    confirmed: bool = False,
) -> Decision:
    del confirmed
    name, expected, allowed, reason = _target(app_id, advisor, wire_level, mark)
    if reason:
        return _quiet(reason)
    picked, reason = _tool(tool, allowed)
    if reason:
        return _quiet(reason)
    if _chat(actor):
        return _names(book, name, expected, "chat_cannot")
    if actor != "board":
        return _names(book, name, expected, "actor_cannot")
    with book._lock:
        current = book.accepted.get(name, ())
        if picked in current:
            return _on(name, expected, picked, current, "already")
        nxt = tuple(item for item in allowed if item in current or item == picked)
        book.accepted[name] = nxt
        return _on(name, expected, picked, nxt, "owner_accepted", outcome="accepted")


def record_call(
    book: Book,
    *,
    app_id: object,
    advisor: object,
    tool: object,
    actor: object,
    wire_level: object = "known",
    mark: object = None,
    note: object = "",
    confirmed: bool = False,
) -> Decision:
    del confirmed
    name, expected, allowed, reason = _target(app_id, advisor, wire_level, mark)
    if reason:
        return _quiet(reason)
    picked, reason = _tool(tool, allowed)
    if reason:
        return _quiet(reason)
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
        if picked not in book.accepted.get(name, ()):
            return _quiet("tool_off")
        stored = {"said": SAID, "note": cleaned, "advisor": expected, "tool": picked}
        book.rows[name] = stored
        return _from(name, stored, "not_called")


def shown(book: Book, app_id: object) -> Decision:
    name, reason = _app(app_id)
    if reason:
        return _quiet(reason)
    with book._lock:
        row = book.rows.get(name)
        if row is None:
            return _quiet("no_call")
        return _from(name, row, "not_called")


def _target(app_id: object, advisor: object, wire_level: object, mark: object):
    name, reason = _app(app_id)
    if reason:
        return "", "", (), reason
    spec = CALLS.get(name)
    if spec is None:
        return "", "", (), "not_in_manifest"
    if wire_level != "known":
        return "", "", (), "not_known"
    if mark not in ("managed", "adopted"):
        return "", "", (), "not_managed"
    expected, allowed = spec
    who, reason = _advisor(advisor, expected)
    if reason:
        return "", "", (), reason
    return name, who, allowed, ""


def _from(app_id: str, row: dict, reason: str) -> Decision:
    return Decision(
        "recorded",
        reason,
        app_id=app_id,
        advisor=row["advisor"],
        tool=row["tool"],
        said=row["said"],
        note=row["note"],
        kept=True,
        tools_on=True,
        via="gateway",
        opened=False,
        called=False,
        sent=False,
        started=False,
        stopped=False,
        pulled=False,
        performed=False,
        swarm_stopped=False,
    )


def _on(
    app_id: str,
    advisor: str,
    tool: str,
    on: tuple[str, ...],
    reason: str,
    *,
    outcome: str = "accepted",
) -> Decision:
    return Decision(
        outcome,
        reason,
        app_id=app_id,
        advisor=advisor,
        tool=tool,
        on=on,
        kept=True,
        tools_on=bool(on) and (tool == "" or tool in on),
        opened=False,
        called=False,
        sent=False,
        started=False,
        stopped=False,
        pulled=False,
        performed=False,
        swarm_stopped=False,
    )


def _names(book: Book, app_id: str, advisor: str, reason: str) -> Decision:
    with book._lock:
        current = book.accepted.get(app_id, ())
        if not current:
            return _quiet(reason)
        return _on(app_id, advisor, "", current, reason, outcome="refused")


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


def _advisor(value: object, expected: str) -> tuple[str, str]:
    if not isinstance(value, str) or value == "" or value != value.strip() or "\n" in value or "\r" in value:
        return "", "advisor"
    if _hidden(value):
        return "", "credential"
    if value == "family":
        return "", "family_blocked"
    if value != expected:
        return "", "not_that_advisor"
    return value, ""


def _tool(value: object, allowed: tuple[str, ...]) -> tuple[str, str]:
    if isinstance(value, (list, tuple)) or not isinstance(value, str):
        return "", "tool"
    if value == "" or value != value.strip() or "\n" in value or "\r" in value:
        return "", "tool"
    if _hidden(value):
        return "", "credential"
    if value not in allowed:
        return "", "not_in_manifest"
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
