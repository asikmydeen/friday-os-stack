"""Decide what a disposable browser session may do.

The session sits on its own network. A credential broker may hold the
vault entry for that session. The model receives page text and does not
receive the secret. Read and draft proceed. Send, pay, delete, and
publish wait for an approval. confirmed=true is ignored.

A page kept here is evidence. The sentence is "A page was read." The
raw page is not a goal and is not instructions. The vault secret is
removed, including a percent-encoded copy and a copy rebuilt by that
removal, and is not stored. The Board discards the session when the
owner stops it. The executor discards it when the task finishes. Chat
cannot discard it, and that refusal leaves the page. A different case
of that reason leaves the page.

This module does not start a browser, does not fetch, and does not
open a socket. Friday's ask path does not call it. The server still
fetches when it is enabled and does not call this record.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from urllib.parse import quote

from memoryd.store import credential_shape

OPEN = frozenset({"read", "draft"})
WAITING = frozenset({"send", "pay", "delete", "publish"})
NOTE_ACTORS = frozenset({"friday", "executor"})
DISCARD = {"owner_stopped": "board", "task_finished": "executor"}
PAGE = "A page was read."
TEXT_LIMIT = 8000


@dataclass(frozen=True)
class Decision:
    outcome: str
    reason: str
    said: str = ""
    body: str = ""
    kept: bool = False
    started: bool = False
    fetched: bool = False
    discarded: bool = False


class Book:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.rows: dict[str, dict] = {}


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


def note_page(
    book: Book,
    *,
    owner_id: str,
    body: str,
    actor: str,
    secret: str = "",
    confirmed: bool = False,
) -> Decision:
    del confirmed
    problem = _owner(owner_id)
    if problem:
        return Decision("refused", problem)
    if actor not in NOTE_ACTORS:
        return Decision("refused", "actor_cannot_record")
    if not isinstance(body, str) or body.strip() == "":
        return Decision("refused", "evidence_body")
    if not isinstance(secret, str):
        return Decision("refused", "secret")
    stripped = _without_secret(body, secret)
    if secret.strip() != "" and _still_holds(stripped, secret):
        return Decision("refused", "secret")
    if stripped.strip() == "":
        return Decision("refused", "evidence_body")
    if credential_shape(stripped):
        return Decision("refused", "credential")
    kept = stripped[:TEXT_LIMIT]
    with book._lock:
        row = book.rows.get(owner_id)
        if row and not row["discarded"] and row["body"]:
            return Decision(
                "recorded",
                "already",
                said=row["said"],
                body=row["body"],
                kept=True,
            )
        book.rows[owner_id] = {
            "body": kept,
            "said": PAGE,
            "discarded": False,
            "started": False,
            "fetched": False,
        }
    return Decision("recorded", "evidence", said=PAGE, body=kept, kept=True)


def discard(
    book: Book,
    *,
    owner_id: str,
    why: str,
    actor: str,
    confirmed: bool = False,
) -> Decision:
    del confirmed
    problem = _owner(owner_id)
    if problem:
        return Decision("refused", problem)
    expected = DISCARD.get(why) if isinstance(why, str) else None
    if expected is None:
        return Decision("refused", "not_a_discard")
    if actor != expected:
        return Decision("refused", "actor_cannot_discard")
    with book._lock:
        row = book.rows.get(owner_id)
        if row is not None:
            row["body"] = ""
            row["said"] = ""
            row["discarded"] = True
            row["started"] = False
            row["fetched"] = False
    return Decision("discarded", why, discarded=True)


def shown(book: Book, owner_id: str) -> Decision:
    problem = _owner(owner_id)
    if problem:
        return Decision("refused", problem)
    with book._lock:
        row = book.rows.get(owner_id)
        if not row or row["discarded"] or not row["body"]:
            return Decision("refused", "no_page")
        return Decision("recorded", "evidence", said=row["said"], body=row["body"], kept=True)


def _without_secret(body: str, secret: str) -> str:
    if secret.strip() == "":
        return body
    needles = _secret_forms(secret)
    text = body
    for _ in range(len(body) + 1):
        nxt = text
        for needle in needles:
            nxt = nxt.replace(needle, "")
        if nxt == text:
            break
        text = nxt
    return text


def _still_holds(text: str, secret: str) -> bool:
    return any(needle in text for needle in _secret_forms(secret))


def _secret_forms(secret: str) -> tuple[str, ...]:
    encoded = quote(secret, safe="")
    plus = encoded.replace("%20", "+")
    forms: list[str] = []
    for item in (secret, encoded, encoded.lower(), plus, plus.lower()):
        if item and item not in forms:
            forms.append(item)
    return tuple(forms)


def _owner(value: object) -> str | None:
    if not isinstance(value, str) or value.strip() == "":
        return "owner"
    if credential_shape(value):
        return "credential"
    if value != value.strip() or "\n" in value or "\r" in value:
        return "owner"
    return None
