"""Resume one journal from objects the caller already saw.

A label names the journal. It does not mean the operation finished.
Applied is written only when every step's postcondition holds. A
network and a volume, with no running container, stay unapplied. A
container that is already stopped is not stopped again. Two labeled
containers block the journal, and this function does not ask for
another. Catalog install stays closed.

A caller may supply a runtime for the container step. That runtime
reports labeled containers and creates one when the step has none.
Applied is recorded only when the runtime says the container is up. A
second resume does not create it again. This module does not inspect
Docker and does not call the host Docker daemon. Without a runtime it
does not create a container.
"""

from __future__ import annotations

from dataclasses import dataclass

LABEL = "friday.operation"
EXECUTOR = "executor"
PRESENT = frozenset({
    "running",
    "exited",
    "stopped",
    "created",
    "paused",
    "dead",
    "restarting",
})
STOPPED = frozenset({"exited", "stopped"})
KNOWN = frozenset({
    "network",
    "volume",
    "container",
    "start",
    "stop",
    "disconnect",
    "pull",
})


@dataclass(frozen=True)
class Recovery:
    outcome: str
    reason: str
    operation_id: str | None = None
    step: str | None = None
    action: str | None = None
    create: bool = False
    started: bool = False


def recover(
    store,
    operation_id: str,
    seen,
    *,
    actor: str,
    confirmed: bool = False,
    runtime=None,
) -> Recovery:
    del confirmed
    with store._lock:
        operation = store.operations.get(operation_id)
        if operation is None:
            return Recovery("refused", "unknown_operation")
        if actor != EXECUTOR:
            return Recovery("refused", "actor_cannot_apply", operation_id=operation_id)
        if operation.get("operation") == "install":
            return Recovery("refused", "catalog_install_closed", operation_id=operation_id)
        if operation.get("state") == "applied":
            return Recovery("applied", "already_applied", operation_id=operation_id)
        steps = operation.get("steps") or []
        if not steps or any(step.get("name") not in KNOWN for step in steps):
            return Recovery("refused", "unknown_step", operation_id=operation_id)
        try:
            view = _view(seen, operation_id, _digest(store, operation))
        except ValueError as exc:
            return Recovery("refused", str(exc), operation_id=operation_id)
        started = False
        for index, step in enumerate(steps):
            if runtime is not None and step.get("name") == "container":
                try:
                    statuses, made = _runtime_step(runtime, operation_id)
                except ValueError as exc:
                    return Recovery("refused", str(exc), operation_id=operation_id)
                view["containers"] = statuses
                if made and statuses == ["running"]:
                    started = True
            kind, reason, action, create = _post(step["name"], view)
            if kind == "hold":
                return Recovery("refused", reason, operation_id=operation_id, started=started)
            if kind == "pass":
                continue
            _rewrite(operation, index, "running" if kind == "run" else "blocked")
            return Recovery(
                "running" if kind == "run" else "blocked",
                reason,
                operation_id=operation_id,
                step=step["name"],
                action=action,
                create=create,
                started=started,
            )
        _rewrite(operation, len(steps), "applied")
        return Recovery("applied", "applied", operation_id=operation_id, started=started)


def _digest(store, operation: dict) -> str:
    approval = store.approvals.get(operation.get("approval_id"))
    if not approval:
        return ""
    digest = approval.get("body", {}).get("image_digest")
    return digest if isinstance(digest, str) else ""


def _view(seen, operation_id: str, digest: str) -> dict:
    if not isinstance(seen, dict):
        raise ValueError("observation_missing")
    connected = seen.get("connected", None)
    if connected is not None and not isinstance(connected, bool):
        raise ValueError("observation_missing")
    images = seen.get("images", [])
    if not isinstance(images, list) or any(not isinstance(item, str) for item in images):
        raise ValueError("observation_missing")
    return {
        "networks": len(_matched(seen.get("networks", []), operation_id, False)),
        "volumes": len(_matched(seen.get("volumes", []), operation_id, False)),
        "containers": _matched(seen.get("containers", []), operation_id, True),
        "connected": connected,
        "images": set(images),
        "digest": digest,
    }


