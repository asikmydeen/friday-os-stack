"""The adapter delivers a turn. The tunnel stays off."""

from __future__ import annotations

import unittest

from doors.reach import adapter_touch, deliver, join_mesh, mesh_open, tunnel


class DoorTests(unittest.TestCase):
    def test_the_adapter_delivers_a_turn_and_cannot_approve(self) -> None:
        decision = deliver("adapter", confirmed=True)
        self.assertEqual((decision.outcome, decision.reason), ("delivered", "turn"))
        self.assertEqual(deliver("chat").reason, "not_an_adapter")
        for target in ("approve", "executor", "postgres"):
            decision = adapter_touch(target, confirmed=True)
            self.assertEqual(decision.reason, "adapter_cannot_approve")
            self.assertEqual(decision.__dict__.keys(), {"outcome", "reason"})

    def test_the_mesh_opens_the_board_and_does_not_join_core(self) -> None:
        self.assertEqual(join_mesh().reason, "not_core")
        self.assertEqual(mesh_open("board").reason, "board")
        self.assertEqual(mesh_open("mcp").reason, "mcp_listener")
        for name in ("postgres", "qdrant", "executor"):
            self.assertEqual(mesh_open(name).reason, "mesh_not_core")

    def test_the_tunnel_stays_off(self) -> None:
        self.assertEqual(tunnel().reason, "tunnel_off")
        self.assertEqual(
            tunnel(enabled=False, target="board", access_checked=True).reason,
            "tunnel_off",
        )

    def test_an_enabled_tunnel_is_the_board_after_an_access_check(self) -> None:
        self.assertEqual(
            tunnel(enabled=True, target="board", access_checked=False).reason,
            "access_unchecked",
        )
        decision = tunnel(enabled=True, target="board", access_checked=True)
        self.assertEqual((decision.outcome, decision.reason), ("allowed", "board"))
        self.assertEqual(tunnel(enabled=True, target="postgres").reason, "not_publishable")
        self.assertEqual(tunnel(enabled=True, target="qdrant").reason, "not_publishable")
        self.assertEqual(tunnel(enabled=True, target="memory-mcp").reason, "not_publishable")
        self.assertEqual(tunnel(enabled=True, target="taskrunner").reason, "not_publishable")
        self.assertEqual(tunnel(enabled=True, target="radarr").reason, "not_publishable")
        self.assertEqual(tunnel(enabled=True, target="sonarr").reason, "not_publishable")
        self.assertEqual(tunnel(enabled=True, target="prowlarr").reason, "not_publishable")
        self.assertEqual(tunnel(enabled=True, target="qbittorrent").reason, "not_publishable")
        self.assertEqual(tunnel(enabled=True, target="jellyfin").reason, "board_only")
        self.assertEqual(tunnel(enabled=True, target="friday").reason, "board_only")


if __name__ == "__main__":
    unittest.main()
