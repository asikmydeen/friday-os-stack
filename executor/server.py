"""Record approvals and tasks. Perform nothing outside the journal.

The Board presents Friday-Approval. Friday presents Friday-Notify and
can only write a task. A task is not an approval. Install is refused
and no approval row is stored for it.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from gate.rules import (
    LIFE_ACTIONS,
    MemoryStore,
    create_approval,
    record_task,
    submit,
)
from runtime.http import header, same

REQUIRED = ("BOARD_APPROVAL_TOKEN", "FRIDAY_NOTIFY_TOKEN")


def ready(env: dict[str, str]) -> str:
    if any(not env.get(name) for name in REQUIRED):
        return "secrets"
    return ""


def app(store: MemoryStore, env: dict[str, str], path: Path | None = None):
    def handle(method: str, route: str, headers, payload: dict) -> tuple[int, dict]:
        if route == "/health" and method == "GET":
            return 200, {"outcome": "ok", "reason": "health", "started": False}
        secret = ready(env)
        if route == "/ready" and method == "GET":
            return (200 if not secret else 503), {
                "outcome": "ok" if not secret else "refused",
                "reason": "ready" if not secret else secret,
                "started": False,
            }
        if secret:
            return 503, {"outcome": "refused", "reason": secret, "started": False}
        if route == "/tasks" and method == "POST":
            if not _token(headers, "Friday-Notify", env["FRIDAY_NOTIFY_TOKEN"]):
                return 401, {"outcome": "refused", "reason": "unauthenticated", "started": False}
            decision = record_task(
                store,
                owner_id=str(payload.get("owner_id") or ""),
                role_id=payload.get("role_id"),
                goal=str(payload.get("goal") or ""),
                steps=list(payload.get("steps") or []),
            )
            _flush(store, path)
            return _status(decision), _body(decision)
        if not _token(headers, "Friday-Approval", env["BOARD_APPROVAL_TOKEN"]):
            return 401, {"outcome": "refused", "reason": "unauthenticated", "started": False}
        if route == "/approvals" and method == "POST":
            action = str(payload.get("action") or payload.get("operation") or "")
            if action == "install" or payload.get("operation") == "install":
                return 403, {"outcome": "refused", "reason": "catalog_install_closed", "started": False}
            kind = "life" if action in LIFE_ACTIONS else "machine"
            decision = create_approval(
                store,
                actor=str(payload.get("actor") or ""),
                owner_id=str(payload.get("owner_id") or ""),
                kind=kind,
                body=payload.get("body") or {},
            )
            _flush(store, path)
            return _status(decision), _body(decision)
        if route == "/exchange" and method == "POST":
            decision = submit(
                store,
                actor=str(payload.get("actor") or ""),
                action=str(payload.get("action") or ""),
                owner_id=str(payload.get("owner_id") or ""),
                approval_id=payload.get("approval_id"),
                body=payload.get("body") or {},
            )
            _flush(store, path)
            body = _body(decision)
            body["started"] = False
            return _status(decision), body
        if route == "/complete" and method == "POST":
            return 403, {
                "outcome": "refused",
                "reason": "not_performed",
                "started": False,
            }
        return 404, {"outcome": "refused", "reason": "unknown_path", "started": False}

    return handle


def _token(headers, name: str, expected: str) -> bool:
    presented = header(headers, name)
    return bool(expected) and bool(presented) and same(presented, expected)


def _status(decision) -> int:
    if decision.outcome in {"approved", "exchanged", "allowed"}:
        return 200
    if decision.outcome == "waiting":
        return 202
    return 403


def _body(decision) -> dict:
    return {
        "outcome": decision.outcome,
        "reason": decision.reason,
        "approval_id": decision.approval_id,
        "operation_id": decision.operation_id,
        "task_id": decision.task_id,
        "started": False,
    }


def _flush(store: MemoryStore, path: Path | None) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "approvals": _boxes(store.approvals),
        "operations": store.operations,
        "tasks": store.tasks,
    }
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload), encoding="utf-8")
    temporary.replace(path)


def _boxes(approvals: dict) -> dict:
    copied = {}
    for key, row in approvals.items():
        item = dict(row)
        expires = item.get("expires_at")
        if isinstance(expires, datetime):
            item["expires_at"] = expires.isoformat()
        copied[key] = item
    return copied


def load_store(path: Path) -> MemoryStore:
    store = MemoryStore()
    if not path.is_file():
        return store
    raw = json.loads(path.read_text(encoding="utf-8"))
    for key, row in raw.get("approvals", {}).items():
        item = dict(row)
        expires = item.get("expires_at")
        if isinstance(expires, str):
            item["expires_at"] = datetime.fromisoformat(expires)
        store.approvals[key] = item
    store.operations.update(raw.get("operations", {}))
    store.tasks.update(raw.get("tasks", {}))
    return store


def main() -> None:
    from runtime.http import serve

    env = dict(os.environ)
    reason = ready(env)
    if reason:
        raise SystemExit(f"executor: {reason}")
    store_path = Path(env["STORE_PATH"]) if env.get("STORE_PATH") else None
    store = load_store(store_path) if store_path else MemoryStore()
    host = env.get("BIND_HOST", "0.0.0.0")
    port = int(env.get("PORT", "8080"))
    serve(app(store, env, store_path), host, port).serve_forever()
