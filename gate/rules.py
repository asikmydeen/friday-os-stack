"""Decide whether an action may run.

The durable record is sql/approvals.sql. MemoryStore is the same
transition, in process, so the rules can be tested without a database.
Exchange holds one lock for the read, the status change, and the journal
insert. That lock is the in-process stand-in for approval_exchange().
"""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Mapping

BOARD = "board"
EXECUTOR = "executor"
TTL = timedelta(minutes=10)

LIFE_ACTIONS = frozenset({"send", "pay", "delete", "publish"})
MACHINE_ACTIONS = frozenset({
    "install",
    "uninstall",
    "grant",
    "backup",
    "publish_port",
    "publish_hostname",
    "start",
    "stop",
    "pull",
    "disconnect",
    "upgrade",
})
OPEN_ACTIONS = frozenset({"draft", "recall", "granted_tool"})
SENSITIVE = LIFE_ACTIONS | MACHINE_ACTIONS

# Prefixes the spec keeps off the app disk. "/" is refused on its own,
# because every absolute path would otherwise match it.
FORBIDDEN_PREFIXES = (
    "/etc",
    "/home",
    "/run/secrets",
    "/soul",
    "/var/lib/friday/sqlite",
    "/var/lib/docker",
)
DOCKER_SOCKET = "/var/run/docker.sock"
LOOPBACK = "127.0.0.1"
PUBLISH_OPS = frozenset({"publish_port", "publish_hostname"})

MACHINE_FIELDS = (
    "operation",
    "app_id",
    "catalog_pin",
    "template_hash",
    "rendered_digest",
    "image_digest",
    "mounts",
    "ports",
    "privileges",
    "devices",
    "manifest_privileges",
    "manifest_devices",
    "network_mode",
    "pid_mode",
    "ipc_mode",
    "storage_disk",
    "storage_device",
    "data_device",
)


@dataclass(frozen=True)
class Decision:
    outcome: str
    reason: str
    approval_id: str | None = None
    operation_id: str | None = None
    task_id: str | None = None


class MemoryStore:
    def __init__(self) -> None:
        self.approvals: dict[str, dict] = {}
        self.operations: dict[str, dict] = {}
        self.tasks: dict[str, dict] = {}
        self._lock = threading.Lock()


def create_approval(
    store: MemoryStore,
    *,
    actor: str,
    owner_id: str,
    kind: str,
    body: Mapping,
    now: datetime | None = None,
    links: Mapping[str, str] | None = None,
) -> Decision:
    if actor != BOARD:
        return Decision("refused", "actor_cannot_approve")
    # confirmed=true is not part of the record. Drop it and keep going.
    fields = {key: value for key, value in body.items() if key != "confirmed"}
    if kind == "life":
        canonical, reason = _life_body(fields)
    elif kind == "machine":
        canonical, reason = _machine_body(fields, links or {})
    else:
        return Decision("refused", "unknown_kind")
    if reason:
        return Decision("refused", reason)
    if canonical.get("operation") == "install":
        return Decision("refused", "catalog_install_closed")
    stamp = _clock(now)
    approval_id = str(uuid.uuid4())
    with store._lock:
        store.approvals[approval_id] = {
            "id": approval_id,
            "kind": kind,
            "owner_id": owner_id,
            "status": "approved",
            "body": canonical,
            "expires_at": stamp + TTL,
            "operation_id": None,
            "created_by": BOARD,
        }
    return Decision("approved", "recorded", approval_id=approval_id)


def submit(
    store: MemoryStore,
    *,
    actor: str,
    action: str,
    owner_id: str,
    approval_id: str | None = None,
    body: Mapping | None = None,
    confirmed: bool = False,
    now: datetime | None = None,
    links: Mapping[str, str] | None = None,
    steps: list[dict] | None = None,
) -> Decision:
    del confirmed  # a model flag is never an approval
    if action in OPEN_ACTIONS:
        return Decision("allowed", "open_action")
    if action == "install":
        return Decision("refused", "catalog_install_closed")
    if action not in SENSITIVE:
        return Decision("refused", "unknown_action")
    if actor != BOARD:
        reason = "actor_cannot_exchange" if approval_id else "approval_required"
        return Decision("waiting", reason)
    if not approval_id:
        return Decision("waiting", "approval_required")
    return _exchange(
        store,
        approval_id=approval_id,
        owner_id=owner_id,
        action=action,
        body=body or {},
        now=now,
        links=links or {},
        steps=steps,
    )


