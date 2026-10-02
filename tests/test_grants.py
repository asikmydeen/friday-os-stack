"""Grants name tools. An inbound mutating call waits."""

from __future__ import annotations

import inspect
import unittest
from pathlib import Path

import mcpbus.grants as grants
from mcpbus.grants import (
    GrantBook,
    accept_grant_tool,
    accept_tool,
    inbound,
    prompt_for,
    record_grant,
    visible,
    wire_as_grant,
)


class GrantTests(unittest.TestCase):
    def test_visible_tools_are_the_intersection(self) -> None:
        self.assertEqual(
            visible(["b", "a", "secret"], ["c", "b"]),
            ("b",),
        )

    def test_an_unlisted_tool_stays_out_of_the_prompt(self) -> None:
        decision = inbound("secret", ["secret"], ["recall"])
        self.assertEqual(decision.reason, "not_in_prompt")

    def test_a_mutating_call_waits_and_creates_no_approval(self) -> None:
        for tool in ("send", "pay", "delete", "publish", "install", "grant", "start", "stop"):
            decision = inbound(tool, [tool], [tool], confirmed=True)
            self.assertEqual((decision.outcome, decision.reason), ("waiting", "board_must_approve"))
            self.assertEqual(decision.__dict__.keys(), {"outcome", "reason"})

    def test_a_granted_read_is_allowed(self) -> None:
        decision = inbound("recall", ["recall"], ["recall", "secret"])
        self.assertEqual((decision.outcome, decision.reason), ("allowed", "granted_tool"))

    def test_only_the_board_accepts_a_tool(self) -> None:
        self.assertEqual(accept_tool("chat", "recall", confirmed=True).reason, "actor_cannot_approve")
        self.assertEqual(accept_tool("board", "recall").reason, "owner_accepted")

    def test_a_wire_stays_off_until_the_board_accepts_it(self) -> None:
        self.assertEqual(wire_as_grant(accepted=False).reason, "awaiting_acceptance")
        self.assertEqual(
            wire_as_grant(accepted=True, actor="chat").reason,
            "awaiting_acceptance",
        )
        decision = wire_as_grant(accepted=True, actor="board")
        self.assertEqual((decision.outcome, decision.reason), ("granted", "accepted"))


SERVER = "https://peer.example/mcp"
OTHER = "https://other.example/mcp"


def _grant(book: GrantBook, **kwargs):
    fields = {
        "actor": "board",
        "server": SERVER,
        "role": "cto",
        "tools": ["recall", "status"],
        "secret_ref": "HARNESS_REF",
    }
    fields.update(kwargs)
    return record_grant(book, **fields)


