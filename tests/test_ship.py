"""ship-mcp is recorded by name. The value stays in the process."""

from __future__ import annotations

import inspect
import os
import unittest
from pathlib import Path

import updates.ship as ship
from updates.ship import (
    TOKEN_NAME,
    Book,
    links,
    matches,
    names,
    record_surface,
    show,
    submit,
    tasks,
    template_of,
)

KEPT = "The password is kept outside the machine"
TOKEN = "token=abcd"
HUNTER = "password is hunter22"
HEX = "a" * 64
OTHER = "b" * 64
URL = "https://coder.example"


class Seq:
    def __init__(self, values: tuple[str, ...]) -> None:
        self.values = list(values)
        self.calls = 0

    def token_hex(self, nbytes: int) -> str:
        if nbytes != 32:
            raise ValueError("nbytes")
        self.calls += 1
        if not self.values:
            raise IndexError("empty")
        return self.values.pop(0)


class Boom:
    def token_hex(self, nbytes: int) -> str:
        del nbytes
        raise RuntimeError("token=abcd")


def _record(book: Book, **kwargs):
    fields = {
        "actor": "board",
        "enabled": True,
        "coder_url": URL,
        "coder_token": "supplied",
        "rng": Seq((HEX,)),
    }
    fields.update(kwargs)
    return record_surface(book, **fields)


