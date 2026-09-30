"""An unchecked signature is not an update, and taskrunner stays off."""

from __future__ import annotations

import unittest

from updates.signed import code_profile, propose


class UpdateTests(unittest.TestCase):
    def test_someone_other_than_the_board_cannot_propose(self) -> None:
        decision = propose(actor="chat", signature="abc")
        self.assertEqual(decision.reason, "owner_must_see")

    def test_an_empty_signature_is_unsigned(self) -> None:
        decision = propose(actor="board", signature="")
        self.assertEqual((decision.outcome, decision.reason), ("refused", "unsigned"))

    def test_a_signature_string_is_not_checked_or_applied(self) -> None:
        decision = propose(actor="board", signature="not-a-real-signature")
        self.assertEqual(decision.outcome, "refused")
        self.assertEqual(decision.reason, "signature_not_checked")
        self.assertNotIn(decision.outcome, {"applied", "signed"})

    def test_the_code_profile_does_not_start_taskrunner(self) -> None:
        self.assertEqual(code_profile().reason, "profile_off")
        self.assertEqual(
            code_profile(enabled=False, coder_url="https://coder.example", token="supplied").reason,
            "profile_off",
        )
        self.assertEqual(code_profile(enabled=True).reason, "no_coder_url")
        self.assertEqual(
            code_profile(enabled=True, coder_url="https://coder.example").reason,
            "token_required",
        )
        self.assertEqual(
            code_profile(enabled=True, coder_url="https://coder.example", token="").reason,
            "token_required",
        )
        decision = code_profile(
            enabled=True,
            coder_url="https://coder.example",
            token="supplied",
        )
        self.assertEqual((decision.outcome, decision.reason), ("waiting", "not_started"))


if __name__ == "__main__":
    unittest.main()
