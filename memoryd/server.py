"""HTTP front for the notes store.

Friday presents Friday-Memory. The header is the memory token. The
Qdrant key is required to be present so a half-written environment does
not serve recall. This process sends that key only to Qdrant.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

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


def app(notes: Notes, env: dict[str, str], path: Path | None = None, indexer=None, searcher=None):
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
        if route == "/save" and method == "POST":
            decision = notes.save(
                owner_id=str(payload.get("owner_id") or ""),
                owner_kind=str(payload.get("owner_kind") or ""),
                content=str(payload.get("content") or ""),
                visibility=str(payload.get("visibility") or "master"),
                category=str(payload.get("category") or ""),
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
            if searcher is None:
                return 503, {"outcome": "refused", "reason": "index_not_ready"}
            limit = payload.get("limit", 8)
            decision = searcher(
                owner_id=str(payload.get("owner_id") or ""),
                owner_kind=str(payload.get("owner_kind") or ""),
                text=str(payload.get("text") or ""),
                limit=limit if isinstance(limit, int) else 8,
            )
            return _status(decision), _body(decision)
        return 404, {"outcome": "refused", "reason": "unknown_path"}

    return handle


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
    indexer, searcher = _index_api(env, notes)
    if indexer is not None:
        threading.Thread(target=_index_loop, args=(indexer,), name="memory-index", daemon=True).start()
    server = serve(app(notes, env, notes_path, indexer, searcher), host, port)
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
        return None, None
    from memoryd.embed import ollama_embed
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

    return indexer, searcher


def _index_loop(indexer) -> None:
    while True:
        try:
            indexer()
        except Exception:
            pass
        time.sleep(2)
