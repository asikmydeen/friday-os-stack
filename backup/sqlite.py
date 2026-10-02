"""Copy one open SQLite connection with the backup API.

The caller supplies two open connections. One may be a named file that
connection already has open. The destination is a connection the
executor already opened. This module does not open a file. A path is
refused. A byte copy of a live file is refused. An empty-string
connection is a temporary disk database and is refused, including after
its journal mode is set to memory. A pure memory database stays in
memory journal mode. Writers must already be paused. Chat cannot run
it. confirmed is ignored. The source is left in place. Nothing is
deleted and no container is started.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class Decision:
    outcome: str
    reason: str
    copied: bool = False


def copy_store(
    source,
    destination,
    *,
    actor: str,
    paused: object,
    method: str,
    confirmed: bool = False,
) -> Decision:
    del confirmed
    if actor != "executor":
        return Decision("refused", "actor_cannot_backup")
    if paused is not True:
        return Decision("refused", "not_paused")
    if method == "live_file":
        return Decision("refused", "live_sqlite")
    if method != "backup_api":
        return Decision("refused", "not_the_backup_api")
    if _path(source) or _path(destination):
        return Decision("refused", "live_file")
    if source is destination:
        return Decision("refused", "same_connection")
    if not isinstance(source, sqlite3.Connection) or not isinstance(destination, sqlite3.Connection):
        return Decision("refused", "not_a_connection")
    source_kind = _kind(source)
    destination_kind = _kind(destination)
    if source_kind is None or destination_kind is None:
        return Decision("refused", "not_open")
    if source_kind == "temp" or destination_kind == "temp":
        return Decision("refused", "file_backed")
    try:
        source.backup(destination)
    except sqlite3.Error:
        return Decision("refused", "backup_failed")
    return Decision("copied", "backup_api", copied=True)


def _path(value: object) -> bool:
    return isinstance(value, (str, bytes, os.PathLike))


def _kind(connection: sqlite3.Connection) -> str | None:
    try:
        rows = connection.execute("PRAGMA database_list").fetchall()
    except sqlite3.Error:
        return None
    if not rows:
        return "temp"
    for row in rows:
        name = row[2] if len(row) > 2 else None
        if isinstance(name, str) and name != "":
            return "file"
    journal = _memory_journal(connection)
    if journal is None:
        return None
    if journal:
        return "memory"
    return "temp"


def _memory_journal(connection: sqlite3.Connection) -> bool | None:
    try:
        current = connection.execute("PRAGMA journal_mode").fetchone()
    except sqlite3.Error:
        return None
    if not current or str(current[0]).lower() != "memory":
        return False
    try:
        probed = connection.execute("PRAGMA journal_mode=PERSIST").fetchone()
    except sqlite3.Error:
        return None
    if probed and str(probed[0]).lower() == "memory":
        return True
    try:
        connection.execute("PRAGMA journal_mode=MEMORY")
    except sqlite3.Error:
        return None
    return False
