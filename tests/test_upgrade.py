"""A known app's upgrade is a record. The image is not upgraded."""

from __future__ import annotations

import unittest
from pathlib import Path

from guests.upgrade import SAID, Book, accept_tool, apply_upgrade, record_upgrade, shown


class CatalogUpgrade(unittest.TestCase):
    def test_the_board_records_the_ask_and_nothing_is_upgraded(self) -> None:
        book = Book()
        noted = record_upgrade(
            book,
            app_id="jellyfin",
            actor="board",
            wire_level="known",
            mark="managed",
            note="the player image",
            tools=["player", "library_scan"],
            confirmed=True,
        )
        self.assertEqual(noted.outcome, "recorded")
        self.assertEqual(noted.reason, "not_upgraded")
        self.assertEqual(noted.said, SAID)
        self.assertEqual(noted.said, "An upgrade was asked.")
        self.assertEqual(noted.note, "the player image")
        self.assertNotEqual(noted.said, noted.note)
        self.assertEqual(noted.tools, ("player", "library_scan"))
        self.assertEqual(noted.on, ())
        self.assertFalse(noted.tools_on)
        self.assertFalse(noted.upgraded)
        self.assertFalse(noted.restarted)
        self.assertFalse(noted.pulled)
        self.assertFalse(noted.started)
        self.assertFalse(noted.stopped)
        self.assertFalse(noted.called)
        self.assertFalse(noted.performed)
        self.assertFalse(noted.applied)
        self.assertFalse(noted.swarm_stopped)
        self.assertNotIn("approval", noted.__dict__)
        self.assertEqual(book.rows["jellyfin"]["said"], SAID)
        one = accept_tool(
            book,
            app_id="jellyfin",
            tool="player",
            actor="board",
            mark="managed",
            confirmed=True,
        )
        self.assertEqual(one.outcome, "accepted")
        self.assertEqual(one.reason, "owner_accepted")
        self.assertEqual(one.on, ("player",))
        self.assertNotIn("library_scan", one.on)
        self.assertTrue(one.tools_on)
        self.assertFalse(one.upgraded)
        self.assertFalse(one.applied)
        other = accept_tool(
            book,
            app_id="jellyfin",
            tool="library_scan",
            actor="board",
            mark="managed",
        )
        self.assertEqual(other.on, ("player", "library_scan"))
        self.assertFalse(other.upgraded)
        again = record_upgrade(
            book,
            app_id="jellyfin",
            actor="board",
            mark="managed",
            note="a later image",
            tools=["library_scan"],
            confirmed=True,
        )
        self.assertEqual(again.reason, "already")
        self.assertEqual(again.note, "the player image")
        self.assertEqual(again.tools, ("player", "library_scan"))
        self.assertEqual(again.on, ("player", "library_scan"))
        self.assertFalse(again.upgraded)
        self.assertEqual(book.rows["jellyfin"]["note"], "the player image")
        sonarr = record_upgrade(
            book,
            app_id="sonarr",
            actor="board",
            mark="managed",
            note="The password is kept outside the machine",
            tools=["sonarr"],
        )
        self.assertEqual(sonarr.reason, "not_upgraded")
        self.assertIn("outside the machine", sonarr.note)
        self.assertEqual(sonarr.on, ())
        self.assertFalse(sonarr.tools_on)
        self.assertEqual(
            accept_tool(
                book, app_id="sonarr", tool="player", actor="board", mark="managed"
            ).reason,
            "not_offered",
        )
        self.assertEqual(book.accepted["jellyfin"], ("player", "library_scan"))
        self.assertNotIn("player", book.accepted["sonarr"])
        self.assertNotIn("player", shown(book, "sonarr").note)
        self.assertFalse(shown(book, "sonarr").upgraded)
        self.assertEqual(len(book.rows), 2)
        closed = apply_upgrade(book, "jellyfin", confirmed=True)
        self.assertEqual(closed.outcome, "refused")
        self.assertEqual(closed.reason, "catalog_install_closed")
        self.assertFalse(closed.applied)
        self.assertFalse(closed.upgraded)
        self.assertFalse(closed.tools_on)
        self.assertEqual(closed.on, ("player", "library_scan"))
        self.assertEqual(book.accepted["jellyfin"], ("player", "library_scan"))
        self.assertEqual(apply_upgrade(book, confirmed=True).reason, "catalog_install_closed")

    def test_a_new_name_stays_off_and_a_bad_list_does_not_clear(self) -> None:
        book = Book()
        noted = record_upgrade(
            book,
            app_id="home-assistant",
            actor="board",
            mark="managed",
            tools=("home_status", "home_control"),
        )
        self.assertEqual(noted.on, ())
        self.assertFalse(noted.tools_on)
        self.assertFalse(noted.upgraded)
        status = accept_tool(
            book,
            app_id="home-assistant",
            tool="home_status",
            actor="board",
            mark="managed",
        )
        self.assertEqual(status.on, ("home_status",))
        self.assertNotIn("home_control", status.on)
        chat = accept_tool(
            book,
            app_id="home-assistant",
            tool="home_control",
            actor="chat",
            mark="managed",
            confirmed=True,
        )
        self.assertEqual(chat.reason, "chat_cannot")
        self.assertEqual(chat.on, ("home_status",))
        self.assertNotIn("home_control", book.accepted["home-assistant"])
        self.assertFalse(chat.upgraded)
        strange = accept_tool(
            book,
            app_id="home-assistant",
            tool="delete_library",
            actor="board",
            mark="managed",
        )
        self.assertEqual(strange.reason, "not_offered")
        self.assertEqual(strange.on, ("home_status",))
        self.assertNotIn("delete_library", book.accepted["home-assistant"])
        self.assertFalse(strange.upgraded)
        junk = record_upgrade(
            book,
            app_id="home-assistant",
            actor="board",
            mark="managed",
            tools="home_control",
        )
        self.assertEqual(junk.outcome, "refused")
        self.assertEqual(junk.reason, "tool_list")
        self.assertEqual(junk.tools, ("home_status", "home_control"))
        self.assertEqual(junk.on, ("home_status",))
        self.assertEqual(book.rows["home-assistant"]["tools"], ("home_status", "home_control"))
        self.assertEqual(
            record_upgrade(
                book,
                app_id="radarr",
                actor="board",
                mark="managed",
                tools=["radarr", 1],
            ).reason,
            "tool_list",
        )
        self.assertNotIn("radarr", book.rows)
        self.assertEqual(
            record_upgrade(
                book,
                app_id="radarr",
                actor="board",
                mark="managed",
                tools=["Player"],
            ).reason,
            "tool_list",
        )
        self.assertNotIn("radarr", book.rows)
        many = record_upgrade(
            book,
            app_id="radarr",
            actor="board",
            mark="managed",
            tools=[f"tool{i}" for i in range(9)],
        )
        self.assertEqual(many.reason, "tool_list")
        self.assertNotIn("radarr", book.rows)
        self.assertEqual(
            accept_tool(
                book,
                app_id="home-assistant",
                tool="home_status",
                actor="board",
                mark="managed",
            ).reason,
            "already",
        )

    def test_a_credential_is_not_stored(self) -> None:
        book = Book()
        first = record_upgrade(
            book,
            app_id="jellyfin",
            actor="board",
            mark="managed",
            note="the shelf",
            tools=["player"],
        )
        self.assertEqual(first.reason, "not_upgraded")
        kept = record_upgrade(
            book,
            app_id="jellyfin",
            actor="board",
            mark="managed",
            note="token=abcd",
            tools=["player"],
        )
        self.assertEqual(kept.reason, "credential")
        self.assertEqual(kept.note, "")
        self.assertEqual(kept.app_id, "")
        self.assertNotIn("abcd", repr(kept))
        self.assertEqual(book.rows["jellyfin"]["note"], "the shelf")
        hunter = record_upgrade(
            book,
            app_id="radarr",
            actor="board",
            mark="managed",
            note="password is hunter22",
        )
        self.assertEqual(hunter.reason, "credential")
        self.assertNotIn("hunter22", str(book.rows))
        self.assertNotIn("hunter22", repr(hunter))
        self.assertNotIn("radarr", book.rows)
        encoded = record_upgrade(
            book,
            app_id="prowlarr",
            actor="board",
            mark="managed",
            tools=["token%3Dabcd"],
        )
        self.assertEqual(encoded.reason, "credential")
        self.assertNotIn("prowlarr", book.rows)
        self.assertNotIn("abcd", repr(encoded))
        plus = record_upgrade(
            book,
            app_id="bazarr",
            actor="board",
            mark="managed",
            note="password+is+hunter22",
        )
        self.assertEqual(plus.reason, "credential")
        self.assertNotIn("bazarr", book.rows)
        triple = record_upgrade(
            book,
            app_id="tautulli",
            actor="board",
            mark="managed",
            tools=["token%25253Dabcd"],
        )
        self.assertEqual(triple.reason, "credential")
        self.assertEqual(triple.tools, ())
        self.assertNotIn("tautulli", book.rows)
        self.assertNotIn("abcd", repr(triple))
        named = record_upgrade(
            book,
            app_id="token=abcd",
            actor="board",
            mark="managed",
            note="hello",
        )
        self.assertEqual(named.reason, "credential")
        self.assertNotIn("abcd", repr(named))
        self.assertNotIn("abcd", repr(book))
        hidden_tool = accept_tool(
            book,
            app_id="jellyfin",
            tool="token%3Dabcd",
            actor="board",
            mark="managed",
        )
        self.assertEqual(hidden_tool.reason, "credential")
        self.assertEqual(hidden_tool.on, ())
        self.assertNotIn("abcd", repr(hidden_tool))
        self.assertEqual(book.accepted["jellyfin"], ())

    def test_chat_cannot_record_and_a_core_or_adopted_app_is_refused(self) -> None:
        book = Book()
        refused = record_upgrade(
            book, app_id="jellyfin", actor="chat", mark="managed", tools=["player"]
        )
        self.assertEqual(refused.reason, "chat_cannot")
        self.assertEqual(refused.note, "")
        self.assertFalse(refused.upgraded)
        self.assertEqual(book.rows, {})
        noted = record_upgrade(
            book,
            app_id="jellyfin",
            actor="board",
            mark="managed",
            note="the shelf",
            tools=["player"],
        )
        self.assertEqual(noted.reason, "not_upgraded")
        turned = accept_tool(
            book, app_id="jellyfin", tool="player", actor="board", mark="managed"
        )
        self.assertEqual(turned.on, ("player",))
        chat = record_upgrade(
            book,
            app_id="jellyfin",
            actor=" Chat ",
            mark="managed",
            note="replace it",
            tools=["other"],
            confirmed=True,
        )
        self.assertEqual(chat.reason, "chat_cannot")
        self.assertEqual(chat.note, "the shelf")
        self.assertEqual(chat.tools, ("player",))
        self.assertEqual(chat.on, ("player",))
        self.assertFalse(chat.upgraded)
        self.assertEqual(book.rows["jellyfin"]["note"], "the shelf")
        family = record_upgrade(
            book,
            app_id="jellyfin",
            actor="Family",
            mark="managed",
            tools=["other"],
        )
        self.assertEqual(family.reason, "family_blocked")
        self.assertEqual(family.tools, ("player",))
        self.assertEqual(book.rows["jellyfin"]["tools"], ("player",))
        friday = record_upgrade(
            book,
            app_id="jellyfin",
            actor="friday",
            mark="managed",
            note="replace it",
        )
        self.assertEqual(friday.reason, "actor_cannot")
        self.assertEqual(book.rows["jellyfin"]["note"], "the shelf")
        self.assertEqual(
            record_upgrade(book, app_id="jellyfin", actor="board ", mark="managed").reason,
            "actor_cannot",
        )
        self.assertEqual(
            record_upgrade(book, app_id=" jellyfin", actor="board", mark="managed").reason,
            "app_id",
        )
        self.assertEqual(
            record_upgrade(book, app_id="jellyfin\n", actor="board", mark="managed").reason,
            "app_id",
        )
        plain = record_upgrade(
            book,
            app_id="bazarr",
            actor="board",
            mark="managed",
            note="The password is kept outside the machine",
        )
        self.assertEqual(plain.reason, "not_upgraded")
        self.assertIn("outside the machine", shown(book, "bazarr").note)
        self.assertFalse(shown(book, "bazarr").upgraded)
        self.assertEqual(
            record_upgrade(
                book,
                app_id="The password is kept outside the machine",
                actor="board",
                mark="managed",
            ).reason,
            "app_id",
        )
        for name in ("postgres", "qdrant", "memory-mcp", "Friday", "gateway"):
            blocked = record_upgrade(
                book,
                app_id=name,
                actor="board",
                wire_level="known",
                mark="managed",
            )
            self.assertEqual(blocked.reason, "core_locked", name)
            self.assertFalse(blocked.upgraded)
            self.assertNotIn(name, book.rows)
        self.assertEqual(
            record_upgrade(
                book,
                app_id="sonarr",
                actor="board",
                wire_level="Known",
                mark="managed",
            ).reason,
            "not_known",
        )
        self.assertEqual(
            record_upgrade(
                book,
                app_id="sonarr",
                actor="board",
                wire_level="listed",
                mark="managed",
            ).reason,
            "not_known",
        )
        adopted = record_upgrade(
            book,
            app_id="plex",
            actor="board",
            wire_level="known",
            mark="adopted",
            confirmed=True,
        )
        self.assertEqual(adopted.reason, "not_managed")
        self.assertFalse(adopted.upgraded)
        self.assertFalse(adopted.restarted)
        self.assertNotIn("plex", book.rows)
        swarm = record_upgrade(
            book,
            app_id="qbittorrent",
            actor="board",
            mark="adopted",
            confirmed=True,
        )
        self.assertEqual(swarm.reason, "not_managed")
        self.assertFalse(swarm.swarm_stopped)
        self.assertFalse(swarm.upgraded)
        self.assertNotIn("qbittorrent", book.rows)
        self.assertEqual(
            record_upgrade(book, app_id="plex", actor="board", mark="Managed").reason,
            "not_managed",
        )
        self.assertEqual(
            record_upgrade(book, app_id="sonarr", actor="executor", mark="managed").reason,
            "actor_cannot",
        )
        self.assertNotIn("sonarr", book.rows)
        self.assertEqual(shown(book, "jellyfin").said, SAID)
        self.assertFalse(shown(book, "jellyfin").upgraded)
        self.assertEqual(shown(book, "jellyfin").on, ("player",))
        self.assertEqual(shown(book, "missing").reason, "no_upgrade")
        blank = record_upgrade(
            book,
            app_id="tautulli",
            actor="board",
            mark="managed",
            note="   ",
        )
        self.assertEqual(blank.reason, "not_upgraded")
        self.assertEqual(blank.note, "")
        self.assertEqual(blank.tools, ())
        self.assertFalse(blank.upgraded)
        long_note = record_upgrade(
            book,
            app_id="prowlarr",
            actor="board",
            mark="managed",
            note=("shelf " * 400),
        )
        self.assertEqual(long_note.reason, "not_upgraded")
        self.assertLessEqual(len(long_note.note), 1200)
        self.assertFalse(long_note.started)
        self.assertFalse(long_note.pulled)
        self.assertEqual(
            accept_tool(
                book, app_id="missing", tool="player", actor="board", mark="managed"
            ).reason,
            "no_upgrade",
        )
        source = Path(record_upgrade.__code__.co_filename).read_text(encoding="utf-8")
        self.assertNotIn("urlopen", source)
        self.assertNotIn("subprocess", source)
        self.assertNotIn("import socket", source)
        self.assertNotIn("docker", source)
        self.assertNotIn("connect(", source)
        self.assertNotIn("catalog/wires", source)
        root = Path(record_upgrade.__code__.co_filename).parents[1]
        ask = (root / "friday" / "ask.py").read_text(encoding="utf-8")
        self.assertNotIn("record_upgrade", ask)
        self.assertNotIn("guests.upgrade", ask)
        board = (root / "board" / "server.js").read_text(encoding="utf-8")
        self.assertNotIn("record_upgrade", board)
        for name in ("registry.py", "start.py", "stop.py", "pull.py", "call.py", "lifecycle.py"):
            text = (root / "guests" / name).read_text(encoding="utf-8")
            self.assertNotIn("record_upgrade", text)
        self.assertNotIn("record_upgrade", (root / "gateway" / "proxy.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
