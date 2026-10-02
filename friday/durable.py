"""Write Friday's state book to a SQLite file the caller names.

The rules stay in friday.state. This module opens that file, loads the
rows, and writes them back after a recorded change. A later open of the
same file sees those rows. Without a path, nothing is opened. A
credential-shaped row is not written and is not loaded. Chat still
cannot delete a turn. A delivery is not sent and a job is not started.
The ask module does not import this file.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from friday.state import (
    Book,
    Decision,
    _TASK,
    _named_role,
    _owner,
    _public_name,
    _secret,
    _text,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS turns (
    seq INTEGER PRIMARY KEY,
    owner_id TEXT NOT NULL,
    speaker TEXT NOT NULL,
    role TEXT NOT NULL,
    body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS obligations (
    seq INTEGER PRIMARY KEY,
    owner_id TEXT NOT NULL,
    name TEXT NOT NULL,
    body TEXT NOT NULL,
    state TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reminders (
    seq INTEGER PRIMARY KEY,
    owner_id TEXT NOT NULL,
    body TEXT NOT NULL,
    when_text TEXT NOT NULL,
    fired INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS deliveries (
    seq INTEGER PRIMARY KEY,
    owner_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    key_text TEXT NOT NULL,
    status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    seq INTEGER PRIMARY KEY,
    owner_id TEXT NOT NULL,
    role TEXT NOT NULL,
    task_id TEXT NOT NULL,
    workspace TEXT NOT NULL,
    state TEXT NOT NULL
);
"""


def open_book(path: object) -> Book:
    """Open the file and load the book. A bad path raises OSError('state_path')."""
    target = _file(path)
    if target is None:
        raise OSError("state_path")
    try:
        conn = sqlite3.connect(target, check_same_thread=False, isolation_level=None)
    except sqlite3.Error:
        raise OSError("state_path") from None
    try:
        conn.executescript(_SCHEMA)
        book = Book()
        book._state_conn = conn
        book._state_guard = threading.Lock()
        _load(book)
    except sqlite3.Error:
        conn.close()
        raise OSError("state_path") from None
    return book


def state_from_env(env: dict[str, str]) -> Book | None:
    """None when FRIDAY_STATE is unset. A set path is opened or refused."""
    raw = env.get("FRIDAY_STATE") or ""
    if raw == "":
        return None
    return open_book(raw)


def persist(book: Book, fn, **kwargs) -> Decision:
    """Apply one state rule, then write the file if a row was recorded."""
    guard = getattr(book, "_state_guard", None)
    if guard is None:
        return fn(book, **kwargs)
    with guard:
        decision = fn(book, **kwargs)
        if decision.outcome != "recorded":
            return decision
        try:
            _save(book)
        except sqlite3.Error:
            _load(book)
            return Decision("refused", "state_write", sent=False, started=False, created=False)
        return decision


def _file(value: object) -> Path | None:
    if not isinstance(value, (str, Path)):
        return None
    raw = str(value)
    if raw == "" or raw != raw.strip() or "\n" in raw or "\r" in raw or "\x00" in raw:
        return None
    path = Path(raw)
    if not path.is_absolute() or path.is_symlink():
        return None
    parent = path.parent
    if not parent.is_dir() or parent.is_symlink():
        return None
    if path.exists() and not path.is_file():
        return None
    return path


def _kept(rows) -> list:
    return [row for row in rows if row is not None]


def _load(book: Book) -> None:
    conn = book._state_conn
    turns = _kept(
        _turn(owner_id, speaker, role, body)
        for owner_id, speaker, role, body in conn.execute(
            "SELECT owner_id, speaker, role, body FROM turns ORDER BY seq"
        )
    )
    obligations = _kept(
        _obligation(owner_id, name, body, state)
        for owner_id, name, body, state in conn.execute(
            "SELECT owner_id, name, body, state FROM obligations ORDER BY seq"
        )
    )
    reminders = _kept(
        _reminder(owner_id, body, when_text, fired)
        for owner_id, body, when_text, fired in conn.execute(
            "SELECT owner_id, body, when_text, fired FROM reminders ORDER BY seq"
        )
    )
    deliveries = _kept(
        _delivery(owner_id, item_id, key_text, status)
        for owner_id, item_id, key_text, status in conn.execute(
            "SELECT owner_id, item_id, key_text, status FROM deliveries ORDER BY seq"
        )
    )
    jobs = _kept(
        _job(owner_id, role, task_id, workspace, state)
        for owner_id, role, task_id, workspace, state in conn.execute(
            "SELECT owner_id, role, task_id, workspace, state FROM jobs ORDER BY seq"
        )
    )
    with book._lock:
        book._turns[:] = turns
        book._obligations[:] = obligations
        book._reminders[:] = reminders
        book._deliveries[:] = deliveries
        book._jobs[:] = jobs


