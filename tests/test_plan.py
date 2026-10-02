"""The coding-plan URL is recorded by name. The key is not stored."""

from __future__ import annotations

import inspect
import os
import unittest
from pathlib import Path

import updates.plan as plan
from updates.plan import (
    KEY_NAME,
    NAME,
    Book,
    engine_of,
    matches,
    names,
    record_plan,
    show,
    use_plan,
)

KEPT = "The password is kept outside the machine"
TOKEN = "token=abcd"
HUNTER = "password is hunter22"
URL = "https://coding.example/v1"
OTHER = "https://other.example/v1"


def _record(book: Book, **kwargs):
    fields = {
        "actor": "board",
        "engine": "claude-code",
        "base_url": URL,
    }
    fields.update(kwargs)
    return record_plan(book, **fields)


class PlanTests(unittest.TestCase):
    def test_an_unset_url_stores_nothing_and_does_not_read_the_key(self) -> None:
        book = Book()
        previous = os.environ.get(KEY_NAME)
        os.environ[KEY_NAME] = "from-the-env"
        try:
            for base in (None, "", "   "):
                decision = _record(book, base_url=base, confirmed=True)
                self.assertEqual((decision.outcome, decision.reason), ("recorded", "unset"))
                self.assertEqual(decision.name, "")
                self.assertFalse(decision.started)
                self.assertFalse(decision.called)
                self.assertFalse(decision.read_env)
            self.assertEqual(names(book), ())
            self.assertEqual(engine_of(book), "")
            self.assertFalse(matches(book, "from-the-env"))
            self.assertEqual(os.environ[KEY_NAME], "from-the-env")
            gsd = _record(book, engine="gsd", base_url=None)
            self.assertEqual(gsd.reason, "unset")
            self.assertEqual(names(book), ())
            self.assertEqual(use_plan(book, actor="board", confirmed=True).reason, "unset")
            self.assertFalse(use_plan(book, actor="board").called)
        finally:
            if previous is None:
                os.environ.pop(KEY_NAME, None)
            else:
                os.environ[KEY_NAME] = previous

    def test_the_board_records_the_name_and_chat_does_not(self) -> None:
        book = Book()
        for actor in ("chat", "friday", "adapter"):
            refused = _record(book, actor=actor, confirmed=True)
            self.assertEqual(refused.reason, "board_only")
            self.assertEqual(refused.name, "")
            self.assertFalse(refused.started)
            self.assertFalse(refused.called)
        self.assertEqual(names(book), ())
        recorded = _record(book, confirmed=True)
        self.assertEqual((recorded.outcome, recorded.reason), ("recorded", "name_only"))
        self.assertEqual(recorded.name, NAME)
        self.assertEqual(recorded.engine, "claude-code")
        self.assertFalse(recorded.started)
        self.assertFalse(recorded.called)
        self.assertFalse(recorded.read_env)
        self.assertNotIn(URL, repr(recorded))
        self.assertNotIn(URL, repr(book))
        self.assertEqual(names(book), (NAME, KEY_NAME))
        self.assertEqual(show(book).reason, "value_hidden")
        self.assertEqual(show(book).name, NAME)
        hidden = show(book, "anthropic")
        self.assertEqual(hidden.name, KEY_NAME)
        self.assertEqual(hidden.reason, "value_hidden")
        self.assertTrue(matches(book, URL))
        self.assertFalse(matches(book, "from-the-env"))
        self.assertEqual(engine_of(book), "claude-code")
        chat = _record(book, actor="chat", base_url=OTHER, anthropic_key=TOKEN)
        self.assertEqual(chat.reason, "board_only")
        self.assertEqual(chat.name, NAME)
        self.assertNotIn(TOKEN, repr(chat))
        self.assertNotIn(OTHER, repr(chat))
        self.assertTrue(matches(book, URL))
        self.assertFalse(matches(book, OTHER))

    def test_a_second_record_keeps_the_first_url(self) -> None:
        book = Book()
        self.assertEqual(_record(book).reason, "name_only")
        again = _record(book, base_url=OTHER, engine="gsd", confirmed=True)
        self.assertEqual(again.reason, "name_only")
        self.assertEqual(engine_of(book), "claude-code")
        self.assertTrue(matches(book, URL))
        self.assertFalse(matches(book, OTHER))
        poisoned = _record(book, base_url=TOKEN)
        self.assertEqual(poisoned.reason, "name_only")
        self.assertNotIn(TOKEN, repr(poisoned))
        self.assertNotIn("abcd", repr(book))
        self.assertTrue(matches(book, URL))
        caller = _record(book, anthropic_key="pasted-key")
        self.assertEqual(caller.reason, "caller_value")
        self.assertEqual(caller.name, NAME)
        self.assertFalse(matches(book, "pasted-key"))

    def test_a_caller_key_is_not_stored(self) -> None:
        book = Book()
        for key in (TOKEN, HUNTER, "pasted-key", True, "   "):
            fresh = Book()
            refused = _record(fresh, anthropic_key=key)
            self.assertEqual(refused.reason, "credential" if key in {TOKEN, HUNTER} else "caller_value")
            self.assertEqual(names(fresh), ())
            self.assertNotIn("abcd", repr(refused))
            self.assertNotIn("hunter22", repr(refused))
            self.assertNotIn("pasted-key", repr(refused))
        supplied = _record(book, supplied=KEPT)
        self.assertEqual(supplied.reason, "caller_value")
        self.assertEqual(names(book), ())
        kept_key = _record(book, anthropic_key=KEPT)
        self.assertEqual(kept_key.reason, "name_only")
        self.assertTrue(matches(book, URL))
        self.assertFalse(matches(book, KEPT))
        kept_book = Book()
        self.assertEqual(_record(kept_book, base_url=KEPT).reason, "name_only")
        self.assertTrue(matches(kept_book, KEPT))
        self.assertNotIn(KEPT, repr(kept_book))

    def test_a_bad_url_or_the_other_engine_stores_nothing(self) -> None:
        bad = {
            "https://127.0.0.1/v1": "loopback",
            "https://127.1/v1": "loopback",
            "https://0x7f.0.0.1/v1": "loopback",
            "https://localhost/v1": "loopback",
            "https://[::1]/v1": "loopback",
            "https://169.254.1.1/v1": "link_local",
            "https://friday/v1": "core_closed",
            "https://metadata.google.internal/v1": "metadata",
            "https://user:secret@coding.example/v1": "url",
            "https://coding.example/v1?x=1": "url",
            "ftp://coding.example/v1": "url",
            "https://coding.example/v1 extra": "url",
            "https://coding.example/v1\n": "url",
            True: "url",
            TOKEN: "credential",
            HUNTER: "credential",
        }
        for base, reason in bad.items():
            book = Book()
            decision = _record(book, base_url=base)
            self.assertEqual(decision.reason, reason, base)
            self.assertEqual(names(book), ())
            self.assertNotIn("abcd", repr(decision))
            self.assertNotIn("hunter22", repr(decision))
        book = Book()
        self.assertEqual(_record(book, engine="gsd", base_url=URL).reason, "not_for_that_engine")
        self.assertEqual(names(book), ())
        for engine in ("Claude-Code", " claude-code", "", "claude", True, KEPT):
            fresh = Book()
            self.assertEqual(_record(fresh, engine=engine).reason, "engine", engine)
            self.assertEqual(names(fresh), ())
        loop = Book()
        self.assertEqual(_record(loop, engine="gsd", base_url="https://127.0.0.1/v1").reason, "loopback")
        self.assertEqual(names(loop), ())

    def test_use_does_not_call_and_the_ask_path_stays_put(self) -> None:
        book = Book()
        self.assertEqual(_record(book).reason, "name_only")
        used = use_plan(book, actor="board", text="run the job", confirmed=True)
        self.assertEqual(used.reason, "not_called")
        self.assertFalse(used.started)
        self.assertFalse(used.called)
        self.assertFalse(used.read_env)
        self.assertTrue(matches(book, URL))
        secret = use_plan(book, actor="board", text=TOKEN)
        self.assertEqual(secret.reason, "credential")
        self.assertEqual(secret.name, NAME)
        self.assertNotIn(TOKEN, repr(secret))
        self.assertTrue(matches(book, URL))
        chat = use_plan(book, actor="chat", text=HUNTER)
        self.assertEqual(chat.reason, "board_only")
        self.assertNotIn("hunter22", repr(chat))
        self.assertFalse(chat.called)
        source = inspect.getsource(plan)
        self.assertNotIn("os.environ", source)
        self.assertNotIn("import socket", source)
        self.assertNotIn("sqlite3", source)
        self.assertNotIn("psycopg", source)
        self.assertNotIn("urlopen", source)
        ask = Path("friday/ask.py").read_text(encoding="utf-8")
        self.assertNotIn("updates.plan", ask)
        self.assertNotIn("record_plan", ask)
        page = Path("board/server.js").read_text(encoding="utf-8")
        self.assertNotIn("CODING_PLAN", page)


if __name__ == "__main__":
    unittest.main()