class ConnectionGrantTests(unittest.TestCase):
    def test_unaccepted_tools_stay_out_of_the_prompt(self) -> None:
        book = GrantBook()
        recorded = _grant(book, confirmed=True)
        self.assertEqual((recorded.outcome, recorded.reason), ("recorded", "prompt"))
        self.assertEqual(recorded.server, SERVER)
        self.assertEqual(recorded.role, "cto")
        self.assertEqual(recorded.secret_ref, "HARNESS_REF")
        self.assertEqual(recorded.prompt, ())
        self.assertFalse(recorded.started)
        self.assertFalse(recorded.called)
        self.assertEqual(prompt_for(book, SERVER, "cto"), ())
        self.assertEqual(prompt_for(book, SERVER, "media"), ())
        self.assertNotIn(SERVER, repr(book))
        accepted = accept_grant_tool(book, actor="board", server=SERVER, tool="recall", confirmed=True)
        self.assertEqual((accepted.outcome, accepted.reason), ("accepted", "owner_accepted"))
        self.assertEqual(accepted.prompt, ("recall",))
        self.assertEqual(prompt_for(book, SERVER, "cto"), ("recall",))
        self.assertNotIn("status", accepted.prompt)
        other = accept_grant_tool(book, actor="board", server=SERVER, tool="send")
        self.assertEqual(other.reason, "not_offered")
        self.assertEqual(other.prompt, ("recall",))
        self.assertFalse(other.called)

    def test_chat_cannot_record_or_accept_and_a_secret_is_not_stored(self) -> None:
        book = GrantBook()
        self.assertEqual(_grant(book).reason, "prompt")
        for actor in ("chat", "friday", "adapter"):
            refused = _grant(book, actor=actor, server=OTHER, secret="pasted-secret", confirmed=True)
            self.assertEqual(refused.reason, "actor_cannot_approve")
            self.assertEqual(refused.server, "")
            self.assertNotIn("pasted-secret", repr(refused))
            self.assertFalse(refused.called)
        self.assertEqual(prompt_for(book, SERVER, "cto"), ())
        self.assertEqual(prompt_for(book, OTHER, "cto"), ())
        chat = accept_grant_tool(book, actor="chat", server=SERVER, tool="status")
        self.assertEqual(chat.reason, "actor_cannot_approve")
        self.assertEqual(prompt_for(book, SERVER, "cto"), ())
        fresh = GrantBook()
        leaked = _grant(fresh, secret="token=abcd")
        self.assertEqual(leaked.reason, "credential")
        self.assertEqual(leaked.server, "")
        self.assertNotIn("abcd", repr(leaked))
        self.assertNotIn("abcd", repr(fresh))
        self.assertEqual(prompt_for(fresh, SERVER, "cto"), ())
        hunter = _grant(GrantBook(), password="password is hunter22")
        self.assertEqual(hunter.reason, "credential")
        self.assertNotIn("hunter22", repr(hunter))
        kept = _grant(book, secret="The password is kept outside the machine")
        self.assertEqual(kept.reason, "kept")
        self.assertEqual(kept.server, SERVER)
        self.assertEqual(kept.prompt, ())

    def test_a_second_grant_keeps_the_first_and_a_bad_server_stores_nothing(self) -> None:
        book = GrantBook()
        self.assertEqual(_grant(book).reason, "prompt")
        again = _grant(book, server=SERVER, role="media", tools=["status"], secret_ref="OTHER_REF")
        self.assertEqual(again.reason, "kept")
        self.assertEqual(again.role, "cto")
        self.assertEqual(again.secret_ref, "HARNESS_REF")
        self.assertEqual(prompt_for(book, SERVER, "media"), ())
        bad = {
            "https://127.0.0.1/mcp": "loopback",
            "https://127.1/mcp": "loopback",
            "https://0x7f.0.0.1/mcp": "loopback",
            "https://localhost/mcp": "loopback",
            "https://[::1]/mcp": "loopback",
            "https://169.254.1.1/mcp": "link_local",
            "https://friday/mcp": "core_closed",
            "https://webhooks/mcp": "core_closed",
            "https://metadata.google.internal/mcp": "metadata",
            "https://user:secret@peer.example/mcp": "url",
            "https://peer.example/mcp?x=1": "url",
            "ftp://peer.example/mcp": "url",
            "token=abcd": "credential",
        }
        for server, reason in bad.items():
            fresh = GrantBook()
            decision = _grant(fresh, server=server)
            self.assertEqual(decision.reason, reason, server)
            self.assertEqual(decision.server, "")
            self.assertNotIn("abcd", repr(decision))
            self.assertEqual(prompt_for(fresh, server, "cto"), ())
        self.assertEqual(_grant(GrantBook(), role="family").reason, "family_blocked")
        self.assertEqual(_grant(GrantBook(), role="fetcher").reason, "role_name")
        self.assertEqual(_grant(GrantBook(), secret_ref="secret=value").reason, "credential")
        self.assertEqual(_grant(GrantBook(), secret_ref="").reason, "secret_ref")
        self.assertEqual(_grant(GrantBook(), tools=[]).reason, "tool_name")
        self.assertEqual(_grant(GrantBook(), tools="recall").reason, "tool_name")

    def test_ask_does_not_call_the_grant_and_nothing_is_opened(self) -> None:
        source = inspect.getsource(grants)
        self.assertNotIn("os.environ", source)
        self.assertNotIn("import socket", source)
        self.assertNotIn("urlopen", source)
        self.assertNotIn("sqlite3", source)
        ask = Path("friday/ask.py").read_text(encoding="utf-8")
        self.assertNotIn("record_grant", ask)
        self.assertNotIn("mcpbus.grants", ask)
        outbound = Path("mcpbus/outbound.py").read_text(encoding="utf-8")
        self.assertNotIn("record_grant", outbound)


if __name__ == "__main__":
    unittest.main()
