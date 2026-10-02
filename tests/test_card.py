"""A research card and a kept decision.

The raw page is not stored. The file-store tests do not open Postgres.
PostgresCardTests uses a fake connection, not a live server.
"""

from __future__ import annotations

import hashlib
import unittest
import uuid
from pathlib import Path
from urllib.parse import quote, quote_plus

from friday.ask import ask
from memoryd.card import record_card
from memoryd.index import COLLECTIONS
from memoryd.server import app
from memoryd.sqlstore import PostgresNotes
from memoryd.store import Notes, credential_shape

KEPT = "The password is kept outside the machine"
PAGE = "RAWPAGE-MARKER-991 the fetched page body is not the note"
TOKEN = "memory-token"
QDRANT = "qdrant-token"
ROOT = Path(__file__).resolve().parents[1]


def _rows(notes: Notes, category: str, owner_id: str = "owner-1", owner_kind: str = "person") -> tuple[dict, ...]:
    packed = notes.recall(owner_id=owner_id, owner_kind=owner_kind, category=category)
    return packed.notes


class CardTests(unittest.TestCase):
    def test_a_card_and_a_decision_are_stored_and_the_page_is_not(self) -> None:
        notes = Notes()
        summary = f"One film is already in the library. {PAGE}"
        card = record_card(
            notes,
            caller_id="owner-1",
            caller_kind="person",
            kind="finding",
            text=summary,
            page=PAGE,
            confirmed=True,
        )
        self.assertEqual(card.reason, "created")
        uuid.UUID(card.note_id)
        self.assertFalse(credential_shape(card.note_id))
        stored = _rows(notes, "finding")
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0]["content"], "One film is already in the library.")
        self.assertNotIn("RAWPAGE-MARKER-991", stored[0]["content"])
        self.assertEqual(stored[0]["category"], "finding")
        self.assertEqual(stored[0]["visibility"], "master")
        self.assertNotIn(PAGE, repr(card))

        decision = record_card(
            notes,
            caller_id="owner-1",
            caller_kind="person",
            kind="knowledge",
            text=KEPT,
            page=PAGE,
            confirmed=True,
        )
        self.assertEqual(decision.reason, "created")
        kept = _rows(notes, "knowledge")
        self.assertEqual(kept[0]["content"], KEPT)
        self.assertEqual(kept[0]["category"], "knowledge")
        self.assertNotIn("RAWPAGE-MARKER-991", kept[0]["content"])

        again = record_card(
            notes,
            caller_id="owner-1",
            caller_kind="person",
            kind="knowledge",
            text=KEPT,
            confirmed=True,
        )
        self.assertEqual(again.reason, "revised")
        self.assertEqual(len(_rows(notes, "knowledge")), 1)
        self.assertEqual(_rows(notes, "knowledge")[0]["revision"], 2)

    def test_the_page_itself_and_a_credential_are_not_stored(self) -> None:
        notes = Notes()
        raw = record_card(
            notes,
            caller_id="owner-1",
            caller_kind="person",
            kind="finding",
            text=PAGE,
            page=PAGE,
            confirmed=True,
        )
        self.assertEqual(raw.reason, "raw_page")
        encoded = record_card(
            notes,
            caller_id="owner-1",
            caller_kind="person",
            kind="finding",
            text=quote_plus(PAGE),
            page=PAGE,
        )
        self.assertEqual(encoded.reason, "raw_page")
        self.assertEqual(notes.rows, {})
        self.assertNotIn("RAWPAGE-MARKER-991", repr(raw))
        self.assertNotIn("RAWPAGE-MARKER-991", repr(encoded))

        for text in ("token=abcd", "password is hunter22", "token%3Dabcd", "password+is+hunter22"):
            refused = record_card(
                notes,
                caller_id="owner-1",
                caller_kind="person",
                kind="finding",
                text=text,
                page=PAGE,
                confirmed=True,
            )
            self.assertEqual(refused.reason, "credential")
            self.assertNotIn("abcd", repr(refused))
            self.assertNotIn("hunter22", repr(refused))
        self.assertEqual(notes.rows, {})

        empty = record_card(
            notes,
            caller_id="owner-1",
            caller_kind="person",
            kind="finding",
            text="  \n  ",
        )
        self.assertEqual(empty.reason, "empty_content")
        self.assertEqual(
            record_card(
                notes,
                caller_id="owner-1",
                caller_kind="person",
                kind="findings",
                text="a real summary",
            ).reason,
            "kind",
        )
        self.assertEqual(
            record_card(
                notes,
                caller_id="owner-1",
                caller_kind="person",
                kind="finding",
                text="a real summary",
                page=True,
            ).reason,
            "page",
        )
        self.assertEqual(notes.rows, {})

    def test_an_encoded_or_rebuilt_page_is_not_stored(self) -> None:
        notes = Notes()
        percent = record_card(
            notes,
            caller_id="owner-1",
            caller_kind="person",
            kind="finding",
            text=f"One film is ready. {quote(PAGE, safe='')}",
            page=PAGE,
        )
        self.assertEqual(percent.reason, "created")
        self.assertEqual(_rows(notes, "finding")[0]["content"], "One film is ready.")
        self.assertNotIn("RAWPAGE-MARKER-991", _rows(notes, "finding")[0]["content"])
        self.assertNotIn("%25", _rows(notes, "finding")[0]["content"])

        plus = record_card(
            notes,
            caller_id="owner-1",
            caller_kind="person",
            kind="knowledge",
            text=f"Keep the early train. {quote_plus(PAGE)}",
            page=PAGE,
            confirmed=True,
        )
        self.assertEqual(plus.reason, "created")
        self.assertEqual(_rows(notes, "knowledge")[0]["content"], "Keep the early train.")
        self.assertNotIn("RAWPAGE-MARKER-991", _rows(notes, "knowledge")[0]["content"])

        rebuilt = Notes()
        hidden = record_card(
            rebuilt,
            caller_id="owner-1",
            caller_kind="person",
            kind="finding",
            text=PAGE[:20] + PAGE + PAGE[20:],
            page=PAGE,
            confirmed=True,
        )
        self.assertEqual(hidden.reason, "raw_page")
        self.assertEqual(rebuilt.rows, {})
        self.assertNotIn("RAWPAGE-MARKER-991", repr(hidden))

        doubled = record_card(
            rebuilt,
            caller_id="owner-1",
            caller_kind="person",
            kind="finding",
            text=f"One film is ready. {quote(quote(PAGE, safe=''), safe='')}",
            page=PAGE,
        )
        self.assertEqual(doubled.reason, "created")
        self.assertEqual(_rows(rebuilt, "finding")[0]["content"], "One film is ready.")
        self.assertNotIn("RAWPAGE-MARKER-991", _rows(rebuilt, "finding")[0]["content"])
        self.assertNotIn("2520", _rows(rebuilt, "finding")[0]["content"])

        short = record_card(
            rebuilt,
            caller_id="owner-1",
            caller_kind="person",
            kind="knowledge",
            text="One film is ready. secret-pg1",
            page="secret-pg1",
        )
        self.assertEqual(short.reason, "created")
        self.assertEqual(_rows(rebuilt, "knowledge")[0]["content"], "One film is ready.")
        self.assertNotIn("secret-pg1", _rows(rebuilt, "knowledge")[0]["content"])

        letter = record_card(
            rebuilt,
            caller_id="owner-1",
            caller_kind="person",
            kind="finding",
            text="The library stays open.",
            page="a",
        )
        self.assertEqual(letter.reason, "created")
        self.assertIn("The library stays open.", [note["content"] for note in _rows(rebuilt, "finding")])

    def test_a_long_summary_is_trimmed_and_a_second_owner_is_not_written(self) -> None:
        notes = Notes()
        wide = "north " * 300
        decision = record_card(
            notes,
            caller_id="owner-1",
            caller_kind="person",
            kind="finding",
            text=wide,
        )
        self.assertEqual(decision.reason, "created")
        stored = _rows(notes, "finding")[0]["content"]
        self.assertLessEqual(len(stored), 1200)
        self.assertGreater(len(stored), 1100)
        self.assertTrue(stored.startswith("north "))

        other = record_card(
            notes,
            caller_id="chief",
            caller_kind="role",
            subject_id="owner-1",
            subject_kind="person",
            kind="knowledge",
            text="the other decision",
            actor="board",
            confirmed=True,
        )
        self.assertEqual(other.reason, "other_owner")
        self.assertEqual(_rows(notes, "knowledge"), ())
        self.assertEqual(_rows(notes, "knowledge", "chief", "role"), ())

        for actor in ("chat", "Chat", " chat "):
            refused = record_card(
                notes,
                caller_id="owner-1",
                caller_kind="person",
                kind="finding",
                text="chat must not write this",
                actor=actor,
                confirmed=True,
            )
            self.assertEqual(refused.reason, "chat_cannot")
        self.assertEqual(len(_rows(notes, "finding")), 1)

        missing = record_card(
            notes,
            caller_id="token=abcd",
            caller_kind="person",
            kind="finding",
            text="lighthouse",
        )
        self.assertEqual(missing.reason, "credential")
        self.assertNotIn("abcd", repr(missing))
        self.assertEqual(
            record_card(notes, caller_id="", caller_kind="person", kind="finding", text="lighthouse").reason,
            "missing_owner",
        )

    def test_a_role_card_does_not_create_a_collection(self) -> None:
        notes = Notes()
        decision = record_card(
            notes,
            caller_id="chief",
            caller_kind="role",
            kind="finding",
            text="the day stays short",
            page=PAGE,
            confirmed=True,
        )
        self.assertEqual(decision.reason, "created")
        stored = _rows(notes, "finding", "chief", "role")
        self.assertEqual(stored[0]["visibility"], "working")
        self.assertEqual(stored[0]["category"], "finding")
        self.assertNotIn("role_profile_", stored[0]["content"])
        self.assertNotIn("family_shared", stored[0]["content"])
        self.assertNotIn("RAWPAGE-MARKER-991", stored[0]["content"])
        self.assertFalse(hasattr(notes, "collections"))

    def test_ask_does_not_record_a_card_and_postgres_does_not_connect(self) -> None:
        notes = Notes()

        def recall(**kwargs):
            return notes.recall(**kwargs)

        def save(**kwargs):
            return notes.save(**kwargs)

        remembered = ask(
            text="remember the project codename is lighthouse",
            owner_id="owner-1",
            owner_kind="person",
            charters_dir=ROOT / "charters",
            soul_text="You are Friday.",
            recall=recall,
            save=save,
            model=lambda _messages: "unused",
            embed_reason="",
            confirmed=True,
            tool_results=["A page was read."],
        )
        self.assertEqual(remembered.reason, "remembered")
        asked = ask(
            text="what is in the library",
            owner_id="owner-1",
            owner_kind="person",
            charters_dir=ROOT / "charters",
            soul_text="You are Friday.",
            recall=recall,
            save=save,
            model=lambda _messages: "One film.",
            embed_reason="",
            confirmed=True,
        )
        self.assertEqual(asked.reason, "model")
        self.assertEqual(_rows(notes, "finding"), ())
        self.assertEqual(_rows(notes, "knowledge"), ())
        remembered_row = notes.recall(owner_id="owner-1", owner_kind="person", category="note")
        self.assertEqual(remembered_row.notes[0]["category"], "note")

        def connect():
            raise AssertionError("connected")

        client = PostgresNotes(connect)
        for category in ("finding", "findings", "knowledge", " Finding ", " Knowledge "):
            refused = client.save(
                owner_id="owner-1",
                owner_kind="person",
                content=KEPT,
                category=category,
            )
            self.assertEqual(refused.reason, "card_pass")
        class _Neither:
            pass

        self.assertEqual(
            record_card(
                _Neither(),
                caller_id="owner-1",
                caller_kind="person",
                kind="finding",
                text=KEPT,
                page=PAGE,
                confirmed=True,
            ).reason,
            "not_the_file_store",
        )


