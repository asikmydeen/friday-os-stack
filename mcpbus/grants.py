"""Decide which tools a prompt may see, and which calls wait.

The visible set is the intersection of the names the owner granted and
the names the server offered. Anything else stays out of the prompt.
An inbound mutating call waits for the Board. This function does not
create an approval. A catalog wire is one kind of grant and stays off
until the owner accepts it on the Board.

confirmed=true is ignored. This module does not open a listener.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

MUTATING = frozenset({
    "send",
    "pay",
    "delete",
    "publish",
    "install",
    "uninstall",
    "grant",
    "backup",
    "publish_port",
    "publish_hostname",
    "start",
    "stop",
    "pull",
    "disconnect",
    "upgrade",
})


@dataclass(frozen=True)
class Decision:
    outcome: str
    reason: str


def _names(values: Iterable[str]) -> set[str]:
    return {str(value) for value in values}


def visible(granted: Iterable[str], offered: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(_names(granted) & _names(offered)))


def inbound(
    tool: str,
    granted: Iterable[str],
    offered: Iterable[str],
    *,
    confirmed: bool = False,
) -> Decision:
    del confirmed
    if tool not in visible(granted, offered):
        return Decision("refused", "not_in_prompt")
    if tool in MUTATING:
        return Decision("waiting", "board_must_approve")
    return Decision("allowed", "granted_tool")


def accept_tool(actor: str, tool: str, *, confirmed: bool = False) -> Decision:
    del tool, confirmed
    if actor != "board":
        return Decision("refused", "actor_cannot_approve")
    return Decision("accepted", "owner_accepted")


def wire_as_grant(*, accepted: bool, actor: str = "board") -> Decision:
    if accepted is True and actor == "board":
        return Decision("granted", "accepted")
    return Decision("off", "awaiting_acceptance")
