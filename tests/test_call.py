"""A named advisor's API call is a record. The call is not made."""

from __future__ import annotations

import unittest
from pathlib import Path

from guests.call import SAID, Book, accept_tool, record_call, shown


def _accept(book: Book, app_id: str, advisor: str, tool: str):
    return accept_tool(
        book,
        app_id=app_id,
        advisor=advisor,
        tool=tool,
        actor="board",
        wire_level="known",
        mark="managed",
        confirmed=True,
    )


class AdvisorCall(unittest.TestCase):
    def test_the_board_records_the_ask_and_nothing_is_called(self) -> None:
        book = Book()
        off = record_call(
            book,
            app_id="jellyfin",
            advisor="media",
            tool="player",
            actor="board",
            mark="managed",
            note="what is in the library",
            confirmed=True,
        )
        self.assertEqual(off.reason, "tool_off")
        self.assertFalse(off.called)
        self.assertFalse(off.opened)
        self.assertEqual(off.via, "")
        self.assertEqual(book.rows, {})
        turned = _accept(book, "jellyfin", "media", "player")
        self.assertEqual(turned.outcome, "accepted")
        self.assertEqual(turned.reason, "owner_accepted")
        self.assertEqual(turned.on, ("player",))
        self.assertTrue(turned.tools_on)
        self.assertFalse(turned.called)
        self.assertFalse(turned.opened)
        self.assertNotIn("approval", turned.__dict__)
        noted = record_call(
            book,
            app_id="jellyfin",
            advisor="media",
            tool="player",
            actor="board",
            mark="managed",
            note="what is in the library",
            confirmed=True,
        )
        self.assertEqual(noted.outcome, "recorded")
        self.assertEqual(noted.reason, "not_called")
        self.assertEqual(noted.said, SAID)
        self.assertEqual(noted.said, "An API call was asked.")
        self.assertEqual(noted.advisor, "media")
        self.assertEqual(noted.tool, "player")
        self.assertEqual(noted.note, "what is in the library")
        self.assertNotEqual(noted.said, noted.note)
        self.assertEqual(noted.via, "gateway")
        self.assertFalse(noted.opened)
        self.assertFalse(noted.called)
        self.assertFalse(noted.sent)
        self.assertFalse(noted.started)
        self.assertFalse(noted.stopped)
        self.assertFalse(noted.pulled)
        self.assertFalse(noted.performed)
        self.assertFalse(noted.swarm_stopped)
        again = record_call(
            book,
            app_id="jellyfin",
            advisor="media",
            tool="player",
            actor="board",
            mark="managed",
            note="a later question",
            confirmed=True,
        )
        self.assertEqual(again.reason, "already")
        self.assertEqual(again.note, "what is in the library")
        self.assertEqual(again.tool, "player")
        self.assertFalse(again.called)
        self.assertEqual(book.rows["jellyfin"]["note"], "what is in the library")
        other_app = _accept(book, "plex", "media", "player")
        self.assertEqual(other_app.on, ("player",))
        self.assertEqual(book.accepted["jellyfin"], ("player",))
        plex = record_call(
            book,
            app_id="plex",
            advisor="media",
            tool="player",
            actor="board",
            mark="managed",
            note="The password is kept outside the machine",
        )
        self.assertEqual(plex.reason, "not_called")
        self.assertIn("outside the machine", plex.note)
        self.assertEqual(plex.said, SAID)
        self.assertFalse(plex.called)
        self.assertFalse(plex.swarm_stopped)
        self.assertNotIn("library", shown(book, "plex").note)
        self.assertEqual(len(book.rows), 2)

    def test_one_acceptance_does_not_turn_the_other_tool_on(self) -> None:
        book = Book()
        status = _accept(book, "home-assistant", "home", "home_status")
        self.assertEqual(status.on, ("home_status",))
        self.assertNotIn("home_control", status.on)
        blocked = record_call(
            book,
            app_id="home-assistant",
            advisor="home",
            tool="home_control",
            actor="board",
            mark="managed",
        )
        self.assertEqual(blocked.reason, "tool_off")
        self.assertFalse(blocked.called)
        self.assertNotIn("home-assistant", book.rows)
        chat_other = accept_tool(
            book,
            app_id="home-assistant",
            advisor="home",
            tool="home_control",
            actor="chat",
            mark="managed",
            confirmed=True,
        )
        self.assertEqual(chat_other.reason, "chat_cannot")
        self.assertEqual(chat_other.on, ("home_status",))
        self.assertNotIn("home_control", book.accepted["home-assistant"])
        self.assertFalse(chat_other.called)
        control = _accept(book, "home-assistant", "home", "home_control")
        self.assertEqual(control.on, ("home_status", "home_control"))
        self.assertTrue(control.tools_on)
        self.assertFalse(control.called)
        asked = record_call(
            book,
            app_id="home-assistant",
            advisor="home",
            tool="home_status",
            actor="board",
            mark="managed",
            note="the lights",
        )
        self.assertEqual(asked.reason, "not_called")
        self.assertEqual(asked.tool, "home_status")
        later = record_call(
            book,
            app_id="home-assistant",
            advisor="home",
            tool="home_control",
            actor="board",
            mark="managed",
            note="turn them off",
        )
        self.assertEqual(later.reason, "already")
        self.assertEqual(later.tool, "home_status")
        self.assertEqual(later.note, "the lights")
        self.assertFalse(later.called)
        self.assertEqual(
            _accept(book, "home-assistant", "home", "home_status").reason,
            "already",
        )
        self.assertEqual(book.accepted["home-assistant"], ("home_status", "home_control"))

    def test_a_credential_is_not_stored(self) -> None:
        book = Book()
        _accept(book, "jellyfin", "media", "player")
        first = record_call(
            book,
            app_id="jellyfin",
            advisor="media",
            tool="player",
            actor="board",
            mark="managed",
            note="the shelf",
        )
        self.assertEqual(first.reason, "not_called")
        kept = record_call(
            book,
            app_id="jellyfin",
            advisor="media",
            tool="player",
            actor="board",
            mark="managed",
            note="token=abcd",
        )
        self.assertEqual(kept.reason, "credential")
        self.assertEqual(kept.note, "")
        self.assertEqual(kept.app_id, "")
        self.assertNotIn("abcd", repr(kept))
        self.assertEqual(book.rows["jellyfin"]["note"], "the shelf")
        hunter = record_call(
            book,
            app_id="radarr",
            advisor="fetcher",
            tool="radarr",
            actor="board",
            mark="managed",
            note="password is hunter22",
        )
        self.assertEqual(hunter.reason, "credential")
        self.assertNotIn("hunter22", str(book.rows))
        self.assertNotIn("hunter22", repr(hunter))
        self.assertNotIn("radarr", book.rows)
        encoded = record_call(
            book,
            app_id="prowlarr",
            advisor="fetcher",
            tool="prowlarr",
            actor="board",
            mark="managed",
            note="token%3Dabcd",
        )
        self.assertEqual(encoded.reason, "credential")
        self.assertNotIn("prowlarr", book.rows)
        self.assertNotIn("abcd", repr(encoded))
        plus = record_call(
            book,
            app_id="sonarr",
            advisor="fetcher",
            tool="sonarr",
            actor="board",
            mark="managed",
            note="password+is+hunter22",
        )
        self.assertEqual(plus.reason, "credential")
        self.assertNotIn("sonarr", book.rows)
        triple = accept_tool(
            book,
            app_id="bazarr",
            advisor="fetcher",
            tool="token%25253Dabcd",
            actor="board",
            mark="managed",
        )
        self.assertEqual(triple.reason, "credential")
        self.assertEqual(triple.tool, "")
        self.assertNotIn("bazarr", book.accepted)
        self.assertNotIn("abcd", repr(triple))
        nested = record_call(
            book,
            app_id="qbittorrent",
            advisor="fetcher",
            tool="qbittorrent",
            actor="board",
            mark="managed",
            note="password%2520is%2520hunter22",
        )
        self.assertEqual(nested.reason, "credential")
        self.assertNotIn("qbittorrent", book.rows)
        self.assertNotIn("hunter22", repr(nested))
        self.assertFalse(nested.swarm_stopped)
        sentence = record_call(
            book,
            app_id="radarr",
            advisor="fetcher",
            tool="radarr",
            actor="board",
            mark="managed",
            note="see token%25253Dabcd now",
        )
        self.assertEqual(sentence.reason, "credential")
        self.assertNotIn("abcd", repr(sentence))
        self.assertNotIn("radarr", book.rows)
        split = record_call(
            book,
            app_id="sonarr",
            advisor="fetcher",
            tool="sonarr",
            actor="board",
            mark="managed",
            note="password\nis\nhunter22",
        )
        self.assertEqual(split.reason, "credential")
        self.assertNotIn("hunter22", repr(split))
        self.assertNotIn("sonarr", book.rows)
        hidden_app = record_call(
            book,
            app_id="token%25253Dabcd",
            advisor="media",
            tool="player",
            actor="board",
            mark="managed",
        )
        self.assertEqual(hidden_app.reason, "credential")
        self.assertEqual(hidden_app.app_id, "")
        self.assertNotIn("abcd", repr(hidden_app))
        named = record_call(
            book,
            app_id="token=abcd",
            advisor="media",
            tool="player",
            actor="board",
            mark="managed",
        )
        self.assertEqual(named.reason, "credential")
        self.assertNotIn("abcd", repr(named))
        self.assertNotIn("abcd", repr(book))
        hidden_tool = _accept(book, "plex", "media", "token%3Dabcd")
        self.assertEqual(hidden_tool.reason, "credential")
        self.assertNotIn("plex", book.accepted)
        self.assertNotIn("abcd", repr(hidden_tool))
        hidden_advisor = accept_tool(
            book,
            app_id="plex",
            advisor="token%3Dabcd",
            tool="player",
            actor="board",
            mark="managed",
        )
        self.assertEqual(hidden_advisor.reason, "credential")
        self.assertEqual(hidden_advisor.advisor, "")
        self.assertNotIn("abcd", repr(hidden_advisor))

    def test_chat_cannot_record_or_accept_and_the_row_stays(self) -> None:
        book = Book()
        refused = record_call(
            book,
            app_id="jellyfin",
            advisor="media",
            tool="player",
            actor="chat",
            mark="managed",
        )
        self.assertEqual(refused.reason, "chat_cannot")
        self.assertEqual(refused.note, "")
        self.assertFalse(refused.called)
        self.assertEqual(book.rows, {})
        chat_accept = accept_tool(
            book,
            app_id="jellyfin",
            advisor="media",
            tool="player",
            actor="chat",
            mark="managed",
            confirmed=True,
        )
        self.assertEqual(chat_accept.reason, "chat_cannot")
        self.assertEqual(chat_accept.on, ())
        self.assertFalse(chat_accept.tools_on)
        self.assertNotIn("jellyfin", book.accepted)
        turned = _accept(book, "jellyfin", "media", "player")
        self.assertEqual(turned.reason, "owner_accepted")
        noted = record_call(
            book,
            app_id="jellyfin",
            advisor="media",
            tool="player",
            actor="board",
            mark="managed",
            note="the shelf",
        )
        self.assertEqual(noted.reason, "not_called")
        chat = record_call(
            book,
            app_id="jellyfin",
            advisor="media",
            tool="player",
            actor=" Chat ",
            mark="managed",
            note="replace it",
            confirmed=True,
        )
        self.assertEqual(chat.reason, "chat_cannot")
        self.assertEqual(chat.note, "the shelf")
        self.assertEqual(chat.tool, "player")
        self.assertFalse(chat.called)
        self.assertEqual(book.rows["jellyfin"]["note"], "the shelf")
        leave = accept_tool(
            book,
            app_id="jellyfin",
            advisor="media",
            tool="player",
            actor="chat",
            mark="managed",
        )
        self.assertEqual(leave.reason, "chat_cannot")
        self.assertEqual(leave.on, ("player",))
        self.assertTrue(leave.tools_on)
        self.assertEqual(leave.tool, "")
        self.assertFalse(leave.called)
        self.assertEqual(book.accepted["jellyfin"], ("player",))
        friday = record_call(
            book,
            app_id="jellyfin",
            advisor="media",
            tool="player",
            actor="friday",
            mark="managed",
            note="replace it",
        )
        self.assertEqual(friday.reason, "actor_cannot")
        self.assertEqual(book.rows["jellyfin"]["note"], "the shelf")
        self.assertEqual(
            record_call(
                book,
                app_id="jellyfin",
                advisor="media",
                tool="player",
                actor="board ",
                mark="managed",
            ).reason,
            "actor_cannot",
        )
        self.assertEqual(
            accept_tool(
                book,
                app_id="jellyfin",
                advisor="media",
                tool="player",
                actor="friday",
                mark="managed",
            ).reason,
            "actor_cannot",
        )
        self.assertEqual(book.accepted["jellyfin"], ("player",))

    def test_the_wrong_advisor_family_and_a_core_name_are_refused(self) -> None:
        book = Book()
        self.assertEqual(
            record_call(
                book,
                app_id="jellyfin",
                advisor="fetcher",
                tool="player",
                actor="board",
                mark="managed",
            ).reason,
            "not_that_advisor",
        )
        self.assertEqual(
            accept_tool(
                book,
                app_id="jellyfin",
                advisor="family",
                tool="player",
                actor="board",
                mark="managed",
            ).reason,
            "family_blocked",
        )
        self.assertNotIn("jellyfin", book.accepted)
        self.assertEqual(
            record_call(
                book,
                app_id="home-assistant",
                advisor="media",
                tool="home_status",
                actor="board",
                mark="managed",
            ).reason,
            "not_that_advisor",
        )
        self.assertEqual(
            record_call(
                book,
                app_id="jellyfin",
                advisor="Media",
                tool="player",
                actor="board",
                mark="managed",
            ).reason,
            "not_that_advisor",
        )
        self.assertEqual(
            record_call(
                book,
                app_id=" jellyfin",
                advisor="media",
                tool="player",
                actor="board",
                mark="managed",
            ).reason,
            "app_id",
        )
        self.assertEqual(
            record_call(
                book,
                app_id="jellyfin\n",
                advisor="media",
                tool="player",
                actor="board",
                mark="managed",
            ).reason,
            "app_id",
        )
        self.assertEqual(
            record_call(
                book,
                app_id="The password is kept outside the machine",
                advisor="media",
                tool="player",
                actor="board",
                mark="managed",
            ).reason,
            "app_id",
        )
        for name in ("postgres", "qdrant", "memory-mcp", "Friday", "gateway"):
            blocked = record_call(
                book,
                app_id=name,
                advisor="media",
                tool="player",
                actor="board",
                wire_level="known",
                mark="managed",
            )
            self.assertEqual(blocked.reason, "core_locked")
            self.assertFalse(blocked.called)
            self.assertNotIn(name, book.rows)
        self.assertEqual(
            record_call(
                book,
                app_id="sonarr",
                advisor="fetcher",
                tool="sonarr",
                actor="board",
                wire_level="Known",
                mark="managed",
            ).reason,
            "not_known",
        )
        self.assertEqual(
            record_call(
                book,
                app_id="sonarr",
                advisor="fetcher",
                tool="sonarr",
                actor="board",
                wire_level="listed",
                mark="managed",
            ).reason,
            "not_known",
        )
        self.assertEqual(
            accept_tool(
                book,
                app_id="plex",
                advisor="media",
                tool="player",
                actor="board",
                mark="Managed",
            ).reason,
            "not_managed",
        )
        self.assertEqual(
            accept_tool(
                book,
                app_id="plex",
                advisor="media",
                tool="player",
                actor="board",
                mark="Adopted",
            ).reason,
            "not_managed",
        )
        self.assertNotIn("plex", book.accepted)
        adopted = record_call(
            book,
            app_id="plex",
            advisor="media",
            tool="player",
            actor="board",
            wire_level="known",
            mark="adopted",
            confirmed=True,
        )
        self.assertEqual(adopted.reason, "tool_off")
        self.assertFalse(adopted.called)
        self.assertFalse(adopted.started)
        self.assertNotIn("plex", book.rows)
        turned = accept_tool(
            book,
            app_id="plex",
            advisor="media",
            tool="player",
            actor="board",
            mark="adopted",
            confirmed=True,
        )
        self.assertEqual(turned.reason, "owner_accepted")
        self.assertFalse(turned.called)
        self.assertFalse(turned.opened)
        asked = record_call(
            book,
            app_id="plex",
            advisor="media",
            tool="player",
            actor="board",
            mark="adopted",
            note="what is playing",
            confirmed=True,
        )
        self.assertEqual(asked.reason, "not_called")
        self.assertEqual(asked.note, "what is playing")
        self.assertFalse(asked.called)
        self.assertFalse(asked.opened)
        self.assertFalse(asked.started)
        self.assertFalse(asked.stopped)
        self.assertFalse(asked.pulled)
        self.assertFalse(asked.swarm_stopped)
        hidden = record_call(
            book,
            app_id="plex",
            advisor="media",
            tool="player",
            actor="board",
            mark="adopted",
            note="token%25253Dabcd",
        )
        self.assertEqual(hidden.reason, "credential")
        self.assertEqual(hidden.note, "")
        self.assertNotIn("abcd", repr(hidden))
        self.assertEqual(book.rows["plex"]["note"], "what is playing")
        left = record_call(
            book,
            app_id="plex",
            advisor="media",
            tool="player",
            actor=" chat ",
            mark="adopted",
            note="replace it",
        )
        self.assertEqual(left.reason, "chat_cannot")
        self.assertEqual(left.note, "what is playing")
        self.assertFalse(left.called)
        self.assertEqual(
            record_call(
                book,
                app_id="tautulli",
                advisor="media",
                tool="player",
                actor="board",
                mark="managed",
            ).reason,
            "not_in_manifest",
        )
        self.assertEqual(
            record_call(
                book,
                app_id="jellyfin",
                advisor="media",
                tool="health",
                actor="board",
                mark="managed",
            ).reason,
            "not_in_manifest",
        )
        self.assertEqual(
            accept_tool(
                book,
                app_id="jellyfin",
                advisor="media",
                tool=["player"],
                actor="board",
                mark="managed",
            ).reason,
            "tool",
        )
        self.assertNotIn("jellyfin", book.accepted)
        self.assertEqual(
            record_call(
                book,
                app_id="jellyfin",
                advisor="media",
                tool=" player",
                actor="board",
                mark="managed",
            ).reason,
            "tool",
        )
        plain = _accept(book, "bazarr", "fetcher", "bazarr")
        self.assertEqual(plain.reason, "owner_accepted")
        asked = record_call(
            book,
            app_id="bazarr",
            advisor="fetcher",
            tool="bazarr",
            actor="board",
            mark="managed",
            note="The password is kept outside the machine",
        )
        self.assertEqual(asked.reason, "not_called")
        self.assertIn("outside the machine", shown(book, "bazarr").note)
        self.assertFalse(shown(book, "bazarr").called)
        self.assertEqual(shown(book, "missing").reason, "no_call")
        self.assertEqual(shown(book, "jellyfin").reason, "no_call")
        blank = record_call(
            book,
            app_id="bazarr",
            advisor="fetcher",
            tool="bazarr",
            actor="board",
            mark="managed",
            note="   ",
        )
        self.assertEqual(blank.reason, "already")
        self.assertIn("outside the machine", blank.note)
        fresh = Book()
        _accept(fresh, "prowlarr", "fetcher", "prowlarr")
        long_note = record_call(
            fresh,
            app_id="prowlarr",
            advisor="fetcher",
            tool="prowlarr",
            actor="board",
            mark="managed",
            note=("shelf " * 400),
        )
        self.assertEqual(long_note.reason, "not_called")
        self.assertLessEqual(len(long_note.note), 1200)
        self.assertFalse(long_note.called)
        self.assertFalse(long_note.pulled)
        torrent = _accept(fresh, "qbittorrent", "fetcher", "qbittorrent")
        self.assertFalse(torrent.swarm_stopped)
        self.assertFalse(torrent.called)
        source = Path(record_call.__code__.co_filename).read_text(encoding="utf-8")
        self.assertNotIn("urlopen", source)
        self.assertNotIn("subprocess", source)
        self.assertNotIn("import socket", source)
        self.assertNotIn("docker", source)
        self.assertNotIn("connect(", source)
        self.assertNotIn("catalog/wires", source)
        root = Path(record_call.__code__.co_filename).parents[1]
        ask = (root / "friday" / "ask.py").read_text(encoding="utf-8")
        self.assertNotIn("record_call", ask)
        self.assertNotIn("guests.call", ask)
        board = (root / "board" / "server.js").read_text(encoding="utf-8")
        self.assertNotIn("record_call", board)
        registry = (root / "guests" / "registry.py").read_text(encoding="utf-8")
        self.assertNotIn("record_call", registry)
        for name in ("start", "stop", "pull", "known"):
            text = (root / "guests" / f"{name}.py").read_text(encoding="utf-8")
            self.assertNotIn("record_call", text)
        gateway = (root / "gateway" / "server.py").read_text(encoding="utf-8")
        self.assertNotIn("record_call", gateway)


if __name__ == "__main__":
    unittest.main()
