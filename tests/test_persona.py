"""The persona pass copies profile notes. It does not open Postgres."""

from __future__ import annotations

import unittest
import uuid
from pathlib import Path

from friday.ask import ask
from memoryd.persona import extract, portrait
from memoryd.server import app
from memoryd.sqlstore import PostgresNotes
from memoryd.store import Notes, credential_shape

KEPT = "The password is kept outside the machine"
TOKEN = "memory-token"
QDRANT = "qdrant-token"
ROOT = Path(__file__).resolve().parents[1]


def _persona(notes: Notes, owner_id: str = "owner-1", owner_kind: str = "person") -> tuple[dict, ...]:
    packed = notes.recall(owner_id=owner_id, owner_kind=owner_kind, category="persona")
    return packed.notes


def _retitle(notes: Notes, content: str, note_id: object) -> None:
    saved = notes.save(owner_id="owner-1", owner_kind="person", content=content, category="persona")
    row = notes.rows.pop(saved.note_id)
    row.id = note_id
    notes.rows[note_id] = row


class PersonaTests(unittest.TestCase):
    def test_profile_notes_become_one_persona_note_and_a_remember_does_not(self) -> None:
        notes = Notes()
        notes.save(owner_id="owner-1", owner_kind="person", content="likes the early train", category="profile")
        notes.save(owner_id="owner-1", owner_kind="person", content=KEPT, category="profile")
        notes.save(owner_id="owner-1", owner_kind="person", content="codename lighthouse", category="note")
        notes.save(owner_id="owner-1", owner_kind="person", content="tuesday stood", category="episode")
        notes.save(owner_id="owner-2", owner_kind="person", content="other profile", category="profile")

        first = extract(
            notes,
            caller_id="owner-1",
            caller_kind="person",
            confirmed=True,
        )
        self.assertEqual(first.reason, "created")
        uuid.UUID(first.note_id)
        self.assertFalse(credential_shape(first.note_id))
        copied = _persona(notes)
        self.assertEqual(len(copied), 1)
        self.assertIn("likes the early train", copied[0]["content"])
        self.assertIn(KEPT, copied[0]["content"])
        self.assertNotIn("lighthouse", copied[0]["content"])
        self.assertNotIn("tuesday", copied[0]["content"])
        self.assertNotIn("other profile", copied[0]["content"])
        self.assertEqual(copied[0]["category"], "persona")
        profiles = notes.recall(owner_id="owner-1", owner_kind="person", category="profile")
        self.assertEqual(len(profiles.notes), 2)

        again = extract(notes, caller_id="owner-1", caller_kind="person", confirmed=True)
        self.assertEqual(again.reason, "revised")
        self.assertEqual(len(_persona(notes)), 1)
        self.assertEqual(_persona(notes)[0]["revision"], 2)

        notes.save(owner_id="owner-1", owner_kind="person", content="reads late", category="profile")
        changed = extract(notes, caller_id="owner-1", caller_kind="person")
        self.assertEqual(changed.reason, "created")
        self.assertEqual(len(_persona(notes)), 2)

    def test_a_credential_line_is_left_out_and_a_full_window_writes_nothing(self) -> None:
        notes = Notes()
        self.assertEqual(
            notes.save(owner_id="owner-1", owner_kind="person", content="token=abcd", category="profile").reason,
            "credential",
        )
        self.assertEqual(
            notes.save(
                owner_id="owner-1",
                owner_kind="person",
                content="password is hunter22",
                category="profile",
            ).reason,
            "credential",
        )
        self.assertEqual(notes.rows, {})

        notes.save(owner_id="owner-1", owner_kind="person", content="kept early", category="profile")
        notes.save(owner_id="owner-1", owner_kind="person", content="token%3Dabcd", category="profile")
        notes.save(owner_id="owner-1", owner_kind="person", content="password+is+hunter22", category="profile")
        mixed = extract(notes, caller_id="owner-1", caller_kind="person")
        self.assertEqual(mixed.reason, "created")
        self.assertEqual(_persona(notes)[0]["content"], "kept early")

        blocked = Notes()
        blocked.save(owner_id="owner-1", owner_kind="person", content="older trait", category="profile")
        for index in range(8):
            blocked.save(
                owner_id="owner-1",
                owner_kind="person",
                content=f"token%3Dabcd{index}",
                category="profile",
            )
        decision = extract(blocked, caller_id="owner-1", caller_kind="person", confirmed=True)
        self.assertEqual(decision.reason, "credential")
        self.assertEqual(_persona(blocked), ())
        self.assertNotIn("abcd", repr(decision))
        self.assertTrue(any(row.content == "older trait" for row in blocked.rows.values()))
        window = blocked.recall(owner_id="owner-1", owner_kind="person", category="profile")
        self.assertEqual(len(window.notes), 8)
        self.assertNotIn("older trait", " ".join(note["content"] for note in window.notes))

    def test_the_ninth_profile_row_stays_outside_the_window(self) -> None:
        notes = Notes()
        for index in range(9):
            notes.save(owner_id="owner-1", owner_kind="person", content=f"trait-{index}", category="profile")
        decision = extract(notes, caller_id="owner-1", caller_kind="person")
        self.assertEqual(decision.reason, "created")
        text = _persona(notes)[0]["content"]
        self.assertIn("trait-8", text)
        self.assertIn("trait-1", text)
        self.assertNotIn("trait-0", text)

        long_notes = Notes()
        long_notes.save(owner_id="owner-1", owner_kind="person", content="north " * 300, category="profile")
        self.assertEqual(extract(long_notes, caller_id="owner-1", caller_kind="person").reason, "created")
        trimmed = _persona(long_notes)[0]["content"]
        self.assertLessEqual(len(trimmed), 1200)
        self.assertGreater(len(trimmed), 1100)
        self.assertTrue(trimmed.startswith("north "))

    def test_someone_else_and_chat_write_nothing(self) -> None:
        notes = Notes()
        notes.save(owner_id="owner-1", owner_kind="person", content="likes quiet", category="profile")
        other = extract(
            notes,
            caller_id="chief",
            caller_kind="role",
            subject_id="owner-1",
            subject_kind="person",
            actor="board",
            confirmed=True,
        )
        self.assertEqual(other.reason, "other_owner")
        self.assertEqual(_persona(notes), ())
        self.assertEqual(_persona(notes, "chief", "role"), ())

        for actor in ("chat", "Chat", " chat "):
            refused = extract(notes, caller_id="owner-1", caller_kind="person", actor=actor, confirmed=True)
            self.assertEqual(refused.reason, "chat_cannot")
        self.assertEqual(_persona(notes), ())

        missing = extract(notes, caller_id="token=abcd", caller_kind="person")
        self.assertEqual(missing.reason, "credential")
        self.assertNotIn("abcd", repr(missing))
        self.assertEqual(extract(notes, caller_id="", caller_kind="person").reason, "missing_owner")

    def test_a_role_note_does_not_create_a_collection(self) -> None:
        notes = Notes()
        notes.save(owner_id="chief", owner_kind="role", content="keeps the day short", visibility="working", category="profile")
        decision = extract(notes, caller_id="chief", caller_kind="role", confirmed=True)
        self.assertEqual(decision.reason, "created")
        copied = _persona(notes, "chief", "role")
        self.assertEqual(copied[0]["category"], "persona")
        self.assertEqual(copied[0]["visibility"], "working")
        self.assertNotIn("role_profile_", copied[0]["content"])
        self.assertFalse(hasattr(notes, "collections"))
        plain = extract(notes, caller_id="owner-1", caller_kind="person")
        self.assertEqual(plain.reason, "nothing_to_extract")

    def test_a_portrait_question_returns_only_persona_notes(self) -> None:
        notes = Notes()
        notes.save(owner_id="owner-1", owner_kind="person", content=KEPT, category="persona")
        notes.save(owner_id="owner-1", owner_kind="person", content="secret episode", category="episode")
        notes.save(owner_id="owner-1", owner_kind="person", content="token%3Dabcd", category="persona")
        wide = "north " * 300
        notes.save(owner_id="owner-1", owner_kind="person", content=wide, category="persona")

        shown = portrait(notes, caller_id="owner-1", caller_kind="person", text="Who am I?", confirmed=True)
        self.assertEqual(shown.reason, "portrait")
        self.assertLessEqual(len(shown.notes), 8)
        blob = " ".join(note["content"] for note in shown.notes)
        self.assertIn(KEPT, blob)
        self.assertNotIn("episode", blob)
        self.assertNotIn("abcd", blob)
        self.assertTrue(all(len(note["content"]) <= 1200 for note in shown.notes))
        self.assertTrue(all(note["category"] == "persona" for note in shown.notes))

        idle = portrait(notes, caller_id="owner-1", caller_kind="person", text="what is running")
        self.assertEqual(idle.reason, "not_a_portrait")
        self.assertEqual(idle.notes, ())
        hidden = portrait(notes, caller_id="owner-1", caller_kind="person", text="token%3Dabcd")
        self.assertEqual(hidden.reason, "credential")
        self.assertEqual(hidden.notes, ())
        self.assertNotIn("abcd", repr(hidden))
        plus = portrait(notes, caller_id="owner-1", caller_kind="person", text="password+is+hunter22")
        self.assertEqual(plus.reason, "credential")
        self.assertEqual(plus.notes, ())
        other = portrait(
            notes,
            caller_id="owner-2",
            caller_kind="person",
            subject_id="owner-1",
            subject_kind="person",
            text="who am i",
            confirmed=True,
        )
        self.assertEqual(other.reason, "other_owner")
        self.assertEqual(other.notes, ())
        chat = portrait(notes, caller_id="owner-1", caller_kind="person", text="what am I like", actor="chat")
        self.assertEqual(chat.reason, "chat_cannot")
        self.assertEqual(chat.notes, ())

    def test_a_credential_shaped_or_empty_note_id_is_not_shown(self) -> None:
        notes = Notes()
        clean = notes.save(owner_id="owner-1", owner_kind="person", content="lighthouse", category="persona")
        kept = notes.save(owner_id="owner-1", owner_kind="person", content=KEPT, category="persona")
        for index, bad in enumerate(("token=abcd", "token%3Dabcd", "password+is+hunter22", "", " token=abcd ", 4404)):
            _retitle(notes, f"side channel {index}", bad)
        shown = portrait(notes, caller_id="owner-1", caller_kind="person", text="who am i", confirmed=True)
        self.assertEqual(shown.reason, "portrait")
        self.assertEqual({note["id"] for note in shown.notes}, {clean.note_id, kept.note_id})
        self.assertEqual({note["content"] for note in shown.notes}, {"lighthouse", KEPT})
        self.assertNotIn("abcd", repr(shown))
        self.assertNotIn("hunter22", repr(shown))
        self.assertNotIn("side channel", repr(shown))
        self.assertTrue(all(set(note) == {"id", "content", "owner_id", "owner_kind", "category"} for note in shown.notes))

        only = Notes()
        _retitle(only, "lighthouse", "token=abcd")
        hidden = portrait(only, caller_id="owner-1", caller_kind="person", text="what am i like")
        self.assertEqual(hidden.reason, "nothing_to_show")
        self.assertEqual(hidden.notes, ())
        self.assertNotIn("abcd", repr(hidden))
        self.assertNotIn("lighthouse", repr(hidden))

    def test_ask_does_not_extract_and_postgres_does_not_connect(self) -> None:
        notes = Notes()
        notes.save(owner_id="owner-1", owner_kind="person", content="likes quiet", category="profile")

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
        )
        self.assertEqual(remembered.reason, "remembered")
        asked = ask(
            text="who am I",
            owner_id="owner-1",
            owner_kind="person",
            charters_dir=ROOT / "charters",
            soul_text="You are Friday.",
            recall=recall,
            save=save,
            model=lambda _messages: "You like the early train.",
            embed_reason="",
            confirmed=True,
        )
        self.assertEqual(asked.reason, "model")
        self.assertEqual(_persona(notes), ())

        def connect():
            raise AssertionError("connected")

        client = PostgresNotes(connect)
        self.assertEqual(
            client.save(
                owner_id="owner-1",
                owner_kind="person",
                content=KEPT,
                category="persona",
            ).reason,
            "persona_pass",
        )
        self.assertEqual(
            client.save(
                owner_id="owner-1",
                owner_kind="person",
                content=KEPT,
                category=" Persona ",
            ).reason,
            "persona_pass",
        )
        self.assertEqual(
            extract(client, caller_id="owner-1", caller_kind="person", confirmed=True).reason,
            "not_the_file_store",
        )
        self.assertEqual(
            portrait(client, caller_id="owner-1", caller_kind="person", text="who am i").reason,
            "not_the_file_store",
        )


