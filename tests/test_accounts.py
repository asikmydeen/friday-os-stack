"""Adopt-only accounts do not write the owner's tracker."""

from __future__ import annotations

import unittest
from pathlib import Path

from guests.accounts import (
    Book,
    accept_tool,
    add_card,
    browse,
    download_client,
    embed,
    enable_phone,
    grant_browser,
    grant_token,
    holds,
    note_receipt,
    offer_tools,
    use_account,
)


class AccountTests(unittest.TestCase):
    def test_an_unknown_person_does_not_change_the_owner_tracker(self) -> None:
        book = Book("owner")
        grant_token(
            book,
            actor="board",
            service="fitness",
            person_id="owner",
            token="slot-a",
        )
        tracker = ["owner-steps"]
        before = list(tracker)
        decision = use_account(
            book,
            "fitness",
            "stranger",
            tracker,
            known=False,
            confirmed=True,
        )
        self.assertEqual(decision.said, "connect your account")
        self.assertEqual(decision.reason, "unknown_person")
        self.assertIs(decision.written, False)
        self.assertEqual(tracker, before)
        self.assertEqual(book.receipts, [])
        self.assertNotIn("slot-a", repr(book))
        self.assertNotIn("slot-a", repr(decision))

    def test_a_missing_fitness_token_writes_nothing(self) -> None:
        book = Book("owner")
        tracker = {"steps": 1}
        before = dict(tracker)
        missing = use_account(book, "fitness", "owner", tracker, confirmed=True)
        self.assertEqual(missing.said, "connect your account")
        self.assertEqual(missing.reason, "connect_your_account")
        self.assertIs(missing.written, False)
        self.assertEqual(tracker, before)
        refused = grant_token(
            book,
            actor="chat",
            service="fitness",
            person_id="owner",
            token="slot-a",
            confirmed=True,
        )
        self.assertEqual(refused.reason, "actor_cannot_approve")
        self.assertFalse(holds(book, "fitness", "owner", "slot-a"))
        for secret in ("token=abcd", "password is hunter22"):
            shaped = grant_token(
                book,
                actor="board",
                service="fitness",
                person_id="owner",
                token=secret,
            )
            self.assertEqual(shaped.reason, "token_refused")
            self.assertFalse(holds(book, "fitness", "owner", secret))
        kept = grant_token(
            book,
            actor="board",
            service="fitness",
            person_id="owner",
            token="The password is kept outside the machine",
        )
        self.assertEqual(kept.reason, "name_only")
        self.assertEqual(kept.name, "fitness")
        self.assertNotIn("outside", repr(kept))
        present = use_account(book, "fitness", "owner", tracker)
        self.assertEqual((present.outcome, present.reason), ("recorded", "not_sent"))
        self.assertIs(present.written, False)
        self.assertEqual(present.said, "")
        self.assertEqual(tracker, before)
        replaced = grant_token(
            book,
            actor="board",
            service="fitness",
            person_id="owner",
            token="token=abcd",
        )
        self.assertEqual(replaced.reason, "token_refused")
        self.assertTrue(holds(book, "fitness", "owner", "The password is kept outside the machine"))
        self.assertFalse(holds(book, "fitness", "owner", "token=abcd"))

    def test_calendar_mail_and_phone_do_not_write_or_create_a_collection(self) -> None:
        book = Book("owner")
        tracker = []
        for service in ("calendar", "mail"):
            decision = use_account(book, service, "owner", tracker)
            self.assertEqual(decision.said, "not connected")
            self.assertEqual(decision.reason, "not_connected")
            self.assertIs(decision.written, False)
        phone = use_account(book, "phone", "owner", tracker)
        self.assertEqual(phone.said, "connect your account")
        self.assertEqual(phone.reason, "not_enabled")
        self.assertIs(phone.collection_created, False)
        self.assertIs(book.messages_created, False)
        self.assertEqual(enable_phone(book, actor="chat").reason, "actor_cannot_approve")
        grant_token(book, actor="board", service="phone", person_id="owner", token="slot-phone")
        held = use_account(book, "phone", "owner", tracker)
        self.assertEqual(held.reason, "not_enabled")
        self.assertEqual(held.said, "")
        self.assertIs(held.collection_created, False)
        self.assertEqual(tracker, [])
        self.assertIs(book.phone_enabled, False)
        enabled = enable_phone(book, actor="board", confirmed=True)
        self.assertEqual(enabled.reason, "not_created")
        self.assertIs(book.messages_created, False)
        self.assertIs(book.phone_enabled, True)
        sent = use_account(book, "phone", "owner", tracker)
        self.assertEqual((sent.outcome, sent.reason), ("recorded", "not_sent"))
        self.assertIs(sent.collection_created, False)
        self.assertIs(book.messages_created, False)
        self.assertEqual(tracker, [])
        other = grant_token(
            book,
            actor="board",
            service="fitness",
            person_id="other",
            token="slot-b",
        )
        self.assertEqual(other.reason, "unknown_person")
        self.assertEqual(other.said, "connect your account")
        self.assertFalse(holds(book, "fitness", "other", "slot-b"))

    def test_family_is_blocked_from_connections_and_download_clients(self) -> None:
        book = Book("owner")
        grant_token(book, actor="board", service="fitness", person_id="owner", token="slot-a")
        tracker = ["owner-steps"]
        before = list(tracker)
        blocked = use_account(book, "fitness", "owner", tracker, role="family")
        self.assertEqual(blocked.reason, "family_blocked")
        self.assertEqual(blocked.said, "")
        self.assertIs(blocked.written, False)
        self.assertEqual(tracker, before)
        self.assertEqual(download_client("family", confirmed=True).reason, "family_blocked")
        self.assertEqual(download_client("media").reason, "not_fetcher")
        self.assertEqual(download_client("fetcher").reason, "catalog_install_closed")
        self.assertIs(download_client("fetcher").tools_on, False)

    def test_shopper_searches_and_buyer_opens_and_neither_checks_out(self) -> None:
        book = Book("owner")
        tracker_untouched = use_account(book, "fitness", "owner", [])
        self.assertEqual(tracker_untouched.reason, "connect_your_account")
        closed = browse(book, "shopper", "search", confirmed=True)
        self.assertEqual(closed.said, "connect your account")
        self.assertIs(closed.fetched, False)
        self.assertIs(closed.checked_out, False)
        granted = grant_browser(
            book,
            actor="board",
            url="https://192.0.2.20/shop",
            confirmed=True,
        )
        self.assertEqual(granted.reason, "name_only")
        self.assertEqual(grant_browser(book, actor="chat", url="https://192.0.2.20/shop").reason, "actor_cannot_approve")
        search = browse(book, "shopper", "search")
        opened = browse(book, "buyer", "open")
        self.assertEqual((search.outcome, search.reason), ("recorded", "not_fetched"))
        self.assertEqual((opened.outcome, opened.reason), ("recorded", "not_fetched"))
        self.assertIs(search.fetched, False)
        self.assertIs(search.checked_out, False)
        self.assertIs(opened.checked_out, False)
        self.assertEqual(browse(book, "shopper", "checkout").reason, "not_checkout")
        self.assertEqual(browse(book, "buyer", "pay").reason, "not_checkout")
        self.assertIs(browse(book, "buyer", "pay").checked_out, False)
        self.assertEqual(browse(book, "shopper", "open").reason, "action")
        self.assertEqual(browse(book, "media", "search").reason, "role")
        self.assertEqual(browse(book, "family", "search").reason, "family_blocked")
        core = grant_browser(book, actor="board", url="http://postgres:5432/shop")
        self.assertEqual(core.reason, "core_closed")
        self.assertEqual(book.browser_url, "https://192.0.2.20/shop")

    def test_a_custom_card_keeps_tools_off_until_the_board_accepts_a_named_one(self) -> None:
        book = Book("owner")
        refused = add_card(book, "kiosk", "http://postgres/health", confirmed=True)
        self.assertEqual(refused.reason, "core_closed")
        self.assertNotIn("kiosk", book.cards)
        unnamed = add_card(book, "kiosk", "http://example.test/health")
        self.assertEqual(unnamed.reason, "resolved")
        link = add_card(
            book,
            "kiosk",
            "http://kiosk.example/health",
            resolved={"kiosk.example": ["169.254.1.1"]},
        )
        self.assertEqual(link.reason, "link_local")
        decision = add_card(
            book,
            "kiosk",
            "http://kiosk.example/health",
            resolved={"kiosk.example": ["192.0.2.40"]},
        )
        self.assertEqual(decision.reason, "tools_off")
        self.assertIs(decision.tools_on, False)
        self.assertEqual(decision.health_url, "http://kiosk.example/health")
        offered = offer_tools(book, "kiosk", ["kiosk_status"])
        self.assertEqual(offered.reason, "tools_off")
        self.assertIs(offered.tools_on, False)
        self.assertEqual(book.cards["kiosk"]["accepted"], [])
        chat = accept_tool(book, actor="chat", card_id="kiosk", tool="kiosk_status", confirmed=True)
        self.assertEqual(chat.reason, "actor_cannot_approve")
        missing = accept_tool(book, actor="board", card_id="kiosk", tool="kiosk_extra")
        self.assertEqual(missing.reason, "not_named")
        self.assertEqual(book.cards["kiosk"]["accepted"], [])
        accepted = accept_tool(book, actor="board", card_id="kiosk", tool="kiosk_status")
        self.assertEqual(accepted.reason, "owner_accepted")
        self.assertIs(accepted.tools_on, True)
        self.assertIs(accepted.started, False)
        self.assertEqual(book.cards["kiosk"]["accepted"], ["kiosk_status"])
        extra = offer_tools(book, "kiosk", ["kiosk_delete"])
        self.assertEqual(extra.reason, "tools_off")
        self.assertIs(extra.tools_on, False)
        self.assertEqual(book.cards["kiosk"]["accepted"], ["kiosk_status"])
        self.assertIn("kiosk_delete", book.cards["kiosk"]["offered"])

    def test_media_files_are_not_embedded_and_a_receipt_is_not_an_episode(self) -> None:
        book = Book("owner")
        for kind in ("video", "photo", "download"):
            decision = embed(book, kind, "library/movies/clip")
            self.assertEqual(decision.reason, "not_embedded")
            self.assertIs(decision.embedded, False)
        shaped = note_receipt(book, "token=abcd")
        self.assertEqual(shaped.reason, "credential")
        self.assertEqual(book.receipts, [])
        kept = note_receipt(book, "The password is kept outside the machine")
        self.assertEqual(kept.reason, "receipt")
        receipt = note_receipt(book, "added this movie")
        self.assertEqual(receipt.reason, "receipt")
        self.assertEqual(receipt.said, "added this movie")
        self.assertIs(receipt.embedded, False)
        self.assertIs(receipt.written, False)
        self.assertEqual(
            book.receipts,
            [
                {"text": "The password is kept outside the machine", "category": "receipt"},
                {"text": "added this movie", "category": "receipt"},
            ],
        )
        self.assertTrue(all(row["category"] != "episode" for row in book.receipts))

    def test_ask_does_not_call_this_module(self) -> None:
        text = Path("friday/ask.py").read_text(encoding="utf-8")
        self.assertNotIn("guests", text)
        self.assertNotIn("use_account", text)


if __name__ == "__main__":
    unittest.main()
