"""An apt upgrade is not applied, and a reflash does not erase a disk."""

from __future__ import annotations

import inspect
import unittest
from pathlib import Path

from updates import packages
from updates.packages import package_change, reflash

KEPT = "The password is kept outside the machine"


class PackageTests(unittest.TestCase):
    def test_chat_cannot_upgrade_or_reflash(self) -> None:
        for actor in ("chat", "friday", "adapter", ""):
            change = package_change(actor, "apt-get upgrade", confirmed=True)
            self.assertEqual(change.reason, "board_only")
            self.assertFalse(change.applied)
            self.assertFalse(change.ran)
            flashed = reflash(actor, "sda", confirmed=True)
            self.assertEqual(flashed.reason, "board_only")
            self.assertFalse(flashed.erased)
            self.assertFalse(flashed.written)
            self.assertEqual(flashed.name, "")

    def test_an_upgrade_is_refused_in_any_case_and_nothing_runs(self) -> None:
        commands = (
            "apt upgrade",
            "  APT UPGRADE  ",
            "sudo -n apt-get -y dist-upgrade",
            "DEBIAN_FRONTEND=noninteractive apt-get full-upgrade",
            "/usr/bin/aptitude safe-upgrade",
            "command apt-get --download-only upgrade",
            "sudo -u root apt-get upgrade",
            "sudo --user root apt upgrade",
            "env apt upgrade",
            "nice -n 10 apt full-upgrade",
            "timeout 5 apt-get dist-upgrade",
            '"apt" "upgrade"',
        )
        for command in commands:
            decision = package_change("board", command, confirmed=True)
            self.assertEqual(decision.reason, "apt_upgrade_refused", command)
            self.assertEqual(decision.outcome, "refused")
            self.assertFalse(decision.applied)
            self.assertFalse(decision.ran)
            self.assertFalse(decision.written)
            self.assertNotIn(command.strip(), repr(decision))

    def test_another_apt_command_stays_in_the_signed_slot(self) -> None:
        decision = package_change("board", "apt-get install linux-image-amd64", confirmed=True)
        self.assertEqual(decision.reason, "signed_slot_only")
        self.assertFalse(decision.applied)
        self.assertFalse(decision.ran)

    def test_a_sentence_is_not_a_package_change(self) -> None:
        decision = package_change("board", KEPT, confirmed=True)
        self.assertEqual(decision.reason, "not_a_package_change")
        self.assertNotEqual(decision.reason, "credential")
        self.assertFalse(decision.ran)
        self.assertNotIn(KEPT, repr(decision))
        sentence = package_change("board", "please apt upgrade the machine", confirmed=True)
        self.assertEqual(sentence.reason, "not_a_package_change")
        self.assertFalse(sentence.ran)

    def test_a_credential_shaped_command_is_not_stored(self) -> None:
        for command in ("token=abcd", "password is hunter22", "apt-get upgrade token=abcd"):
            decision = package_change("board", command, confirmed=True)
            self.assertEqual(decision.reason, "credential")
            self.assertNotIn(command, repr(decision))
            self.assertNotIn("hunter22", repr(decision))
            self.assertNotIn("abcd", repr(decision))
            self.assertFalse(decision.ran)

    def test_a_broken_command_is_refused(self) -> None:
        self.assertEqual(package_change("board", "").reason, "command")
        self.assertEqual(package_change("board", "apt\nupgrade").reason, "command")
        self.assertEqual(package_change("board", None).reason, "command")
        self.assertEqual(package_change("board", ["apt", "upgrade"]).reason, "command")

    def test_a_reflash_is_a_new_install_and_does_not_erase(self) -> None:
        decision = reflash("board", "sda", confirmed=True)
        self.assertEqual((decision.outcome, decision.reason), ("refused", "not_an_upgrade"))
        self.assertEqual(decision.name, "sda")
        self.assertFalse(decision.erased)
        self.assertFalse(decision.written)
        self.assertFalse(decision.applied)
        kept = reflash("board", KEPT)
        self.assertEqual(kept.reason, "not_an_upgrade")
        self.assertEqual(kept.name, KEPT)
        self.assertFalse(kept.erased)

    def test_a_credential_shaped_disk_name_is_not_repeated(self) -> None:
        for target in ("token=abcd", "password is hunter22", " sda"):
            decision = reflash("board", target, confirmed=True)
            self.assertIn(decision.reason, {"credential", "name"})
            self.assertEqual(decision.name, "")
            self.assertNotIn("hunter22", repr(decision))
            self.assertNotIn("abcd", repr(decision))
            self.assertFalse(decision.erased)
        self.assertEqual(reflash("board", "sda\n").reason, "name")

    def test_the_module_does_not_run_a_command_or_join_ask(self) -> None:
        source = inspect.getsource(packages)
        self.assertNotIn("subprocess", source)
        self.assertNotIn("socket", source)
        self.assertNotIn("urllib", source)
        self.assertNotIn("os.system", source)
        ask = Path("friday/ask.py").read_text(encoding="utf-8")
        self.assertNotIn("updates.packages", ask)
        self.assertNotIn("package_change", ask)
        self.assertNotIn("reflash", ask)
        page = Path("board/server.js").read_text(encoding="utf-8")
        self.assertNotIn("package_change", page)
        self.assertNotIn("apt_upgrade", page)


if __name__ == "__main__":
    unittest.main()
