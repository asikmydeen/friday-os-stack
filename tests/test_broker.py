"""A site secret is recorded by name. The model is not given the value."""

from __future__ import annotations

import dataclasses
import os
import unittest
from pathlib import Path

from browser.broker import NAME, Book, hold, matches, names, record_site, show

KEPT = "The password is kept outside the machine"
SITE = "shop.example"
OTHER = "other.example"
MINT = "a" * 64
SECOND = "b" * 64
NOTIFY = "notify-token-value"
DOOR = "door-token-value"
MCP = "mcp-token-value"
CARD = "4111111111111111"


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


def _record(book: Book, site: object = SITE, **kwargs):
    fields = {"actor": "board", "site": site, "rng": Seq((MINT,))}
    fields.update(kwargs)
    return record_site(book, **fields)


class BrokerTests(unittest.TestCase):
    def test_the_board_records_the_name_and_chat_does_not(self) -> None:
        book = Book()
        for actor in ("chat", "friday", "model", "broker"):
            refused = _record(book, actor=actor, confirmed=True)
            self.assertEqual(refused.outcome, "refused")
            self.assertEqual(refused.reason, "board_only")
            self.assertEqual(refused.name, "")
            self.assertFalse(refused.started)
            self.assertFalse(refused.fetched)
            self.assertFalse(refused.sent)
            self.assertFalse(refused.approved)
            self.assertNotIn(MINT, repr(refused))
            self.assertNotIn(MINT, repr(book))
        self.assertEqual(names(book), ())
        self.assertFalse(matches(book, MINT))
        self.assertEqual(hold(book, "broker").reason, "unknown_secret")

        stored = _record(book, confirmed=True)
        self.assertEqual(stored.outcome, "recorded")
        self.assertEqual(stored.reason, "name_only")
        self.assertEqual(stored.name, NAME)
        self.assertEqual(stored.site, SITE)
        self.assertNotIn("value", dataclasses.asdict(stored))
        self.assertNotIn(MINT, repr(stored))
        self.assertNotIn(MINT, repr(book))
        self.assertEqual(repr(book), "Book()")
        self.assertTrue(matches(book, MINT))
        self.assertFalse(matches(book, SECOND))
        self.assertFalse(matches(book, ""))
        self.assertEqual(names(book), (NAME,))
        shown = show(book)
        self.assertEqual(shown.reason, "value_hidden")
        self.assertEqual(shown.name, NAME)
        self.assertEqual(shown.site, SITE)
        self.assertNotIn(MINT, repr(shown))
        self.assertFalse(shown.sent)

        for actor in ("chat", "friday"):
            again = _record(book, actor=actor, site=OTHER, supplied=CARD, confirmed=True)
            self.assertEqual(again.reason, "board_only")
            self.assertEqual(again.name, NAME)
            self.assertEqual(again.site, SITE)
            self.assertNotIn(CARD, repr(again))
            self.assertNotIn(CARD, repr(book))
        self.assertTrue(matches(book, MINT))
        self.assertFalse(matches(book, CARD))
        self.assertEqual(hold(book, "broker").site, SITE)

    def test_the_model_is_not_given_the_value(self) -> None:
        book = Book()
        stored = _record(book)
        self.assertEqual(stored.reason, "name_only")
        model = hold(book, "model")
        self.assertEqual(model.outcome, "withheld")
        self.assertEqual(model.reason, "model_sees_page")
        self.assertEqual(model.name, NAME)
        self.assertEqual(model.site, SITE)
        self.assertNotIn(MINT, repr(model))
        self.assertNotIn("value", dataclasses.asdict(model))
        self.assertFalse(model.sent)
        self.assertFalse(model.fetched)
        broker = hold(book, "broker")
        self.assertEqual(broker.outcome, "held")
        self.assertEqual(broker.reason, "for_the_site")
        self.assertEqual(broker.site, SITE)
        self.assertNotIn(MINT, repr(broker))
        self.assertEqual(hold(book, "page").reason, "unknown_party")

    def test_a_second_record_keeps_the_first_site_and_value(self) -> None:
        book = Book()
        rng = Seq((MINT, SECOND))
        first = record_site(book, actor="board", site="Shop.Example.", rng=rng)
        self.assertEqual(first.site, SITE)
        again = record_site(book, actor="board", site=OTHER, rng=rng, confirmed=True)
        self.assertEqual(again.reason, "name_only")
        self.assertEqual(again.site, SITE)
        self.assertEqual(rng.calls, 1)
        self.assertTrue(matches(book, MINT))
        self.assertFalse(matches(book, SECOND))
        trimmed = record_site(book, actor="board", site="  shop.example  ", rng=rng)
        self.assertEqual(trimmed.site, SITE)
        self.assertEqual(rng.calls, 1)
        leaked = "password is hunter22"
        kept = record_site(
            book,
            actor="board",
            site=OTHER,
            rng=Seq((leaked,)),
            supplied=leaked,
            confirmed=True,
        )
        self.assertEqual(kept.reason, "name_only")
        self.assertEqual(kept.site, SITE)
        self.assertNotIn("hunter22", repr(kept))
        self.assertNotIn("hunter22", repr(book))
        self.assertTrue(matches(book, MINT))
        self.assertFalse(matches(book, leaked))

    def test_a_caller_value_is_not_stored(self) -> None:
        book = Book()
        for supplied in (KEPT, "token=abcd", "password is hunter22", CARD, "   ", True):
            decision = _record(book, supplied=supplied, rng=Seq(("should-not-stick",)))
            if supplied in {"token=abcd", "password is hunter22", CARD}:
                self.assertEqual(decision.reason, "credential")
                self.assertEqual(decision.name, "")
                self.assertEqual(decision.site, "")
            else:
                self.assertEqual(decision.reason, "caller_value")
                self.assertEqual(decision.name, NAME)
            self.assertFalse(decision.started)
            self.assertFalse(decision.fetched)
            self.assertFalse(decision.sent)
            self.assertFalse(decision.approved)
            self.assertNotIn("should-not-stick", repr(decision))
            self.assertNotIn("should-not-stick", repr(book))
            self.assertNotIn("hunter22", repr(decision))
            self.assertNotIn("abcd", repr(decision))
            self.assertNotIn(CARD, repr(decision))
            self.assertFalse(matches(book, "should-not-stick"))
        self.assertEqual(names(book), ())
        self.assertEqual(show(book).reason, "unknown_secret")
        self.assertEqual(hold(book, "model").reason, "model_sees_page")
        self.assertEqual(hold(book, "model").name, "")
        stored = _record(book)
        self.assertEqual(stored.reason, "name_only")
        self.assertTrue(matches(book, MINT))

    def test_a_bad_site_stores_nothing(self) -> None:
        book = Book()
        pasted = "https://user:hunter22@shop.example/path"
        cases = (
            ("postgres", "core_closed"),
            ("Friday", "core_closed"),
            ("qdrant", "core_closed"),
            ("memory-mcp", "core_closed"),
            ("executor", "core_closed"),
            ("gateway", "core_closed"),
            ("169.254.169.254", "link_local"),
            ("fe80::1", "link_local"),
            ("127.0.0.1", "loopback"),
            ("127.1", "loopback"),
            ("127.0.1", "loopback"),
            ("2130706433", "loopback"),
            ("0177.0.0.1", "loopback"),
            ("0x7f.0.0.1", "loopback"),
            ("0x7f000001", "loopback"),
            ("::1", "loopback"),
            ("::ffff:127.0.0.1", "loopback"),
            ("localhost", "loopback"),
            ("0.0.0.0", "loopback"),
            ("board", "core_closed"),
            ("ollama", "core_closed"),
            ("1.2.3", "site"),
            ("metadata.google.internal", "metadata"),
            (pasted, "site"),
            ("shop.example:443", "site"),
            ("", "site"),
            ("   ", "site"),
            (KEPT, "site"),
            (7, "site"),
            (("shop.example", OTHER), "one_at_a_time"),
            ("token=abcd", "credential"),
            (CARD, "credential"),
        )
        for site, reason in cases:
            decision = _record(book, site=site, rng=Seq(("should-not-stick",)))
            self.assertEqual(decision.reason, reason, site)
            self.assertEqual(decision.site, "")
            self.assertFalse(decision.fetched)
            self.assertFalse(decision.sent)
            self.assertNotIn("hunter22", repr(decision))
            self.assertNotIn("should-not-stick", repr(decision))
            self.assertNotIn("should-not-stick", repr(book))
            self.assertNotIn(CARD, repr(decision))
            if reason == "credential":
                self.assertEqual(decision.name, "")
        self.assertEqual(names(book), ())
        stored = _record(book)
        self.assertEqual(stored.site, SITE)
        self.assertTrue(matches(book, MINT))

    def test_the_other_tokens_are_not_reused(self) -> None:
        book = Book()
        rng = Seq((NOTIFY, MINT))
        decision = record_site(
            book,
            actor="board",
            site=SITE,
            rng=rng,
            notify_token=NOTIFY,
        )
        self.assertEqual(decision.reason, "name_only")
        self.assertEqual(decision.site, SITE)
        self.assertNotIn(NOTIFY, repr(decision))
        self.assertNotIn(NOTIFY, repr(book))
        self.assertFalse(matches(book, NOTIFY))
        self.assertTrue(matches(book, MINT))
        self.assertNotIn("FRIDAY_NOTIFY_TOKEN", names(book))
        self.assertNotIn("DOOR_TOKEN", names(book))
        self.assertNotIn("MCP_TOKEN", names(book))

        empty = Book()
        both = Seq((DOOR, DOOR))
        refused = record_site(
            empty,
            actor="board",
            site=SITE,
            rng=both,
            door_token=DOOR,
            confirmed=True,
        )
        self.assertEqual(refused.reason, "not_minted")
        self.assertEqual(refused.name, NAME)
        self.assertEqual(refused.site, "")
        self.assertFalse(refused.started)
        self.assertNotIn(DOOR, repr(refused))
        self.assertEqual(names(empty), ())
        self.assertFalse(matches(empty, DOOR))

        separate = Book()
        drawn = Seq((MCP, SECOND))
        recorded = record_site(
            separate,
            actor="board",
            site=SITE,
            rng=drawn,
            mcp_token=MCP,
            notify_token=KEPT,
            door_token="",
        )
        self.assertEqual(recorded.reason, "name_only")
        self.assertNotIn(MCP, repr(recorded))
        self.assertNotIn(MCP, repr(separate))
        self.assertFalse(matches(separate, MCP))
        self.assertFalse(matches(separate, KEPT))
        self.assertTrue(matches(separate, SECOND))

        stuck = Book()
        same = Seq((MCP, MCP))
        blocked = record_site(stuck, actor="board", site=SITE, rng=same, mcp_token=MCP)
        self.assertEqual(blocked.reason, "not_minted")
        self.assertEqual(names(stuck), ())
        self.assertFalse(matches(stuck, MCP))

    def test_a_credential_shaped_mint_is_not_stored(self) -> None:
        book = Book()
        leaked = "password is hunter22"
        refused = record_site(book, actor="board", site=SITE, rng=Seq((leaked,)))
        self.assertEqual(refused.reason, "not_minted")
        self.assertEqual(refused.name, NAME)
        self.assertEqual(refused.site, "")
        self.assertNotIn("hunter22", repr(refused))
        self.assertNotIn("hunter22", repr(book))
        self.assertEqual(names(book), ())
        self.assertFalse(matches(book, leaked))

        shaped = "sk-" + ("a" * 20)
        again = record_site(book, actor="board", site=SITE, rng=Seq((shaped, "token=abcd")))
        self.assertEqual(again.reason, "not_minted")
        self.assertNotIn(shaped, repr(again))
        self.assertNotIn("abcd", repr(again))
        self.assertEqual(names(book), ())

        upper = "AB" * 32
        folded = record_site(book, actor="board", site=SITE, rng=Seq((upper,)))
        self.assertEqual(folded.reason, "not_minted")
        self.assertNotIn(upper, repr(folded))
        self.assertNotIn(upper, repr(book))

        card = record_site(book, actor="board", site=SITE, rng=Seq((CARD,)))
        self.assertEqual(card.reason, "not_minted")
        self.assertNotIn(CARD, repr(card))
        self.assertNotIn(CARD, repr(book))

        generated = "c" * 64
        decision = record_site(book, actor="board", site=SITE, rng=Seq((generated,)))
        self.assertEqual(decision.reason, "name_only")
        self.assertEqual(decision.site, SITE)
        self.assertNotIn(generated, repr(decision))
        self.assertNotIn(generated, repr(book))
        self.assertTrue(matches(book, generated))
        self.assertFalse(decision.approved)

        sentence = Book()
        kept = record_site(sentence, actor="board", site=SITE, rng=Seq((KEPT,)))
        self.assertEqual(kept.reason, "name_only")
        self.assertNotIn(KEPT, repr(sentence))
        self.assertTrue(matches(sentence, KEPT))
        self.assertFalse(kept.started)
        self.assertFalse(kept.fetched)
        self.assertFalse(kept.sent)
        model = hold(sentence, "model")
        self.assertEqual(model.reason, "model_sees_page")
        self.assertNotIn(KEPT, repr(model))

    def test_a_failed_mint_and_the_environment_stay_put(self) -> None:
        book = Book()
        previous = os.environ.get(NAME)
        os.environ[NAME] = "preset-value"
        try:
            boom = record_site(book, actor="board", site=SITE, rng=Boom())
            self.assertEqual(boom.reason, "not_minted")
            self.assertNotIn("abcd", repr(boom))
            self.assertNotIn("abcd", repr(book))
            self.assertEqual(names(book), ())
            blank = record_site(book, actor="board", site=SITE, rng=Seq(("",)))
            self.assertEqual(blank.reason, "not_minted")
            missing = record_site(book, actor="board", site=SITE, rng=None)
            self.assertEqual(missing.reason, "not_minted")
            broken = record_site(book, actor="board", site=SITE, rng=Seq(("ab\n" + "c" * 32,)))
            self.assertEqual(broken.reason, "not_minted")
            self.assertEqual(os.environ[NAME], "preset-value")
            self.assertFalse(matches(book, "preset-value"))
            self.assertEqual(names(book), ())
            self.assertEqual(hold(book, "broker").reason, "unknown_secret")
        finally:
            if previous is None:
                os.environ.pop(NAME, None)
            else:
                os.environ[NAME] = previous

    def test_ask_does_not_call_this_module(self) -> None:
        ask = Path("friday/ask.py").read_text(encoding="utf-8")
        self.assertNotIn("browser.broker", ask)
        self.assertNotIn("record_site", ask)
        server = Path("browser/server.py").read_text(encoding="utf-8")
        self.assertNotIn("browser.broker", server)
        self.assertNotIn("record_site", server)
        session = Path("browser/session.py").read_text(encoding="utf-8")
        self.assertNotIn("browser.broker", session)
        self.assertNotIn("record_site", session)
        page = Path("board/server.js").read_text(encoding="utf-8")
        self.assertNotIn("SITE_CREDENTIAL", page)
        self.assertNotIn("browser/broker", page)
        module = Path("browser/broker.py").read_text(encoding="utf-8")
        self.assertNotIn("os.environ", module)
        self.assertNotIn("open(", module)
        self.assertNotIn("import socket", module)
        self.assertNotIn("urlopen", module)


if __name__ == "__main__":
    unittest.main()
