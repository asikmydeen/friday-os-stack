"""A webhook secret is recorded by name. The value stays in the process."""

from __future__ import annotations

import dataclasses
import os
import unittest
from pathlib import Path

from webhooks.secret import Book, matches, names, register, show

KEPT = "The password is kept outside the machine"
MINT = "minted-jellyfin-value"
OTHER = "minted-radarr-value"
THIRD = "minted-sonarr-value"
NOTIFY = "notify-token-value"


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


def _register(book: Book, app: str = "jellyfin", **kwargs):
    fields = {"actor": "board", "rng": Seq((MINT,))}
    fields.update(kwargs)
    return register(book, app, **fields)


class WebhookSecretTests(unittest.TestCase):
    def test_the_board_records_the_name_and_chat_does_not(self) -> None:
        book = Book()
        for actor in ("chat", "friday", "adapter"):
            refused = _register(book, actor=actor, confirmed=True)
            self.assertEqual(refused.reason, "board_only")
            self.assertEqual(refused.name, "WEBHOOK_SECRET_JELLYFIN")
            self.assertNotIn(MINT, repr(refused))
            self.assertNotIn(MINT, repr(book))
        self.assertEqual(names(book), ())
        self.assertFalse(matches(book, "jellyfin", MINT))

        stored = _register(book, confirmed=True)
        self.assertEqual(stored.outcome, "recorded")
        self.assertEqual(stored.reason, "name_only")
        self.assertEqual(stored.name, "WEBHOOK_SECRET_JELLYFIN")
        self.assertNotIn("value", dataclasses.asdict(stored))
        self.assertNotIn(MINT, repr(stored))
        self.assertNotIn(MINT, repr(book))
        self.assertEqual(repr(book), "Book()")
        self.assertTrue(matches(book, "jellyfin", MINT))
        self.assertFalse(matches(book, "jellyfin", OTHER))
        self.assertFalse(matches(book, "jellyfin", ""))
        self.assertEqual(names(book), ("WEBHOOK_SECRET_JELLYFIN",))
        shown = show(book, "jellyfin")
        self.assertEqual(shown.reason, "value_hidden")
        self.assertEqual(shown.name, "WEBHOOK_SECRET_JELLYFIN")
        self.assertNotIn(MINT, repr(shown))

    def test_a_second_record_keeps_the_first_value(self) -> None:
        book = Book()
        rng = Seq((MINT, OTHER))
        first = register(book, "jellyfin", actor="board", rng=rng)
        self.assertEqual(first.reason, "name_only")
        again = register(book, "jellyfin", actor="board", rng=rng, confirmed=True)
        self.assertEqual(again.reason, "name_only")
        self.assertEqual(rng.calls, 1)
        self.assertTrue(matches(book, "jellyfin", MINT))
        self.assertFalse(matches(book, "jellyfin", OTHER))
        chat = register(book, "jellyfin", actor="chat", rng=Seq(("nope",)), confirmed=True)
        self.assertEqual(chat.reason, "board_only")
        self.assertTrue(matches(book, "jellyfin", MINT))

    def test_each_app_gets_its_own_secret(self) -> None:
        book = Book()
        rng = Seq((MINT, OTHER, THIRD))
        for app, value, label in (
            ("jellyfin", MINT, "WEBHOOK_SECRET_JELLYFIN"),
            ("radarr", OTHER, "WEBHOOK_SECRET_RADARR"),
            ("sonarr", THIRD, "WEBHOOK_SECRET_SONARR"),
        ):
            decision = register(book, app, actor="board", rng=rng)
            self.assertEqual(decision.name, label)
            self.assertNotIn(value, repr(decision))
            self.assertTrue(matches(book, app, value))
        self.assertEqual(
            names(book),
            ("WEBHOOK_SECRET_JELLYFIN", "WEBHOOK_SECRET_RADARR", "WEBHOOK_SECRET_SONARR"),
        )
        self.assertFalse(matches(book, "radarr", MINT))
        self.assertNotIn("FRIDAY_NOTIFY_TOKEN", names(book))
        self.assertNotIn("MEMORY_TOKEN", names(book))
        self.assertNotIn("QDRANT_API_KEY", names(book))

    def test_other_apps_and_a_caller_value_store_nothing(self) -> None:
        book = Book()
        stored = _register(book)
        self.assertTrue(matches(book, "jellyfin", MINT))
        for app in (
            "plex",
            "prowlarr",
            "qbittorrent",
            "friday",
            "postgres",
            "qdrant",
            "memory-mcp",
            "taskrunner",
            "Jellyfin",
            "",
        ):
            decision = _register(book, app, rng=Seq(("should-not-stick",)))
            self.assertEqual(decision.reason, "not_a_webhook_app")
            self.assertEqual(decision.name, "")
            self.assertFalse(matches(book, app, "should-not-stick"))
        self.assertEqual(register(book, None, actor="board", rng=Seq(("x",))).reason, "not_a_webhook_app")
        for supplied in (KEPT, "token=abcd", "   ", True):
            decision = _register(book, "radarr", supplied=supplied, rng=Seq(("should-not-stick",)))
            self.assertEqual(decision.reason, "caller_value")
            self.assertEqual(decision.name, "WEBHOOK_SECRET_RADARR")
            self.assertNotIn("should-not-stick", repr(decision))
            self.assertNotIn(str(supplied), repr(decision))
            self.assertNotIn(str(supplied), repr(book))
            self.assertFalse(matches(book, "radarr", "should-not-stick"))
        self.assertEqual(names(book), ("WEBHOOK_SECRET_JELLYFIN",))
        self.assertTrue(matches(book, "jellyfin", MINT))
        self.assertEqual(show(book, "radarr").reason, "unknown_secret")
        self.assertEqual(show(book, "plex").reason, "unknown_secret")

    def test_the_notify_token_is_not_the_webhook_secret(self) -> None:
        book = Book()
        rng = Seq((NOTIFY, OTHER))
        decision = register(book, "jellyfin", actor="board", rng=rng, notify_token=NOTIFY)
        self.assertEqual(decision.reason, "name_only")
        self.assertNotIn(NOTIFY, repr(decision))
        self.assertNotIn(NOTIFY, repr(book))
        self.assertNotIn(OTHER, repr(decision))
        self.assertFalse(matches(book, "jellyfin", NOTIFY))
        self.assertTrue(matches(book, "jellyfin", OTHER))

        empty = Book()
        both = Seq((NOTIFY, NOTIFY))
        refused = register(empty, "sonarr", actor="board", rng=both, notify_token=NOTIFY, confirmed=True)
        self.assertEqual(refused.reason, "not_minted")
        self.assertEqual(refused.name, "WEBHOOK_SECRET_SONARR")
        self.assertNotIn(NOTIFY, repr(refused))
        self.assertEqual(names(empty), ())
        self.assertFalse(matches(empty, "sonarr", NOTIFY))

        sentence = Book()
        kept = register(
            sentence,
            "radarr",
            actor="board",
            rng=Seq((OTHER,)),
            notify_token=KEPT,
        )
        self.assertEqual(kept.reason, "name_only")
        self.assertNotIn(KEPT, repr(sentence))
        self.assertTrue(matches(sentence, "radarr", OTHER))
        self.assertFalse(matches(sentence, "radarr", KEPT))

    def test_radarr_and_sonarr_do_not_share_a_secret(self) -> None:
        book = Book()
        rng = Seq((MINT, MINT, OTHER))
        first = register(book, "radarr", actor="board", rng=rng)
        self.assertEqual(first.reason, "name_only")
        shared = register(book, "sonarr", actor="board", rng=rng)
        self.assertEqual(shared.reason, "name_only")
        self.assertEqual(rng.calls, 3)
        self.assertTrue(matches(book, "radarr", MINT))
        self.assertTrue(matches(book, "sonarr", OTHER))
        self.assertFalse(matches(book, "sonarr", MINT))

        stuck = Book()
        both = Seq((MINT, MINT))
        register(stuck, "radarr", actor="board", rng=Seq((MINT,)))
        refused = register(stuck, "sonarr", actor="board", rng=both)
        self.assertEqual(refused.reason, "not_minted")
        self.assertEqual(refused.name, "WEBHOOK_SECRET_SONARR")
        self.assertNotIn(MINT, repr(refused))
        self.assertEqual(names(stuck), ("WEBHOOK_SECRET_RADARR",))
        self.assertTrue(matches(stuck, "radarr", MINT))
        self.assertFalse(matches(stuck, "sonarr", MINT))

        crossed = Book()
        same = Seq((MINT, MINT))
        register(crossed, "radarr", actor="board", rng=same)
        jellyfin = register(crossed, "jellyfin", actor="board", rng=Seq((MINT,)))
        self.assertEqual(jellyfin.reason, "name_only")
        self.assertTrue(matches(crossed, "jellyfin", MINT))
        self.assertTrue(matches(crossed, "radarr", MINT))

    def test_a_credential_shaped_mint_is_not_stored(self) -> None:
        book = Book()
        leaked = "password is hunter22"
        refused = register(book, "jellyfin", actor="board", rng=Seq((leaked,)))
        self.assertEqual(refused.reason, "not_minted")
        self.assertNotIn("hunter22", repr(refused))
        self.assertNotIn("hunter22", repr(book))
        self.assertEqual(names(book), ())
        self.assertFalse(matches(book, "jellyfin", leaked))

        shaped = "sk-" + ("a" * 20)
        again = register(book, "radarr", actor="board", rng=Seq((shaped, "token=abcd")))
        self.assertEqual(again.reason, "not_minted")
        self.assertNotIn(shaped, repr(again))
        self.assertNotIn("abcd", repr(again))
        self.assertEqual(names(book), ())

        generated = "a" * 64
        kept = "The password is kept outside the machine"
        decision = register(book, "sonarr", actor="board", rng=Seq((generated,)))
        self.assertEqual(decision.reason, "name_only")
        self.assertNotIn(generated, repr(decision))
        self.assertNotIn(generated, repr(book))
        self.assertTrue(matches(book, "sonarr", generated))
        sentence = register(book, "jellyfin", actor="board", rng=Seq((kept,)))
        self.assertEqual(sentence.reason, "name_only")
        self.assertTrue(matches(book, "jellyfin", kept))
        self.assertFalse(matches(book, "sonarr", kept))

    def test_a_failed_mint_and_the_environment_stay_put(self) -> None:
        book = Book()
        key = "WEBHOOK_SECRET_JELLYFIN"
        previous = os.environ.get(key)
        os.environ[key] = "preset-value"
        try:
            boom = register(book, "jellyfin", actor="board", rng=Boom())
            self.assertEqual(boom.reason, "not_minted")
            self.assertNotIn("abcd", repr(boom))
            self.assertNotIn("abcd", repr(book))
            self.assertEqual(names(book), ())
            blank = register(book, "jellyfin", actor="board", rng=Seq(("",)))
            self.assertEqual(blank.reason, "not_minted")
            self.assertEqual(os.environ[key], "preset-value")
            self.assertFalse(matches(book, "jellyfin", "preset-value"))
        finally:
            if previous is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = previous

    def test_ask_does_not_call_this_module(self) -> None:
        ask = Path("friday/ask.py").read_text(encoding="utf-8")
        self.assertNotIn("webhooks", ask)
        server = Path("webhooks/server.py").read_text(encoding="utf-8")
        self.assertNotIn("webhooks.secret", server)
        self.assertNotIn("register", server)
        page = Path("board/server.js").read_text(encoding="utf-8")
        self.assertNotIn("WEBHOOK_SECRET", page)
        self.assertNotIn("webhooks/secret", page)
        module = Path("webhooks/secret.py").read_text(encoding="utf-8")
        self.assertNotIn("os.environ", module)
        self.assertNotIn("open(", module)
        self.assertNotIn("import socket", module)


if __name__ == "__main__":
    unittest.main()