def resume_operation(store: MemoryStore, operation_id: str) -> Decision:
    with store._lock:
        operation = store.operations.get(operation_id)
        if operation is None:
            return Decision("refused", "unknown_operation")
        return Decision(
            "exchanged",
            "resumed",
            approval_id=operation["approval_id"],
            operation_id=operation_id,
        )


def complete_step(
    store: MemoryStore,
    operation_id: str,
    step_name: str,
    *,
    actor: str,
) -> Decision:
    if actor != EXECUTOR:
        return Decision("refused", "actor_cannot_apply", operation_id=operation_id)
    with store._lock:
        operation = store.operations.get(operation_id)
        if operation is None:
            return Decision("refused", "unknown_operation")
        found = False
        steps = []
        for step in operation["steps"]:
            if step["name"] == step_name:
                found = True
                steps.append({"name": step_name, "state": "done"})
            else:
                steps.append(dict(step))
        if not found:
            return Decision("refused", "unknown_step", operation_id=operation_id)
        if operation.get("state") == "applied":
            return Decision("exchanged", "already_applied", operation_id=operation_id)
        # A claim is not the postcondition. recover() writes applied.
        operation["steps"] = steps
        operation["state"] = "running"
        return Decision("exchanged", "step_recorded", operation_id=operation_id)


def record_task(
    store: MemoryStore,
    *,
    owner_id: str,
    role_id: str | None,
    goal: str,
    steps: list[Mapping],
) -> Decision:
    normalized = []
    for step in steps:
        name = step["name"]
        state = step.get("state", "pending")
        if state not in {"pending", "running", "done", "blocked"}:
            return Decision("refused", "unknown_step_state")
        normalized.append({"name": name, "state": state})
    state_name = task_state(normalized)
    task_id = str(uuid.uuid4())
    with store._lock:
        store.tasks[task_id] = {
            "id": task_id,
            "owner_id": owner_id,
            "role_id": role_id,
            "goal": goal,
            "steps": normalized,
            "state": state_name,
        }
    return Decision("allowed", state_name, task_id=task_id)


def resume_task(store: MemoryStore, task_id: str) -> Decision:
    with store._lock:
        task = store.tasks.get(task_id)
        if task is None:
            return Decision("refused", "unknown_task")
        # Recompute from the steps already stored. Done steps stay done,
        # a running step is not started again, and this path does not
        # insert an approval.
        task["state"] = task_state(task["steps"])
        return Decision("allowed", "resumed", task_id=task_id)


def _sensitive_name(name: object) -> bool:
    return isinstance(name, str) and name.strip().casefold() in SENSITIVE


def task_state(steps: list) -> str:
    """ready, running, waiting, done, or blocked. A running step wins over a later wait."""
    if any(step.get("state") == "blocked" for step in steps):
        return "blocked"
    if steps and all(step.get("state") == "done" for step in steps):
        return "done"
    if any(step.get("state") == "running" for step in steps):
        return "running"
    if any(_sensitive_name(step.get("name")) and step.get("state") != "done" for step in steps):
        return "waiting"
    return "ready"


def canonicalize(path: str, links: Mapping[str, str] | None = None) -> str:
    """Resolve symlinks one component at a time.

    Lexical ".." is applied to the resolved stack, so a symlink to /etc
    cannot be walked back into an allowed prefix before the check.
    """
    if not isinstance(path, str) or not path.startswith("/"):
        raise ValueError("mount_not_absolute")
    link_map = {}
    for src, dst in (links or {}).items():
        if not str(src).startswith("/") or not str(dst).startswith("/"):
            raise ValueError("mount_not_absolute")
        link_map[src] = dst
    parts = path.split("/")
    stack: list[str] = []
    index = 1
    hops = 0
    while index < len(parts):
        part = parts[index]
        index += 1
        if part in ("", "."):
            continue
        if part == "..":
            if stack:
                stack.pop()
            continue
        stack.append(part)
        built = "/" + "/".join(stack)
        if built in link_map:
            hops += 1
            if hops > 32:
                raise ValueError("mount_symlink_loop")
            target = link_map[built]
            parts = target.split("/") + parts[index:]
            stack = []
            index = 1
    if not stack:
        return "/"
    return "/" + "/".join(stack)


