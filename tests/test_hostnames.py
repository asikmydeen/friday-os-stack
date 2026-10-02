"""One public name is recorded. The tunnel is not started."""

from __future__ import annotations

import unittest
from pathlib import Path

from doors.hostnames import Book, add_name, recheck


def _add(book: Book, **kwargs):
    fields = {
        "actor": "board",
        "name": "board",
        "service": "board",
        "access": "cloudflare_access",
        "enabled": True,
    }
    fields.update(kwargs)
    return add_name(book, **fields)


class HostnameTests(unittest.TestCase):
    def test_the_tunnel_stays_off_until_one_checked_name_is_recorded(self) -> None:
        book = Book()
        off = _add(book, enabled=False, confirmed=True)
        self.assertEqual((off.outcome, off.reason), ("off", "tunnel_off"))
        self.assertEqual(book.routes, {})
        self.assertIs(off.started, False)
        self.assertIs(off.created, False)
        self.assertIs(off.called_cloudflare, False)
        recorded = _add(book, name="friday", service="board")
        self.assertEqual((recorded.outcome, recorded.reason), ("recorded", "not_started"))
        self.assertEqual(recorded.service, "board")
        self.assertIs(recorded.exposed, False)
        self.assertEqual(set(book.routes), {"friday"})

    def test_one_name_at_a_time_and_a_second_call_can_name_a_player(self) -> None:
        book = Book()
        batch = add_name(
            book,
            actor="board",
            name=["board", "jellyfin"],
            service="board",
            access="cloudflare_access",
            enabled=True,
        )
        self.assertEqual(batch.reason, "one_at_a_time")
        self.assertEqual(book.routes, {})
        self.assertEqual(_add(book).reason, "not_started")
        player = _add(
            book,
            name="movies.example",
            service="jellyfin",
            access="app_login",
            wire_login_sufficient=True,
        )
        self.assertEqual((player.outcome, player.service), ("recorded", "jellyfin"))
        self.assertEqual(set(book.routes), {"board", "movies.example"})
        again = _add(book, name="board", service="jellyfin")
        self.assertEqual(again.reason, "already_recorded")
        self.assertEqual(book.routes["board"].service, "board")

    def test_core_routes_other_than_the_board_are_refused(self) -> None:
        book = Book()
        self.assertEqual(_add(book, service="friday").reason, "friday_not_a_route")
        for service in ("executor", "gateway", "ollama"):
            self.assertEqual(_add(book, name=service, service=service).reason, "board_only")
        self.assertEqual(book.routes, {})

    def test_unpublished_apps_stay_unnamed_and_the_swarm_is_not_stopped(self) -> None:
        book = Book()
        for service in (
            "memory-mcp",
            "qdrant",
            "postgres",
            "taskrunner",
            "radarr",
            "sonarr",
            "prowlarr",
            "qbittorrent",
        ):
            decision = _add(book, name=service, service=service, confirmed=True)
            self.assertEqual(decision.reason, "not_publishable")
            self.assertIs(decision.swarm_stopped, False)
        self.assertEqual(_add(book, service="home-assistant").reason, "route_not_listed")
        plex = _add(book, name="plex", service="plex")
        self.assertEqual(plex.reason, "not_started")
        self.assertEqual(book.routes["plex"].service, "plex")

    def test_the_app_login_counts_only_when_the_wire_says_so(self) -> None:
        book = Book()
        bare = _add(book, service="jellyfin", access="app_login", wire_login_sufficient=False)
        self.assertEqual(bare.reason, "login_not_sufficient")
        self.assertEqual(_add(book, access=True).reason, "access_unchecked")
        self.assertEqual(_add(book, access="").reason, "access_unchecked")
        checked = _add(
            book,
            name="movies.example",
            service="jellyfin",
            access=" App_Login ",
            wire_login_sufficient=True,
        )
        self.assertEqual(checked.reason, "not_started")
        self.assertEqual(book.routes["movies.example"].access, "app_login")

    def test_chat_cannot_add_a_name_or_store_a_token_value(self) -> None:
        book = Book()
        chat = _add(book, actor="chat", confirmed=True)
        self.assertEqual(chat.reason, "actor_cannot_approve")
        value = _add(book, token="hunter22")
        self.assertEqual(value.reason, "value_not_stored")
        self.assertNotIn("hunter22", repr(value))
        self.assertNotIn("hunter22", repr(book))
        named = _add(book, token_name="CLOUDFLARE_TUNNEL_TOKEN")
        self.assertEqual(named.token_name, "CLOUDFLARE_TUNNEL_TOKEN")
        self.assertEqual(book.routes["board"].token_name, "CLOUDFLARE_TUNNEL_TOKEN")
        self.assertEqual(repr(book), "Book()")
        self.assertEqual(_add(book, name="other", token_name="hunter22").reason, "secret_name")
        self.assertNotIn("other", book.routes)

    def test_a_failed_check_removes_the_name_even_if_a_container_is_running(self) -> None:
        book = Book()
        _add(book, name="movies.example", service="jellyfin")
        _add(book, name="board", service="board")
        chat = recheck(book, "movies.example", actor="chat", access_ok=False, container_running=True, confirmed=True)
        self.assertEqual(chat.reason, "actor_cannot_approve")
        self.assertEqual(set(book.routes), {"movies.example", "board"})
        fuzzy = recheck(book, "movies.example", actor="board", access_ok="yes", container_running=True)
        self.assertEqual(fuzzy.reason, "access_unchecked")
        self.assertIn("movies.example", book.routes)
        kept = recheck(book, "movies.example", actor="board", access_ok=True, container_running=True)
        self.assertEqual(kept.reason, "not_started")
        self.assertIs(kept.started, False)
        self.assertIs(kept.created, False)
        self.assertIs(kept.exposed, False)
        removed = recheck(book, "movies.example", actor="board", access_ok=False, container_running=True)
        self.assertEqual((removed.outcome, removed.reason), ("removed", "torn_down"))
        self.assertIs(removed.exposed, False)
        self.assertEqual(set(book.routes), {"board"})
        self.assertEqual(recheck(book, "movies.example", actor="board", access_ok="yes").reason, "unknown_name")

    def test_ask_does_not_call_this_module(self) -> None:
        text = Path("friday/ask.py").read_text(encoding="utf-8")
        self.assertNotIn("hostnames", text)
        self.assertNotIn("add_name", text)


if __name__ == "__main__":
    unittest.main()