class PersonaHttpTests(unittest.TestCase):
    def test_the_route_extracts_and_save_does_not(self) -> None:
        notes = Notes()
        notes.save(owner_id="owner-1", owner_kind="person", content="likes quiet", category="profile")
        handle = app(notes, {"MEMORY_TOKEN": TOKEN, "QDRANT_API_KEY": QDRANT})
        headers = {"Friday-Memory": TOKEN}

        status, denied = handle("POST", "/persona", {}, {"action": "extract", "owner_id": "owner-1", "owner_kind": "person"})
        self.assertEqual(status, 401)
        self.assertNotIn("quiet", str(denied))

        status, chat = handle(
            "POST",
            "/persona",
            headers,
            {"action": "extract", "actor": "chat", "owner_id": "owner-1", "owner_kind": "person", "confirmed": True},
        )
        self.assertEqual((status, chat["reason"]), (403, "chat_cannot"))
        self.assertEqual(_persona(notes), ())

        status, other = handle(
            "POST",
            "/persona",
            headers,
            {
                "action": "extract",
                "owner_id": "owner-2",
                "owner_kind": "person",
                "subject_id": "owner-1",
                "subject_kind": "person",
                "confirmed": True,
            },
        )
        self.assertEqual((status, other["reason"]), (200, "other_owner"))
        self.assertEqual(_persona(notes), ())

        status, bad = handle(
            "POST",
            "/persona",
            headers,
            {"action": "Extract", "owner_id": "owner-1", "owner_kind": "person", "confirmed": True},
        )
        self.assertEqual((status, bad["reason"]), (403, "action"))
        self.assertEqual(_persona(notes), ())

        status, saved = handle(
            "POST",
            "/save",
            headers,
            {"owner_id": "owner-1", "owner_kind": "person", "content": KEPT, "category": "persona"},
        )
        self.assertEqual((status, saved["reason"]), (403, "persona_pass"))
        self.assertEqual(_persona(notes), ())

        status, created = handle(
            "POST",
            "/persona",
            headers,
            {"action": "extract", "owner_id": "owner-1", "owner_kind": "person", "confirmed": True},
        )
        self.assertEqual(status, 200, created)
        self.assertEqual(created["reason"], "created")
        self.assertIn("likes quiet", _persona(notes)[0]["content"])

        status, shown = handle(
            "POST",
            "/persona",
            headers,
            {"action": "portrait", "owner_id": "owner-1", "owner_kind": "person", "text": "who am i", "confirmed": True},
        )
        self.assertEqual(shown["reason"], "portrait")
        self.assertIn("likes quiet", shown["notes"][0]["content"])
        self.assertNotIn(QDRANT, str(shown))
