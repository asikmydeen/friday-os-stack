"""A working note can be copied. Chat cannot promote. Postgres is not a live server."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
import uuid
from pathlib import Path

from friday.ask import ask
from memoryd.index import COLLECTIONS
from memoryd.promote import promote
from memoryd.server import app
from memoryd.sqlstore import PostgresNotes
from memoryd.store import Notes

KEPT = "The password is kept outside the machine"
TOKEN = "memory-token"
QDRANT = "qdrant-token"
ROOT = Path(__file__).resolve().parents[1]


class PromoteTests(unittest.TestCase):
    def test_the_board_copies_a_working_note_and_chat_does_not(self) -> None:
        notes = Notes()
        person = notes.save(
            owner_id="chief",
            owner_kind="person",
            content="same words",
            visibility="working",
            category="note",
        )
        working = notes.save(
            owner_id="chief",
            owner_kind="role",
            content=KEPT,
            visibility="working",
            category="note",
        )
        self.assertEqual(working.reason, "created")
        before = tuple(COLLECTIONS)

        refused = promote(notes, actor="chat", note_id=working.note_id, confirmed=True)
        self.assertEqual(refused.reason, "board_only")
        self.assertEqual(promote(notes, actor="friday", note_id=working.note_id).reason, "board_only")
        self.assertEqual(len(notes.rows), 2)

        copied = promote(notes, actor="board", note_id=working.note_id, confirmed=True)
        self.assertEqual(copied.reason, "created")
        self.assertNotEqual(copied.note_id, working.note_id)
        source = notes.rows[working.note_id]
        self.assertEqual((source.visibility, source.revision, source.content), ("working", 1, KEPT))
        copy = notes.rows[copied.note_id]
        self.assertEqual(copy.visibility, "promoted")
        self.assertEqual(copy.promoted_from, working.note_id)
        self.assertEqual(copy.category, "note")
        self.assertNotEqual(copy.category, "episode")

        again = promote(notes, actor="board", note_id=working.note_id)
        self.assertEqual(again.note_id, copied.note_id)
        self.assertEqual(again.revision, 2)
        self.assertEqual(len(notes.rows), 3)
        self.assertEqual(notes.rows[working.note_id].revision, 1)
        notes.rows[copied.note_id].promoted_from = "other-row"
        moved = promote(notes, actor="board", note_id=working.note_id)
        self.assertEqual(moved.reason, "not_a_copy")
        self.assertEqual(notes.rows[copied.note_id].revision, 2)
        self.assertEqual(notes.rows[copied.note_id].promoted_from, "other-row")
        notes.rows[copied.note_id].promoted_from = working.note_id

        role = notes.recall(owner_id="chief", owner_kind="role")
        self.assertEqual(role.notes[0]["promoted_from"], working.note_id)
        self.assertEqual(role.notes[0]["revision"], 2)
        person_pack = notes.recall(owner_id="chief", owner_kind="person")
        self.assertEqual([note["visibility"] for note in person_pack.notes], ["working"])
        self.assertEqual(person_pack.notes[0]["id"], person.note_id)
        self.assertEqual(tuple(COLLECTIONS), before)
        self.assertNotIn("role_profile_chief", COLLECTIONS)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "notes.json"
            notes.dump(path)
            loaded = Notes.load(path)
        kept = loaded.rows[copied.note_id]
        self.assertEqual(kept.promoted_from, working.note_id)
        self.assertEqual(kept.content, KEPT)

    def test_a_credential_master_or_missing_row_is_not_copied(self) -> None:
        notes = Notes()
        working = notes.save(
            owner_id="chief",
            owner_kind="role",
            content=KEPT,
            visibility="working",
            category="note",
        )
        master = notes.save(
            owner_id="owner-1",
            owner_kind="person",
            content="lighthouse",
            visibility="master",
            category="note",
        )
        self.assertEqual(promote(notes, actor="board", note_id=master.note_id).reason, "not_working")
        self.assertEqual(promote(notes, actor="board", note_id="missing").reason, "unknown_note")
        self.assertEqual(promote(notes, actor="board", note_id=True).reason, "unknown_note")  # type: ignore[arg-type]
        notes.rows[working.note_id].content = "password is hunter22"
        refused = promote(notes, actor="board", note_id=working.note_id, confirmed=True)
        self.assertEqual(refused.reason, "credential")
        self.assertIsNone(refused.note_id)
        self.assertNotIn("hunter22", str(refused))
        self.assertEqual(len(notes.rows), 2)
        self.assertTrue(all(row.visibility != "promoted" for row in notes.rows.values()))

        blocked = notes.save(
            owner_id="owner-1",
            owner_kind="person",
            content="token=abcd",
            visibility="working",
        )
        self.assertEqual(blocked.reason, "credential")
        self.assertEqual(len(notes.rows), 2)

    def test_a_promoted_save_must_point_at_the_working_row(self) -> None:
        notes = Notes()
        working = notes.save(
            owner_id="chief",
            owner_kind="role",
            content=KEPT,
            visibility="working",
            category="note",
        )
        bare = notes.save(
            owner_id="chief",
            owner_kind="role",
            content=KEPT,
            visibility="promoted",
            category="note",
        )
        self.assertEqual(bare.reason, "promoted_from")
        other = notes.save(
            owner_id="owner-1",
            owner_kind="person",
            content=KEPT,
            visibility="promoted",
            category="note",
            promoted_from=working.note_id,
        )
        self.assertEqual(other.reason, "other_owner")
        rewritten = notes.save(
            owner_id="chief",
            owner_kind="role",
            content="a different sentence",
            visibility="promoted",
            category="note",
            promoted_from=working.note_id,
        )
        self.assertEqual(rewritten.reason, "not_a_copy")
        self.assertEqual(len(notes.rows), 1)

    def test_ask_does_not_promote_and_save_does_not_either(self) -> None:
        notes = Notes()

        def recall(**kwargs):
            return notes.recall(**kwargs)

        def save(**kwargs):
            return notes.save(**kwargs)

        answer = ask(
            text="ask my chief remember the role label is north",
            owner_id="owner-1",
            owner_kind="person",
            charters_dir=ROOT / "charters",
            soul_text="You are Friday.",
            recall=recall,
            save=save,
            model=lambda _messages: "unused",
            embed_reason="",
            confirmed=True,
        )
        self.assertEqual(answer.reason, "remembered")
        pack = notes.recall(owner_id="chief", owner_kind="role")
        self.assertEqual([note["visibility"] for note in pack.notes], ["working"])

        def connect():
            raise AssertionError("connected")

        client = PostgresNotes(connect)
        decision = client.save(
            owner_id="chief",
            owner_kind="role",
            content=KEPT,
            visibility="promoted",
        )
        self.assertEqual(decision.reason, "promoted_from")
        self.assertEqual(
            promote(client, actor="board", note_id="working-1", confirmed=True).reason,
            "unknown_note",
        )
        self.assertNotIn("promote", (ROOT / "friday" / "ask.py").read_text(encoding="utf-8"))

        handle = app(notes, {"MEMORY_TOKEN": TOKEN, "QDRANT_API_KEY": QDRANT})
        status, denied = handle(
            "POST",
            "/promote",
            {"Friday-Memory": TOKEN},
            {"actor": "chat", "id": pack.notes[0]["id"], "confirmed": True},
        )
        self.assertEqual((status, denied["reason"]), (403, "board_only"))
        self.assertEqual(
            [note["visibility"] for note in notes.recall(owner_id="chief", owner_kind="role").notes],
            ["working"],
        )
        status, copied = handle(
            "POST",
            "/promote",
            {"Friday-Memory": TOKEN},
            {"actor": "board", "id": pack.notes[0]["id"], "confirmed": True},
        )
        self.assertEqual(status, 200)
        self.assertEqual(copied["reason"], "created")
        self.assertNotIn("content", copied)
        self.assertNotIn(KEPT, str(copied))
        status, saved = handle(
            "POST",
            "/save",
            {"Friday-Memory": TOKEN},
            {
                "owner_id": "chief",
                "owner_kind": "role",
                "content": KEPT,
                "visibility": "promoted",
                "promoted_from": pack.notes[0]["id"],
                "confirmed": True,
            },
        )
        self.assertEqual(saved["reason"], "promoted_from")
        self.assertEqual(status, 403)
        visibilities = [note["visibility"] for note in notes.recall(owner_id="chief", owner_kind="role").notes]
        self.assertEqual(visibilities, ["promoted", "working"])
        self.assertNotIn(KEPT, str(saved))


WORKING = "11111111-1111-4111-8111-111111111111"


class _Conn:
    def __init__(self, rows: dict) -> None:
        self.rows = rows
        self.calls: list[str] = []
        self._sql = ""
        self._params = ()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=None):
        self.calls.append(" ".join(sql.split()))
        self._sql = self.calls[-1]
        self._params = params or ()
        return self

    def fetchone(self):
        sql = self._sql
        params = self._params
        if sql == "SELECT 1":
            return (1,)
        if sql.startswith("SELECT owner_id"):
            row = self.rows.get(str(params[0]).casefold())
            if row is None:
                return None
            return (
                row["owner_id"],
                row["owner_kind"],
                row["content"],
                row["visibility"],
                row["category"],
                row["deleted"],
            )
        if "visibility = 'promoted'" in sql:
            owner, kind, category, content = params
            return self._copy(owner, kind, category, content)
        if "memory_save" in sql:
            owner, kind, content, category, pointer = params
            found = self._copy(owner, kind, category, content)
            if found is not None:
                row = self.rows[found[0].casefold()]
                row["revision"] += 1
                return (row["id"], row["revision"])
            new_id = str(uuid.uuid4())
            self.rows[new_id.casefold()] = {
                "id": new_id,
                "owner_id": owner,
                "owner_kind": kind,
                "content": content,
                "visibility": "promoted",
                "category": category,
                "deleted": False,
                "revision": 1,
                "promoted_from": pointer,
            }
            return (new_id, 1)
        raise AssertionError(sql)

    def _copy(self, owner, kind, category, content):
        digest = hashlib.md5(content.encode()).hexdigest()
        for row in self.rows.values():
            if row["deleted"] or row["visibility"] != "promoted":
                continue
            if (row["owner_id"], row["owner_kind"], row["category"]) != (owner, kind, category):
                continue
            if hashlib.md5(row["content"].encode()).hexdigest() != digest:
                continue
            return (row["id"], row["revision"], row["promoted_from"])
        return None


class PostgresPromoteTests(unittest.TestCase):
    def _notes(self, rows: dict) -> tuple[PostgresNotes, _Conn]:
        conn = _Conn(rows)
        return PostgresNotes(lambda: conn), conn

    def _working(self, content: str = KEPT, **extra) -> dict:
        row = {
            "id": WORKING,
            "owner_id": "chief",
            "owner_kind": "role",
            "content": content,
            "visibility": "working",
            "category": "note",
            "deleted": False,
            "revision": 1,
            "promoted_from": None,
        }
        row.update(extra)
        return {WORKING: row}

    def test_the_board_writes_memory_save_with_the_working_id(self) -> None:
        notes, conn = self._notes(self._working())
        before = tuple(COLLECTIONS)
        copied = promote(notes, actor="board", note_id=WORKING, confirmed=True)
        self.assertEqual(copied.reason, "created")
        self.assertEqual(copied.revision, 1)
        self.assertNotEqual(copied.note_id, WORKING)
        saved = [sql for sql in conn.calls if "memory_save" in sql]
        self.assertEqual(len(saved), 1)
        self.assertIn("'promoted'", saved[0])
        self.assertIn("%s::uuid", saved[0])
        self.assertEqual(notes.rows if hasattr(notes, "rows") else None, None)
        stored = next(row for row in conn.rows.values() if row["visibility"] == "promoted")
        self.assertEqual(stored["promoted_from"], WORKING)
        self.assertEqual(conn.rows[WORKING]["revision"], 1)
        again = promote(notes, actor="board", note_id=WORKING)
        self.assertEqual(again.note_id, copied.note_id)
        self.assertEqual(again.revision, 2)
        self.assertEqual(len([row for row in conn.rows.values() if row["visibility"] == "promoted"]), 1)
        conn.rows[stored["id"].casefold()]["promoted_from"] = "33333333-3333-4333-8333-333333333333"
        held = promote(notes, actor="board", note_id=WORKING)
        self.assertEqual(held.reason, "not_a_copy")
        self.assertEqual(conn.rows[stored["id"].casefold()]["revision"], 2)
        self.assertEqual(len([sql for sql in conn.calls if "memory_save" in sql]), 2)
        self.assertEqual(tuple(COLLECTIONS), before)
        self.assertNotIn("role_profile_chief", COLLECTIONS)

    def test_chat_a_missing_pointer_and_a_secret_do_not_write(self) -> None:
        def connect():
            raise AssertionError("connected")

        closed = PostgresNotes(connect)
        self.assertEqual(
            closed.save(
                owner_id="chief",
                owner_kind="role",
                content=KEPT,
                visibility="promoted",
            ).reason,
            "promoted_from",
        )
        self.assertEqual(promote(closed, actor="chat", note_id=WORKING, confirmed=True).reason, "board_only")

        secret = "password is hunter22"
        notes, conn = self._notes(self._working(secret))
        refused = promote(notes, actor="board", note_id=WORKING, confirmed=True)
        self.assertEqual(refused.reason, "credential")
        self.assertNotIn("hunter22", str(refused))
        self.assertFalse(any("memory_save" in sql for sql in conn.calls))
        self.assertTrue(all(row["visibility"] != "promoted" for row in conn.rows.values()))

        notes, conn = self._notes(self._working())
        other = notes.save(
            owner_id="owner-1",
            owner_kind="person",
            content=KEPT,
            visibility="promoted",
            category="note",
            promoted_from=WORKING,
        )
        self.assertEqual(other.reason, "other_owner")
        self.assertFalse(any("memory_save" in sql for sql in conn.calls))
        rewritten = notes.save(
            owner_id="chief",
            owner_kind="role",
            content="a different sentence",
            visibility="promoted",
            category="note",
            promoted_from=WORKING,
        )
        self.assertEqual(rewritten.reason, "not_a_copy")
        self.assertFalse(any("memory_save" in sql for sql in conn.calls))

    def test_the_route_copies_for_the_board_and_save_stays_closed(self) -> None:
        notes, conn = self._notes(self._working())
        handle = app(notes, {"MEMORY_TOKEN": TOKEN, "QDRANT_API_KEY": QDRANT})
        status, copied = handle(
            "POST",
            "/promote",
            {"Friday-Memory": TOKEN},
            {"actor": "board", "id": WORKING, "confirmed": True},
        )
        self.assertEqual(status, 200)
        self.assertEqual(copied["reason"], "created")
        self.assertNotIn(KEPT, str(copied))
        self.assertTrue(any("memory_save" in sql for sql in conn.calls))
        status, saved = handle(
            "POST",
            "/save",
            {"Friday-Memory": TOKEN},
            {
                "owner_id": "chief",
                "owner_kind": "role",
                "content": KEPT,
                "visibility": "promoted",
                "promoted_from": WORKING,
                "confirmed": True,
            },
        )
        self.assertEqual((status, saved["reason"]), (403, "promoted_from"))
        self.assertEqual(len([sql for sql in conn.calls if "memory_save" in sql]), 1)


if __name__ == "__main__":
    unittest.main()
