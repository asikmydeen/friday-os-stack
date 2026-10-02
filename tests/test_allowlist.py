"""One fire allowlists jellyfin. Every other catalog id stays closed."""

from __future__ import annotations

import unittest
from pathlib import Path

from catalog.allowlist import Book, fire, install
from catalog.discover import draft_ids, request_install

ROOT = Path(__file__).resolve().parents[1]
PIN = ROOT / "catalog" / "PIN"
TOKEN = "token=abcd"
KEPT = "The password is kept outside the machine"


def _fire(book: Book, app_id: object, **extra: object):
    fields = {"actor": "board", "app_id": app_id, "confirmed": False}
    fields.update(extra)
    return fire(book, **fields)


class AllowlistTests(unittest.TestCase):
    def test_one_fire_allowlists_jellyfin_only(self) -> None:
        before = PIN.read_text(encoding="utf-8")
        book = Book()
        self.assertEqual(book.ids, set())
        closed = install(book, "jellyfin", confirmed=True)
        self.assertEqual(closed.reason, "catalog_install_closed")
        self.assertIs(closed.allowlisted, False)
        self.assertIs(closed.started, False)
        decision = _fire(book, " Jellyfin ", confirmed=True)
        self.assertEqual(decision.outcome, "allowlisted")
        self.assertEqual(decision.reason, "jellyfin")
        self.assertEqual(decision.app_id, "jellyfin")
        self.assertIs(decision.allowlisted, True)
        self.assertEqual(decision.install, "refused")
        self.assertIs(decision.started, False)
        self.assertIs(decision.applied, False)
        self.assertNotIn("confirmed", decision.__dict__)
        self.assertNotIn("note", decision.__dict__)
        self.assertNotIn("said", decision.__dict__)
        self.assertEqual(book.ids, {"jellyfin"})
        self.assertEqual(repr(book), "Book()")
        again = _fire(book, "jellyfin")
        self.assertEqual(again.reason, "jellyfin")
        self.assertEqual(book.ids, {"jellyfin"})
        self.assertEqual(PIN.read_text(encoding="utf-8"), before)
        source = (ROOT / "catalog" / "allowlist.py").read_text(encoding="utf-8")
        self.assertNotIn("catalog/wires", source)
        self.assertNotIn("open(", source)
        self.assertNotIn("write_text", source)

    def test_every_other_catalog_id_stays_closed(self) -> None:
        book = Book()
        others = tuple(app_id for app_id in draft_ids() if app_id != "jellyfin")
        self.assertIn("plex", others)
        self.assertIn("home-assistant", others)
        for app_id in others:
            decision = _fire(book, app_id, confirmed=True)
            self.assertEqual(decision.reason, "stays_closed", app_id)
            self.assertIs(decision.allowlisted, False)
            self.assertIs(decision.started, False)
            installed = install(book, app_id, confirmed=True)
            self.assertEqual(installed.reason, "catalog_install_closed", app_id)
            self.assertIs(installed.allowlisted, False)
            self.assertIs(installed.started, False)
            self.assertIs(installed.applied, False)
        self.assertEqual(book.ids, set())
        _fire(book, "jellyfin")
        for app_id in (*others, "nextcloud"):
            decision = _fire(book, app_id)
            self.assertEqual(decision.reason, "stays_closed", app_id)
            installed = install(book, app_id)
            self.assertEqual(installed.reason, "catalog_install_closed")
            self.assertIs(installed.allowlisted, False)
        kept = install(book, "jellyfin", confirmed=True)
        self.assertEqual(kept.reason, "catalog_install_closed")
        self.assertIs(kept.allowlisted, True)
        self.assertIs(kept.started, False)
        self.assertIs(kept.applied, False)
        self.assertEqual(book.ids, {"jellyfin"})
        self.assertEqual(request_install("jellyfin", confirmed=True).reason, "catalog_install_closed")
        self.assertEqual(request_install("plex", confirmed=True).reason, "catalog_install_closed")

    def test_chat_cannot_fire_and_a_sentence_is_not_stored(self) -> None:
        book = Book()
        _fire(book, "jellyfin")
        for actor in ("chat", "Chat", " chat ", "friday", "executor", "board "):
            decision = _fire(book, "plex", actor=actor, confirmed=True)
            reason = "chat_cannot_allow" if actor.strip().casefold() == "chat" else "actor_cannot_allow"
            self.assertEqual(decision.reason, reason, actor)
            self.assertIs(decision.started, False)
        self.assertEqual(book.ids, {"jellyfin"})
        said = _fire(Book(), "jellyfin is allowlisted")
        self.assertEqual(said.reason, "app_id")
        self.assertEqual(said.app_id, "")
        self.assertNotIn("said", said.__dict__)
        empty = Book()
        self.assertEqual(_fire(empty, "jellyfin is allowlisted").reason, "app_id")
        self.assertEqual(empty.ids, set())
        self.assertEqual(_fire(empty, KEPT).reason, "app_id")
        self.assertNotIn(KEPT, repr(_fire(empty, KEPT)))
        self.assertEqual(empty.ids, set())

    def test_a_credential_shaped_id_is_not_stored(self) -> None:
        book = Book()
        _fire(book, "jellyfin")
        for secret in (TOKEN, "token%3Dabcd", "password+is+hunter22", "token%253Dabcd"):
            decision = _fire(book, secret, confirmed=True)
            self.assertEqual(decision.reason, "credential")
            self.assertEqual(decision.app_id, "")
            self.assertNotIn("abcd", repr(decision))
            self.assertNotIn("hunter22", repr(decision))
            self.assertNotIn(secret, repr(decision))
            missed = install(book, secret)
            self.assertEqual(missed.reason, "credential")
            self.assertNotIn("abcd", repr(missed))
            self.assertNotIn("hunter22", repr(missed))
        self.assertEqual(book.ids, {"jellyfin"})
        self.assertEqual(_fire(book, "").reason, "app_id")
        self.assertEqual(_fire(book, "../jellyfin").reason, "app_id")
        self.assertEqual(book.ids, {"jellyfin"})

    def test_ask_does_not_call_it_and_the_image_copies_it(self) -> None:
        ask = (ROOT / "friday" / "ask.py").read_text(encoding="utf-8")
        self.assertNotIn("catalog.allowlist", ask)
        self.assertNotIn("allowlist", ask)
        docker = (ROOT / "executor" / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("COPY catalog catalog", docker)
        stamp = (ROOT / "scripts" / "fetch-core.sh").read_text(encoding="utf-8")
        self.assertIn('"$ROOT/catalog"', stamp)
        script = (ROOT / "image" / "build-inside.sh").read_text(encoding="utf-8")
        self.assertIn("/src/catalog/allowlist.py", script)
        self.assertIn("usr/lib/friday/catalog/allowlist.py", script)


if __name__ == "__main__":
    unittest.main()
