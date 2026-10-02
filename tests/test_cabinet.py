"""Advisor tools stay off until the Board accepts them. Job cap stays 0."""

from __future__ import annotations

import dataclasses
import tempfile
import unittest
from pathlib import Path

from cabinet.configure import Config, charter_tools, effective

ROOT = Path(__file__).resolve().parents[1]
STARTER = ("cfo", "chief", "coach", "cto", "home", "media")
SECRET = "hunter22"


class CabinetTests(unittest.TestCase):
    def test_effective_tools_are_the_charter_minus_deny(self) -> None:
        self.assertEqual(effective(["play", "delete", "play"], ["delete"]), ("play",))
        self.assertEqual(effective(["delete"], ["delete"]), ())
        text = "---\nid: media\ntools: [play, delete]\ndeny_tools: delete\n---\n\nBody\n"
        self.assertEqual(charter_tools(text), (("play", "delete"), ("delete",)))
        self.assertEqual(charter_tools("---\nid: media\ntools: Not A Tool\n---\n"), ((), ()))

    def test_a_new_name_stays_off_until_the_board_accepts_it(self) -> None:
        config = Config()
        tools = ("status",)
        shelf = config.shelf("chief", tools, (), ("status", "install_jellyfin"))
        self.assertEqual([(item.name, item.state) for item in shelf], [
            ("status", "off"),
            ("install_jellyfin", "off"),
        ])
        refused = config.accept(
            "chat",
            "chief",
            "status",
            tools=tools,
            deny=(),
            confirmed=True,
        )
        self.assertEqual(refused.reason, "actor_cannot_approve")
        self.assertEqual(config.shelf("chief", tools, (), ())[0].state, "off")

        accepted = config.accept("board", "chief", "status", tools=tools, deny=(), confirmed=True)
        self.assertEqual(accepted.reason, "owner_accepted")
        self.assertEqual(config.shelf("chief", tools, (), ())[0].state, "on")

        added = ("status", "logs")
        upgraded = config.shelf("chief", added, (), ())
        self.assertEqual([(item.name, item.state) for item in upgraded], [
            ("status", "on"),
            ("logs", "off"),
        ])
        config.accept("board", "chief", "logs", tools=added, deny=())
        self.assertEqual(config.shelf("chief", added, (), ())[1].state, "on")

        offered = config.shelf("chief", tools, (), ("install_jellyfin",))
        self.assertEqual(offered[-1].state, "off")
        config.accept(
            "board",
            "chief",
            "install_jellyfin",
            tools=tools,
            deny=(),
            offered=("install_jellyfin",),
        )
        self.assertEqual(
            config.shelf("chief", tools, (), ("install_jellyfin",))[-1].state,
            "on",
        )
        renamed = config.shelf("chief", tools, (), ("install_media",))
        self.assertEqual([(item.name, item.state) for item in renamed], [
            ("status", "on"),
            ("install_media", "off"),
        ])
        self.assertNotIn("install_jellyfin", [item.name for item in renamed])

    def test_a_denied_tool_stays_off(self) -> None:
        config = Config()
        decision = config.accept(
            "board",
            "media",
            "delete",
            tools=("play", "delete"),
            deny=("delete",),
            confirmed=True,
        )
        self.assertEqual(decision.reason, "denied")
        config.accept("board", "media", "play", tools=("play", "delete"), deny=("delete",))
        shelf = config.shelf("media", ("play", "delete"), ("delete",), ())
        self.assertEqual([(item.name, item.state) for item in shelf], [
            ("play", "on"),
            ("delete", "off"),
        ])

    def test_job_cap_stays_zero_and_dispatch_does_not_start(self) -> None:
        config = Config()
        self.assertEqual(config.cap("chief"), 0)
        refused = config.set_cap("board", "chief", 2, code_on=False, confirmed=True)
        self.assertEqual(refused.reason, "code_profile_off")
        self.assertEqual(refused.cap, 0)
        self.assertIs(refused.started, False)
        self.assertEqual(config.cap("chief"), 0)
        self.assertEqual(config.set_cap("chat", "chief", 1, code_on=True).reason, "actor_cannot_approve")
        self.assertEqual(config.set_cap("board", "chief", True, code_on=True).reason, "cap_range")
        self.assertEqual(config.set_cap("board", "chief", 4, code_on=True).reason, "cap_range")

        raised = config.set_cap("board", "chief", 3, code_on=True)
        self.assertEqual((raised.reason, raised.cap, raised.started), ("not_started", 3, False))
        self.assertEqual(config.cap("chief"), 3)
        job = config.dispatch("chief", "task1", confirmed=True)
        self.assertEqual(job.reason, "not_started")
        self.assertEqual(job.name, "tr-task1")
        self.assertIs(job.started, False)
        self.assertFalse(job.name.startswith("agent-"))

        config.set_cap("board", "cto", 2, code_on=True)
        self.assertEqual(config.cap("chief"), 3)
        self.assertEqual(config.cap("cto"), 2)
        cleared = config.set_cap("board", "chief", 3, code_on=False)
        self.assertEqual(cleared.reason, "code_profile_off")
        self.assertEqual(config.cap("chief"), 0)
        self.assertEqual(config.cap("cto"), 0)

    def test_a_durable_home_and_an_engine_do_not_start(self) -> None:
        config = Config()
        refused = config.set_durable("chat", "cto", True, confirmed=True)
        self.assertEqual(refused.reason, "actor_cannot_approve")
        home = config.set_durable("board", "cto", True)
        self.assertEqual(home.name, "agent-cto")
        self.assertEqual(home.reason, "not_started")
        self.assertIs(home.started, False)
        engine = config.set_engine("board", "cto", "claude-code", 180, confirmed=True)
        self.assertEqual(engine.reason, "not_started")
        self.assertEqual(engine.cap, 0)
        self.assertIs(engine.started, False)
        self.assertEqual(config.set_engine("board", "cto", "other", 30).reason, "engine")
        self.assertEqual(config.set_engine("board", "cto", "gsd", 4).reason, "budget")
        self.assertEqual(config.set_engine("board", "cto", "gsd", True).reason, "budget")
        self.assertEqual(config.cap("cto"), 0)

    def test_a_secret_returns_the_name_only(self) -> None:
        config = Config()
        refused = config.put_secret("chat", "media", "dummy", SECRET, confirmed=True)
        self.assertEqual(refused.reason, "actor_cannot_approve")
        self.assertNotIn(SECRET, repr(refused))
        self.assertNotIn(SECRET, repr(config))
        self.assertFalse(config.matches("media", "dummy", SECRET))

        stored = config.put_secret("board", "media", "dummy", SECRET, confirmed=True)
        self.assertEqual(stored.reason, "name_only")
        self.assertEqual(stored.name, "dummy")
        self.assertNotIn("value", dataclasses.asdict(stored))
        self.assertNotIn(SECRET, repr(stored))
        self.assertNotIn(SECRET, repr(config))
        self.assertTrue(config.matches("media", "dummy", SECRET))
        self.assertFalse(config.matches("media", "dummy", "other"))
        shown = config.show_secret("media", "dummy")
        self.assertEqual(shown.reason, "value_hidden")
        self.assertNotIn(SECRET, repr(shown))
        self.assertEqual(config.secret_names("media"), ("dummy",))
        self.assertEqual(config.put_secret("board", "media", "dummy", "   ").reason, "secret_value")
        self.assertTrue(config.matches("media", "dummy", SECRET))

    def test_other_collections_are_refused(self) -> None:
        config = Config()
        recorded = config.set_collections("board", "chief", ("cabinet_working",), confirmed=True)
        self.assertEqual(recorded.reason, "cabinet_working")
        for name in (
            "family_shared",
            "role_profile_chief",
            "person_profile_owner",
            "friday_profile",
            "knowledge",
            "messages",
        ):
            decision = config.set_collections("board", "chief", (name,))
            self.assertEqual(decision.reason, "collection_closed", name)
        self.assertEqual(config.collections("chief"), ("cabinet_working",))
        self.assertEqual(config.set_collections("chat", "chief", ("cabinet_working",)).reason, "actor_cannot_approve")
        self.assertEqual(config.set_collections("board", "chief", "cabinet_working").reason, "collection_closed")

    def test_starter_advisors_list_at_job_cap_zero(self) -> None:
        listed = Config().advisors(ROOT / "charters")
        self.assertEqual(tuple(item.id for item in listed), STARTER)
        for item in listed:
            self.assertEqual(item.job_cap, 0)
            self.assertEqual(item.tools, ())
        self.assertNotIn("health", [item.id for item in listed])

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "media.md").write_text(
                "---\nid: media\nname: Media\ntools: play, delete\ndeny_tools: delete\n---\n\n",
                encoding="utf-8",
            )
            full = root / "full"
            full.mkdir()
            (full / "health.md").write_text("---\nid: health\nname: Health\n---\n", encoding="utf-8")
            config = Config()
            one = config.advisors(root)
            self.assertEqual([item.id for item in one], ["media"])
            self.assertEqual([(item.name, item.state) for item in one[0].tools], [
                ("play", "off"),
                ("delete", "off"),
            ])


if __name__ == "__main__":
    unittest.main()
