"""SQLite backup API. One open file is copied. A byte copy stays refused."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from backup.sqlite import copy_store

KEPT = "The password is kept outside the machine"
TOKEN = "token=abcd"
ROOT = Path(__file__).resolve().parents[1]


def _memory() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE notes (text TEXT)")
    return connection


def _copy(source, destination, **overrides):
    fields = dict(actor="executor", paused=True, method="backup_api", confirmed=False)
    fields.update(overrides)
    return copy_store(source, destination, **fields)


class SqliteBackupTests(unittest.TestCase):
    def test_the_backup_api_copies_memory_and_leaves_the_source(self) -> None:
        source = _memory()
        destination = _memory()
        source.execute("INSERT INTO notes (text) VALUES (?)", (KEPT,))
        source.commit()
        decision = _copy(source, destination, confirmed=True)
        self.assertEqual((decision.outcome, decision.reason, decision.copied), ("copied", "backup_api", True))
        self.assertNotIn("confirmed", decision.__dict__)
        self.assertEqual(destination.execute("SELECT text FROM notes").fetchall(), [(KEPT,)])
        self.assertEqual(source.execute("SELECT text FROM notes").fetchall(), [(KEPT,)])
        source.execute("INSERT INTO notes (text) VALUES ('lighthouse')")
        source.commit()
        again = _copy(source, destination)
        self.assertEqual(again.reason, "backup_api")
        self.assertEqual(
            sorted(row[0] for row in destination.execute("SELECT text FROM notes")),
            [KEPT, "lighthouse"],
        )
        self.assertEqual(
            sorted(row[0] for row in source.execute("SELECT text FROM notes")),
            [KEPT, "lighthouse"],
        )

    def test_a_stale_destination_row_is_replaced(self) -> None:
        source = _memory()
        destination = _memory()
        source.execute("INSERT INTO notes (text) VALUES ('lighthouse')")
        source.commit()
        destination.execute("INSERT INTO notes (text) VALUES ('stale')")
        destination.commit()
        decision = _copy(source, destination)
        self.assertEqual(decision.reason, "backup_api")
        self.assertEqual(destination.execute("SELECT text FROM notes").fetchall(), [("lighthouse",)])

    def test_chat_and_any_other_actor_cannot_copy(self) -> None:
        source = _memory()
        destination = _memory()
        source.execute("INSERT INTO notes (text) VALUES ('lighthouse')")
        source.commit()
        for actor in ("chat", "friday", "board", "executor ", "Executor"):
            decision = _copy(source, destination, actor=actor, confirmed=True)
            self.assertEqual(decision.reason, "actor_cannot_backup", actor)
            self.assertIs(decision.copied, False)
        self.assertEqual(destination.execute("SELECT text FROM notes").fetchall(), [])
        self.assertEqual(source.execute("SELECT text FROM notes").fetchall(), [("lighthouse",)])

    def test_pause_must_be_exactly_true(self) -> None:
        source = _memory()
        destination = _memory()
        source.execute("INSERT INTO notes (text) VALUES ('lighthouse')")
        source.commit()
        for paused in (False, "true", "True", 1, None):
            decision = _copy(source, destination, paused=paused)
            self.assertEqual(decision.reason, "not_paused")
            self.assertIs(decision.copied, False)
        self.assertEqual(destination.execute("SELECT text FROM notes").fetchall(), [])

    def test_a_path_is_not_opened(self) -> None:
        destination = _memory()
        decision = _copy(TOKEN, destination)
        self.assertEqual(decision.reason, "live_file")
        self.assertNotIn("abcd", repr(decision))
        self.assertNotIn(TOKEN, repr(decision))
        named = _copy(Path("/tmp/not-a-friday-disk.sqlite"), destination)
        self.assertEqual(named.reason, "live_file")
        self.assertNotIn("not-a-friday-disk", repr(named))
        self.assertEqual(destination.execute("SELECT text FROM notes").fetchall(), [])
        kept = _copy(KEPT, destination)
        self.assertEqual(kept.reason, "live_file")
        self.assertNotIn(KEPT, repr(kept))

    def test_one_open_file_is_copied_into_the_destination_the_executor_opened(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.sqlite"
            filed = sqlite3.connect(path)
            filed.execute("PRAGMA journal_mode=WAL")
            filed.execute("CREATE TABLE notes (text TEXT)")
            filed.execute("INSERT INTO notes (text) VALUES ('stay')")
            filed.commit()
            destination = _memory()
            decision = _copy(filed, destination)
            self.assertEqual((decision.outcome, decision.reason, decision.copied), ("copied", "backup_api", True))
            self.assertNotIn(str(path), repr(decision))
            self.assertNotIn("stay", repr(decision))
            self.assertEqual(destination.execute("SELECT text FROM notes").fetchall(), [("stay",)])
            self.assertEqual(filed.execute("SELECT text FROM notes").fetchall(), [("stay",)])
            for actor in ("chat", "friday", "board"):
                blocked = _memory()
                refused = _copy(filed, blocked, actor=actor, confirmed=True)
                self.assertEqual(refused.reason, "actor_cannot_backup", actor)
                self.assertIs(refused.copied, False)
                self.assertEqual(blocked.execute("SELECT text FROM notes").fetchall(), [])
            missed = _memory()
            live = _copy(filed, missed, method="live_file")
            self.assertEqual(live.reason, "live_sqlite")
            self.assertIs(live.copied, False)
            self.assertEqual(missed.execute("SELECT text FROM notes").fetchall(), [])
            self.assertEqual(filed.execute("SELECT text FROM notes").fetchall(), [("stay",)])
            opened = sqlite3.connect(Path(directory) / "dest.sqlite")
            into = _copy(filed, opened)
            self.assertEqual(into.reason, "backup_api")
            self.assertEqual(opened.execute("SELECT text FROM notes").fetchall(), [("stay",)])
            filed.execute("INSERT INTO notes (text) VALUES ('lighthouse')")
            filed.commit()
            again = _copy(filed, opened)
            self.assertEqual(again.reason, "backup_api")
            self.assertEqual(
                sorted(row[0] for row in opened.execute("SELECT text FROM notes")),
                ["lighthouse", "stay"],
            )
            self.assertEqual(
                sorted(row[0] for row in filed.execute("SELECT text FROM notes")),
                ["lighthouse", "stay"],
            )
            opened.close()
            source = _memory()
            source.execute("INSERT INTO notes (text) VALUES ('lighthouse')")
            source.commit()
            outward = sqlite3.connect(Path(directory) / "out.sqlite")
            copied = _copy(source, outward)
            self.assertEqual(copied.reason, "backup_api")
            self.assertEqual(outward.execute("SELECT text FROM notes").fetchall(), [("lighthouse",)])
            self.assertEqual(source.execute("SELECT text FROM notes").fetchall(), [("lighthouse",)])
            outward.close()
            filed.close()

    def test_an_unnamed_temporary_database_is_not_copied(self) -> None:
        source = _memory()
        temporary = sqlite3.connect("")
        temporary.execute("CREATE TABLE notes (text TEXT)")
        temporary.execute("INSERT INTO notes (text) VALUES ('disk')")
        temporary.commit()
        destination = _memory()
        blank_name = _copy(temporary, destination)
        self.assertEqual(blank_name.reason, "file_backed")
        self.assertIs(blank_name.copied, False)
        self.assertEqual(destination.execute("SELECT text FROM notes").fetchall(), [])
        temporary.execute("PRAGMA journal_mode=MEMORY")
        hidden = _copy(temporary, destination)
        self.assertEqual(hidden.reason, "file_backed")
        self.assertEqual(temporary.execute("PRAGMA journal_mode").fetchone()[0].lower(), "memory")
        self.assertEqual(destination.execute("SELECT text FROM notes").fetchall(), [])
        temporary.close()
        self.assertEqual(source.execute("PRAGMA journal_mode").fetchone()[0].lower(), "memory")

    def test_other_methods_and_a_closed_connection_do_not_copy(self) -> None:
        source = _memory()
        destination = _memory()
        source.execute("INSERT INTO notes (text) VALUES ('lighthouse')")
        source.commit()
        live = _copy(source, destination, method="live_file")
        self.assertEqual(live.reason, "live_sqlite")
        shutdown = _copy(source, destination, method="clean_shutdown")
        self.assertEqual(shutdown.reason, "not_the_backup_api")
        blank = _copy(source, destination, method="backup_api ")
        self.assertEqual(blank.reason, "not_the_backup_api")
        self.assertEqual(destination.execute("SELECT text FROM notes").fetchall(), [])
        same = _copy(source, source)
        self.assertEqual(same.reason, "same_connection")
        self.assertEqual(source.execute("SELECT text FROM notes").fetchall(), [("lighthouse",)])
        closed = _memory()
        closed.close()
        decision = _copy(closed, destination)
        self.assertEqual(decision.reason, "not_open")
        self.assertIs(decision.copied, False)
        self.assertEqual(destination.execute("SELECT text FROM notes").fetchall(), [])

    def test_the_module_does_not_open_a_file_and_ask_does_not_call_it(self) -> None:
        source = (ROOT / "backup" / "sqlite.py").read_text(encoding="utf-8")
        self.assertNotIn("connect(", source)
        self.assertNotIn("subprocess", source)
        self.assertNotIn("shutil", source)
        self.assertNotIn("copyfile", source)
        self.assertNotIn("read_bytes", source)
        self.assertNotIn("open(", source)
        self.assertNotIn("coordinated", source)
        ask = (ROOT / "friday" / "ask.py").read_text(encoding="utf-8")
        self.assertNotIn("copy_store", ask)
        self.assertNotIn("backup.sqlite", ask)
