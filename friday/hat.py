"""Whose charter the next turn wears.

"ask my <role>" and "@<role>" last for that turn. "talk to my <role>"
and "stay with <role>" keep that charter for later turns from the same
caller, until "back to Friday". "stay with that advisor" keeps the
charter from the latest one-turn address. A one-turn address does not
replace a stay. The book is in this process. A restart returns to
Friday. Nothing here writes a note, accepts a tool, or opens a socket.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass

from friday.charters import Charter
from memoryd.store import credential_shape

BACK = re.compile(r"^back to friday\b", re.IGNORECASE)
THAT = re.compile(
    r"^stay with (?:that(?:\s+advisor)?|them)\b[:,\s]*(.*)$",
    re.IGNORECASE | re.DOTALL,
)
STAY = re.compile(
    r"^(?:stay with(?: my)?|talk to my)\s+([A-Za-z0-9_-]+)\b[:,\s]*(.*)$",
    re.IGNORECASE | re.DOTALL,
)
ASK = re.compile(
    r"^(?:ask my |@)([A-Za-z0-9_-]+)\b[:,\s]*(.*)$",
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True)
class Turn:
    role: Charter | None
    content: str
    reason: str = ""


class Hats:
    """Stay book for one process. The key is the caller, not the role."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.staying: dict[tuple[str, str], str] = {}
        self.asked: dict[tuple[str, str], str] = {}


def sign(reply: str, role: Charter | None) -> str:
    """A spoken reply from a charter starts with that charter's name."""
    if role is None or not reply:
        return reply
    prefix = role.name + ": "
    if reply.startswith(prefix):
        return reply
    return prefix + reply


def address(
    text: str,
    charters: dict[str, Charter],
    hats: Hats,
    owner_id: str,
    owner_kind: str,
) -> Turn:
    stripped = text.strip()
    key = (owner_id, owner_kind)
    with hats._lock:
        if BACK.match(stripped):
            hats.staying.pop(key, None)
            hats.asked.pop(key, None)
            return Turn(None, stripped)
        stayed = _kept(charters, hats, key)
        that = THAT.match(stripped)
        if that:
            if credential_shape(owner_id):
                return Turn(None, "", "credential")
            pinned = _named(charters, hats.asked.get(key))
            if pinned is None:
                hats.asked.pop(key, None)
            else:
                hats.staying[key] = pinned.id
                return Turn(pinned, that.group(1).strip(), "staying")
        match = STAY.match(stripped)
        if match:
            charter = charters.get(match.group(1).casefold())
            if charter is not None:
                if credential_shape(owner_id):
                    return Turn(None, "", "credential")
                hats.staying[key] = charter.id
                hats.asked[key] = charter.id
                return Turn(charter, match.group(2).strip(), "staying")
        match = ASK.match(stripped)
        if match:
            charter = charters.get(match.group(1).casefold())
            if charter is not None:
                if not credential_shape(owner_id):
                    hats.asked[key] = charter.id
                rest = match.group(2).strip()
                return Turn(charter, rest or stripped)
        if stayed is not None:
            return Turn(stayed, stripped)
        return Turn(None, stripped)


def _kept(charters: dict[str, Charter], hats: Hats, key: tuple[str, str]) -> Charter | None:
    charter = _named(charters, hats.staying.get(key))
    if charter is None and key in hats.staying:
        hats.staying.pop(key, None)
    return charter


def _named(charters: dict[str, Charter], role_id: object) -> Charter | None:
    if not isinstance(role_id, str) or role_id == "":
        return None
    charter = charters.get(role_id.casefold())
    if charter is None or charter.id != role_id:
        return None
    return charter
