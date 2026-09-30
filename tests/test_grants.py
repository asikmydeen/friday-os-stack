"""Grants name tools. An inbound mutating call waits."""

from __future__ import annotations

import unittest

from mcpbus.grants import accept_tool, inbound, visible, wire_as_grant


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


if __name__ == "__main__":
    unittest.main()
