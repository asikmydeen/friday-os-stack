"""Mattermost roster decisions. Nothing here calls Mattermost."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from doors.mattermost import accept_post, roster, write_bridge


class MattermostTests(unittest.TestCase):
    def test_one_owner_and_the_enabled_charters_are_recorded(self) -> None:
        decision = roster("", ("chief",))
        self.assertEqual(decision.reason, "owner_required")
        decision = roster("owner", ("chief", "friday"))
        self.assertEqual(decision.reason, "charter_required")
        decision = roster("owner", ("chief", "chief"))
        self.assertEqual(decision.reason, "charter_required")
        decision = roster("owner", ("chief",), co_owners=("sam",), confirmed=True)
        self.assertEqual(decision.reason, "one_owner")
        decision = roster("owner", ("chief", "cto"), software=("web",))
        self.assertEqual(decision.reason, "dev_role_disabled")
        decision = roster("owner", ("chief", "cto"), software=("cto",), obligations=("pay-rent", "pay-rent"))
        self.assertEqual(decision.reason, "obligation_name")
        decision = roster(
            "owner",
            ("chief", "cto", "home"),
            software=("cto",),
            obligations=("pay-rent",),
            confirmed=True,
        )
        self.assertEqual(decision.outcome, "recorded")
        self.assertEqual(decision.reason, "not_started")
        self.assertEqual(decision.bots, ("friday", "chief", "cto", "home"))
        self.assertEqual(decision.rooms, ("Cabinet", "Dev", "Work", "Friday"))
        self.assertEqual(decision.dev, ("cto",))
        self.assertEqual(decision.threads, ("pay-rent",))

    def test_a_post_is_the_owner_in_an_enrolled_room_with_no_stranger(self) -> None:
        bots = ("friday", "chief")
        decision = accept_post(
            sender="friday",
            room="Cabinet",
            members=("friday", "chief"),
            owner="owner",
            bots=bots,
            confirmed=True,
        )
        self.assertEqual(decision.reason, "bot_does_not_create_work")
        decision = accept_post(
            sender="owner",
            room="Town",
            members=("owner",),
            owner="owner",
            bots=bots,
        )
        self.assertEqual(decision.reason, "room_not_enrolled")
        decision = accept_post(
            sender="sam",
            room="Cabinet",
            members=("owner", "sam"),
            owner="owner",
            bots=bots,
        )
        self.assertEqual(decision.reason, "not_owner")
        decision = accept_post(
            sender="owner",
            room="Work",
            members=("friday",),
            owner="owner",
            bots=bots,
        )
        self.assertEqual(decision.reason, "owner_absent")
        decision = accept_post(
            sender="owner",
            room="Cabinet",
            members=("owner", "sam"),
            owner="owner",
            bots=bots,
            confirmed=True,
        )
        self.assertEqual(decision.reason, "stranger")
        decision = accept_post(
            sender="owner",
            room="Friday",
            members=("owner", "friday"),
            owner="owner",
            bots=bots,
        )
        self.assertEqual((decision.outcome, decision.reason), ("accepted", "owner_post"))

    def test_the_bridge_file_is_one_private_token(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            decision = write_bridge(root, "")
            self.assertEqual(decision.reason, "token_required")
            self.assertFalse((root / "mattermost-bridge.env").exists())
            decision = write_bridge(root, "bridge-token")
            self.assertEqual((decision.outcome, decision.reason), ("recorded", "bridge_written"))
            self.assertNotIn("bridge-token", str(decision))
            path = root / "mattermost-bridge.env"
            self.assertEqual(path.read_text(), "MATTERMOST_BRIDGE_TOKEN=bridge-token\n")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            link = root / "linked"
            os.symlink(root, link)
            decision = write_bridge(link, "bridge-token")
            self.assertEqual(decision.reason, "bridge_directory")


if __name__ == "__main__":
    unittest.main()