class CardHttpTests(unittest.TestCase):
    def test_the_route_records_and_save_does_not(self) -> None:
        notes = Notes()
        handle = app(notes, {"MEMORY_TOKEN": TOKEN, "QDRANT_API_KEY": QDRANT})
        headers = {"Friday-Memory": TOKEN}
        body = {
            "action": "record",
            "owner_id": "owner-1",
            "owner_kind": "person",
            "kind": "finding",
            "text": f"One film is waiting. {PAGE}",
            "page": PAGE,
            "confirmed": True,
        }

        status, denied = handle("POST", "/card", {}, body)
        self.assertEqual(status, 401)
        self.assertNotIn("RAWPAGE-MARKER-991", str(denied))
        self.assertNotIn(QDRANT, str(denied))

        status, chat = handle("POST", "/card", headers, {**body, "actor": "chat"})
        self.assertEqual((status, chat["reason"]), (403, "chat_cannot"))
        self.assertEqual(_rows(notes, "finding"), ())

        status, other = handle(
            "POST",
            "/card",
            headers,
            {
                **body,
                "owner_id": "owner-2",
                "subject_id": "owner-1",
                "subject_kind": "person",
            },
        )
        self.assertEqual((status, other["reason"]), (200, "other_owner"))
        self.assertEqual(_rows(notes, "finding"), ())

        status, bad = handle("POST", "/card", headers, {**body, "action": "Record"})
        self.assertEqual((status, bad["reason"]), (403, "action"))

        status, saved = handle(
            "POST",
            "/save",
            headers,
            {
                "owner_id": "owner-1",
                "owner_kind": "person",
                "content": PAGE,
                "category": "finding",
            },
        )
        self.assertEqual((status, saved["reason"]), (403, "card_pass"))
        self.assertNotIn("RAWPAGE-MARKER-991", str(saved))
        status, knowledge = handle(
            "POST",
            "/save",
            headers,
            {
                "owner_id": "owner-1",
                "owner_kind": "person",
                "content": "token=abcd",
                "category": " Knowledge ",
            },
        )
        self.assertEqual((status, knowledge["reason"]), (403, "card_pass"))
        self.assertNotIn("abcd", str(knowledge))
        self.assertEqual(notes.rows, {})

        status, created = handle("POST", "/card", headers, body)
        self.assertEqual(status, 200, created)
        self.assertEqual(created["reason"], "created")
        stored = _rows(notes, "finding")
        self.assertEqual(stored[0]["content"], "One film is waiting.")
        self.assertNotIn("RAWPAGE-MARKER-991", stored[0]["content"])
        self.assertNotIn("RAWPAGE-MARKER-991", str(created))


