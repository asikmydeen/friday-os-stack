"""Record one soul proposal. Applying it needs a matching token.

The record names SOUL.md or CHAPTER.md. The Board is the only actor.
Chat cannot record a proposal or apply one. A matching token is the
only way the recorded text replaces the current text, and that token
is not stored. A blank token does not apply. A credential-shaped token
does not apply. A week flag does not apply it and does not schedule
one. A proposal whose name is not SOUL.md or CHAPTER.md does not
replace the current text. The previous text is kept on the record.

This module does not read or write a file, including the example soul.
It does not open Postgres or Qdrant, and it does not create a
collection. The Board page keeps its own record and does not call this
module. confirmed=true is ignored. Friday's ask path does not call
it.
"""

from __future__ import annotations

import hmac
import re
import uuid
from dataclasses import dataclass
from urllib.parse import unquote_plus

from memoryd.store import credential_shape

FILES = frozenset({"SOUL.md", "CHAPTER.md"})
_ACTOR = "board"
_GENERATED = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class Decision:
    outcome: str
    reason: str
    name: str = ""
    proposal_id: str = ""
    path: str = ""
    applied: bool = False
    files_written: bool = False
    example_read: bool = False
    token_stored: bool = False
    scheduled: bool = False


@dataclass
class _Proposal:
    id: str
    name: str
    text: str
    applied: bool = False


@dataclass(frozen=True)
class _Snapshot:
    proposal_id: str
    name: str
    previous: str


class Book:
    def __init__(self) -> None:
        self.current: dict[str, str] = {}
        self.proposals: dict[str, _Proposal] = {}
        self.history: list[_Snapshot] = []

    def __repr__(self) -> str:
        return "Book()"


def record_proposal(
    book: Book,
    *,
    actor: str,
    name: str,
    text: str,
    confirmed: bool = False,
) -> Decision:
    del confirmed
    if actor != _ACTOR:
        return Decision("refused", "board_only")
    if name not in FILES:
        return Decision("refused", "not_a_soul_file")
    if not isinstance(text, str) or text.strip() == "":
        return Decision("refused", "empty")
    body = text.strip()
    if _hidden(body):
        return Decision("refused", "credential")
    if any(item.name == name and not item.applied for item in book.proposals.values()):
        return Decision("refused", "proposal_open")
    proposal_id = uuid.uuid4().hex
    book.proposals[proposal_id] = _Proposal(id=proposal_id, name=name, text=body)
    return Decision(
        "recorded",
        "proposal",
        name=name,
        proposal_id=proposal_id,
        path=_path(proposal_id),
    )


def apply_proposal(
    book: Book,
    *,
    actor: str,
    proposal_id: str,
    token: str,
    expected: str,
    confirmed: bool = False,
    weekly: bool = False,
) -> Decision:
    del confirmed, weekly
    if actor != _ACTOR:
        return Decision("refused", "board_only")
    if not isinstance(proposal_id, str) or proposal_id == "":
        return Decision("refused", "unknown_proposal")
    proposal = book.proposals.get(proposal_id)
    if proposal is None:
        return Decision("refused", "unknown_proposal")
    if proposal.name not in FILES:
        return Decision("refused", "not_a_soul_file", proposal_id=proposal.id)
    name = proposal.name
    if not isinstance(proposal.text, str) or proposal.text.strip() == "":
        return Decision("refused", "empty", name=name, proposal_id=proposal.id)
    body = proposal.text.strip()
    token_reason = _token(token, expected)
    if token_reason is not None:
        return Decision("refused", token_reason, name=name, proposal_id=proposal.id)
    if _hidden(body):
        return Decision("refused", "credential", name=name, proposal_id=proposal.id)
    if proposal.applied:
        return Decision(
            "refused",
            "already_applied",
            name=proposal.name,
            proposal_id=proposal.id,
            path=_path(proposal.id),
        )
    previous = book.current.get(name, "")
    book.history.append(_Snapshot(proposal_id=proposal.id, name=name, previous=previous))
    book.current[name] = body
    proposal.text = body
    proposal.applied = True
    return Decision(
        "applied",
        "applied",
        name=proposal.name,
        proposal_id=proposal.id,
        path=_path(proposal.id),
        applied=True,
    )


def _path(proposal_id: str) -> str:
    return f"soul/proposals/{proposal_id}.md"


def _token(presented: object, expected: object) -> str | None:
    if not isinstance(presented, str) or not isinstance(expected, str):
        return "token_required"
    if presented.strip() == "" or expected.strip() == "":
        return "token_required"
    try:
        matched = hmac.compare_digest(presented, expected)
    except (TypeError, ValueError):
        return "token_mismatch"
    if not matched:
        return "token_mismatch"
    if _GENERATED.fullmatch(presented) and _GENERATED.fullmatch(expected):
        return None
    if credential_shape(presented) or credential_shape(expected):
        return "credential"
    return None


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
