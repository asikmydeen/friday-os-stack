"""An unchecked signature is not an update, and taskrunner stays off."""

from __future__ import annotations

import unittest
from pathlib import Path

from updates.signed import checksum_line, code_profile, propose


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
        digest = "ab" * 32
        seen = []

        def verifier(line, signature):
            seen.append((line, signature))
            return line == checksum_line(digest, "friday-0.0.2-usb.img.xz") and signature == "detached"

        decision = propose(
            actor="board",
            signature="not-a-real-signature",
            checksum=digest,
            filename="friday-0.0.2-usb.img.xz",
        )
        self.assertEqual(decision.reason, "signature_not_checked")
        self.assertEqual(seen, [])

    def test_a_matching_checksum_line_is_still_not_applied(self) -> None:
        digest = "ab" * 32
        filename = "friday-0.0.2-usb.img.xz"
        line = checksum_line(digest, filename)
        self.assertEqual(line, f"{digest}  {filename}\n")
        seen = []

        def verifier(payload, signature):
            seen.append((payload, signature))
            return payload == line and signature == "detached"

        decision = propose(
            actor="chat",
            signature="detached",
            checksum=digest,
            filename=filename,
            verifier=verifier,
        )
        self.assertEqual(decision.reason, "owner_must_see")
        self.assertEqual(seen, [])
        decision = propose(
            actor="board",
            signature="",
            checksum=digest,
            filename=filename,
            verifier=verifier,
        )
        self.assertEqual(decision.reason, "unsigned")
        self.assertEqual(seen, [])
        decision = propose(actor="board", signature="detached", checksum="AB" * 32, filename=filename, verifier=verifier)
        self.assertEqual(decision.reason, "checksum_missing")
        decision = propose(actor="board", signature="detached", checksum=digest, filename="../image.xz", verifier=verifier)
        self.assertEqual(decision.reason, "checksum_missing")
        self.assertEqual(seen, [])
        decision = propose(actor="board", signature="other", checksum=digest, filename=filename, verifier=verifier)
        self.assertEqual((decision.outcome, decision.reason), ("refused", "signature_rejected"))
        decision = propose(actor="board", signature="detached", checksum=digest, filename=filename, verifier=verifier)
        self.assertEqual((decision.outcome, decision.reason), ("refused", "checked_not_applied"))
        self.assertNotIn(decision.outcome, {"applied", "signed"})

        def broken(_payload, _signature):
            raise OSError("no key")

        decision = propose(actor="board", signature="detached", checksum=digest, filename=filename, verifier=broken)
        self.assertEqual(decision.reason, "signature_not_checked")

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

    def test_the_board_page_shows_the_decision_and_ask_does_not(self) -> None:
        page = Path("board/server.js").read_text(encoding="utf-8")
        self.assertIn("No key is configured. Nothing is applied.", page)
        self.assertIn("checked_not_applied", page)
        self.assertIn("signature_not_checked", page)
        self.assertNotIn("applied: true", page)
        self.assertNotIn("key_configured: true", page)
        ask = Path("friday/ask.py").read_text(encoding="utf-8")
        self.assertNotIn("updates.signed", ask)
        self.assertNotIn("/api/updates", ask)


if __name__ == "__main__":
    unittest.main()