class ShipTests(unittest.TestCase):
    def test_the_profile_stays_off_without_a_coder_url(self) -> None:
        book = Book()
        off = _record(book, enabled=False, confirmed=True)
        self.assertEqual((off.outcome, off.reason), ("off", "profile_off"))
        self.assertFalse(off.started)
        self.assertFalse(off.created)
        self.assertFalse(off.called)
        self.assertEqual(names(book), ())
        self.assertEqual(links(book), ())
        self.assertEqual(_record(book, enabled="true").reason, "profile_off")
        self.assertEqual(_record(book, coder_url="").reason, "no_coder_url")
        self.assertEqual(_record(book, coder_url="   ").reason, "no_coder_url")
        self.assertEqual(_record(book, coder_token=None).reason, "token_required")
        self.assertEqual(_record(book, coder_token="").reason, "token_required")
        self.assertEqual(names(book), ())

    def test_the_board_records_the_name_and_chat_does_not(self) -> None:
        book = Book()
        for actor in ("chat", "friday", "adapter"):
            refused = _record(book, actor=actor, confirmed=True)
            self.assertEqual(refused.reason, "board_only")
            self.assertEqual(refused.name, "")
            self.assertFalse(refused.started)
        self.assertEqual(names(book), ())
        recorded = _record(book, confirmed=True)
        self.assertEqual((recorded.outcome, recorded.reason), ("recorded", "name_only"))
        self.assertEqual(recorded.name, TOKEN_NAME)
        self.assertFalse(recorded.started)
        self.assertFalse(recorded.created)
        self.assertFalse(recorded.called)
        self.assertNotIn(HEX, repr(recorded))
        self.assertNotIn(HEX, repr(book))
        self.assertEqual(names(book), (TOKEN_NAME, "GITHUB_TOKEN"))
        self.assertEqual(show(book).reason, "value_hidden")
        self.assertEqual(show(book, "github").name, "GITHUB_TOKEN")
        self.assertEqual(show(book, "github").reason, "value_hidden")
        self.assertTrue(matches(book, HEX))
        self.assertFalse(matches(book, "supplied"))
        self.assertEqual(template_of(book), "taskrunner-universal")
        self.assertEqual(links(book), ("coder",))
        self.assertEqual(tasks(book), ())
        chat = _record(book, actor="chat", coder_token=TOKEN)
        self.assertEqual(chat.reason, "board_only")
        self.assertEqual(chat.name, TOKEN_NAME)
        self.assertNotIn(TOKEN, repr(chat))
        self.assertTrue(matches(book, HEX))

    def test_a_caller_value_is_not_stored_and_the_second_record_keeps_the_first(self) -> None:
        book = Book()
        for supplied in (KEPT, TOKEN, "   ", True):
            refused = _record(book, supplied=supplied)
            self.assertEqual(refused.reason, "credential" if supplied == TOKEN else "caller_value")
            self.assertNotIn(TOKEN, repr(refused))
            self.assertNotIn(HEX, repr(book))
        self.assertEqual(names(book), ())
        github = _record(book, github_token="gh-value")
        self.assertEqual(github.reason, "caller_value")
        self.assertNotIn("gh-value", repr(github))
        self.assertNotIn("gh-value", repr(book))
        self.assertEqual(names(book), ())

        recorded = _record(book, template="custom-template")
        self.assertEqual(recorded.reason, "name_only")
        self.assertEqual(template_of(book), "custom-template")
        again = _record(book, rng=Seq((OTHER,)), template="other-template", coder_url="https://other.example")
        self.assertEqual(again.reason, "name_only")
        self.assertTrue(matches(book, HEX))
        self.assertFalse(matches(book, OTHER))
        self.assertEqual(template_of(book), "custom-template")
        self.assertEqual(links(book), ("coder",))
        poisoned = _record(book, coder_token=TOKEN, rng=Seq((OTHER,)))
        self.assertEqual(poisoned.reason, "name_only")
        self.assertNotIn(TOKEN, repr(poisoned))
        self.assertNotIn(TOKEN, repr(book))
        self.assertTrue(matches(book, HEX))

    def test_a_credential_shaped_draw_or_url_is_not_stored(self) -> None:
        book = Book()
        leaked = _record(book, coder_url=TOKEN)
        self.assertEqual(leaked.reason, "credential")
        self.assertEqual(leaked.name, "")
        self.assertNotIn(TOKEN, repr(leaked))
        self.assertNotIn(TOKEN, repr(book))
        self.assertEqual(links(book), ())
        hunter = _record(book, coder_token=HUNTER)
        self.assertEqual(hunter.reason, "credential")
        self.assertNotIn("hunter22", repr(hunter))
        self.assertEqual(names(book), ())
        shaped = _record(book, template=TOKEN)
        self.assertEqual(shaped.reason, "credential")
        self.assertEqual(template_of(book), "")
        bad = _record(book, rng=Seq((HUNTER, TOKEN)))
        self.assertEqual(bad.reason, "not_minted")
        self.assertNotIn("hunter22", repr(bad))
        self.assertNotIn("abcd", repr(bad))
        self.assertEqual(names(book), ())
        self.assertFalse(matches(book, HUNTER))

        kept_url = _record(book, coder_url=KEPT, rng=Seq((KEPT,)))
        self.assertEqual(kept_url.reason, "name_only")
        self.assertEqual(links(book), ("coder",))
        self.assertTrue(matches(book, KEPT))
        self.assertNotIn(KEPT, repr(kept_url))
        sentence = Book()
        named = _record(sentence, template=KEPT, rng=Seq((HEX,)))
        self.assertEqual(named.reason, "name_only")
        self.assertEqual(template_of(sentence), KEPT)
        self.assertTrue(matches(sentence, HEX))

    def test_the_mint_is_not_the_notify_token_or_the_coder_token(self) -> None:
        book = Book()
        shared = _record(book, rng=Seq((HEX, OTHER)), notify_token=HEX, coder_token="supplied")
        self.assertEqual(shared.reason, "name_only")
        self.assertTrue(matches(book, OTHER))
        self.assertFalse(matches(book, HEX))
        stuck = Book()
        refused = _record(stuck, rng=Seq((HEX, HEX)), notify_token=HEX)
        self.assertEqual(refused.reason, "not_minted")
        self.assertEqual(names(stuck), ())
        coder = Book()
        distinct = _record(coder, rng=Seq(("supplied", OTHER)), coder_token="supplied")
        self.assertEqual(distinct.reason, "name_only")
        self.assertTrue(matches(coder, OTHER))
        self.assertFalse(matches(coder, "supplied"))

    def test_submit_does_not_start_taskrunner_or_call_coder(self) -> None:
        book = Book()
        missing = submit(book, actor="board", task="open a pull request", confirmed=True)
        self.assertEqual(missing.reason, "not_recorded")
        self.assertFalse(missing.started)
        self.assertFalse(missing.created)
        self.assertFalse(missing.called)
        _record(book)
        chat = submit(book, actor="chat", task=KEPT, confirmed=True)
        self.assertEqual(chat.reason, "not_started")
        self.assertFalse(chat.created)
        self.assertFalse(chat.called)
        self.assertEqual(tasks(book), ())
        secret = submit(book, actor="board", task=TOKEN)
        self.assertEqual(secret.reason, "credential")
        self.assertNotIn(TOKEN, repr(secret))
        self.assertEqual(tasks(book), ())
        waiting = submit(book, actor="board", task=KEPT, confirmed=True)
        self.assertEqual(waiting.reason, "not_started")
        self.assertFalse(waiting.started)
        self.assertFalse(waiting.created)
        self.assertFalse(waiting.called)
        self.assertEqual(tasks(book), (KEPT,))
        again = submit(book, actor="board", task="a different task")
        self.assertEqual(again.reason, "not_started")
        self.assertEqual(tasks(book), (KEPT,))
        poisoned = submit(book, actor="board", task=HUNTER)
        self.assertEqual(poisoned.reason, "not_started")
        self.assertNotIn("hunter22", repr(poisoned))
        self.assertEqual(tasks(book), (KEPT,))

    def test_the_environment_and_the_ask_path_stay_put(self) -> None:
        book = Book()
        previous = os.environ.get(TOKEN_NAME)
        os.environ[TOKEN_NAME] = "preset-value"
        try:
            boom = _record(book, rng=Boom())
            self.assertEqual(boom.reason, "not_minted")
            self.assertNotIn("abcd", repr(boom))
            self.assertEqual(names(book), ())
            self.assertEqual(os.environ[TOKEN_NAME], "preset-value")
            self.assertFalse(matches(book, "preset-value"))
            recorded = _record(book)
            self.assertEqual(os.environ[TOKEN_NAME], "preset-value")
            self.assertFalse(matches(book, "preset-value"))
            self.assertTrue(matches(book, HEX))
        finally:
            if previous is None:
                os.environ.pop(TOKEN_NAME, None)
            else:
                os.environ[TOKEN_NAME] = previous
        source = inspect.getsource(ship)
        self.assertNotIn("os.environ", source)
        self.assertNotIn("import socket", source)
        self.assertNotIn("psycopg", source)
        self.assertNotIn("sqlite3", source)
        self.assertNotIn("urllib", source)
        ask = Path("friday/ask.py").read_text(encoding="utf-8")
        self.assertNotIn("updates.ship", ask)
        self.assertNotIn("record_surface", ask)
        page = Path("board/server.js").read_text(encoding="utf-8")
        self.assertNotIn("SHIP_MCP", page)
        self.assertNotIn("updates/ship", page)


if __name__ == "__main__":
    unittest.main()
