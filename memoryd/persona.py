"""Copy one owner's profile notes into one persona note.

The source is that owner's newest 8 profile rows. An ordinary remember
and an episode are not profile rows, so they are not copied. A
credential-shaped line is left out, including a percent-encoded or
plus-encoded copy. When every row in that window is a credential,
nothing is written. A portrait question returns at most 8 persona
notes, each trimmed to 1200 characters, and no other category. A
credential-shaped note id is not shown, including a percent-encoded or
plus-encoded copy. An empty id is not shown.

Chat cannot extract or read. The file store is the only writer. No
collection is created. This module does not open Postgres or Qdrant
and does not call a model. Friday's ask path does not call it.

confirmed=true is ignored.
"""

from __future__ import annotations

from urllib.parse import unquote_plus

from memoryd.isolate import same_owner
from memoryd.store import RECALL_CAP, Decision, credential_shape

TRIM = 1200
_PORTRAIT = frozenset({
    "who am i",
    "who am i?",
    "what am i like",
    "what am i like?",
})


def chat_blocked(actor: object) -> bool:
    return isinstance(actor, str) and actor.strip().casefold() == "chat"


def extract(
    notes,
    *,
    caller_id: str,
    caller_kind: str,
    subject_id: str | None = None,
    subject_kind: str | None = None,
    actor: object = "",
    confirmed: bool = False,
) -> Decision:
    """Write one persona note for this owner. Write nothing for anyone else."""
    del confirmed
    if chat_blocked(actor):
        return Decision("refused", "chat_cannot")
    gate = same_owner(caller_id, caller_kind, subject_id, subject_kind)
    if gate == "missing_owner":
        return Decision("refused", "missing_owner")
    if gate == "other_owner":
        return Decision("ok", "other_owner")
    caller = _caller(caller_id, caller_kind)
    if caller is None:
        return Decision("refused", "missing_owner")
    if _hidden(caller[0]):
        return Decision("refused", "credential")
    if not _file_store(notes):
        return Decision("refused", "not_the_file_store")
    packed = notes.recall(
        owner_id=caller[0],
        owner_kind=caller[1],
        limit=RECALL_CAP,
        category="profile",
    )
    if packed.outcome != "ok":
        return Decision(packed.outcome, packed.reason)
    parts: list[str] = []
    blocked = False
    for note in packed.notes:
        if note.get("category") != "profile":
            continue
        raw = str(note.get("content") or "")
        if _hidden(raw):
            blocked = True
            continue
        text = _trim(raw)
        if text == "" or _hidden(text):
            if _hidden(text):
                blocked = True
            continue
        parts.append(text)
    if not parts:
        if blocked:
            return Decision("refused", "credential")
        return Decision("ok", "nothing_to_extract")
    fact = _trim(" ".join(parts))
    if fact == "":
        return Decision("ok", "nothing_to_extract")
    if _hidden(fact):
        return Decision("refused", "credential")
    visibility = "working" if caller[1] == "role" else "master"
    saved = notes.save(
        owner_id=caller[0],
        owner_kind=caller[1],
        content=fact,
        visibility=visibility,
        category="persona",
    )
    if saved.outcome != "saved":
        return Decision(saved.outcome, saved.reason)
    return saved


def portrait(
    notes,
    *,
    caller_id: str,
    caller_kind: str,
    text: object,
    subject_id: str | None = None,
    subject_kind: str | None = None,
    actor: object = "",
    confirmed: bool = False,
) -> Decision:
    """Persona notes for a portrait question. Other categories stay out."""
    del confirmed
    if chat_blocked(actor):
        return Decision("refused", "chat_cannot")
    gate = same_owner(caller_id, caller_kind, subject_id, subject_kind)
    if gate == "missing_owner":
        return Decision("refused", "missing_owner")
    if gate == "other_owner":
        return Decision("ok", "other_owner")
    caller = _caller(caller_id, caller_kind)
    if caller is None:
        return Decision("refused", "missing_owner")
    if _hidden(caller[0]):
        return Decision("refused", "credential")
    if not isinstance(text, str):
        return Decision("refused", "text")
    if _hidden(text):
        return Decision("refused", "credential")
    if _question(text) not in _PORTRAIT:
        return Decision("ok", "not_a_portrait")
    if not _file_store(notes):
        return Decision("refused", "not_the_file_store")
    packed = notes.recall(
        owner_id=caller[0],
        owner_kind=caller[1],
        limit=RECALL_CAP,
        category="persona",
    )
    if packed.outcome != "ok":
        return Decision(packed.outcome, packed.reason)
    shown: list[dict] = []
    for note in packed.notes:
        if note.get("category") != "persona":
            continue
        raw = str(note.get("content") or "")
        if _hidden(raw):
            continue
        kept = _trim(raw)
        if kept == "" or _hidden(kept):
            continue
        note_id = _note_id(note)
        if note_id is None:
            continue
        shown.append(
            {
                "id": note_id,
                "content": kept,
                "owner_id": note.get("owner_id"),
                "owner_kind": note.get("owner_kind"),
                "category": "persona",
            }
        )
        if len(shown) >= RECALL_CAP:
            break
    if not shown:
        return Decision("ok", "nothing_to_show")
    return Decision("ok", "portrait", notes=tuple(shown))


def _note_id(note: dict) -> str | None:
    note_id = note.get("id")
    if not isinstance(note_id, str) or note_id == "" or note_id != note_id.strip():
        return None
    if _hidden(note_id):
        return None
    return note_id


def _caller(caller_id, caller_kind) -> tuple[str, str] | None:
    gate = same_owner(caller_id, caller_kind)
    if gate is not None:
        return None
    cleaned = caller_id.strip()
    return cleaned, caller_kind


def _file_store(notes) -> bool:
    return isinstance(getattr(notes, "rows", None), dict)


def _question(text: str) -> str:
    return " ".join(text.replace("\n", " ").split()).casefold()


def _trim(text: str) -> str:
    return " ".join(text.replace("\n", " ").split())[:TRIM]


def _hidden(text: str) -> bool:
    if not isinstance(text, str) or text == "":
        return False
    seen = text
    for _ in range(3):
        if credential_shape(" ".join(seen.split())):
            return True
        decoded = unquote_plus(seen)
        if decoded == seen:
            return False
        seen = decoded
    return credential_shape(" ".join(seen.split()))
