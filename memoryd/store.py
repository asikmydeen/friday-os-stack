"""In-process notes with the same identity rules as sql/memories.sql.

A person and a role never share a row. The same live identity updates
one row and bumps the revision. A changed sentence is a new row. Recall
without an owner is refused, including when the store holds one note.
Deleted notes stay out of the pack. Nothing here talks to Qdrant.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from pathlib import Path

RECALL_CAP = 8
OWNER_KINDS = frozenset({"person", "role"})
VISIBILITIES = frozenset({"master", "working", "promoted"})


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
    ) -> Decision:
        if not owner_id or owner_kind not in OWNER_KINDS:
            return Decision("refused", "missing_owner")
        if visibility not in VISIBILITIES:
            return Decision("refused", "visibility")
        if not isinstance(content, str) or content.strip() == "":
            return Decision("refused", "empty_content")
        category = category or ""
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
        )
        return Decision("saved", "created", note_id=note_id, revision=1)

    def recall(
        self,
        *,
        owner_id: str | None,
        owner_kind: str | None,
        limit: int = RECALL_CAP,
    ) -> Decision:
        if not owner_id or owner_kind not in OWNER_KINDS:
            return Decision("refused", "missing_owner")
        cap = RECALL_CAP if not isinstance(limit, int) or isinstance(limit, bool) else min(limit, RECALL_CAP)
        if cap < 1:
            cap = 1
        matched = [
            row
            for row in self.rows.values()
            if not row.deleted and row.owner_id == owner_id and row.owner_kind == owner_kind
        ]
        matched.sort(key=lambda row: row.revision, reverse=True)
        notes = tuple(
            {
                "id": row.id,
                "owner_id": row.owner_id,
                "owner_kind": row.owner_kind,
                "revision": row.revision,
                "content": row.content,
                "visibility": row.visibility,
                "category": row.category,
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
