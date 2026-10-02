"""Record Friday's state book. This module does not open SQLite.

The book holds a conversation, one thread per obligation, reminders,
deliveries, and a coder-job mirror. The rows stay in this process. A
restart drops them. friday/durable.py writes the same rows to a file
the caller names. Nothing here writes a file, writes a memory note,
creates an approval, asks a provider, or starts taskrunner.

Chat cannot delete a turn, close an obligation, fire a reminder, or
send a delivery. A delivery stays pending or uncertain. A mirrored job
is named tr-<task> and is not created. A second mirror keeps the first
role. An owner id with surrounding space or a newline is refused.
Friday's ask path does not call this module.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass

from memoryd.store import credential_shape

_ROLE = re.compile(r"[a-z][a-z0-9_-]{0,31}\Z")
_TASK = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
_SPEAKERS = frozenset({"owner", "friday"})
_DELIVERY = frozenset({"pending", "uncertain"})


@dataclass(frozen=True)
class Decision:
    outcome: str
    reason: str
    name: str = ""
    state: str = ""
    count: int = 0
    started: bool = False
    sent: bool = False
    created: bool = False


class Book:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._turns: list[dict] = []
        self._obligations: list[dict] = []
        self._reminders: list[dict] = []
        self._deliveries: list[dict] = []
        self._jobs: list[dict] = []

    def __repr__(self) -> str:
        return "Book()"


def record_turn(
    book: Book,
    *,
    actor: str,
    owner_id: object,
    speaker: object,
    role: object,
    text: object,
    confirmed: bool = False,
) -> Decision:
    del confirmed
    if actor != "friday":
        return Decision("refused", "actor_cannot_record")
    reason = _owner(owner_id)
    if reason:
        return Decision("refused", reason)
    if speaker not in _SPEAKERS:
        return Decision("refused", "speaker")
    reason = _named_role(role, allow_friday=True)
    if reason:
        return Decision("refused", reason)
    body, reason = _text(text)
    if reason:
        return Decision("refused", reason)
    row = {"owner_id": owner_id, "speaker": speaker, "role": role, "text": body}
    with book._lock:
        book._turns.append(row)
        count = _count(book._turns, owner_id)
    return Decision("recorded", "turn", count=count)


def turns(book: Book, owner_id: object) -> tuple[dict, ...]:
    if _owner(owner_id):
        return ()
    with book._lock:
        return tuple(dict(row) for row in book._turns if row["owner_id"] == owner_id)


def delete_turn(
    book: Book,
    *,
    actor: str,
    owner_id: object,
    confirmed: bool = False,
) -> Decision:
    del actor, owner_id, confirmed
    return Decision("refused", "stays")


def record_obligation(
    book: Book,
    *,
    actor: str,
    owner_id: object,
    name: object,
    text: object,
    confirmed: bool = False,
) -> Decision:
    del confirmed
    if actor != "board":
        return Decision("refused", "board_only", name=_public_name(name))
    reason = _owner(owner_id)
    if reason:
        return Decision("refused", reason)
    slug = _public_name(name)
    if slug == "":
        return Decision("refused", "credential" if _secret(name) else "name")
    with book._lock:
        found = _find(book._obligations, owner_id, "name", slug)
        if found is not None:
            return Decision("recorded", "already", name=slug, state=found["state"], count=1)
    body, reason = _text(text)
    if reason:
        return Decision("refused", reason, name=slug)
    with book._lock:
        found = _find(book._obligations, owner_id, "name", slug)
        if found is not None:
            return Decision("recorded", "already", name=slug, state=found["state"], count=1)
        book._obligations.append(
            {"owner_id": owner_id, "name": slug, "text": body, "state": "open"}
        )
    return Decision("recorded", "obligation", name=slug, state="open", count=1)


def close_obligation(
    book: Book,
    *,
    actor: str,
    owner_id: object,
    name: object,
    confirmed: bool = False,
) -> Decision:
    del confirmed
    slug = _public_name(name)
    if actor != "board":
        return Decision("refused", "board_only", name=slug, state=_state(book, owner_id, slug))
    reason = _owner(owner_id)
    if reason:
        return Decision("refused", reason)
    if slug == "":
        return Decision("refused", "credential" if _secret(name) else "name")
    with book._lock:
        found = _find(book._obligations, owner_id, "name", slug)
        if found is None:
            return Decision("refused", "unknown_obligation", name=slug)
        if found["state"] == "done":
            return Decision("recorded", "already_done", name=slug, state="done", count=1)
        found["state"] = "done"
    return Decision("recorded", "done", name=slug, state="done", count=1)


def obligations(book: Book, owner_id: object) -> tuple[dict, ...]:
    if _owner(owner_id):
        return ()
    with book._lock:
        return tuple(dict(row) for row in book._obligations if row["owner_id"] == owner_id)


def record_reminder(
    book: Book,
    *,
    actor: str,
    owner_id: object,
    text: object,
    when: object,
    confirmed: bool = False,
) -> Decision:
    del confirmed
    if actor != "board":
        return Decision("refused", "board_only", sent=False)
    reason = _owner(owner_id)
    if reason:
        return Decision("refused", reason, sent=False)
    body, reason = _text(text)
    if reason:
        return Decision("refused", reason, sent=False)
    moment, reason = _text(when)
    if reason:
        return Decision("refused", "when" if reason == "empty" else reason, sent=False)
    with book._lock:
        book._reminders.append(
            {"owner_id": owner_id, "text": body, "when": moment, "fired": False}
        )
        count = _count(book._reminders, owner_id)
    return Decision("recorded", "not_sent", count=count, sent=False)


def fire_reminder(
    book: Book,
    *,
    actor: str,
    owner_id: object,
    confirmed: bool = False,
) -> Decision:
    del actor, owner_id, confirmed
    return Decision("refused", "not_sent", sent=False)


def reminders(book: Book, owner_id: object) -> tuple[dict, ...]:
    if _owner(owner_id):
        return ()
    with book._lock:
        return tuple(dict(row) for row in book._reminders if row["owner_id"] == owner_id)


def record_delivery(
    book: Book,
    *,
    actor: str,
    owner_id: object,
    item_id: object,
    key: object,
    status: str = "pending",
    confirmed: bool = False,
) -> Decision:
    del confirmed
    if actor != "friday":
        return Decision("refused", "actor_cannot_record", sent=False)
    reason = _owner(owner_id)
    if reason:
        return Decision("refused", reason, sent=False)
    if not isinstance(item_id, str) or _TASK.fullmatch(item_id) is None or _secret(item_id):
        return Decision("refused", "credential" if _secret(item_id) else "item", sent=False)
    with book._lock:
        found = _find(book._deliveries, owner_id, "item_id", item_id)
        if found is not None:
            return Decision(
                "recorded",
                "already",
                name=item_id,
                state=found["status"],
                count=1,
                sent=False,
            )
    if status not in _DELIVERY:
        return Decision("refused", "unknown_status", name=item_id, sent=False)
    token, reason = _text(key)
    if reason:
        return Decision("refused", "key" if reason == "empty" else reason, name=item_id, sent=False)
    with book._lock:
        found = _find(book._deliveries, owner_id, "item_id", item_id)
        if found is not None:
            return Decision(
                "recorded",
                "already",
                name=item_id,
                state=found["status"],
                count=1,
                sent=False,
            )
        book._deliveries.append(
            {"owner_id": owner_id, "item_id": item_id, "key": token, "status": status}
        )
    return Decision("recorded", "not_sent", name=item_id, state=status, count=1, sent=False)


def send_delivery(
    book: Book,
    *,
    actor: str,
    owner_id: object,
    item_id: object,
    confirmed: bool = False,
) -> Decision:
    del actor, confirmed
    if _owner(owner_id) or not isinstance(item_id, str):
        return Decision("refused", "not_sent", sent=False)
    with book._lock:
        found = _find(book._deliveries, owner_id, "item_id", item_id)
        state = "" if found is None else found["status"]
    return Decision("refused", "not_sent", name=item_id if found is not None else "", state=state, sent=False)


def deliveries(book: Book, owner_id: object) -> tuple[dict, ...]:
    if _owner(owner_id):
        return ()
    with book._lock:
        return tuple(dict(row) for row in book._deliveries if row["owner_id"] == owner_id)


def mirror_job(
    book: Book,
    *,
    actor: str,
    owner_id: object,
    role: object,
    task_id: object,
    code_on: object = False,
    token: object = None,
    confirmed: bool = False,
) -> Decision:
    del confirmed
    existing = _job_name(book, owner_id, task_id) if actor != "friday" else ""
    if actor != "friday":
        return Decision("refused", "actor_cannot_record", name=existing, started=False, created=False)
    reason = _owner(owner_id)
    if reason:
        return Decision("refused", reason, started=False, created=False)
    reason = _named_role(role, allow_friday=False)
    if reason:
        return Decision("refused", reason, started=False, created=False)
    if not isinstance(task_id, str) or _TASK.fullmatch(task_id) is None or _secret(task_id):
        return Decision(
            "refused",
            "credential" if _secret(task_id) else "task",
            started=False,
            created=False,
        )
    workspace = f"tr-{task_id}"
    with book._lock:
        found = _find(book._jobs, owner_id, "task_id", task_id)
        if found is not None:
            return Decision(
                "recorded",
                "already",
                name=found["workspace"],
                state="not_started",
                count=1,
                started=False,
                created=False,
            )
    if token is not None and token != "":
        if not isinstance(token, str) or _secret(token):
            return Decision(
                "refused",
                "credential" if isinstance(token, str) and _secret(token) else "token",
                started=False,
                created=False,
            )
    if code_on is not True:
        return Decision("refused", "code_profile_off", name=workspace, started=False, created=False)
    with book._lock:
        found = _find(book._jobs, owner_id, "task_id", task_id)
        if found is not None:
            return Decision(
                "recorded",
                "already",
                name=found["workspace"],
                state="not_started",
                count=1,
                started=False,
                created=False,
            )
        book._jobs.append(
            {
                "owner_id": owner_id,
                "role": role,
                "task_id": task_id,
                "workspace": workspace,
                "state": "not_started",
            }
        )
    return Decision(
        "recorded",
        "not_started",
        name=workspace,
        state="not_started",
        count=1,
        started=False,
        created=False,
    )


def jobs(book: Book, owner_id: object) -> tuple[dict, ...]:
    if _owner(owner_id):
        return ()
    with book._lock:
        return tuple(dict(row) for row in book._jobs if row["owner_id"] == owner_id)


def _owner(value: object) -> str | None:
    if not isinstance(value, str) or value.strip() == "":
        return "owner"
    if credential_shape(value):
        return "credential"
    if value != value.strip() or "\n" in value or "\r" in value:
        return "owner"
    return None


def _named_role(value: object, *, allow_friday: bool) -> str | None:
    if _secret(value):
        return "credential"
    if value == "friday":
        return None if allow_friday else "role"
    if isinstance(value, str) and _ROLE.fullmatch(value) is not None:
        return None
    return "role"


def _secret(value: object) -> bool:
    return isinstance(value, str) and credential_shape(value)


def _public_name(value: object) -> str:
    if not isinstance(value, str) or _ROLE.fullmatch(value) is None or _secret(value):
        return ""
    return value


def _text(value: object) -> tuple[str, str | None]:
    if not isinstance(value, str) or value.strip() == "":
        return "", "empty"
    if credential_shape(value):
        return "", "credential"
    return value.strip(), None


def _count(rows: list[dict], owner_id: object) -> int:
    return sum(1 for row in rows if row["owner_id"] == owner_id)


def _find(rows: list[dict], owner_id: object, field: str, value: str) -> dict | None:
    for row in rows:
        if row["owner_id"] == owner_id and row[field] == value:
            return row
    return None


def _state(book: Book, owner_id: object, name: str) -> str:
    if name == "" or _owner(owner_id):
        return ""
    with book._lock:
        found = _find(book._obligations, owner_id, "name", name)
    return "" if found is None else found["state"]


def _job_name(book: Book, owner_id: object, task_id: object) -> str:
    if _owner(owner_id) or not isinstance(task_id, str):
        return ""
    with book._lock:
        found = _find(book._jobs, owner_id, "task_id", task_id)
    return "" if found is None else found["workspace"]
