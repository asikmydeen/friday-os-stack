"""HTTP front for the notes store.

Friday presents Friday-Memory. The header is the memory token. The
Qdrant key is required to be present so a half-written environment does
not serve recall. This process sends that key only to Qdrant. `/hub`
searches `knowledge` and `friday_findings` for that owner when a client
is configured. It does not create a collection. `/persona` copies profile
notes into one persona note, or returns those notes for a portrait
question. It does not create a collection. `/card` records one
research card or one kept decision on the file store. The raw page is
not stored. It does not create a collection. With `POSTGRES_HOST`
set, that route writes the row through `memory_save`. `/save` still
refuses those categories. `/promote` copies one
working note for the Board. Chat cannot. The raw note is not the reply.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from memoryd.card import record_card
from memoryd.isolate import export_notes, reflect, same_owner, search_for
from memoryd.persona import chat_blocked, extract, portrait
from memoryd.promote import promote
from memoryd.store import Notes
from runtime.http import header, same

REQUIRED = ("MEMORY_TOKEN", "QDRANT_API_KEY")


def ready(env: dict[str, str] | None = None, notes=None) -> tuple[bool, str]:
    source = os.environ if env is None else env
    missing = [name for name in REQUIRED if not source.get(name)]
    if missing:
        return False, "secrets"
    ping = getattr(notes, "ping", None)
    if ping is not None and not ping():
        return False, "postgres"
    return True, "ready"


def app(notes: Notes, env: dict[str, str], path: Path | None = None, indexer=None, searcher=None, hubber=None):
    def handle(method: str, route: str, headers, payload: dict) -> tuple[int, dict]:
        if route == "/health" and method == "GET":
            return 200, {"outcome": "ok", "reason": "health"}
        ok, reason = ready(env, notes)
        if route == "/ready" and method == "GET":
            return (200 if ok else 503), {"outcome": "ok" if ok else "refused", "reason": reason}
        token = header(headers, "Friday-Memory")
        expected = env.get("MEMORY_TOKEN", "")
        if not expected or not token or not same(token, expected):
            return 401, {"outcome": "refused", "reason": "unauthenticated"}
        if not ok:
            return 503, {"outcome": "refused", "reason": reason}
        if route == "/promote" and method == "POST":
            raw_id = payload.get("id")
            decision = promote(
                notes,
                actor=payload.get("actor") if isinstance(payload.get("actor"), str) else "",
                note_id=raw_id if isinstance(raw_id, str) else "",
                confirmed=payload.get("confirmed", False),
            )
            if decision.outcome == "saved":
                _flush(notes, path)
            return _status(decision), _body(decision)
        if route == "/save" and method == "POST":
            category = payload.get("category") or ""
            if isinstance(category, str) and category.strip().casefold() == "persona":
                return 403, {"outcome": "refused", "reason": "persona_pass"}
            if isinstance(category, str) and category.strip().casefold() in {"finding", "findings", "knowledge"}:
                return 403, {"outcome": "refused", "reason": "card_pass"}
            decision = notes.save(
                owner_id=str(payload.get("owner_id") or ""),
                owner_kind=str(payload.get("owner_kind") or ""),
                content=str(payload.get("content") or ""),
                visibility=str(payload.get("visibility") or "master"),
                category=str(category or ""),
            )
            _flush(notes, path)
            return _status(decision), _body(decision)
        if route == "/recall" and method == "POST":
            limit = payload.get("limit", 8)
            decision = notes.recall(
                owner_id=payload.get("owner_id"),
                owner_kind=payload.get("owner_kind"),
                limit=limit if isinstance(limit, int) else 8,
            )
            return _status(decision), _body(decision)
        if route == "/tombstone" and method == "POST":
            decision = notes.tombstone(str(payload.get("id") or ""))
            _flush(notes, path)
            return _status(decision), _body(decision)
        if route == "/index" and method == "POST":
            if indexer is None:
                return 200, {"outcome": "ok", "reason": "idle"}
            return 200, {"outcome": "ok", "reason": indexer()}
        if route == "/search" and method == "POST":
            gate = _gate(payload)
            if gate is not None:
                return gate
            if searcher is None:
                return 503, {"outcome": "refused", "reason": "index_not_ready"}
            caller_id, caller_kind, subject_id, subject_kind = _parties(payload)
            limit = payload.get("limit", 8)
            decision = search_for(
                searcher,
                caller_id=caller_id,
                caller_kind=caller_kind,
                subject_id=caller_id if subject_id is None else subject_id,
                subject_kind=caller_kind if subject_kind is None else subject_kind,
                text=str(payload.get("text") or ""),
                limit=limit if isinstance(limit, int) and not isinstance(limit, bool) else 8,
            )
            return _status(decision), _body(decision)
        if route == "/hub" and method == "POST":
            gate = _gate(payload)
            if gate is not None:
                return gate
            if hubber is None:
                return 503, {"outcome": "refused", "reason": "index_not_ready"}
            caller_id, caller_kind, subject_id, subject_kind = _parties(payload)
            limit = payload.get("limit", 8)
            raw_text = payload.get("text")
            decision = hubber(
                owner_id=caller_id,
                owner_kind=caller_kind,
                subject_id=subject_id,
                subject_kind=subject_kind,
                text=raw_text if isinstance(raw_text, str) else "",
                topic=payload.get("topic", None),
                limit=limit if isinstance(limit, int) and not isinstance(limit, bool) else 8,
                confirmed=payload.get("confirmed", False),
            )
            return _status(decision), _body(decision)
        if route == "/card" and method == "POST":
            if chat_blocked(payload.get("actor", "")):
                return 403, {"outcome": "refused", "reason": "chat_cannot"}
            if payload.get("action") != "record":
                return 403, {"outcome": "refused", "reason": "action"}
            gate = _gate(payload)
            if gate is not None:
                return gate
            caller_id, caller_kind, subject_id, subject_kind = _parties(payload)
            decision = record_card(
                notes,
                caller_id=caller_id,
                caller_kind=caller_kind,
                kind=payload.get("kind", ""),
                text=payload.get("text", ""),
                page=payload.get("page", None),
                subject_id=subject_id,
                subject_kind=subject_kind,
                actor=payload.get("actor", ""),
                confirmed=payload.get("confirmed", False),
            )
            if decision.outcome == "saved":
                _flush(notes, path)
            return _status(decision), _body(decision)
        if route == "/persona" and method == "POST":
            if chat_blocked(payload.get("actor", "")):
                return 403, {"outcome": "refused", "reason": "chat_cannot"}
            gate = _gate(payload)
            if gate is not None:
                return gate
            caller_id, caller_kind, subject_id, subject_kind = _parties(payload)
            action = payload.get("action")
            if action == "portrait":
                decision = portrait(
                    notes,
                    caller_id=caller_id,
                    caller_kind=caller_kind,
                    subject_id=subject_id,
                    subject_kind=subject_kind,
                    text=payload.get("text", ""),
                    actor=payload.get("actor", ""),
                    confirmed=payload.get("confirmed", False),
                )
            elif action == "extract":
                decision = extract(
                    notes,
                    caller_id=caller_id,
                    caller_kind=caller_kind,
                    subject_id=subject_id,
                    subject_kind=subject_kind,
                    actor=payload.get("actor", ""),
                    confirmed=payload.get("confirmed", False),
                )
            else:
                return 403, {"outcome": "refused", "reason": "action"}
            if decision.outcome == "saved":
                _flush(notes, path)
            return _status(decision), _body(decision)
        if route == "/reflect" and method == "POST":
            gate = _gate(payload)
            if gate is not None:
                return gate
            caller_id, caller_kind, subject_id, subject_kind = _parties(payload)
            decision = reflect(
                notes,
                caller_id=caller_id,
                caller_kind=caller_kind,
                subject_id=subject_id,
                subject_kind=subject_kind,
            )
            if decision.outcome == "saved":
                _flush(notes, path)
            return _status(decision), _body(decision)
        if route == "/export" and method == "POST":
            gate = _gate(payload)
            if gate is not None:
                return gate
            caller_id, caller_kind, subject_id, subject_kind = _parties(payload)
            decision = export_notes(
                notes,
                caller_id=caller_id,
                caller_kind=caller_kind,
                subject_id=subject_id,
                subject_kind=subject_kind,
            )
            return _status(decision), _body(decision)
        return 404, {"outcome": "refused", "reason": "unknown_path"}

    return handle


def _parties(payload: dict) -> tuple[str, str, str | None, str | None]:
    caller_id = str(payload.get("caller_id") or payload.get("owner_id") or "")
    caller_kind = str(payload.get("caller_kind") or payload.get("owner_kind") or "")
    if "subject_id" in payload or "subject_kind" in payload:
        return (
            caller_id,
            caller_kind,
            str(payload.get("subject_id") or ""),
            str(payload.get("subject_kind") or ""),
        )
    return caller_id, caller_kind, None, None


def _gate(payload: dict) -> tuple[int, dict] | None:
    caller_id, caller_kind, subject_id, subject_kind = _parties(payload)
    reason = same_owner(caller_id, caller_kind, subject_id, subject_kind)
    if reason == "missing_owner":
        return 403, {"outcome": "refused", "reason": "missing_owner"}
    if reason == "other_owner":
        return 200, {"outcome": "ok", "reason": "other_owner", "notes": []}
    return None


def _status(decision) -> int:
    return 200 if decision.outcome in {"ok", "saved"} else 403


def _flush(notes: Notes, path: Path | None) -> None:
    if path is not None:
        notes.dump(path)


def _body(decision) -> dict:
    body = {"outcome": decision.outcome, "reason": decision.reason}
    if decision.notes:
        body["notes"] = list(decision.notes)
    if decision.note_id:
        body["id"] = decision.note_id
        body["revision"] = decision.revision
    return body


def open_notes(env: dict[str, str]):
    from memoryd.sqlstore import PostgresNotes, config_reason, configured

    if configured(env):
        reason = config_reason(env)
        if reason:
            raise SystemExit(f"memoryd: {reason}")
        notes = PostgresNotes.from_env(env)
        if not _wait_postgres(notes):
            raise SystemExit("memoryd: postgres")
        return notes, None
    notes_path = Path(env["NOTES_PATH"]) if env.get("NOTES_PATH") else None
    notes = Notes.load(notes_path) if notes_path else Notes()
    return notes, notes_path


def main() -> None:
    from runtime.http import serve

    env = dict(os.environ)
    ok, reason = ready(env)
    if not ok:
        raise SystemExit(f"memoryd: {reason}")
    host = env.get("BIND_HOST", "0.0.0.0")
    port = int(env.get("PORT", "8080"))
    notes, notes_path = open_notes(env)
    indexer, searcher, hubber = _index_api(env, notes)
    if indexer is not None:
        threading.Thread(target=_index_loop, args=(indexer,), name="memory-index", daemon=True).start()
    server = serve(app(notes, env, notes_path, indexer, searcher, hubber), host, port)
    server.serve_forever()


def _wait_postgres(notes) -> bool:
    deadline = time.time() + 60
    while time.time() < deadline:
        if notes.ping():
            return True
        time.sleep(1)
    return False


def _index_api(env: dict[str, str], notes):
    from memoryd.sqlstore import configured

    if not configured(env) or not env.get("QDRANT_URL"):
        return None, None, None
    from memoryd.embed import ollama_embed
    from memoryd.hub import hub_search
    from memoryd.index import drain, search
    from memoryd.qdrant import Qdrant

    qdrant = Qdrant(env["QDRANT_URL"], env.get("QDRANT_API_KEY", ""))
    embed = ollama_embed(env.get("OLLAMA_URL", ""))
    worker = env.get("INDEX_WORKER") or "memoryd"

    def indexer() -> str:
        try:
            return drain(notes, qdrant, embed, worker)
        except Exception:
            return "postgres"

    def searcher(**kwargs):
        return search(qdrant, embed, **kwargs)

    def hubber(**kwargs):
        return hub_search(qdrant, embed, **kwargs)

    return indexer, searcher, hubber


def _index_loop(indexer) -> None:
    while True:
        try:
            indexer()
        except Exception:
            pass
        time.sleep(2)