class _Conn:
    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}
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
        if "memory_save" not in self._sql:
            raise AssertionError(self._sql)
        owner, kind, content, visibility, category = self._params
        digest = hashlib.md5(content.encode()).hexdigest()
        for row in self.rows.values():
            if row["deleted"]:
                continue
            if (row["owner_id"], row["owner_kind"], row["visibility"], row["category"]) != (
                owner,
                kind,
                visibility,
                category,
            ):
                continue
            if hashlib.md5(row["content"].encode()).hexdigest() != digest:
                continue
            row["revision"] += 1
            return (row["id"], row["revision"])
        new_id = str(uuid.uuid4())
        self.rows[new_id] = {
            "id": new_id,
            "owner_id": owner,
            "owner_kind": kind,
            "content": content,
            "visibility": visibility,
            "category": category,
            "deleted": False,
            "revision": 1,
        }
        return (new_id, 1)


class PostgresCardTests(unittest.TestCase):
    def _notes(self) -> tuple[PostgresNotes, _Conn]:
        conn = _Conn()
        return PostgresNotes(lambda: conn), conn

    def test_post_card_writes_memory_save_and_save_does_not_connect(self) -> None:
        notes, conn = self._notes()
        before = tuple(COLLECTIONS)
        handle = app(notes, {"MEMORY_TOKEN": TOKEN, "QDRANT_API_KEY": QDRANT})
        headers = {"Friday-Memory": TOKEN}
        body = {
            "action": "record",
            "owner_id": "owner-1",
            "owner_kind": "person",
            "kind": "finding",
            "text": f"One film is waiting. {PAGE}",
            "page": PAGE,
            "confirmed": True,
        }
        status, created = handle("POST", "/card", headers, body)
        self.assertEqual(status, 200, created)
        self.assertEqual(created["reason"], "created")
        self.assertNotIn("RAWPAGE-MARKER-991", str(created))
        self.assertNotIn(PAGE, str(created))
        saved = [sql for sql in conn.calls if "memory_save" in sql]
        self.assertEqual(len(saved), 1)
        self.assertNotIn("::uuid", saved[0])
        stored = next(iter(conn.rows.values()))
        self.assertEqual(stored["content"], "One film is waiting.")
        self.assertEqual(stored["category"], "finding")
        self.assertEqual(stored["visibility"], "master")
        self.assertNotIn("RAWPAGE-MARKER-991", stored["content"])
        again = handle("POST", "/card", headers, body)
        self.assertEqual(again[0], 200)
        self.assertEqual(again[1]["reason"], "revised")
        self.assertEqual(again[1]["id"], created["id"])
        self.assertEqual(stored["revision"], 2)
        self.assertEqual(len(conn.rows), 1)
        knowledge = handle(
            "POST",
            "/card",
            headers,
            {**body, "kind": "knowledge", "text": "One film is waiting."},
        )
        self.assertEqual(knowledge[1]["reason"], "created")
        self.assertNotEqual(knowledge[1]["id"], created["id"])
        self.assertEqual(len(conn.rows), 2)
        self.assertEqual(tuple(COLLECTIONS), before)
        self.assertNotIn("role_profile_owner-1", COLLECTIONS)
        self.assertNotIn("family_shared", COLLECTIONS)

        writes = len([sql for sql in conn.calls if "memory_save" in sql])
        status, blocked = handle(
            "POST",
            "/save",
            headers,
            {
                "owner_id": "owner-1",
                "owner_kind": "person",
                "content": "One film is waiting.",
                "category": "finding",
                "confirmed": True,
            },
        )
        self.assertEqual((status, blocked["reason"]), (403, "card_pass"))
        self.assertEqual(len([sql for sql in conn.calls if "memory_save" in sql]), writes)
        self.assertEqual(len(conn.rows), 2)
        self.assertNotIn("record_card", (ROOT / "friday" / "ask.py").read_text(encoding="utf-8"))
        self.assertNotIn("save_card", (ROOT / "friday" / "ask.py").read_text(encoding="utf-8"))

    def test_chat_a_secret_and_a_direct_save_do_not_connect(self) -> None:
        def connect():
            raise AssertionError("connected")

        closed = PostgresNotes(connect)
        self.assertEqual(
            record_card(
                closed,
                caller_id="owner-1",
                caller_kind="person",
                kind="finding",
                text=KEPT,
                actor="chat",
                confirmed=True,
            ).reason,
            "chat_cannot",
        )
        self.assertEqual(
            record_card(
                closed,
                caller_id="owner-1",
                caller_kind="person",
                kind="finding",
                text="password is hunter22",
                page=PAGE,
                confirmed=True,
            ).reason,
            "credential",
        )
        refused = closed.save_card(
            owner_id="owner-1",
            owner_kind="person",
            content="password is hunter22",
            category="finding",
        )
        self.assertEqual(refused.reason, "credential")
        self.assertNotIn("hunter22", str(refused))
        for category in ("finding", "findings", "knowledge", " Finding "):
            self.assertEqual(
                closed.save(
                    owner_id="owner-1",
                    owner_kind="person",
                    content=KEPT,
                    category=category,
                ).reason,
                "card_pass",
            )
        self.assertEqual(
            closed.save_card(
                owner_id="owner-1",
                owner_kind="person",
                content=KEPT,
                category="findings",
            ).reason,
            "kind",
        )

    def test_a_role_card_stays_one_row_and_another_owner_is_not_written(self) -> None:
        notes, conn = self._notes()
        role = record_card(
            notes,
            caller_id="chief",
            caller_kind="role",
            kind="finding",
            text=f"the day stays short. {PAGE}",
            page=PAGE,
            confirmed=True,
        )
        self.assertEqual(role.reason, "created")
        stored = next(iter(conn.rows.values()))
        self.assertEqual(stored["visibility"], "working")
        self.assertEqual(stored["category"], "finding")
        self.assertEqual(stored["owner_kind"], "role")
        self.assertNotIn("RAWPAGE-MARKER-991", stored["content"])
        again = record_card(
            notes,
            caller_id="chief",
            caller_kind="role",
            kind="finding",
            text="the day stays short.",
        )
        self.assertEqual(again.note_id, role.note_id)
        self.assertEqual(again.revision, 2)
        self.assertEqual(len(conn.rows), 1)
        calls = len(conn.calls)
        other = record_card(
            notes,
            caller_id="owner-2",
            caller_kind="person",
            subject_id="owner-1",
            subject_kind="person",
            kind="knowledge",
            text=KEPT,
            confirmed=True,
        )
        self.assertEqual(other.reason, "other_owner")
        self.assertEqual(len(conn.calls), calls)
        self.assertEqual(len(conn.rows), 1)
        self.assertNotIn("role_profile_chief", COLLECTIONS)
