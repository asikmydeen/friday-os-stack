"""One inactive charter can be recorded. The file is not copied."""

from __future__ import annotations

import unittest
from pathlib import Path

import friday.ask as ask
from cabinet.enable import FULL_PACK, Book, enable_role, links

KEPT = "The password is kept outside the machine"
TOKEN = "token=abcd"
HUNTER = "password is hunter22"
ROOT = Path(__file__).resolve().parents[1]


def _enable(book: Book, **kwargs):
    fields = {"actor": "board", "role": "health"}
    fields.update(kwargs)
    return enable_role(book, **fields)


class EnableTests(unittest.TestCase):
    def test_the_pack_on_disk_is_the_pack_this_module_names(self) -> None:
        found = {path.stem for path in (ROOT / "charters" / "full").glob("*.md")}
        self.assertEqual(found, set(FULL_PACK))
        self.assertIn("family", FULL_PACK)

    def test_the_board_records_the_relative_link_and_copies_nothing(self) -> None:
        book = Book()
        decision = _enable(book, confirmed=True)
        self.assertEqual((decision.outcome, decision.reason), ("recorded", "not_copied"))
        self.assertEqual(decision.role, "health")
        self.assertEqual(decision.target, "full/health.md")
        self.assertFalse(decision.copied)
        self.assertFalse(decision.linked)
        self.assertFalse(decision.started)
        self.assertFalse(decision.created)
        self.assertEqual(decision.job_cap, 0)
        self.assertEqual(links(book), (("health", "full/health.md"),))
        self.assertFalse((ROOT / "charters" / "health.md").exists())

    def test_chat_cannot_record_one_and_the_link_stays(self) -> None:
        book = Book()
        self.assertEqual(_enable(book).reason, "not_copied")
        for actor in ("chat", "friday", "adapter", "Chat", " chat", " chat ", "Board"):
            refused = _enable(book, actor=actor, role="researcher", confirmed=True)
            self.assertEqual(refused.reason, "board_only")
            self.assertEqual(refused.role, "")
            self.assertFalse(refused.copied)
            self.assertFalse(refused.started)
        self.assertEqual(links(book), (("health", "full/health.md"),))

    def test_a_second_record_keeps_the_first_link(self) -> None:
        book = Book()
        self.assertEqual(_enable(book, role="researcher").target, "full/researcher.md")
        again = _enable(book, role="researcher", target="full/health.md", confirmed=True)
        self.assertEqual(again.reason, "already")
        self.assertEqual(again.target, "full/researcher.md")
        self.assertFalse(again.copied)
        other = _enable(book, role="health")
        self.assertEqual(other.reason, "not_copied")
        self.assertEqual(
            links(book),
            (("health", "full/health.md"), ("researcher", "full/researcher.md")),
        )

    def test_family_and_a_starter_are_not_enabled(self) -> None:
        book = Book()
        self.assertEqual(_enable(book, role="health").reason, "not_copied")
        family = _enable(book, role="family", confirmed=True)
        self.assertEqual(family.reason, "family_blocked")
        self.assertEqual(family.role, "")
        self.assertFalse(family.created)
        self.assertFalse(family.started)
        starter = _enable(book, role="chief")
        self.assertEqual(starter.reason, "already_active")
        self.assertEqual(starter.role, "")
        self.assertEqual(_enable(book, role="not-a-charter").reason, "unknown_role")
        self.assertEqual(_enable(book, role=" health").reason, "role_name")
        self.assertEqual(_enable(book, role="health\n").reason, "role_name")
        self.assertEqual(_enable(book, role=None).reason, "role_name")
        self.assertEqual(links(book), (("health", "full/health.md"),))

    def test_a_bad_path_or_mount_stores_nothing(self) -> None:
        book = Book()
        absolute = _enable(book, target="/soul/agents/full/health.md")
        self.assertEqual(absolute.reason, "absolute_path")
        self.assertEqual(absolute.target, "")
        self.assertFalse(absolute.copied)
        escaped = _enable(book, target="full/../health.md")
        self.assertEqual(escaped.reason, "outside_mount")
        dotted = _enable(book, target="./full/health.md")
        self.assertEqual(dotted.reason, "outside_mount")
        slashed = _enable(book, target="full/..\\health.md")
        self.assertEqual(slashed.reason, "outside_mount")
        self.assertEqual(slashed.target, "")
        mount = _enable(book, mount="./charters/full", confirmed=True)
        self.assertEqual(mount.reason, "drops_starter_set")
        self.assertFalse(mount.copied)
        self.assertFalse(mount.created)
        other = _enable(book, mount="/etc")
        self.assertEqual(other.reason, "mount_closed")
        kept_mount = _enable(book, mount=KEPT)
        self.assertEqual(kept_mount.reason, "mount_closed")
        self.assertEqual(links(book), ())
        kept = _enable(book)
        self.assertEqual(kept.reason, "not_copied")
        sentence = _enable(book, role="legal", target=KEPT)
        self.assertEqual(sentence.reason, "outside_mount")
        self.assertNotEqual(sentence.reason, "credential")
        self.assertEqual(links(book), (("health", "full/health.md"),))

    def test_a_credential_shaped_name_is_not_stored(self) -> None:
        book = Book()
        self.assertEqual(_enable(book, role="legal", target=KEPT).reason, "outside_mount")
        self.assertEqual(_enable(book, role="legal").reason, "not_copied")
        for name in (TOKEN, HUNTER, "token%3Dabcd", "token%25253Dabcd", "password+is+hunter22"):
            refused = _enable(book, role=name, confirmed=True)
            self.assertEqual(refused.reason, "credential")
            self.assertEqual(refused.role, "")
            self.assertNotIn("abcd", repr(refused))
            self.assertNotIn("hunter22", repr(refused))
            self.assertNotIn(name, repr(refused))
        later = _enable(book, role="legal", target=TOKEN)
        self.assertEqual(later.reason, "already")
        self.assertEqual(later.target, "full/legal.md")
        self.assertNotIn("abcd", repr(later))
        self.assertNotIn("abcd", repr(book))
        mounted = _enable(book, role="health", mount=TOKEN)
        self.assertEqual(mounted.reason, "credential")
        self.assertEqual(mounted.role, "")
        self.assertNotIn("abcd", repr(mounted))
        self.assertEqual(links(book), (("legal", "full/legal.md"),))

    def test_a_credential_shaped_target_on_a_new_role_is_not_stored(self) -> None:
        for name in (TOKEN, HUNTER, "token%3Dabcd", "token%25253Dabcd", "password+is+hunter22"):
            book = Book()
            refused = _enable(book, target=name, confirmed=True)
            self.assertEqual(refused.reason, "credential")
            self.assertEqual(refused.role, "")
            self.assertEqual(refused.target, "")
            self.assertFalse(refused.copied)
            self.assertFalse(refused.linked)
            self.assertNotIn("abcd", repr(refused))
            self.assertNotIn("hunter22", repr(refused))
            self.assertNotIn("abcd", repr(book))
            self.assertNotIn("hunter22", repr(book))
            self.assertEqual(links(book), ())

    def test_ask_does_not_call_this_module(self) -> None:
        text = Path(ask.__file__).read_text(encoding="utf-8")
        self.assertNotIn("enable_role", text)
        self.assertNotIn("cabinet.enable", text)
        page = (ROOT / "board" / "server.js").read_text(encoding="utf-8")
        self.assertNotIn("enable_role", page)
        self.assertNotIn("cabinet.enable", page)
        self.assertIn("/api/charters", page)
        self.assertIn("The file is not copied.", page)


if __name__ == "__main__":
    unittest.main()
