"""Write one approval through approval_store.

The caller supplies the connection. A forbidden mount, a credential-shaped
target, chat, and catalog install are refused before that connection
opens. A failure is the reason postgres and does not include the body or
the driver text. Without a connection the process file remains. A second
exchange of the same body returns the same operation id. A different body
voids an approved row and does not rewrite an exchanged one. Nothing is
sent and no container is started.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping
from urllib.parse import unquote_plus

from gate.rules import (
    BOARD,
    LIFE_ACTIONS,
    MACHINE_ACTIONS,
    TTL,
    Decision,
    MemoryStore,
    claim_body,
    create_approval,
)
from memoryd.store import credential_shape

SCHEMA = Path(__file__).resolve().parents[1] / "sql" / "approvals.sql"
_DIGEST_KEYS = frozenset({
    "payload_digest",
    "catalog_pin",
    "template_hash",
    "rendered_digest",
    "image_digest",
})
_DIGEST_VALUE = re.compile(r"[0-9a-f]{40}\Z|[0-9a-f]{64}\Z")
_SQL_REASONS = frozenset({
    "actor_cannot_approve",
    "actor_cannot_exchange",
    "catalog_install_closed",
    "unknown_kind",
    "missing_owner",
    "unknown_action",
    "unknown_approval",
    "owner_mismatch",
    "already_exchanged",
    "not_approved",
    "void",
    "expired",
})


class ApprovalError(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class PostgresApprovals:
    def __init__(self, connect) -> None:
        self._connect = connect

    @classmethod
    def from_env(cls, env: dict[str, str]) -> PostgresApprovals:
        if not env.get("POSTGRES_PASSWORD") or not env.get("POSTGRES_USER"):
            raise ApprovalError("postgres")
        try:
            import psycopg
        except ImportError as exc:
            raise ApprovalError("postgres") from exc
        host = env["POSTGRES_HOST"]
        port = int(env.get("POSTGRES_PORT") or "5432")
        dbname = env.get("POSTGRES_DB") or "memories"
        user = env["POSTGRES_USER"]
        password = env["POSTGRES_PASSWORD"]

        def connect():
            return psycopg.connect(
                host=host,
                port=port,
                dbname=dbname,
                user=user,
                password=password,
                connect_timeout=5,
            )

        return cls(connect)

    def ensure(self) -> bool:
        try:
            script = SCHEMA.read_text(encoding="utf-8")
        except OSError:
            return False
        try:
            parts = statements(script)
        except ValueError:
            return False
        if not parts:
            return False
        try:
            with self._connect() as conn:
                for part in parts:
                    conn.execute(part)
        except Exception:
            return False
        return True

    def store(self, owner_id: str, kind: str, body: Mapping) -> str:
        payload = json.dumps(body, sort_keys=True, separators=(",", ":"))
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT approval_store(%s, %s, %s, %s::jsonb)::text",
                    (BOARD, owner_id, kind, payload),
                ).fetchone()
        except Exception as exc:
            raise ApprovalError(_reason(exc)) from None
        found = _uuid(None if row is None else row[0])
        if not found:
            raise ApprovalError("postgres")
        return found

    def exchange(self, approval_id: str, owner_id: str, body: Mapping) -> str:
        payload = json.dumps(body, sort_keys=True, separators=(",", ":"))
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT approval_exchange_owner(%s, %s::uuid, %s, %s::jsonb)::text",
                    (BOARD, approval_id, owner_id, payload),
                ).fetchone()
                found = _uuid(None if row is None else row[0])
                if found:
                    return found
                status = conn.execute(
                    "SELECT status FROM approvals WHERE id = %s::uuid",
                    (approval_id,),
                ).fetchone()
        except ApprovalError:
            raise
        except Exception as exc:
            raise ApprovalError(_reason(exc)) from None
        name = "" if status is None else status[0]
        if name in {"void", "expired"}:
            raise ApprovalError(name)
        raise ApprovalError("postgres")


def record_approval(store: MemoryStore, fields: Mapping, client=None) -> Decision:
    """Record one approval. Refusals do not open the connection."""
    if not isinstance(fields, Mapping):
        return Decision("refused", "unknown_action")
    if client is not None and (_install(fields) or _tree_hidden(fields)):
        reason = "catalog_install_closed" if _install(fields) else "credential"
        return Decision("refused", reason)
    actor = str(fields.get("actor") or "")
    owner = fields.get("owner_id")
    if client is not None and (not isinstance(owner, str) or owner.strip() == ""):
        return Decision("refused", "missing_owner")
    action = str(fields.get("action") or fields.get("operation") or "")
    kind = "life" if action in LIFE_ACTIONS else "machine"
    body = fields.get("body") if isinstance(fields.get("body"), Mapping) else {}
    links = fields.get("links") if isinstance(fields.get("links"), Mapping) else {}
    target = store if client is None else MemoryStore()
    decision = create_approval(
        target,
        actor=actor,
        owner_id=str(owner or ""),
        kind=kind,
        body=body,
        links=links,
    )
    if decision.outcome != "approved" or client is None:
        return decision
    canonical = target.approvals[decision.approval_id]["body"]
    try:
        approval_id = client.store(str(owner), kind, canonical)
    except ApprovalError as exc:
        return Decision("refused", exc.reason)
    held = target.approvals[decision.approval_id]
    with store._lock:
        store.approvals[approval_id] = {
            "id": approval_id,
            "kind": held["kind"],
            "owner_id": held["owner_id"],
            "status": "approved",
            "body": held["body"],
            "expires_at": held["expires_at"],
            "operation_id": None,
            "created_by": BOARD,
        }
    return Decision("approved", "recorded", approval_id=approval_id)


def exchange_approval(
    store: MemoryStore,
    fields: Mapping,
    client,
    book: dict[str, str],
) -> Decision:
    """Exchange one approval. A bad claim does not open the connection."""
    if not isinstance(fields, Mapping) or client is None:
        return Decision("refused", "unknown_action")
    if _install(fields):
        return Decision("refused", "catalog_install_closed")
    if _tree_hidden(fields):
        return Decision("refused", "credential")
    actor = fields.get("actor")
    approval_id = fields.get("approval_id")
    if actor != BOARD:
        reason = "actor_cannot_exchange" if approval_id else "approval_required"
        return Decision("waiting", reason)
    if not isinstance(approval_id, str) or _uuid(approval_id) == "":
        return Decision("waiting", "approval_required")
    owner = fields.get("owner_id")
    if not isinstance(owner, str) or owner.strip() == "":
        return Decision("refused", "missing_owner")
    action = fields.get("action")
    if action not in LIFE_ACTIONS and action not in MACHINE_ACTIONS:
        return Decision("refused", "unknown_action")
    raw = fields.get("body") if isinstance(fields.get("body"), Mapping) else {}
    links = fields.get("links") if isinstance(fields.get("links"), Mapping) else {}
    kind = "life" if action in LIFE_ACTIONS else "machine"
    canonical, reason = claim_body(kind, raw, links)
    if reason or canonical is None:
        return Decision("refused", reason or "unknown_action", approval_id=approval_id)
    try:
        operation_id = client.exchange(approval_id, owner, canonical)
    except ApprovalError as exc:
        return Decision("refused", exc.reason, approval_id=approval_id)
    previous = book.get(approval_id)
    book[approval_id] = operation_id
    _mirror(store, approval_id, owner, kind, canonical, operation_id)
    kept = "already_exchanged" if previous == operation_id else "exchanged"
    return Decision(
        "exchanged",
        kept,
        approval_id=approval_id,
        operation_id=operation_id,
    )


def statements(script: str) -> list[str]:
    """Split a script. A dollar-quoted function body stays one statement."""
    out: list[str] = []
    buf: list[str] = []
    index = 0
    length = len(script)
    while index < length:
        if script.startswith("--", index):
            end = script.find("\n", index)
            index = length if end == -1 else end + 1
            continue
        if script.startswith("$$", index):
            end = script.find("$$", index + 2)
            if end == -1:
                raise ValueError("schema")
            buf.append(script[index:end + 2])
            index = end + 2
            continue
        if script[index] == ";":
            text = "".join(buf).strip()
            if text:
                out.append(text)
            buf = []
            index += 1
            continue
        buf.append(script[index])
        index += 1
    tail = "".join(buf).strip()
    if tail:
        out.append(tail)
    return out


def _mirror(
    store: MemoryStore,
    approval_id: str,
    owner_id: str,
    kind: str,
    body: Mapping,
    operation_id: str,
) -> None:
    operation_name = body.get("operation") or body.get("action_class")
    with store._lock:
        approval = store.approvals.get(approval_id)
        if approval is None:
            store.approvals[approval_id] = {
                "id": approval_id,
                "kind": kind,
                "owner_id": owner_id,
                "status": "exchanged",
                "body": dict(body),
                "expires_at": datetime.now(timezone.utc) + TTL,
                "operation_id": operation_id,
                "created_by": BOARD,
            }
        else:
            approval["status"] = "exchanged"
            approval["operation_id"] = operation_id
        store.operations[operation_id] = {
            "id": operation_id,
            "approval_id": approval_id,
            "owner_id": owner_id,
            "kind": kind,
            "operation": operation_name,
            "steps": [{"name": operation_name, "state": "pending"}],
            "state": "ready",
        }


def _install(fields: Mapping) -> bool:
    if fields.get("action") == "install" or fields.get("operation") == "install":
        return True
    body = fields.get("body")
    if isinstance(body, Mapping) and (body.get("operation") == "install" or body.get("action") == "install"):
        return True
    return False


def _tree_hidden(value: object, key: str = "") -> bool:
    if isinstance(value, str):
        if _uuid(value):
            return False
        if key in _DIGEST_KEYS and _DIGEST_VALUE.fullmatch(value.casefold()) is not None:
            return False
        return _hidden(value)
    if isinstance(value, Mapping):
        return any(_tree_hidden(str(name)) or _tree_hidden(item, str(name)) for name, item in value.items())
    if isinstance(value, (list, tuple)):
        return any(_tree_hidden(item) for item in value)
    return False


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


def _reason(exc: Exception) -> str:
    if isinstance(exc, ApprovalError):
        return exc.reason
    text = str(exc).strip()
    if text in _SQL_REASONS:
        return text
    return "postgres"


def _uuid(value: object) -> str:
    if isinstance(value, uuid.UUID):
        value = str(value)
    if not isinstance(value, str):
        return ""
    try:
        parsed = uuid.UUID(value)
    except ValueError:
        return ""
    if str(parsed) != value:
        return ""
    return value
