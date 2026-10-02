"""A known app's start is a record. The container is not started."""

from __future__ import annotations

import unittest
from pathlib import Path

from guests.start import SAID, Book, record_start, shown


class KnownStart(unittest.TestCase):
    def test_the_board_records_the_ask_and_nothing_starts(self) -> None:
        book = Book()
        noted = record_start(
            book,
            app_id="jellyfin",
            actor="board",
            wire_level="known",
            mark="managed",
            note="docker start jellyfin",
            confirmed=True,
        )
        self.assertEqual(noted.outcome, "recorded")
        self.assertEqual(noted.reason, "not_started")
        self.assertEqual(noted.said, SAID)
        self.assertEqual(noted.said, "A start was asked.")
        self.assertEqual(noted.note, "docker start jellyfin")
        self.assertNotEqual(noted.said, noted.note)
        self.assertFalse(noted.started)
        self.assertFalse(noted.pulled)
        self.assertFalse(noted.performed)
        self.assertFalse(noted.called)
        self.assertNotIn("approval", noted.__dict__)
        self.assertEqual(book.rows["jellyfin"]["said"], SAID)
        again = record_start(
            book,
            app_id="jellyfin",
            actor="board",
            mark="managed",
            note="a later command",
            confirmed=True,
        )
        self.assertEqual(again.reason, "already")
        self.assertEqual(again.note, "docker start jellyfin")
        self.assertFalse(again.started)
        self.assertEqual(book.rows["jellyfin"]["note"], "docker start jellyfin")
        other = record_start(
            book,
            app_id="sonarr",
            actor="board",
            mark="managed",
            note="The password is kept outside the machine",
        )
        self.assertEqual(other.reason, "not_started")
        self.assertIn("outside the machine", other.note)
        self.assertEqual(other.said, SAID)
        self.assertNotIn("docker", shown(book, "sonarr").note)
        self.assertFalse(shown(book, "sonarr").started)
        self.assertEqual(len(book.rows), 2)

    def test_a_credential_is_not_stored(self) -> None:
        book = Book()
        first = record_start(
            book,
            app_id="jellyfin",
            actor="board",
            mark="managed",
            note="the shelf",
        )
        self.assertEqual(first.reason, "not_started")
        kept = record_start(
            book,
            app_id="jellyfin",
            actor="board",
            mark="managed",
            note="token=abcd",
        )
        self.assertEqual(kept.reason, "credential")
        self.assertEqual(kept.note, "")
        self.assertEqual(kept.app_id, "")
        self.assertNotIn("abcd", repr(kept))
        self.assertEqual(book.rows["jellyfin"]["note"], "the shelf")
        hunter = record_start(
            book,
            app_id="radarr",
            actor="board",
            mark="managed",
            note="password is hunter22",
        )
        self.assertEqual(hunter.reason, "credential")
        self.assertNotIn("hunter22", str(book.rows))
        self.assertNotIn("hunter22", repr(hunter))
        self.assertNotIn("radarr", book.rows)
        encoded = record_start(
            book,
            app_id="prowlarr",
            actor="board",
            mark="managed",
            note="token%3Dabcd",
        )
        self.assertEqual(encoded.reason, "credential")
        self.assertNotIn("prowlarr", book.rows)
        self.assertNotIn("abcd", repr(encoded))
        plus = record_start(
            book,
            app_id="lidarr",
            actor="board",
            mark="managed",
            note="password+is+hunter22",
        )
        self.assertEqual(plus.reason, "credential")
        self.assertNotIn("lidarr", book.rows)
        triple = record_start(
            book,
            app_id="bazarr",
            actor="board",
            mark="managed",
            note="token%25253Dabcd",
        )
        self.assertEqual(triple.reason, "credential")
        self.assertEqual(triple.note, "")
        self.assertNotIn("bazarr", book.rows)
        self.assertNotIn("abcd", repr(triple))
        nested = record_start(
            book,
            app_id="tautulli",
            actor="board",
            mark="managed",
            note="password%2520is%2520hunter22",
        )
        self.assertEqual(nested.reason, "credential")
        self.assertNotIn("tautulli", book.rows)
        self.assertNotIn("hunter22", repr(nested))
        named = record_start(
            book,
            app_id="token=abcd",
            actor="board",
            mark="managed",
            note="hello",
        )
        self.assertEqual(named.reason, "credential")
        self.assertNotIn("abcd", repr(named))
        self.assertNotIn("abcd", repr(book))
        hidden_id = record_start(
            book,
            app_id="token%3Dabcd",
            actor="board",
            mark="managed",
        )
        self.assertEqual(hidden_id.reason, "credential")
        self.assertEqual(hidden_id.app_id, "")
        self.assertNotIn("abcd", repr(hidden_id))

    def test_chat_cannot_record_and_a_core_or_adopted_app_is_refused(self) -> None:
        book = Book()
        refused = record_start(book, app_id="jellyfin", actor="chat", mark="managed")
        self.assertEqual(refused.reason, "chat_cannot")
        self.assertEqual(refused.note, "")
        self.assertFalse(refused.started)
        self.assertEqual(book.rows, {})
        noted = record_start(
            book,
            app_id="jellyfin",
            actor="board",
            mark="managed",
            note="the shelf",
        )
        self.assertEqual(noted.reason, "not_started")
        chat = record_start(
            book,
            app_id="jellyfin",
            actor=" Chat ",
            mark="managed",
            note="replace it",
            confirmed=True,
        )
        self.assertEqual(chat.reason, "chat_cannot")
        self.assertEqual(chat.note, "the shelf")
        self.assertFalse(chat.started)
        self.assertEqual(book.rows["jellyfin"]["note"], "the shelf")
        friday = record_start(
            book,
            app_id="jellyfin",
            actor="friday",
            mark="managed",
            note="replace it",
        )
        self.assertEqual(friday.reason, "actor_cannot")
        self.assertEqual(book.rows["jellyfin"]["note"], "the shelf")
        self.assertEqual(
            record_start(book, app_id="jellyfin", actor="board ", mark="managed").reason,
            "actor_cannot",
        )
        self.assertEqual(
            record_start(book, app_id=" jellyfin", actor="board", mark="managed").reason,
            "app_id",
        )
        self.assertEqual(
            record_start(book, app_id="jellyfin\n", actor="board", mark="managed").reason,
            "app_id",
        )
        plain_ask = record_start(
            book,
            app_id="bazarr",
            actor="board",
            mark="managed",
            note="The password is kept outside the machine",
        )
        self.assertEqual(plain_ask.reason, "not_started")
        plain = shown(book, "bazarr")
        self.assertIn("outside the machine", plain.note)
        self.assertEqual(
            record_start(
                book,
                app_id="The password is kept outside the machine",
                actor="board",
                mark="managed",
            ).reason,
            "app_id",
        )
        for name in ("postgres", "qdrant", "memory-mcp", "Friday", "gateway"):
            blocked = record_start(
                book,
                app_id=name,
                actor="board",
                wire_level="known",
                mark="managed",
            )
            self.assertEqual(blocked.reason, "core_locked")
            self.assertFalse(blocked.started)
            self.assertNotIn(name, book.rows)
        self.assertEqual(
            record_start(
                book,
                app_id="sonarr",
                actor="board",
                wire_level="Known",
                mark="managed",
            ).reason,
            "not_known",
        )
        self.assertEqual(
            record_start(
                book,
                app_id="sonarr",
                actor="board",
                wire_level="listed",
                mark="managed",
            ).reason,
            "not_known",
        )
        adopted = record_start(
            book,
            app_id="plex",
            actor="board",
            wire_level="known",
            mark="adopted",
            confirmed=True,
        )
        self.assertEqual(adopted.reason, "not_managed")
        self.assertFalse(adopted.started)
        self.assertNotIn("plex", book.rows)
        self.assertEqual(
            record_start(book, app_id="plex", actor="board", mark="Managed").reason,
            "not_managed",
        )
        self.assertEqual(
            record_start(book, app_id="plex", actor="board", mark=True).reason,
            "not_managed",
        )
        self.assertEqual(
            record_start(book, app_id="sonarr", actor="executor", mark="managed").reason,
            "actor_cannot",
        )
        self.assertNotIn("sonarr", book.rows)
        self.assertEqual(shown(book, "jellyfin").said, SAID)
        self.assertFalse(shown(book, "jellyfin").started)
        self.assertEqual(shown(book, "missing").reason, "no_start")
        blank = record_start(
            book,
            app_id="tautulli",
            actor="board",
            mark="managed",
            note="   ",
        )
        self.assertEqual(blank.reason, "not_started")
        self.assertEqual(blank.note, "")
        self.assertFalse(blank.started)
        long_note = record_start(
            book,
            app_id="prowlarr",
            actor="board",
            mark="managed",
            note=("shelf " * 400),
        )
        self.assertEqual(long_note.reason, "not_started")
        self.assertLessEqual(len(long_note.note), 1200)
        self.assertFalse(long_note.pulled)
        source = Path(record_start.__code__.co_filename).read_text(encoding="utf-8")
        self.assertNotIn("urlopen", source)
        self.assertNotIn("subprocess", source)
        self.assertNotIn("import socket", source)
        self.assertNotIn("docker", source)
        self.assertNotIn("connect(", source)
        root = Path(record_start.__code__.co_filename).parents[1]
        ask = (root / "friday" / "ask.py").read_text(encoding="utf-8")
        self.assertNotIn("record_start", ask)
        self.assertNotIn("guests.start", ask)
        board = (root / "board" / "server.js").read_text(encoding="utf-8")
        self.assertNotIn("record_start", board)


if __name__ == "__main__":
    unittest.main()
