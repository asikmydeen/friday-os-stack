"""A known app's stop is a record. The container is not stopped."""

from __future__ import annotations

import unittest
from pathlib import Path

from guests.stop import SAID, Book, record_stop, shown


class KnownStop(unittest.TestCase):
    def test_the_board_records_the_ask_and_nothing_stops(self) -> None:
        book = Book()
        noted = record_stop(
            book,
            app_id="jellyfin",
            actor="board",
            wire_level="known",
            mark="managed",
            note="stop the player",
            confirmed=True,
        )
        self.assertEqual(noted.outcome, "recorded")
        self.assertEqual(noted.reason, "not_stopped")
        self.assertEqual(noted.said, SAID)
        self.assertEqual(noted.said, "A stop was asked.")
        self.assertEqual(noted.note, "stop the player")
        self.assertNotEqual(noted.said, noted.note)
        self.assertFalse(noted.stopped)
        self.assertFalse(noted.pulled)
        self.assertFalse(noted.deleted)
        self.assertFalse(noted.performed)
        self.assertFalse(noted.called)
        self.assertNotIn("approval", noted.__dict__)
        self.assertEqual(book.rows["jellyfin"]["said"], SAID)
        again = record_stop(
            book,
            app_id="jellyfin",
            actor="board",
            mark="managed",
            note="a later command",
            confirmed=True,
        )
        self.assertEqual(again.reason, "already")
        self.assertEqual(again.note, "stop the player")
        self.assertFalse(again.stopped)
        self.assertFalse(again.deleted)
        self.assertEqual(book.rows["jellyfin"]["note"], "stop the player")
        other = record_stop(
            book,
            app_id="sonarr",
            actor="board",
            mark="managed",
            note="The password is kept outside the machine",
        )
        self.assertEqual(other.reason, "not_stopped")
        self.assertIn("outside the machine", other.note)
        self.assertEqual(other.said, SAID)
        self.assertFalse(other.deleted)
        self.assertNotIn("player", shown(book, "sonarr").note)
        self.assertFalse(shown(book, "sonarr").stopped)
        self.assertEqual(len(book.rows), 2)

    def test_a_credential_is_not_stored(self) -> None:
        book = Book()
        first = record_stop(
            book,
            app_id="jellyfin",
            actor="board",
            mark="managed",
            note="the shelf",
        )
        self.assertEqual(first.reason, "not_stopped")
        kept = record_stop(
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
        hunter = record_stop(
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
        encoded = record_stop(
            book,
            app_id="prowlarr",
            actor="board",
            mark="managed",
            note="token%3Dabcd",
        )
        self.assertEqual(encoded.reason, "credential")
        self.assertNotIn("prowlarr", book.rows)
        self.assertNotIn("abcd", repr(encoded))
        plus = record_stop(
            book,
            app_id="lidarr",
            actor="board",
            mark="managed",
            note="password+is+hunter22",
        )
        self.assertEqual(plus.reason, "credential")
        self.assertNotIn("lidarr", book.rows)
        triple = record_stop(
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
        nested = record_stop(
            book,
            app_id="tautulli",
            actor="board",
            mark="managed",
            note="password%2520is%2520hunter22",
        )
        self.assertEqual(nested.reason, "credential")
        self.assertNotIn("tautulli", book.rows)
        self.assertNotIn("hunter22", repr(nested))
        named = record_stop(
            book,
            app_id="token=abcd",
            actor="board",
            mark="managed",
            note="hello",
        )
        self.assertEqual(named.reason, "credential")
        self.assertNotIn("abcd", repr(named))
        self.assertNotIn("abcd", repr(book))
        hidden_id = record_stop(
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
        refused = record_stop(book, app_id="jellyfin", actor="chat", mark="managed")
        self.assertEqual(refused.reason, "chat_cannot")
        self.assertEqual(refused.note, "")
        self.assertFalse(refused.stopped)
        self.assertFalse(refused.deleted)
        self.assertEqual(book.rows, {})
        noted = record_stop(
            book,
            app_id="jellyfin",
            actor="board",
            mark="managed",
            note="the shelf",
        )
        self.assertEqual(noted.reason, "not_stopped")
        chat = record_stop(
            book,
            app_id="jellyfin",
            actor=" Chat ",
            mark="managed",
            note="replace it",
            confirmed=True,
        )
        self.assertEqual(chat.reason, "chat_cannot")
        self.assertEqual(chat.note, "the shelf")
        self.assertFalse(chat.stopped)
        self.assertEqual(book.rows["jellyfin"]["note"], "the shelf")
        friday = record_stop(
            book,
            app_id="jellyfin",
            actor="friday",
            mark="managed",
            note="replace it",
        )
        self.assertEqual(friday.reason, "actor_cannot")
        self.assertEqual(book.rows["jellyfin"]["note"], "the shelf")
        self.assertEqual(
            record_stop(book, app_id="jellyfin", actor="board ", mark="managed").reason,
            "actor_cannot",
        )
        self.assertEqual(
            record_stop(book, app_id=" jellyfin", actor="board", mark="managed").reason,
            "app_id",
        )
        self.assertEqual(
            record_stop(book, app_id="jellyfin\n", actor="board", mark="managed").reason,
            "app_id",
        )
        plain_ask = record_stop(
            book,
            app_id="bazarr",
            actor="board",
            mark="managed",
            note="The password is kept outside the machine",
        )
        self.assertEqual(plain_ask.reason, "not_stopped")
        plain = shown(book, "bazarr")
        self.assertIn("outside the machine", plain.note)
        self.assertFalse(plain.deleted)
        self.assertEqual(
            record_stop(
                book,
                app_id="The password is kept outside the machine",
                actor="board",
                mark="managed",
            ).reason,
            "app_id",
        )
        for name in ("postgres", "qdrant", "memory-mcp", "Friday", "gateway"):
            blocked = record_stop(
                book,
                app_id=name,
                actor="board",
                wire_level="known",
                mark="managed",
            )
            self.assertEqual(blocked.reason, "core_locked")
            self.assertFalse(blocked.stopped)
            self.assertNotIn(name, book.rows)
        self.assertEqual(
            record_stop(
                book,
                app_id="sonarr",
                actor="board",
                wire_level="Known",
                mark="managed",
            ).reason,
            "not_known",
        )
        self.assertEqual(
            record_stop(
                book,
                app_id="sonarr",
                actor="board",
                wire_level="listed",
                mark="managed",
            ).reason,
            "not_known",
        )
        adopted = record_stop(
            book,
            app_id="plex",
            actor="board",
            wire_level="known",
            mark="adopted",
            confirmed=True,
        )
        self.assertEqual(adopted.reason, "not_managed")
        self.assertFalse(adopted.stopped)
        self.assertFalse(adopted.deleted)
        self.assertNotIn("plex", book.rows)
        self.assertEqual(
            record_stop(book, app_id="plex", actor="board", mark="Managed").reason,
            "not_managed",
        )
        self.assertEqual(
            record_stop(book, app_id="plex", actor="board", mark=True).reason,
            "not_managed",
        )
        self.assertEqual(
            record_stop(book, app_id="sonarr", actor="executor", mark="managed").reason,
            "actor_cannot",
        )
        self.assertNotIn("sonarr", book.rows)
        self.assertEqual(shown(book, "jellyfin").said, SAID)
        self.assertFalse(shown(book, "jellyfin").stopped)
        self.assertEqual(shown(book, "missing").reason, "no_stop")
        blank = record_stop(
            book,
            app_id="tautulli",
            actor="board",
            mark="managed",
            note="   ",
        )
        self.assertEqual(blank.reason, "not_stopped")
        self.assertEqual(blank.note, "")
        self.assertFalse(blank.stopped)
        long_note = record_stop(
            book,
            app_id="prowlarr",
            actor="board",
            mark="managed",
            note=("shelf " * 400),
        )
        self.assertEqual(long_note.reason, "not_stopped")
        self.assertLessEqual(len(long_note.note), 1200)
        self.assertFalse(long_note.pulled)
        self.assertFalse(long_note.deleted)
        source = Path(record_stop.__code__.co_filename).read_text(encoding="utf-8")
        self.assertNotIn("urlopen", source)
        self.assertNotIn("subprocess", source)
        self.assertNotIn("import socket", source)
        self.assertNotIn("docker", source)
        self.assertNotIn("connect(", source)
        root = Path(record_stop.__code__.co_filename).parents[1]
        ask = (root / "friday" / "ask.py").read_text(encoding="utf-8")
        self.assertNotIn("record_stop", ask)
        self.assertNotIn("guests.stop", ask)
        board = (root / "board" / "server.js").read_text(encoding="utf-8")
        self.assertNotIn("record_stop", board)
        registry = (root / "guests" / "registry.py").read_text(encoding="utf-8")
        self.assertNotIn("record_stop", registry)


if __name__ == "__main__":
    unittest.main()
