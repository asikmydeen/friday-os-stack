"""Decide what a disposable browser session may do.

The session sits on its own network. A credential broker may hold the
vault entry for that session. The model receives page text and does not
receive the secret. Read and draft proceed. Send, pay, delete, and
publish wait for an approval. confirmed=true is ignored.

This module does not start a browser and does not open a socket.
"""

from __future__ import annotations

from dataclasses import dataclass

OPEN = frozenset({"read", "draft"})
WAITING = frozenset({"send", "pay", "delete", "publish"})


@dataclass(frozen=True)
class Decision:
    outcome: str
    reason: str


def placement() -> Decision:
    return Decision("isolated", "own_network")


def credential(who: str) -> Decision:
    if who == "model":
        return Decision("withheld", "model_sees_evidence")
    if who == "broker":
        return Decision("held", "for_the_session")
    return Decision("refused", "unknown_party")


def act(action: str, *, confirmed: bool = False) -> Decision:
    del confirmed
    if action in OPEN:
        return Decision("allowed", action)
    if action in WAITING:
        return Decision("waiting", "approval_required")
    return Decision("refused", "unknown_action")
