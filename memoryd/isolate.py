"""Reflection, export, and an advisor lookup stay inside one owner.

A missing owner is refused. A caller asking for someone else gets
nothing back, and reflection writes nothing. A role does not read a
person's notes, even when the id text matches. The folded fact is one
profile note for that same owner, from the newest eight episode lines.
A credential-shaped line is left out. No collection is created. This
module does not open Postgres, Qdrant, or a model, and it does not run
a tool.
"""

from __future__ import annotations

from memoryd.store import OWNER_KINDS, RECALL_CAP, Decision, credential_shape

TRIM = 1200


def same_owner(
    caller_id: str,
    caller_kind: str,
    subject_id: str | None = None,
    subject_kind: str | None = None,
) -> str | None:
    """None when the caller may touch this store. Otherwise a reason."""
    caller = _clean(caller_id, caller_kind)
    if caller is None:
        return "missing_owner"
    if subject_id is None and subject_kind is None:
        return None
    subject = _clean(subject_id, subject_kind)
    if subject is None:
        return "missing_owner"
    if caller != subject:
        return "other_owner"
    return None


def lookup(notes, *, caller_id: str, caller_kind: str, subject_id: str, subject_kind: str) -> Decision:
    """Read one store. Someone else's notes are not returned."""
    return _read(
        notes,
        caller_id=caller_id,
        caller_kind=caller_kind,
        subject_id=subject_id,
        subject_kind=subject_kind,
        kept="lookup",
    )


def export_notes(
    notes,
    *,
    caller_id: str,
    caller_kind: str,
    subject_id: str | None = None,
    subject_kind: str | None = None,
) -> Decision:
    """Bounded notes for this owner. Not a dump of the database."""
    return _read(
        notes,
        caller_id=caller_id,
        caller_kind=caller_kind,
        subject_id=subject_id,
        subject_kind=subject_kind,
        kept="exported",
    )


def search_for(
    search,
    *,
    caller_id: str,
    caller_kind: str,
    subject_id: str,
    subject_kind: str,
    text: str,
    limit: int = RECALL_CAP,
):
    """Search only when the caller is the subject. Otherwise nothing."""
    gate = same_owner(caller_id, caller_kind, subject_id, subject_kind)
    if gate == "missing_owner":
        return Decision("refused", "missing_owner")
    if gate == "other_owner":
        return Decision("ok", "other_owner")
    caller = _clean(caller_id, caller_kind)
    if caller is None:
        return Decision("refused", "missing_owner")
    cap = RECALL_CAP if isinstance(limit, bool) or not isinstance(limit, int) else min(limit, RECALL_CAP)
    if cap < 1:
        cap = 1
    found = search(owner_id=caller[0], owner_kind=caller[1], text=text, limit=cap)
    if found.outcome != "ok":
        return Decision(found.outcome, found.reason)
    return Decision("ok", found.reason, notes=_public(found.notes))


def reflect(
    notes,
    *,
    caller_id: str,
    caller_kind: str,
    subject_id: str | None = None,
    subject_kind: str | None = None,
) -> Decision:
    """Fold this owner's episodes into one profile note. Write nothing for anyone else."""
    gate = same_owner(caller_id, caller_kind, subject_id, subject_kind)
    if gate == "missing_owner":
        return Decision("refused", "missing_owner")
    if gate == "other_owner":
        return Decision("ok", "other_owner")
    caller = _clean(caller_id, caller_kind)
    if caller is None:
        return Decision("refused", "missing_owner")
    packed = notes.recall(
        owner_id=caller[0],
        owner_kind=caller[1],
        limit=RECALL_CAP,
        category="episode",
    )
    if packed.outcome != "ok":
        return Decision(packed.outcome, packed.reason)
    parts: list[str] = []
    blocked = False
    for note in packed.notes:
        if note.get("category") != "episode":
            continue
        raw = str(note.get("content") or "")
        if credential_shape(raw):
            blocked = True
            continue
        text = _trim(raw)
        if text and credential_shape(text):
            blocked = True
            continue
        if text:
            parts.append(text)
    if not parts:
        if blocked:
            return Decision("refused", "credential")
        return Decision("ok", "nothing_to_fold")
    fact = _trim(" ".join(parts))
    if fact == "":
        return Decision("ok", "nothing_to_fold")
    if credential_shape(fact):
        return Decision("refused", "credential")
    visibility = "working" if caller[1] == "role" else "master"
    saved = notes.save(
        owner_id=caller[0],
        owner_kind=caller[1],
        content=fact,
        visibility=visibility,
        category="profile",
    )
    if saved.outcome != "saved":
        return Decision(saved.outcome, saved.reason)
    return saved


def _read(
    notes,
    *,
    caller_id: str,
    caller_kind: str,
    subject_id: str | None,
    subject_kind: str | None,
    kept: str,
) -> Decision:
    gate = same_owner(caller_id, caller_kind, subject_id, subject_kind)
    if gate == "missing_owner":
        return Decision("refused", "missing_owner")
    if gate == "other_owner":
        return Decision("ok", "other_owner")
    caller = _clean(caller_id, caller_kind)
    if caller is None:
        return Decision("refused", "missing_owner")
    packed = notes.recall(owner_id=caller[0], owner_kind=caller[1], limit=RECALL_CAP)
    if packed.outcome != "ok":
        return Decision(packed.outcome, packed.reason)
    return Decision("ok", kept, notes=_public(packed.notes))


def _public(notes) -> tuple[dict, ...]:
    shown: list[dict] = []
    for note in notes[:RECALL_CAP]:
        shown.append(
            {
                "id": str(note.get("id") or ""),
                "content": _trim(str(note.get("content") or "")),
                "owner_id": note.get("owner_id"),
                "owner_kind": note.get("owner_kind"),
                "category": note.get("category") or "",
            }
        )
    return tuple(shown)


def _trim(text: str) -> str:
    return " ".join(text.replace("\n", " ").split())[:TRIM]


def _clean(owner_id, owner_kind) -> tuple[str, str] | None:
    if not isinstance(owner_id, str) or owner_kind not in OWNER_KINDS:
        return None
    cleaned = owner_id.strip()
    if cleaned == "":
        return None
    return cleaned, owner_kind