def _save(book: Book) -> None:
    conn = book._state_conn
    with book._lock:
        turns = list(book._turns)
        obligations = list(book._obligations)
        reminders = list(book._reminders)
        deliveries = list(book._deliveries)
        jobs = list(book._jobs)
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("DELETE FROM turns")
        conn.executemany(
            "INSERT INTO turns (owner_id, speaker, role, body) VALUES (?, ?, ?, ?)",
            [(row["owner_id"], row["speaker"], row["role"], row["text"]) for row in turns],
        )
        conn.execute("DELETE FROM obligations")
        conn.executemany(
            "INSERT INTO obligations (owner_id, name, body, state) VALUES (?, ?, ?, ?)",
            [(row["owner_id"], row["name"], row["text"], row["state"]) for row in obligations],
        )
        conn.execute("DELETE FROM reminders")
        conn.executemany(
            "INSERT INTO reminders (owner_id, body, when_text, fired) VALUES (?, ?, ?, ?)",
            [
                (row["owner_id"], row["text"], row["when"], 1 if row["fired"] else 0)
                for row in reminders
            ],
        )
        conn.execute("DELETE FROM deliveries")
        conn.executemany(
            "INSERT INTO deliveries (owner_id, item_id, key_text, status) VALUES (?, ?, ?, ?)",
            [
                (row["owner_id"], row["item_id"], row["key"], row["status"])
                for row in deliveries
            ],
        )
        conn.execute("DELETE FROM jobs")
        conn.executemany(
            "INSERT INTO jobs (owner_id, role, task_id, workspace, state) VALUES (?, ?, ?, ?, ?)",
            [
                (row["owner_id"], row["role"], row["task_id"], row["workspace"], row["state"])
                for row in jobs
            ],
        )
        conn.execute("COMMIT")
    except sqlite3.Error:
        conn.execute("ROLLBACK")
        raise


def _turn(owner_id, speaker, role, body) -> dict | None:
    if _owner(owner_id) or speaker not in {"owner", "friday"}:
        return None
    if _named_role(role, allow_friday=True):
        return None
    text, reason = _text(body)
    if reason:
        return None
    return {"owner_id": owner_id, "speaker": speaker, "role": role, "text": text}


def _obligation(owner_id, name, body, state) -> dict | None:
    if _owner(owner_id) or state not in {"open", "done"}:
        return None
    slug = _public_name(name)
    text, reason = _text(body)
    if slug == "" or reason:
        return None
    return {"owner_id": owner_id, "name": slug, "text": text, "state": state}


def _reminder(owner_id, body, when_text, fired) -> dict | None:
    if _owner(owner_id) or fired not in {0, 1}:
        return None
    text, reason = _text(body)
    moment, when_reason = _text(when_text)
    if reason or when_reason:
        return None
    return {"owner_id": owner_id, "text": text, "when": moment, "fired": fired == 1}


def _delivery(owner_id, item_id, key_text, status) -> dict | None:
    if _owner(owner_id) or status not in {"pending", "uncertain"}:
        return None
    if not isinstance(item_id, str) or _TASK.fullmatch(item_id) is None or _secret(item_id):
        return None
    token, reason = _text(key_text)
    if reason:
        return None
    return {"owner_id": owner_id, "item_id": item_id, "key": token, "status": status}


def _job(owner_id, role, task_id, workspace, state) -> dict | None:
    if _owner(owner_id) or state != "not_started":
        return None
    if _named_role(role, allow_friday=False):
        return None
    if not isinstance(task_id, str) or _TASK.fullmatch(task_id) is None or _secret(task_id):
        return None
    if workspace != f"tr-{task_id}":
        return None
    return {
        "owner_id": owner_id,
        "role": role,
        "task_id": task_id,
        "workspace": workspace,
        "state": state,
    }
