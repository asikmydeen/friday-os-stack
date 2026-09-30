"""The model sees the page. Send, pay, delete, and publish wait."""

from __future__ import annotations

import unittest

from browser.session import act, credential, placement


class BrowserTests(unittest.TestCase):
    def test_the_session_has_its_own_network(self) -> None:
        self.assertEqual(placement().reason, "own_network")

    def test_the_model_sees_evidence_and_the_broker_holds_the_secret(self) -> None:
        self.assertEqual(credential("model").reason, "model_sees_evidence")
        self.assertEqual(credential("broker").reason, "for_the_session")

    def test_read_and_draft_proceed(self) -> None:
        self.assertEqual(act("read").outcome, "allowed")
        self.assertEqual(act("draft").outcome, "allowed")

    def test_sensitive_actions_wait_and_confirmed_is_ignored(self) -> None:
        for action in ("send", "pay", "delete", "publish"):
            decision = act(action, confirmed=True)
            self.assertEqual((decision.outcome, decision.reason), ("waiting", "approval_required"))
            self.assertNotIn("confirmed", decision.__dict__)


if __name__ == "__main__":
    unittest.main()
