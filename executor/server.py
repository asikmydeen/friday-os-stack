"""Record approvals and tasks. Perform nothing outside the journal.

The Board presents Friday-Approval. Friday presents Friday-Notify and
can only write a task. A task is not an approval. Install is refused
and no approval row is stored for it. GET /tasks lists one owner's
goals for the Board. A credential-shaped goal is left off that list.
Listing does not start a task. /recover compares objects the caller
supplies with one journal. A caller-supplied runtime creates the
container step. Applied is recorded only when that runtime says the
container is up. A second resume does not create it again. The host
Docker daemon is not called. Without a runtime it does not create a
container.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote_plus

from backup.sqlstore import ManifestError, PostgresManifests, record_manifest
from gate.recover import recover
from gate.sqlstore import ApprovalError, PostgresApprovals, exchange_approval, record_approval
from gate.rules import (
    LIFE_ACTIONS,
    MemoryStore,
    create_approval,
    record_task,
    submit,
    task_state,
)
from memoryd.store import credential_shape
from runtime.http import header, same

_ROLE = re.compile(r"[a-z][a-z0-9_-]{0,31}\Z")
_STEP = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")
_TASK_STATES = frozenset({"ready", "running", "waiting", "done", "blocked"})
_STEP_STATES = frozenset({"pending", "running", "done", "blocked"})
_LIST_CAP = 8

REQUIRED = ("BOARD_APPROVAL_TOKEN", "FRIDAY_NOTIFY_TOKEN")


def ready(env: dict[str, str]) -> str:
    if any(not env.get(name) for name in REQUIRED):
        return "secrets"
    return ""


def app(
    store: MemoryStore,
    env: dict[str, str],
    path: Path | None = None,
    manifests=None,
    approvals=None,
    runtime=None,
):
    """manifests is backup_store when POSTGRES_HOST is set. Otherwise the book is memory.

    approvals is approval_store on that same host. Otherwise the gate file remains.
    runtime creates the container step when the caller supplies one. A
    name in the request is not a runtime. The host daemon is not called.
    """
    backup_book: dict[str, str] = {}
    exchange_book: dict[str, str] = {}

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
        if route == "/backup" and method == "POST":
            decision = record_manifest(backup_book, payload, manifests)
            return _backup_status(decision)
        if route == "/backup":
            return 405, {
                "outcome": "refused",
                "reason": "method_refused",
                "copied": False,
                "started": False,
            }
        if route == "/tasks" and method == "GET":
            return _listed(store, headers)
        if route == "/approvals" and method == "POST":
            action = str(payload.get("action") or payload.get("operation") or "")
            if action == "install" or payload.get("operation") == "install":
                return 403, {"outcome": "refused", "reason": "catalog_install_closed", "started": False}
            if approvals is not None:
                decision = record_approval(store, payload, approvals)
                if decision.outcome == "approved":
                    _flush(store, path)
                return _pg_status(decision)
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
            if approvals is not None:
                decision = exchange_approval(store, payload, approvals, exchange_book)
                if decision.outcome == "exchanged":
                    _flush(store, path)
                return _pg_status(decision)
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
        if route == "/recover" and method == "POST":
            decision = recover(
                store,
                str(payload.get("operation_id") or ""),
                payload.get("seen"),
                actor="executor",
                runtime=runtime,
            )
            if decision.outcome in {"running", "applied", "blocked"}:
                _flush(store, path)
            status = 200 if decision.outcome in {"running", "applied"} else 403
            return status, {
                "outcome": decision.outcome,
                "reason": decision.reason,
                "operation_id": decision.operation_id,
                "step": decision.step,
                "action": decision.action,
                "create": decision.create,
                "started": decision.started,
            }
        return 404, {"outcome": "refused", "reason": "unknown_path", "started": False}

    return handle


def _backup_status(decision) -> tuple[int, dict]:
    if decision.outcome == "manifested":
        status = 200
    elif decision.reason == "postgres":
        status = 503
    else:
        status = 403
    body = {
        "outcome": decision.outcome,
        "reason": decision.reason,
        "copied": False,
        "started": False,
    }
    if decision.manifest_id and _pause_id(decision.manifest_id):
        body["manifest_id"] = decision.manifest_id
    return status, body


def _pg_status(decision) -> tuple[int, dict]:
    status = 503 if decision.reason == "postgres" else _status(decision)
    body = _body(decision)
    body["started"] = False
    body["sent"] = False
    if decision.reason == "postgres":
        body["approval_id"] = None
        body["operation_id"] = None
        body["task_id"] = None
    return status, body


def _pause_id(value: str) -> bool:
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        return False
    return str(parsed) == value


def _listed(store: MemoryStore, headers) -> tuple[int, dict]:
    owner = header(headers, "Friday-Owner")
    if _bad_owner(owner):
        return 403, {"outcome": "refused", "reason": "missing_owner", "started": False, "tasks": []}
    with store._lock:
        items = []
        for task in store.tasks.values():
            if not isinstance(task, dict):
                continue
            copied = dict(task)
            steps = copied.get("steps") or []
            copied["steps"] = [dict(step) for step in steps if isinstance(step, dict)]
            items.append(copied)
    rows = []
    for task in reversed(items):
        if task.get("owner_id") != owner:
            continue
        goal = task.get("goal")
        if not isinstance(goal, str) or _secret(goal):
            continue
        shown = " ".join(goal.split())[:200]
        if shown == "" or _secret(shown):
            continue
        ident = task.get("id")
        if not isinstance(ident, str) or ident == "" or _secret(ident):
            continue
        role = task.get("role_id")
        if not isinstance(role, str) or _ROLE.fullmatch(role) is None:
            role = "friday"
        steps = _public_steps(task.get("steps"))
        state = task.get("state")
        if state not in _TASK_STATES:
            state = task_state(steps)
        if state not in _TASK_STATES:
            state = "ready"
        rows.append({"id": ident, "state": state, "role": role, "goal": shown, "steps": steps})
        if len(rows) >= _LIST_CAP:
            break
    return 200, {"outcome": "ok", "reason": "tasks", "started": False, "tasks": rows}


def _public_steps(steps) -> list[dict]:
    found = []
    for step in steps or []:
        if not isinstance(step, dict):
            continue
        name = step.get("name")
        state = step.get("state")
        if not isinstance(name, str) or _STEP.fullmatch(name) is None or _secret(name):
            continue
        if state not in _STEP_STATES:
            continue
        found.append({"name": name, "state": state})
        if len(found) >= _LIST_CAP:
            break
    return found


def _bad_owner(owner: str) -> bool:
    if not isinstance(owner, str) or owner == "" or len(owner) > 64:
        return True
    if owner != owner.strip() or any(mark in owner for mark in "\n\r\x00"):
        return True
    return _secret(owner)


def _secret(text: str) -> bool:
    seen = text
    for _ in range(3):
        if credential_shape(" ".join(seen.split())):
            return True
        decoded = unquote_plus(seen)
        if decoded == seen:
            return False
        seen = decoded
    return credential_shape(" ".join(seen.split()))


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


def open_manifests(env: dict[str, str]):
    """None when Postgres is unset. Otherwise backup_store, after the schema is applied."""
    return _open_client(env, PostgresManifests, ManifestError)


def open_approvals(env: dict[str, str]):
    """None when Postgres is unset. Otherwise approval_store, after the schema is applied."""
    return _open_client(env, PostgresApprovals, ApprovalError)


def _open_client(env: dict[str, str], kind, error: type[Exception]):
    if not env.get("POSTGRES_HOST"):
        return None
    try:
        client = kind.from_env(env)
    except error as exc:
        raise SystemExit("executor: postgres") from exc
    deadline = time.time() + 60
    while True:
        if client.ensure():
            return client
        if time.time() >= deadline:
            raise SystemExit("executor: postgres")
        time.sleep(1)


def main() -> None:
    from runtime.bind import bind_host
    from runtime.http import serve

    env = dict(os.environ)
    reason = ready(env)
    if reason:
        raise SystemExit(f"executor: {reason}")
    store_path = Path(env["STORE_PATH"]) if env.get("STORE_PATH") else None
    store = load_store(store_path) if store_path else MemoryStore()
    manifests = open_manifests(env)
    approvals = open_approvals(env)
    try:
        host = bind_host(env)
    except OSError as exc:
        raise SystemExit(f"executor: {exc}") from None
    port = int(env.get("PORT", "8080"))
    serve(app(store, env, store_path, manifests, approvals), host, port).serve_forever()
