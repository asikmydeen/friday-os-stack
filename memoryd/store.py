"""In-process notes with the same identity rules as sql/memories.sql.

A person and a role never share a row. The same live identity updates
one row and bumps the revision. A changed sentence is a new row. Recall
without an owner is refused, including when the store holds one note.
Deleted notes stay out of the pack. Text that looks like a credential
is refused and nothing is written. Nothing here talks to Qdrant.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

RECALL_CAP = 8
OWNER_KINDS = frozenset({"person", "role"})
VISIBILITIES = frozenset({"master", "working", "promoted"})
# Value shapes only. The words password and token, with no value, are not a hit.
_CREDENTIALS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bxox[abpr]-[A-Za-z0-9-]{20,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{25,}\b"),
    re.compile(
        r"(?i)\b(?:password|passwd|passphrase|passcode|pin|secret|token|api[_ -]?key|access[_ -]?key)\b\s*[:=]\s*[\"'`]?\S{4,}"
    ),
    re.compile(
        r"(?i)\b(?:password|passwd|passphrase|passcode|pin|secret|token|api[_ -]?key|access[_ -]?key)\b\s+is\s+"
        r"(?:[0-9]\S{3,}|\S[0-9]\S{2,}|\S{2}[0-9]\S+|\S{3,}[0-9]\S*)"
    ),
    re.compile(r"\b(?:\d[ -]?){13,19}\b"),
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    re.compile(r"\b[A-Fa-f0-9]{40,}\b"),
    re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{48,}={0,2}(?![A-Za-z0-9+/=])"),
)


def credential_shape(text: str) -> bool:
    """True when text contains a credential value. The match is not returned."""
    if not isinstance(text, str) or text == "":
        return False
    return any(pattern.search(text) for pattern in _CREDENTIALS)


@dataclass(frozen=True)
class Decision:
    outcome: str
    reason: str
    notes: tuple[dict, ...] = ()
    note_id: str | None = None
    revision: int | None = None


@dataclass
class _Row:
    id: str
    owner_id: str
    owner_kind: str
    revision: int
    content: str
    visibility: str
    category: str
    deleted: bool = False
    promoted_from: str | None = None


def _digest(content: str) -> str:
    return hashlib.md5(content.encode(), usedforsecurity=False).hexdigest()


class Notes:
    def __init__(self) -> None:
        self.rows: dict[str, _Row] = {}

    def dump(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = [
            {
                "id": row.id,
                "owner_id": row.owner_id,
                "owner_kind": row.owner_kind,
                "revision": row.revision,
                "content": row.content,
                "visibility": row.visibility,
                "category": row.category,
                "deleted": row.deleted,
                "promoted_from": row.promoted_from,
            }
            for row in self.rows.values()
        ]
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload), encoding="utf-8")
        temporary.replace(path)

    @classmethod
    def load(cls, path: Path) -> Notes:
        notes = cls()
        if not path.is_file():
            return notes
        for item in json.loads(path.read_text(encoding="utf-8")):
            notes.rows[item["id"]] = _Row(
                id=item["id"],
                owner_id=item["owner_id"],
                owner_kind=item["owner_kind"],
                revision=item["revision"],
                content=item["content"],
                visibility=item["visibility"],
                category=item["category"],
                deleted=bool(item.get("deleted")),
                promoted_from=item.get("promoted_from"),
            )
        return notes

    def save(
        self,
        *,
        owner_id: str,
        owner_kind: str,
        content: str,
        visibility: str = "master",
        category: str = "",
        promoted_from: str | None = None,
    ) -> Decision:
        if not owner_id or owner_kind not in OWNER_KINDS:
            return Decision("refused", "missing_owner")
        if visibility not in VISIBILITIES:
            return Decision("refused", "visibility")
        if not isinstance(content, str) or content.strip() == "":
            return Decision("refused", "empty_content")
        if credential_shape(content):
            return Decision("refused", "credential")
        category = category or ""
        source = self._promotion_source(
            owner_id=owner_id,
            owner_kind=owner_kind,
            content=content,
            visibility=visibility,
            category=category,
            promoted_from=promoted_from,
        )
        if isinstance(source, str):
            return Decision("refused", source)
        digest = _digest(content)
        for row in self.rows.values():
            if row.deleted:
                continue
            if (
                row.owner_id == owner_id
                and row.owner_kind == owner_kind
                and row.visibility == visibility
                and row.category == category
                and _digest(row.content) == digest
            ):
                if visibility == "promoted" and row.promoted_from != promoted_from:
                    return Decision("refused", "not_a_copy")
                row.revision += 1
                return Decision("saved", "revised", note_id=row.id, revision=row.revision)
        note_id = str(uuid.uuid4())
        self.rows[note_id] = _Row(
            id=note_id,
            owner_id=owner_id,
            owner_kind=owner_kind,
            revision=1,
            content=content,
            visibility=visibility,
            category=category,
            promoted_from=promoted_from,
        )
        return Decision("saved", "created", note_id=note_id, revision=1)

    def _promotion_source(
        self,
        *,
        owner_id: str,
        owner_kind: str,
        content: str,
        visibility: str,
        category: str,
        promoted_from: str | None,
    ) -> _Row | None | str:
        """None when this save is not a promotion. A string is a refusal."""
        if visibility != "promoted":
            if promoted_from is not None:
                return "promoted_from"
            return None
        if not isinstance(promoted_from, str) or promoted_from == "":
            return "promoted_from"
        source = self.rows.get(promoted_from)
        if source is None or source.deleted:
            return "unknown_note"
        if source.visibility != "working":
            return "not_working"
        if source.owner_id != owner_id or source.owner_kind != owner_kind:
            return "other_owner"
        if source.content != content or source.category != category:
            return "not_a_copy"
        return source

    def recall(
        self,
        *,
        owner_id: str | None,
        owner_kind: str | None,
        limit: int = RECALL_CAP,
        category: str | None = None,
    ) -> Decision:
        if not owner_id or owner_kind not in OWNER_KINDS:
            return Decision("refused", "missing_owner")
        if category is not None and not isinstance(category, str):
            return Decision("refused", "category")
        cap = RECALL_CAP if not isinstance(limit, int) or isinstance(limit, bool) else min(limit, RECALL_CAP)
        if cap < 1:
            cap = 1
        matched = [
            row
            for row in self.rows.values()
            if not row.deleted
            and row.owner_id == owner_id
            and row.owner_kind == owner_kind
            and (category is None or row.category == category)
        ]
        # Same window as Postgres: higher revision, then the later row.
        positions = {row_id: index for index, row_id in enumerate(self.rows)}
        matched.sort(key=lambda row: (row.revision, positions[row.id]), reverse=True)
        notes = tuple(
            {
                "id": row.id,
                "owner_id": row.owner_id,
                "owner_kind": row.owner_kind,
                "revision": row.revision,
                "content": row.content,
                "visibility": row.visibility,
                "category": row.category,
                "promoted_from": row.promoted_from,
            }
            for row in matched[:cap]
        )
        return Decision("ok", "recalled", notes=notes)

    def tombstone(self, note_id: str) -> Decision:
        row = self.rows.get(note_id)
        if row is None or row.deleted:
            return Decision("refused", "unknown_note")
        row.deleted = True
        row.revision += 1
        return Decision("saved", "tombstone", note_id=row.id, revision=row.revision)
