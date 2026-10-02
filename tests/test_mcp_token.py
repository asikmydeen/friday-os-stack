"""The inbound harness secret is recorded by name. The value stays in the process."""

from __future__ import annotations

import dataclasses
import os
import unittest
from pathlib import Path

from mcpbus.token import NAME, Book, matches, names, record_token, show

KEPT = "The password is kept outside the machine"
MINT = "ab" * 32
OTHER = "cd" * 32
NOTIFY = "ef" * 32
DOOR = "12" * 32


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
    fields = {"actor": "board", "rng": Seq((MINT,))}
    fields.update(kwargs)
    return record_token(book, **fields)


class McpTokenTests(unittest.TestCase):
    def test_the_board_records_the_name_and_chat_does_not(self) -> None:
        book = Book()
        for actor in ("chat", "friday", "harness", ""):
            refused = _record(book, actor=actor, confirmed=True)
            self.assertEqual(refused.reason, "board_only")
            self.assertEqual(refused.name, "")
            self.assertFalse(refused.listening)
            self.assertFalse(refused.approved)
            self.assertNotIn(MINT, repr(refused))
            self.assertNotIn(MINT, repr(book))
        self.assertEqual(names(book), ())
        self.assertFalse(matches(book, MINT))

        stored = _record(book, confirmed=True)
        self.assertEqual(stored.outcome, "recorded")
        self.assertEqual(stored.reason, "name_only")
        self.assertEqual(stored.name, NAME)
        self.assertFalse(stored.listening)
        self.assertFalse(stored.approved)
        self.assertNotIn("value", dataclasses.asdict(stored))
        self.assertNotIn(MINT, repr(stored))
        self.assertNotIn(MINT, repr(book))
        self.assertEqual(repr(book), "Book()")
        self.assertTrue(matches(book, MINT))
        self.assertFalse(matches(book, OTHER))
        self.assertFalse(matches(book, ""))
        self.assertFalse(matches(book, None))
        self.assertEqual(names(book), (NAME,))
        shown = show(book)
        self.assertEqual(shown.reason, "value_hidden")
        self.assertEqual(shown.name, NAME)
        self.assertNotIn(MINT, repr(shown))

        for actor in ("chat", "friday"):
            again = _record(book, actor=actor, rng=Seq(("should-not-stick",)), confirmed=True)
            self.assertEqual(again.reason, "board_only")
            self.assertEqual(again.name, NAME)
            self.assertFalse(again.listening)
            self.assertFalse(again.approved)
        self.assertTrue(matches(book, MINT))
        self.assertFalse(matches(book, "should-not-stick"))

    def test_a_second_record_keeps_the_first_value(self) -> None:
        book = Book()
        rng = Seq((MINT, OTHER))
        first = record_token(book, actor="board", rng=rng)
        self.assertEqual(first.reason, "name_only")
        again = record_token(book, actor="board", rng=rng, confirmed=True)
        self.assertEqual(again.reason, "name_only")
        self.assertEqual(rng.calls, 1)
        self.assertTrue(matches(book, MINT))
        self.assertFalse(matches(book, OTHER))

        pasted = record_token(book, actor="board", rng=Seq(("pasted-value",)), supplied="pasted-value")
        self.assertEqual(pasted.reason, "caller_value")
        self.assertEqual(pasted.name, NAME)
        self.assertTrue(matches(book, MINT))
        self.assertFalse(matches(book, "pasted-value"))
        self.assertNotIn("pasted-value", repr(pasted))
        self.assertNotIn("pasted-value", repr(book))

        leaked = "password is hunter22"
        kept = record_token(book, actor="board", rng=Seq((leaked,)), supplied=leaked, confirmed=True)
        self.assertEqual(kept.reason, "name_only")
        self.assertEqual(kept.name, NAME)
        self.assertNotIn("hunter22", repr(kept))
        self.assertNotIn("hunter22", repr(book))
        self.assertTrue(matches(book, MINT))
        self.assertFalse(matches(book, leaked))

    def test_a_caller_value_is_not_stored(self) -> None:
        book = Book()
        for supplied in (KEPT, "token=abcd", "password is hunter22", "   ", True):
            decision = _record(book, supplied=supplied, rng=Seq(("should-not-stick",)))
            if supplied in {"token=abcd", "password is hunter22"}:
                self.assertEqual(decision.reason, "credential")
                self.assertEqual(decision.name, "")
            else:
                self.assertEqual(decision.reason, "caller_value")
                self.assertEqual(decision.name, NAME)
            self.assertFalse(decision.listening)
            self.assertFalse(decision.approved)
            self.assertNotIn("should-not-stick", repr(decision))
            self.assertNotIn("should-not-stick", repr(book))
            self.assertNotIn("hunter22", repr(decision))
            self.assertNotIn("abcd", repr(decision))
            self.assertFalse(matches(book, "should-not-stick"))
        self.assertEqual(names(book), ())
        self.assertEqual(show(book).reason, "unknown_secret")
        stored = _record(book)
        self.assertEqual(stored.reason, "name_only")
        self.assertTrue(matches(book, MINT))

    def test_the_notify_token_and_the_door_token_are_not_reused(self) -> None:
        book = Book()
        rng = Seq((NOTIFY, OTHER))
        decision = record_token(book, actor="board", rng=rng, notify_token=NOTIFY)
        self.assertEqual(decision.reason, "name_only")
        self.assertNotIn(NOTIFY, repr(decision))
        self.assertNotIn(NOTIFY, repr(book))
        self.assertFalse(matches(book, NOTIFY))
        self.assertTrue(matches(book, OTHER))
        self.assertNotIn("FRIDAY_NOTIFY_TOKEN", names(book))
        self.assertNotIn("DOOR_TOKEN", names(book))

        empty = Book()
        both = Seq((NOTIFY, NOTIFY))
        refused = record_token(empty, actor="board", rng=both, notify_token=NOTIFY, confirmed=True)
        self.assertEqual(refused.reason, "not_minted")
        self.assertEqual(refused.name, NAME)
        self.assertFalse(refused.listening)
        self.assertNotIn(NOTIFY, repr(refused))
        self.assertEqual(names(empty), ())
        self.assertFalse(matches(empty, NOTIFY))

        separate = Book()
        drawn = Seq((DOOR, MINT))
        recorded = record_token(separate, actor="board", rng=drawn, door_token=DOOR, notify_token=KEPT)
        self.assertEqual(recorded.reason, "name_only")
        self.assertNotIn(DOOR, repr(recorded))
        self.assertNotIn(DOOR, repr(separate))
        self.assertFalse(matches(separate, DOOR))
        self.assertFalse(matches(separate, KEPT))
        self.assertTrue(matches(separate, MINT))

        stuck = Book()
        same = Seq((DOOR, DOOR))
        blocked = record_token(stuck, actor="board", rng=same, door_token=DOOR)
        self.assertEqual(blocked.reason, "not_minted")
        self.assertEqual(names(stuck), ())
        self.assertFalse(matches(stuck, DOOR))

    def test_a_credential_shaped_mint_is_not_stored(self) -> None:
        book = Book()
        leaked = "password is hunter22"
        refused = record_token(book, actor="board", rng=Seq((leaked,)))
        self.assertEqual(refused.reason, "not_minted")
        self.assertEqual(refused.name, NAME)
        self.assertNotIn("hunter22", repr(refused))
        self.assertNotIn("hunter22", repr(book))
        self.assertEqual(names(book), ())
        self.assertFalse(matches(book, leaked))

        shaped = "sk-" + ("a" * 20)
        again = record_token(book, actor="board", rng=Seq((shaped, "token=abcd")))
        self.assertEqual(again.reason, "not_minted")
        self.assertNotIn(shaped, repr(again))
        self.assertNotIn("abcd", repr(again))
        self.assertEqual(names(book), ())

        upper = "AB" * 32
        folded = record_token(book, actor="board", rng=Seq((upper,)))
        self.assertEqual(folded.reason, "not_minted")
        self.assertNotIn(upper, repr(folded))
        self.assertNotIn(upper, repr(book))

        generated = "a" * 64
        decision = record_token(book, actor="board", rng=Seq((generated,)))
        self.assertEqual(decision.reason, "name_only")
        self.assertNotIn(generated, repr(decision))
        self.assertNotIn(generated, repr(book))
        self.assertTrue(matches(book, generated))

        sentence = Book()
        kept = record_token(sentence, actor="board", rng=Seq((KEPT,)))
        self.assertEqual(kept.reason, "name_only")
        self.assertNotIn(KEPT, repr(sentence))
        self.assertTrue(matches(sentence, KEPT))
        self.assertFalse(kept.listening)
        self.assertFalse(kept.approved)

    def test_a_failed_mint_and_the_environment_stay_put(self) -> None:
        book = Book()
        previous = os.environ.get(NAME)
        os.environ[NAME] = "preset-value"
        try:
            boom = record_token(book, actor="board", rng=Boom())
            self.assertEqual(boom.reason, "not_minted")
            self.assertNotIn("abcd", repr(boom))
            self.assertNotIn("abcd", repr(book))
            self.assertEqual(names(book), ())
            blank = record_token(book, actor="board", rng=Seq(("",)))
            self.assertEqual(blank.reason, "not_minted")
            missing = record_token(book, actor="board", rng=None)
            self.assertEqual(missing.reason, "not_minted")
            broken = record_token(book, actor="board", rng=Seq(("ab\n" + "c" * 32,)))
            self.assertEqual(broken.reason, "not_minted")
            self.assertEqual(os.environ[NAME], "preset-value")
            self.assertFalse(matches(book, "preset-value"))
            self.assertEqual(names(book), ())
        finally:
            if previous is None:
                os.environ.pop(NAME, None)
            else:
                os.environ[NAME] = previous

    def test_ask_does_not_call_this_module(self) -> None:
        ask = Path("friday/ask.py").read_text(encoding="utf-8")
        self.assertNotIn("mcpbus.token", ask)
        self.assertNotIn("record_token", ask)
        server = Path("mcpbus/server.py").read_text(encoding="utf-8")
        self.assertNotIn("mcpbus.token", server)
        self.assertNotIn("record_token", server)
        page = Path("board/server.js").read_text(encoding="utf-8")
        self.assertNotIn("MCP_TOKEN", page)
        self.assertNotIn("mcpbus/token", page)
        module = Path("mcpbus/token.py").read_text(encoding="utf-8")
        self.assertNotIn("os.environ", module)
        self.assertNotIn("open(", module)
        self.assertNotIn("import socket", module)


if __name__ == "__main__":
    unittest.main()
