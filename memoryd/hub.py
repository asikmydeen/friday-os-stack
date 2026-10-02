"""Hub search over knowledge and friday_findings only.

The caller must name an owner. A missing filter is refused before any
embed or query. Another owner is not searched. A credential-shaped
query, owner, or topic is refused and is not repeated, including a
percent-encoded or plus-encoded copy. A stored note whose content or
topic is credential-shaped is not shown. At most 8 notes
come back, each trimmed to 1200 characters. This module does not create
a collection, does not write a point, and does not call ensure.
Friday's /ask calls POST /hub and keeps this pack. This module does
not import Friday. A hub that is not ready does not fail that turn.
"""

from __future__ import annotations

from urllib.parse import unquote_plus

from memoryd.store import OWNER_KINDS, RECALL_CAP, Decision, credential_shape

HUB = ("friday_findings", "knowledge")
TRIM = 1200


def hub_search(
    qdrant,
    embed,
    *,
    owner_id: str,
    owner_kind: str,
    text: str,
    topic: str | None = None,
    subject_id: str | None = None,
    subject_kind: str | None = None,
    limit: int = RECALL_CAP,
    confirmed: bool = False,
) -> Decision:
    del confirmed
    caller = _owner(owner_id, owner_kind)
    if caller is None:
        return Decision("refused", "missing_owner")
    if _hidden(caller[0]):
        return Decision("refused", "credential")
    if subject_id is not None or subject_kind is not None:
        subject = _owner(subject_id, subject_kind)
        if subject is None:
            return Decision("refused", "missing_owner")
        if subject != caller:
            return Decision("ok", "other_owner")
    if not isinstance(text, str) or text.strip() == "":
        return Decision("refused", "empty_content")
    if _hidden(text):
        return Decision("refused", "credential")
    wanted = _topic(topic)
    if isinstance(wanted, Decision):
        return wanted
    query = getattr(qdrant, "query", None)
    if not callable(query):
        return Decision("refused", "index_not_ready")
    if not callable(embed):
        return Decision("refused", "embed_not_ready")
    try:
        vector = embed(text.strip())
    except OSError as exc:
        reason = str(exc)
        if reason not in {"embed_not_ready", "embed_dimensions"} or credential_shape(reason):
            reason = "embed_not_ready"
        return Decision("refused", reason)
    numbers = _numbers(vector)
    if numbers is None:
        return Decision("refused", "embed_dimensions")
    cap = _cap(limit)
    hits: list[tuple[float, str, dict]] = []
    saw = False
    for name in HUB:
        try:
            found = query(name, numbers, caller[0], caller[1], cap)
        except OSError as exc:
            if str(exc) == "missing_collection":
                continue
            return Decision("refused", "index_not_ready")
        if not isinstance(found, list):
            return Decision("refused", "index_not_ready")
        saw = True
        hits.extend(_kept(found, caller, wanted))
    if not saw:
        return Decision("refused", "index_not_ready")
    best: dict[str, tuple[float, dict]] = {}
    for score, note_id, payload in hits:
        previous = best.get(note_id)
        if previous is None or score > previous[0]:
            best[note_id] = (score, payload)
    ordered = sorted(best.items(), key=lambda item: (-item[1][0], item[0]))
    notes = tuple(
        _note(note_id, payload, caller)
        for note_id, (_score, payload) in ordered[:cap]
    )
    return Decision("ok", "searched", notes=notes)


def _owner(owner_id, owner_kind) -> tuple[str, str] | None:
    if not isinstance(owner_id, str) or owner_kind not in OWNER_KINDS:
        return None
    if owner_id == "" or owner_id != owner_id.strip() or "\n" in owner_id or "\r" in owner_id:
        return None
    return owner_id, owner_kind


def _topic(topic) -> str | None | Decision:
    if topic is None:
        return None
    if not isinstance(topic, str):
        return Decision("refused", "topic")
    if topic.strip() == "":
        return None
    if topic != topic.strip() or "\n" in topic or "\r" in topic:
        return Decision("refused", "topic")
    if _hidden(topic):
        return Decision("refused", "credential")
    return topic


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


def _numbers(vector) -> list[float] | None:
    if not isinstance(vector, list) or len(vector) != 768:
        return None
    numbers: list[float] = []
    for item in vector:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            return None
        numbers.append(float(item))
    return numbers


def _cap(limit: int) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int):
        return RECALL_CAP
    if limit < 1:
        return 1
    return min(limit, RECALL_CAP)


def _kept(found: list, caller: tuple[str, str], topic: str | None) -> list[tuple[float, str, dict]]:
    kept: list[tuple[float, str, dict]] = []
    for hit in found:
        if not isinstance(hit, dict):
            continue
        payload = hit.get("payload")
        if not isinstance(payload, dict):
            continue
        if payload.get("owner_id") != caller[0] or payload.get("owner_kind") != caller[1]:
            continue
        if topic is not None and payload.get("topic") != topic:
            continue
        stored_topic = payload.get("topic")
        if isinstance(stored_topic, str) and stored_topic != "" and _hidden(stored_topic):
            continue
        content = payload.get("content")
        if not isinstance(content, str) or _hidden(content):
            continue
        shown = " ".join(content.replace("\n", " ").split())[:TRIM]
        if shown == "" or _hidden(shown):
            continue
        note_id = payload.get("memory_id")
        if not isinstance(note_id, str) or note_id.strip() == "" or note_id != note_id.strip():
            continue
        if _hidden(note_id):
            continue
        score = hit.get("score")
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            continue
        safe = dict(payload)
        safe["content"] = shown
        kept.append((float(score), note_id, safe))
    return kept


def _note(note_id: str, payload: dict, caller: tuple[str, str]) -> dict:
    revision = payload.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int):
        revision = None
    return {
        "id": note_id,
        "owner_id": caller[0],
        "owner_kind": caller[1],
        "content": payload["content"],
        "topic": payload.get("topic") if isinstance(payload.get("topic"), str) else "",
        "revision": revision,
    }
