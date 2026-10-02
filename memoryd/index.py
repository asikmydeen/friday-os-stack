"""Index one Postgres revision into Qdrant, then mark that queue item done.

Postgres stays the authority. A missing point is not treated as a deleted
note. After the embed, the worker reads the row again. A tombstone or a
newer revision is not upserted. A point whose payload revision is newer
is left in place. A point this claim just wrote is removed only when
that payload revision is still the claim, in one filtered delete.
The worker writes the fixed collections only. A role
never shares the person's collection, even when the id text matches.
family_shared, person_*, and role_profile_* are not created here.
"""

from __future__ import annotations

from dataclasses import dataclass

from memoryd.store import RECALL_CAP, OWNER_KINDS, Decision

VECTOR_SIZE = 768
COLLECTIONS = (
    "friday_profile",
    "friday_episodes",
    "friday_findings",
    "friday_persona",
    "knowledge",
    "cabinet_working",
)
_PERSON = {
    "": "friday_profile",
    "note": "friday_profile",
    "profile": "friday_profile",
    "episode": "friday_episodes",
    "finding": "friday_findings",
    "findings": "friday_findings",
    "persona": "friday_persona",
    "knowledge": "knowledge",
}


class Hold(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason


@dataclass(frozen=True)
class Claim:
    queue_id: int
    memory_id: str
    revision: int
    deleted: bool


@dataclass(frozen=True)
class Memory:
    id: str
    owner_id: str
    owner_kind: str
    revision: int
    content: str
    visibility: str
    category: str
    deleted: bool


def _qdrant(action) -> None:
    try:
        action()
    except OSError as exc:
        reason = str(exc)
        if reason not in {"index_not_ready", "index_refused"}:
            reason = "index_not_ready"
        raise Hold(reason) from None


def collection_name(owner_kind: str, category: str) -> str:
    if owner_kind == "role":
        return "cabinet_working"
    return _PERSON.get(category, "friday_profile")


def index_once(store, qdrant, embed, worker: str = "memoryd") -> str:
    try:
        with store.transaction() as tx:
            return _index(tx, qdrant, embed, worker)
    except Hold as held:
        return held.reason


def drain(store, qdrant, embed, worker: str = "memoryd", limit: int = 32) -> str:
    last = "idle"
    for _ in range(limit):
        last = index_once(store, qdrant, embed, worker)
        if last not in {"indexed", "deleted", "missing", "stale"}:
            return last
    return last


def _index(tx, qdrant, embed, worker: str) -> str:
    claim = tx.claim(worker)
    if claim is None:
        return "idle"
    row = tx.fetch(claim.memory_id)
    if row is None:
        tx.finish(claim.queue_id)
        return "missing"
    name = collection_name(row.owner_kind, row.category)
    if claim.deleted or row.deleted:
        _qdrant(lambda: qdrant.ensure(name))
        _qdrant(lambda: qdrant.delete(name, row.id))
        tx.finish(claim.queue_id)
        return "deleted"
    try:
        vector = embed(row.content)
    except OSError as exc:
        reason = str(exc)
        if reason not in {"embed_not_ready", "embed_dimensions"}:
            reason = "embed_not_ready"
        raise Hold(reason) from None
    if not isinstance(vector, list) or len(vector) != VECTOR_SIZE:
        raise Hold("embed_dimensions")
    fresh = tx.fetch(row.id)
    if fresh is None:
        tx.finish(claim.queue_id)
        return "missing"
    if fresh.deleted or fresh.revision != claim.revision:
        return _superseded(tx, qdrant, name, row.id, claim.queue_id, fresh)
    _qdrant(lambda: qdrant.ensure(name))
    _qdrant(
        lambda: qdrant.upsert(
            name,
            fresh.id,
            [float(item) for item in vector],
            {
                "owner_id": fresh.owner_id,
                "owner_kind": fresh.owner_kind,
                "topic": fresh.category,
                "source": "memory",
                "content": fresh.content,
                "visibility": fresh.visibility,
                "revision": fresh.revision,
                "memory_id": fresh.id,
            },
        )
    )
    checked = tx.fetch(row.id)
    if checked is not None and checked.deleted:
        _qdrant(lambda: qdrant.delete(name, row.id))
        tx.finish(claim.queue_id)
        return "deleted"
    if checked is None or checked.revision != claim.revision:
        _drop_own_write(qdrant, name, row.id, claim.revision)
        tx.finish(claim.queue_id)
        return "stale"
    tx.mark_indexed(row.id, claim.revision)
    tx.finish(claim.queue_id)
    return "indexed"


def _superseded(tx, qdrant, name: str, point_id: str, queue_id: int, fresh: Memory) -> str:
    if fresh.deleted:
        _qdrant(lambda: qdrant.ensure(name))
        _qdrant(lambda: qdrant.delete(name, point_id))
        tx.finish(queue_id)
        return "deleted"
    tx.finish(queue_id)
    return "stale"


def _drop_own_write(qdrant, name: str, point_id: str, revision: int) -> None:
    drop = getattr(qdrant, "delete_revision", None)
    if drop is None:
        return
    _qdrant(lambda: drop(name, point_id, revision))


def search(qdrant, embed, *, owner_id: str, owner_kind: str, text: str, limit: int = RECALL_CAP) -> Decision:
    if not owner_id or owner_kind not in OWNER_KINDS:
        return Decision("refused", "missing_owner")
    if not isinstance(text, str) or text.strip() == "":
        return Decision("refused", "empty_content")
    cap = RECALL_CAP if not isinstance(limit, int) or isinstance(limit, bool) else min(limit, RECALL_CAP)
    if cap < 1:
        cap = 1
    try:
        vector = embed(text)
    except OSError as exc:
        reason = str(exc)
        if reason not in {"embed_not_ready", "embed_dimensions"}:
            reason = "embed_not_ready"
        return Decision("refused", reason)
    if not isinstance(vector, list) or len(vector) != VECTOR_SIZE:
        return Decision("refused", "embed_dimensions")
    hits: list[dict] = []
    saw_collection = False
    for name in COLLECTIONS:
        try:
            found = qdrant.query(name, [float(item) for item in vector], owner_id, owner_kind, cap)
        except OSError as exc:
            if str(exc) == "missing_collection":
                continue
            return Decision("refused", "index_not_ready")
        saw_collection = True
        hits.extend(found)
    if not saw_collection and not hits:
        return Decision("refused", "index_not_ready")
    best: dict[str, tuple[float, dict, str]] = {}
    for hit in hits:
        payload = hit.get("payload") or {}
        if payload.get("owner_id") != owner_id or payload.get("owner_kind") != owner_kind:
            continue
        content = payload.get("content")
        if not isinstance(content, str):
            continue
        note_id = str(payload.get("memory_id") or "") or content
        score = float(hit.get("score") or 0)
        previous = best.get(note_id)
        if previous is None or score > previous[0]:
            best[note_id] = (score, payload, content)
    kept = sorted(best.values(), key=lambda item: item[0], reverse=True)
    notes = tuple(
        {
            "id": str(payload.get("memory_id") or ""),
            "owner_id": owner_id,
            "owner_kind": owner_kind,
            "revision": payload.get("revision"),
            "content": content,
            "visibility": str(payload.get("visibility") or ""),
            "category": str(payload.get("topic") or ""),
        }
        for _score, payload, content in kept[:cap]
    )
    return Decision("ok", "searched", notes=notes)