def _exchange(
    store: MemoryStore,
    *,
    approval_id: str,
    owner_id: str,
    action: str,
    body: Mapping,
    now: datetime | None,
    links: Mapping[str, str],
    steps: list[dict] | None,
) -> Decision:
    stamp = _clock(now)
    claimed = dict(body)
    claimed.pop("confirmed", None)
    with store._lock:
        approval = store.approvals.get(approval_id)
        if approval is None:
            return Decision("refused", "unknown_approval")
        if approval["owner_id"] != owner_id:
            return Decision("refused", "owner_mismatch", approval_id=approval_id)
        if approval["status"] == "exchanged":
            return _replay(approval, claimed, links)
        if approval["status"] != "approved":
            return Decision("refused", "not_approved", approval_id=approval_id)
        if stamp >= approval["expires_at"]:
            approval["status"] = "expired"
            return Decision("refused", "expired", approval_id=approval_id)
        # Install stays closed even if a row was inserted some other way.
        # The row is left approved so the refusal is not a consumed exchange.
        if approval["body"].get("operation") == "install":
            return Decision("refused", "catalog_install_closed", approval_id=approval_id)
        recorded = approval["body"].get("operation") or approval["body"].get("action_class")
        if action != recorded:
            approval["status"] = "void"
            return Decision("refused", "void", approval_id=approval_id)
        try:
            claimed_body = _claim_body(approval, claimed, links)
        except ValueError as exc:
            return Decision("refused", str(exc), approval_id=approval_id)
        if _freeze(approval["body"]) != _freeze(claimed_body):
            approval["status"] = "void"
            return Decision("refused", "void", approval_id=approval_id)
        operation_name = approval["body"].get("operation") or approval["body"]["action_class"]
        if steps is None:
            journal_steps = [{"name": operation_name, "state": "pending"}]
        else:
            journal_steps = [dict(step) for step in steps]
        operation_id = str(uuid.uuid4())
        store.operations[operation_id] = {
            "id": operation_id,
            "approval_id": approval_id,
            "owner_id": owner_id,
            "kind": approval["kind"],
            "operation": operation_name,
            "steps": journal_steps,
            "state": "ready",
        }
        approval["status"] = "exchanged"
        approval["operation_id"] = operation_id
        return Decision(
            "exchanged",
            "exchanged",
            approval_id=approval_id,
            operation_id=operation_id,
        )


def _replay(approval: dict, claimed: Mapping, links: Mapping[str, str]) -> Decision:
    """A second exchange returns the same journal and does not rewrite it."""
    try:
        claimed_body = _claim_body(approval, claimed, links)
        same = _freeze(approval["body"]) == _freeze(claimed_body)
    except ValueError:
        same = False
    if not same:
        return Decision(
            "refused",
            "already_exchanged",
            approval_id=approval["id"],
            operation_id=approval["operation_id"],
        )
    return Decision(
        "exchanged",
        "already_exchanged",
        approval_id=approval["id"],
        operation_id=approval["operation_id"],
    )


def _claim_body(approval: dict, claimed: Mapping, links: Mapping[str, str]) -> dict:
    if approval["kind"] == "life":
        body, reason = _life_body(claimed)
    else:
        body, reason = _machine_body(claimed, links)
    if reason:
        raise ValueError(reason)
    return body


def _life_body(fields: Mapping) -> tuple[dict | None, str | None]:
    action = fields.get("action_class")
    if action not in LIFE_ACTIONS:
        return None, "unknown_action"
    target = fields.get("target")
    digest = fields.get("payload_digest")
    if not _text(target):
        return None, "missing:target"
    if not _text(digest):
        return None, "missing:payload_digest"
    return {
        "action_class": action,
        "target": target,
        "payload_digest": digest,
    }, None


