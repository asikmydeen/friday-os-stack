"""Advance a task journal without widening its grant.

A non-sensitive step can be running, done, or blocked. A sensitive step
stays waiting until an approval for that same step and that same owner
is already exchanged. A different owner, a different case of the step
name, and a flag on this call are not that record. Nothing here creates
or exchanges an approval, and a second call does not add a second copy
of a step that already finished.

A tool noticed while the task is running stays off. The Board may
accept that name. Chat cannot, and accepting one name does not accept
another. The tool is not run.

A page, a webhook, or a tool body is stored as evidence. It does not
replace the goal. The door is told one word: working, waiting, or done.
confirmed=true is ignored. This module does not start a container, does
not write Postgres, and does not open a socket.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from gate.rules import _sensitive_name, record_task, task_state
from memoryd.store import credential_shape

_TOOL = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")
_ADVANCE = frozenset({"friday", "executor"})
_MARKS = frozenset({"running", "done", "blocked"})
EVIDENCE = {
    "page": "A page was read.",
    "webhook": "An app sent an event.",
    "tool": "A tool returned evidence.",
}
_DOOR = {
    "done": "done",
    "waiting": "waiting",
    "blocked": "waiting",
    "ready": "working",
    "running": "working",
}


@dataclass(frozen=True)
class Decision:
    outcome: str
    reason: str
    task_id: str | None = None
    said: str = ""
    name: str = ""
    state: str = ""
    on: bool = False
    started: bool = False
    ran: bool = False


def mark_step(
    store,
    task_id: str,
    step_name: str,
    state: str,
    *,
    actor: str,
    exchanged: bool = False,
    confirmed: bool = False,
) -> Decision:
    del confirmed, exchanged  # a model flag is not an exchanged approval
    if state == "pending":
        return Decision("refused", "step_restart", task_id=task_id, state=state)
    if state not in _MARKS:
        return Decision("refused", "unknown_step_state", task_id=task_id)
    with store._lock:
        task = store.tasks.get(task_id)
        if task is None:
            return Decision("refused", "unknown_task")
        index = _index(task, step_name)
        if index is None:
            return Decision("refused", "unknown_step", task_id=task_id, state=task["state"])
        step = task["steps"][index]
        if step["state"] == state:
            return Decision("recorded", "already_" + state, task_id=task_id, state=task["state"])
        if step["state"] == "done":
            return Decision("recorded", "already_done", task_id=task_id, state=task["state"])
        sensitive = _sensitive_name(step["name"])
        if step["state"] == "blocked" and not (sensitive and state == "done"):
            return Decision("recorded", "already_blocked", task_id=task_id, state=task["state"])
        if sensitive:
            reason = _sensitive(store, task, actor, state, step["name"])
        else:
            reason = _open(task, actor, state, index)
        if reason is not None:
            return Decision("refused", reason, task_id=task_id, state=task["state"])
        step["state"] = state
        task["state"] = task_state(task["steps"])
        return Decision("recorded", task["state"], task_id=task_id, state=task["state"])


def notice_tool(
    store,
    task_id: str,
    tool: str,
    *,
    actor: str,
    confirmed: bool = False,
) -> Decision:
    del confirmed
    if not _tool(tool):
        return Decision("refused", "tool_name", task_id=task_id)
    if actor != "friday":
        return Decision("refused", "actor_cannot_notice", task_id=task_id, name=tool if _tool(tool) else "")
    with store._lock:
        task = store.tasks.get(task_id)
        if task is None:
            return Decision("refused", "unknown_task")
        granted = list(task.get("granted") or ())
        if task.get("state") != "running":
            return Decision(
                "refused",
                "not_running",
                task_id=task_id,
                name=tool,
                state=task.get("state", ""),
                on=tool in granted,
            )
        noticed = list(task.get("noticed") or ())
        if tool not in noticed:
            noticed.append(tool)
        task["noticed"] = noticed
        task["granted"] = granted
        return Decision(
            "recorded",
            "off" if tool not in granted else "owner_accepted",
            task_id=task_id,
            name=tool,
            state="running",
            on=tool in granted,
        )


def accept_tool(
    store,
    task_id: str,
    tool: str,
    *,
    actor: str,
    confirmed: bool = False,
) -> Decision:
    del confirmed
    if not _tool(tool):
        return Decision("refused", "tool_name", task_id=task_id)
    with store._lock:
        task = store.tasks.get(task_id)
        if task is None:
            return Decision("refused", "unknown_task")
        noticed = list(task.get("noticed") or ())
        granted = list(task.get("granted") or ())
        if actor != "board":
            return Decision(
                "refused",
                "actor_cannot_approve",
                task_id=task_id,
                name=tool,
                on=tool in granted,
            )
        if tool not in noticed:
            return Decision("refused", "not_noticed", task_id=task_id, name=tool, on=False)
        if tool not in granted:
            granted.append(tool)
        task["granted"] = granted
        task["noticed"] = noticed
        return Decision(
            "recorded",
            "owner_accepted",
            task_id=task_id,
            name=tool,
            on=True,
        )


def report(store, task_id: str) -> Decision:
    with store._lock:
        task = store.tasks.get(task_id)
        if task is None:
            return Decision("refused", "unknown_task")
        state = task.get("state") or ""
        said = _DOOR.get(state, "")
        if said == "":
            return Decision("refused", "unknown_state", task_id=task_id, state=state)
        return Decision("recorded", state if state == "blocked" else said, task_id=task_id, said=said, state=state)


def from_evidence(
    store,
    *,
    owner_id: str,
    role_id: str | None,
    kind: str,
    body: str,
    actor: str,
    confirmed: bool = False,
) -> Decision:
    del confirmed
    if actor not in _ADVANCE:
        return Decision("refused", "actor_cannot_record")
    sentence = EVIDENCE.get(kind)
    if sentence is None:
        return Decision("refused", "evidence_kind")
    if not isinstance(owner_id, str) or owner_id.strip() == "":
        return Decision("refused", "owner")
    if credential_shape(owner_id) or (isinstance(role_id, str) and credential_shape(role_id)):
        return Decision("refused", "credential")
    if not isinstance(body, str) or body.strip() == "":
        return Decision("refused", "evidence_body")
    if credential_shape(body):
        return Decision("refused", "credential")
    created = record_task(
        store,
        owner_id=owner_id,
        role_id=role_id,
        goal=sentence,
        steps=[{"name": "draft", "state": "pending"}],
    )
    if created.task_id is None:
        return Decision("refused", created.reason)
    with store._lock:
        task = store.tasks[created.task_id]
        task["goal"] = sentence
        task["evidence"] = ({"kind": kind, "body": body},)
    return Decision("recorded", "evidence", task_id=created.task_id, state=store.tasks[created.task_id]["state"])


def keep_evidence(
    store,
    task_id: str,
    *,
    kind: str,
    body: str,
    actor: str,
    confirmed: bool = False,
) -> Decision:
    del confirmed
    if actor not in _ADVANCE:
        return Decision("refused", "actor_cannot_record", task_id=task_id)
    if kind not in EVIDENCE:
        return Decision("refused", "evidence_kind", task_id=task_id)
    if not isinstance(body, str) or body.strip() == "":
        return Decision("refused", "evidence_body", task_id=task_id)
    if credential_shape(body):
        return Decision("refused", "credential", task_id=task_id)
    with store._lock:
        task = store.tasks.get(task_id)
        if task is None:
            return Decision("refused", "unknown_task")
        found = list(task.get("evidence") or ())
        row = {"kind": kind, "body": body}
        if row not in found:
            found.append(row)
        task["evidence"] = tuple(found)
        return Decision("recorded", "evidence", task_id=task_id, state=task.get("state", ""))


def _tool(value: object) -> bool:
    return isinstance(value, str) and _TOOL.fullmatch(value) is not None


def _index(task: dict, step_name: str) -> int | None:
    if not isinstance(step_name, str):
        return None
    for index, step in enumerate(task.get("steps") or ()):
        if step.get("name") == step_name:
            return index
    return None


def _sensitive(store, task: dict, actor: str, state: str, step_name: str) -> str | None:
    if state == "done":
        if actor != "board":
            return "actor_cannot_approve"
        if not _already_exchanged(store, step_name, task.get("owner_id")):
            return "approval_required"
        return None
    if state == "blocked":
        if actor not in _ADVANCE:
            return "actor_cannot_advance"
        return None
    return "stays_waiting"


def _already_exchanged(store, step_name: str, owner_id: object) -> bool:
    action = step_name.strip().casefold()
    if not isinstance(owner_id, str) or action == "":
        return False
    for approval in store.approvals.values():
        if approval.get("status") != "exchanged":
            continue
        if approval.get("owner_id") != owner_id:
            continue
        body = approval.get("body") or {}
        recorded = body.get("operation") or body.get("action_class")
        if isinstance(recorded, str) and recorded.strip().casefold() == action:
            return True
    return False


def _open(task: dict, actor: str, state: str, index: int) -> str | None:
    if actor not in _ADVANCE:
        return "actor_cannot_advance"
    if state == "running" and any(
        other.get("state") == "running"
        for other_index, other in enumerate(task["steps"])
        if other_index != index
    ):
        return "step_busy"
    return None
