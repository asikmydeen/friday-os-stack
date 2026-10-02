"""Decide a Mattermost roster. This module does not call Mattermost.

One private team, one owner, the Friday bot, and one restricted bot per
enabled charter. Rooms are Cabinet, Dev, Work, and a Friday DM. Dev
lists only software roles that are also enabled. Co-owners stay empty.
A post is accepted from the owner, in one of those rooms, with no
stranger in the room. A bot does not create work.

write_bridge writes one token file when the caller hands it a directory.
It does not read another path. The bootstrap script does not call it.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

ROOMS = ("Cabinet", "Dev", "Work", "Friday")
_NAME = re.compile(r"[a-z][a-z0-9_-]{0,31}")
_OWNER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{7,127}")


@dataclass(frozen=True)
class Decision:
    outcome: str
    reason: str
    owner: str = ""
    bots: tuple[str, ...] = ()
    rooms: tuple[str, ...] = ()
    dev: tuple[str, ...] = ()
    threads: tuple[str, ...] = ()


def roster(
    owner: str,
    charters: tuple[str, ...],
    *,
    co_owners: tuple[str, ...] = (),
    software: tuple[str, ...] = (),
    obligations: tuple[str, ...] = (),
    confirmed: bool = False,
) -> Decision:
    del confirmed
    if _OWNER.fullmatch(owner) is None:
        return Decision("refused", "owner_required")
    if co_owners:
        return Decision("refused", "one_owner")
    if any(_NAME.fullmatch(item) is None or item == "friday" for item in charters):
        return Decision("refused", "charter_required")
    if len(set(charters)) != len(charters):
        return Decision("refused", "charter_required")
    enabled = set(charters)
    if any(item not in enabled for item in software):
        return Decision("refused", "dev_role_disabled")
    if any(_NAME.fullmatch(item) is None for item in obligations) or len(set(obligations)) != len(obligations):
        return Decision("refused", "obligation_name")
    return Decision(
        "recorded",
        "not_started",
        owner=owner,
        bots=("friday",) + tuple(charters),
        rooms=ROOMS,
        dev=tuple(software),
        threads=tuple(obligations),
    )


def accept_post(
    *,
    sender: str,
    room: str,
    members: tuple[str, ...],
    owner: str,
    bots: tuple[str, ...] = (),
    confirmed: bool = False,
) -> Decision:
    del confirmed
    if sender in bots:
        return Decision("refused", "bot_does_not_create_work")
    if room not in ROOMS:
        return Decision("refused", "room_not_enrolled")
    if sender != owner:
        return Decision("refused", "not_owner")
    if owner not in members:
        return Decision("refused", "owner_absent")
    allowed = {owner, *bots}
    if any(member not in allowed for member in members):
        return Decision("refused", "stranger")
    return Decision("accepted", "owner_post", owner=owner)


def write_bridge(directory: Path, token: str) -> Decision:
    if _TOKEN.fullmatch(token) is None:
        return Decision("refused", "token_required")
    if directory.is_symlink() or not directory.is_dir():
        return Decision("refused", "bridge_directory")
    path = directory / "mattermost-bridge.env"
    if path.is_symlink():
        return Decision("refused", "bridge_directory")
    temporary = directory / "mattermost-bridge.env.tmp"
    fd = os.open(temporary, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    try:
        os.write(fd, f"MATTERMOST_BRIDGE_TOKEN={token}\n".encode())
    finally:
        os.close(fd)
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)
    os.chmod(path, 0o600)
    return Decision("recorded", "bridge_written")
