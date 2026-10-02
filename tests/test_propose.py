"""A proposed wire is recorded and not installed."""

from __future__ import annotations

import unittest
from pathlib import Path

from catalog.propose import Book, accept_tool, apply_proposal, propose_wire, tools_for

PIN = Path("catalog/PIN")


def _draft(book: Book, **extra: object):
    fields = {
        "actor": "media",
        "app": " Jellyfin ",
        "advisor": "media",
        "method": "get",
        "path": "/health",
        "tools": ("library_status", "playing"),
    }
    fields.update(extra)
    return propose_wire(book, **fields)


class ProposeTests(unittest.TestCase):
    def test_an_advisor_draft_stays_off_and_is_not_installed(self) -> None:
        before = PIN.read_text(encoding="utf-8")
        book = Book()
        decision = _draft(book, confirmed=True)
        self.assertEqual(decision.outcome, "recorded")
        self.assertEqual(decision.reason, "proposed")
        self.assertEqual(decision.app, "jellyfin")
        self.assertEqual(decision.advisor, "media")
        self.assertEqual(decision.method, "GET")
        self.assertEqual(decision.path, "/health")
        self.assertEqual(decision.tools, ("library_status", "playing"))
        self.assertEqual(decision.on, ())
        self.assertIs(decision.tools_on, False)
        self.assertEqual(decision.level, "proposed")
        self.assertIs(decision.listed, True)
        self.assertEqual(decision.install, "refused")
        self.assertIs(decision.applied, False)
        self.assertIs(decision.started, False)
        self.assertIs(decision.jinja, False)
        self.assertIs(decision.pin_written, False)
        self.assertIs(decision.wires_read, False)
        self.assertIs(decision.approval, False)
        self.assertIs(decision.probed, False)
        self.assertEqual(len(book.drafts), 1)
        self.assertEqual(PIN.read_text(encoding="utf-8"), before)
        self.assertEqual(repr(book), "Book()")

    def test_chat_and_the_board_cannot_write_the_draft(self) -> None:
        book = Book()
        chat = _draft(book, actor="chat", confirmed=True)
        self.assertEqual(chat.reason, "actor_cannot_propose")
        self.assertEqual(book.drafts, {})
        board = _draft(book, actor="board")
        self.assertEqual(board.reason, "actor_cannot_propose")
        self.assertEqual(book.drafts, {})
        other = _draft(book, actor="fetcher", advisor="media")
        self.assertEqual(other.reason, "actor_cannot_propose")
        self.assertEqual(book.drafts, {})
        family = _draft(book, actor="family", advisor="family")
        self.assertEqual(family.reason, "family_blocked")
        self.assertEqual(book.drafts, {})
        self.assertEqual(_draft(book, actor="no-such", advisor="no-such").reason, "advisor")
        self.assertEqual(book.drafts, {})

    def test_the_board_accepts_one_name_and_chat_leaves_it(self) -> None:
        book = Book()
        _draft(book)
        one = accept_tool(book, "board", "jellyfin", "library_status", confirmed=True)
        self.assertEqual(one.reason, "owner_accepted")
        self.assertEqual(one.on, ("library_status",))
        self.assertNotIn("playing", one.on)
        self.assertIs(one.tools_on, True)
        self.assertIs(one.approval, False)
        self.assertIs(one.started, False)
        missing = accept_tool(book, "board", "jellyfin", "library_refresh")
        self.assertEqual(missing.reason, "not_offered")
        self.assertEqual(missing.on, ("library_status",))
        self.assertIs(missing.tools_on, False)
        chat = accept_tool(book, "chat", "jellyfin", "playing", confirmed=True)
        self.assertEqual(chat.reason, "actor_cannot_approve")
        self.assertEqual(chat.on, ("library_status",))
        self.assertIs(chat.tools_on, False)
        self.assertIs(chat.approval, False)
        again = accept_tool(book, "board", "jellyfin", "library_status")
        self.assertEqual(again.on, ("library_status",))
        other = tools_for(book, "jellyfin", "fetcher")
        self.assertEqual(other.reason, "not_that_advisor")
        self.assertEqual(other.tools, ())
        self.assertEqual(other.on, ())
        shelf = tools_for(book, "jellyfin", "media")
        self.assertEqual(shelf.tools, ("library_status", "playing"))
        self.assertEqual(shelf.on, ("library_status",))
        self.assertEqual(tools_for(book, "jellyfin", "family").reason, "family_blocked")

    def test_a_new_name_does_not_inherit_an_acceptance(self) -> None:
        book = Book()
        _draft(book)
        accept_tool(book, "board", "jellyfin", "library_status")
        revised = _draft(book, tools=("library_status", "library_refresh", "library_status"))
        self.assertEqual(revised.reason, "revised")
        self.assertEqual(revised.tools, ("library_status", "library_refresh"))
        self.assertEqual(revised.on, ("library_status",))
        self.assertNotIn("library_refresh", revised.on)
        self.assertIs(revised.tools_on, False)
        self.assertEqual(len(book.drafts), 1)
        dropped = _draft(book, tools=("library_refresh",))
        self.assertEqual(dropped.on, ())
        self.assertNotIn("library_status", dropped.tools)
        taken = _draft(book, actor="fetcher", advisor="fetcher", tools=("library_status",))
        self.assertEqual(taken.reason, "not_that_advisor")
        self.assertEqual(book.drafts["jellyfin"].advisor, "media")
        self.assertEqual(book.drafts["jellyfin"].tools, ("library_refresh",))
        self.assertEqual(book.accepted["jellyfin"], ())
        other = _draft(book, actor="fetcher", app="sonarr", advisor="fetcher", tools=("library_status",))
        self.assertEqual(other.app, "sonarr")
        self.assertEqual(other.on, ())
        self.assertEqual(len(book.drafts), 2)
        self.assertEqual(book.accepted["jellyfin"], ())

    def test_a_credential_or_a_template_is_not_stored(self) -> None:
        book = Book()
        secret = _draft(book, tools=("token=abcd",))
        self.assertEqual(secret.reason, "credential")
        self.assertNotIn("abcd", repr(secret))
        self.assertEqual(book.drafts, {})
        sentence = _draft(book, path="password is hunter22")
        self.assertEqual(sentence.reason, "credential")
        self.assertNotIn("hunter22", repr(sentence))
        self.assertEqual(book.drafts, {})
        template = _draft(book, path="/health{{ pin }}")
        self.assertEqual(template.reason, "jinja")
        self.assertIs(template.jinja, False)
        self.assertEqual(book.drafts, {})
        self.assertEqual(_draft(book, app="postgres").reason, "core_closed")
        self.assertEqual(_draft(book, method="PUT").reason, "method")
        self.assertEqual(_draft(book, tools="library_status").reason, "tool_name")
        self.assertEqual(_draft(book, tools=()).reason, "tool_name")
        self.assertEqual(book.drafts, {})
        kept = _draft(book, path="/The-password-is-kept-outside")
        self.assertEqual(kept.reason, "proposed")
        self.assertEqual(kept.path, "/The-password-is-kept-outside")
        self.assertNotEqual(kept.reason, "credential")

    def test_host_modes_are_refused_and_apply_stays_closed(self) -> None:
        book = Book()
        recorded = _draft(book)
        self.assertEqual(_draft(book, host_network=True).reason, "host_network")
        self.assertEqual(_draft(book, actor="chat", confirmed=True).reason, "actor_cannot_propose")
        self.assertEqual(book.drafts["jellyfin"].path, "/health")
        self.assertEqual(_draft(book, network_mode="host").reason, "host_network")
        self.assertEqual(_draft(book, network_mode="none").reason, "network_mode")
        self.assertEqual(_draft(book, host_pid=True).reason, "host_pid")
        self.assertEqual(_draft(book, pid_mode="host").reason, "host_pid")
        self.assertEqual(_draft(book, pid_mode="container:app").reason, "pid_mode")
        self.assertEqual(_draft(book, host_ipc=True).reason, "host_ipc")
        self.assertEqual(_draft(book, ipc_mode="host").reason, "host_ipc")
        self.assertEqual(_draft(book, ipc_mode="shareable").reason, "ipc_mode")
        self.assertEqual(_draft(book, privileged=True).reason, "privileged")
        self.assertEqual(_draft(book, devices="/dev/ttyUSB0").reason, "device_not_in_manifest")
        self.assertEqual(_draft(book, devices=("/dev/dri",)).reason, "device_not_in_manifest")
        self.assertEqual(_draft(book, capabilities=("SYS_ADMIN",)).reason, "capability_not_in_manifest")
        self.assertIs(_draft(book, host_network=True, confirmed=True).started, False)
        accept_tool(book, "board", "jellyfin", "playing")
        closed = apply_proposal(book, "jellyfin", confirmed=True)
        self.assertEqual(closed.reason, "catalog_install_closed")
        self.assertEqual(closed.on, ("playing",))
        self.assertIs(closed.tools_on, False)
        self.assertIs(closed.applied, False)
        self.assertIs(closed.started, False)
        self.assertIs(closed.probed, False)
        self.assertEqual(book.accepted["jellyfin"], ("playing",))
        self.assertEqual(apply_proposal(book).reason, "catalog_install_closed")
        self.assertEqual(accept_tool(book, "board", "missing", "playing").reason, "no_draft")
        self.assertEqual(recorded.install, "refused")

    def test_ask_does_not_call_this_module(self) -> None:
        text = Path("friday/ask.py").read_text(encoding="utf-8")
        self.assertNotIn("catalog.propose", text)
        self.assertNotIn("propose_wire", text)


if __name__ == "__main__":
    unittest.main()