def _machine_body(fields: Mapping, links: Mapping[str, str]) -> tuple[dict | None, str | None]:
    for name in MACHINE_FIELDS:
        if name not in fields:
            return None, f"missing:{name}"
    operation = fields["operation"]
    if operation not in MACHINE_ACTIONS:
        return None, "unknown_action"
    for name in (
        "app_id",
        "catalog_pin",
        "template_hash",
        "rendered_digest",
        "image_digest",
        "storage_disk",
        "storage_device",
        "data_device",
    ):
        if not _text(fields[name]):
            return None, f"missing:{name}"
    if fields["network_mode"] not in {"bridge", "none"}:
        return None, "host_network"
    if fields["pid_mode"] != "private":
        return None, "host_pid"
    if fields["ipc_mode"] != "private":
        return None, "host_ipc"
    if fields["storage_device"] == fields["data_device"]:
        return None, "storage_on_data_partition"
    privileges = _str_list(fields["privileges"])
    devices = _str_list(fields["devices"])
    manifest_privileges = _str_list(fields["manifest_privileges"])
    manifest_devices = _str_list(fields["manifest_devices"])
    if privileges is None or devices is None or manifest_privileges is None or manifest_devices is None:
        return None, "missing:list"
    if any(item not in manifest_privileges for item in privileges):
        return None, "privilege_not_in_manifest"
    if any(item not in manifest_devices for item in devices):
        return None, "device_not_in_manifest"
    raw_mounts = _str_list(fields["mounts"])
    if raw_mounts is None:
        return None, "missing:mounts"
    try:
        storage_disk = canonicalize(fields["storage_disk"], links)
        mounts = [canonicalize(mount, links) for mount in raw_mounts]
    except ValueError as exc:
        return None, str(exc)
    reason = _mounts_allowed(mounts, storage_disk)
    if reason:
        return None, reason
    ports, port_reason = _ports(fields["ports"], operation)
    if port_reason:
        return None, port_reason
    return {
        "operation": operation,
        "app_id": fields["app_id"],
        "catalog_pin": fields["catalog_pin"],
        "template_hash": fields["template_hash"],
        "rendered_digest": fields["rendered_digest"],
        "image_digest": fields["image_digest"],
        "mounts": mounts,
        "ports": ports,
        "privileges": privileges,
        "devices": devices,
        "manifest_privileges": manifest_privileges,
        "manifest_devices": manifest_devices,
        "network_mode": fields["network_mode"],
        "pid_mode": "private",
        "ipc_mode": "private",
        "storage_disk": storage_disk,
        "storage_device": fields["storage_device"],
        "data_device": fields["data_device"],
    }, None


def claim_body(
    kind: str,
    fields: Mapping,
    links: Mapping[str, str] | None = None,
) -> tuple[dict | None, str | None]:
    """Canonical body for one kind. A bad mount is a reason, not a stored row."""
    if kind == "life":
        return _life_body(fields)
    if kind == "machine":
        return _machine_body(fields, links or {})
    return None, "unknown_kind"


def _mounts_allowed(mounts: list[str], storage_disk: str) -> str | None:
    if _forbidden(storage_disk):
        return "mount_forbidden"
    for mount in mounts:
        if mount == "/":
            return "mount_root"
        if mount == DOCKER_SOCKET or _forbidden(mount):
            return "mount_forbidden"
        if mount != storage_disk and not mount.startswith(storage_disk.rstrip("/") + "/"):
            return "mount_outside_disk"
    return None


def _forbidden(path: str) -> bool:
    if path == DOCKER_SOCKET:
        return True
    for root in FORBIDDEN_PREFIXES:
        if path == root or path.startswith(root.rstrip("/") + "/"):
            return True
    return False


def _ports(value, operation: str) -> tuple[list[dict] | None, str | None]:
    if not isinstance(value, (list, tuple)):
        return None, "missing:ports"
    ports = []
    for item in value:
        if not isinstance(item, Mapping):
            return None, "missing:ports"
        host_ip = item.get("host_ip")
        host_port = item.get("host_port")
        container_port = item.get("container_port")
        if (
            not _text(host_ip)
            or isinstance(host_port, bool)
            or not isinstance(host_port, int)
            or isinstance(container_port, bool)
            or not isinstance(container_port, int)
        ):
            return None, "missing:ports"
        if operation not in PUBLISH_OPS and host_ip != LOOPBACK:
            return None, "port_not_loopback"
        ports.append({
            "host_ip": host_ip,
            "host_port": host_port,
            "container_port": container_port,
        })
    return ports, None


def _str_list(value) -> list[str] | None:
    if not isinstance(value, (list, tuple)):
        return None
    if any(not _text(item) for item in value):
        return None
    return list(value)


def _text(value) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _freeze(body: Mapping) -> str:
    return json.dumps(body, sort_keys=True, separators=(",", ":"))


def _clock(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return now