def _matched(items, operation_id: str, need_status: bool) -> list[str]:
    if not isinstance(items, list):
        raise ValueError("observation_missing")
    found = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("observation_missing")
        labels = item.get("labels", {})
        if not isinstance(labels, dict):
            raise ValueError("observation_missing")
        if labels.get(LABEL) != operation_id:
            continue
        if not need_status:
            found.append("")
            continue
        status = item.get("status")
        if not isinstance(status, str) or status.casefold() not in PRESENT:
            raise ValueError("observation_incomplete")
        found.append(status.casefold())
    return found


def _post(name: str, view: dict) -> tuple[str, str, str | None, bool]:
    if name == "network":
        return _count(view["networks"], "network", "second_network")
    if name == "volume":
        return _count(view["volumes"], "volume", "second_volume")
    if name == "container":
        return _up(view, missing=("run", "resume", "container", True))
    if name == "start":
        return _up(view, missing=("block", "container_missing", None, False))
    if name == "stop":
        return _stopped(view)
    if name == "disconnect":
        return _disconnect(view)
    if view["digest"] and view["digest"] in view["images"]:
        return "pass", "", None, False
    return "run", "resume", "pull", False


def _count(count: int, action: str, duplicate: str) -> tuple[str, str, str | None, bool]:
    if count == 0:
        return "run", "resume", action, True
    if count == 1:
        return "pass", "", None, False
    return "block", duplicate, None, False


def _up(view: dict, *, missing: tuple[str, str, str | None, bool]) -> tuple[str, str, str | None, bool]:
    containers = view["containers"]
    if len(containers) > 1:
        return "block", "second_container", None, False
    if len(containers) == 0:
        return missing
    status = containers[0]
    if status == "restarting":
        return "hold", "observation_incomplete", None, False
    if status == "running":
        return "pass", "", None, False
    return "run", "container_not_up", "start", False


def _stopped(view: dict) -> tuple[str, str, str | None, bool]:
    containers = view["containers"]
    if len(containers) > 1:
        return "block", "second_container", None, False
    if len(containers) == 0:
        return "block", "container_missing", None, False
    status = containers[0]
    if status == "restarting":
        return "hold", "observation_incomplete", None, False
    if status in STOPPED:
        return "pass", "", None, False
    if status == "running":
        return "run", "labeled_not_success", "stop", False
    return "run", "resume", "stop", False


def _disconnect(view: dict) -> tuple[str, str, str | None, bool]:
    containers = view["containers"]
    if len(containers) > 1:
        return "block", "second_container", None, False
    if view["connected"] is None or (containers and containers[0] == "restarting"):
        return "hold", "observation_incomplete", None, False
    running = len(containers) == 1 and containers[0] == "running"
    if view["connected"] is False and running:
        return "pass", "", None, False
    if not running:
        return "block", "not_left_running", None, False
    return "run", "resume", "disconnect", False


def _runtime_step(runtime, operation_id: str) -> tuple[list[str], bool]:
    found = _runtime_containers(runtime, operation_id)
    if found:
        return found, False
    _runtime_create(runtime, operation_id)
    return _runtime_containers(runtime, operation_id), True


def _runtime_containers(runtime, operation_id: str) -> list[str]:
    ask = getattr(runtime, "containers", None)
    if not callable(ask):
        raise ValueError("runtime_refused")
    reported = _runtime_call(ask, operation_id)
    if reported is None:
        return []
    if not isinstance(reported, list):
        raise ValueError("observation_missing")
    found = []
    for item in reported:
        if not isinstance(item, str) or item.casefold() not in PRESENT:
            raise ValueError("observation_incomplete")
        found.append(item.casefold())
    return found


def _runtime_create(runtime, operation_id: str) -> None:
    create = getattr(runtime, "create_container", None)
    if not callable(create):
        raise ValueError("runtime_refused")
    _runtime_call(create, operation_id)


def _runtime_call(fn, operation_id: str):
    try:
        return fn(operation_id)
    except ValueError as exc:
        if str(exc) in {"runtime_refused", "observation_missing", "observation_incomplete"}:
            raise
        raise ValueError("runtime_refused") from None
    except Exception:
        raise ValueError("runtime_refused") from None


def _rewrite(operation: dict, index: int, state: str) -> None:
    steps = []
    for cursor, step in enumerate(operation["steps"]):
        if state == "applied" or cursor < index:
            step_state = "done"
        else:
            step_state = "pending"
        steps.append({"name": step["name"], "state": step_state})
    operation["steps"] = steps
    operation["state"] = state
