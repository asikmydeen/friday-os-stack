"""Guest install stays closed. Adopt does not start a second copy.

A managed removal records grants and one tunnel name. It does not stop
the container or delete the library.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from guests.lifecycle import (
    Book,
    adopt,
    bundle,
    confirm_delete,
    disconnect,
    install_guest,
    record_removal,
    uninstall,
)

KEPT = "The password is kept outside the machine"


class GuestTests(unittest.TestCase):
    def test_install_and_the_bundle_stay_closed(self) -> None:
        for app_id in ("jellyfin", "plex", "home-assistant", "radarr"):
            decision = install_guest(app_id, confirmed=True)
            self.assertEqual(decision.reason, "catalog_install_closed")
        self.assertEqual(bundle("jellyfin", confirmed=True).reason, "catalog_install_closed")
        self.assertEqual(bundle("plex").reason, "catalog_install_closed")
        self.assertEqual(bundle("home-assistant").reason, "not_in_bundle")

    def test_adopt_records_the_app_and_does_not_start_it_here(self) -> None:
        decision = adopt("plex")
        self.assertEqual(decision.reason, "adopted")
        self.assertEqual(decision.mark, "adopted")
        self.assertIs(decision.running_here, False)

    def test_disconnect_leaves_an_adopted_app_running(self) -> None:
        decision = disconnect("adopted")
        self.assertEqual(decision.reason, "left_running")
        self.assertIs(decision.running_here, True)
        self.assertEqual(disconnect("managed").reason, "not_adopted")

    def test_a_managed_uninstall_keeps_the_files(self) -> None:
        kept = uninstall("managed")
        self.assertEqual(kept.reason, "files_kept")
        self.assertIs(kept.files_kept, True)
        self.assertIs(kept.library_kept, True)
        self.assertIs(kept.stopped, False)
        self.assertIs(kept.deleted, False)
        self.assertEqual(
            uninstall("managed", delete_files=True).reason,
            "files_need_their_own_confirm",
        )
        self.assertEqual(uninstall("adopted", delete_files=True).reason, "not_managed")

    def test_removal_records_grants_and_a_tunnel_name_and_stops_nothing(self) -> None:
        book = Book()
        decision = record_removal(
            book,
            actor="board",
            app_id="jellyfin",
            grants=["media_library", "media_library", KEPT],
            tunnel_name="board.example",
            confirmed=True,
        )
        self.assertEqual(decision.reason, "files_kept")
        self.assertEqual(decision.grants, ("media_library", KEPT))
        self.assertEqual(decision.tunnel_name, "board.example")
        self.assertIs(decision.files_kept, True)
        self.assertIs(decision.library_kept, True)
        self.assertIs(decision.stopped, False)
        self.assertIs(decision.deleted, False)
        self.assertIs(decision.started, False)
        self.assertIs(decision.called, False)
        self.assertEqual(repr(book), "Book()")

        later = record_removal(
            book,
            actor="board",
            app_id="jellyfin",
            grants=["other_tool"],
            tunnel_name="other.example",
            confirmed=True,
        )
        self.assertEqual(later.reason, "already")
        self.assertEqual(later.grants, ("media_library", KEPT))
        self.assertEqual(later.tunnel_name, "board.example")
        self.assertEqual(book.rows["jellyfin"].grants, ("media_library", KEPT))

        other = record_removal(
            book,
            actor="board",
            app_id="plex",
            grants=(),
            tunnel_name="",
        )
        self.assertEqual(other.reason, "files_kept")
        self.assertEqual(other.grants, ())
        self.assertEqual(other.tunnel_name, "")
        self.assertEqual(book.rows["jellyfin"].tunnel_name, "board.example")

    def test_chat_and_a_bad_list_leave_the_row(self) -> None:
        book = Book()
        record_removal(
            book,
            actor="board",
            app_id="jellyfin",
            grants=["media_library"],
            tunnel_name="board.example",
        )
        for actor in ("chat", "Chat", " chat "):
            refused = record_removal(
                book,
                actor=actor,
                app_id="jellyfin",
                grants=["replaced"],
                tunnel_name="gone.example",
                confirmed=True,
            )
            self.assertEqual(refused.reason, "chat_cannot")
            self.assertEqual(refused.grants, ())
        self.assertEqual(book.rows["jellyfin"].grants, ("media_library",))
        self.assertEqual(book.rows["jellyfin"].tunnel_name, "board.example")
        self.assertEqual(
            record_removal(book, actor="friday", app_id="sonarr", grants=["fetcher"]).reason,
            "actor_cannot",
        )
        self.assertNotIn("sonarr", book.rows)
        blocked = record_removal(
            book,
            actor="board",
            app_id="jellyfin",
            grants="media_library",
            tunnel_name="other.example",
        )
        self.assertEqual(blocked.reason, "grant_list")
        self.assertEqual(book.rows["jellyfin"].grants, ("media_library",))
        self.assertEqual(book.rows["jellyfin"].tunnel_name, "board.example")
        self.assertEqual(
            record_removal(book, actor="board", app_id="radarr", grants="not-a-list").reason,
            "grant_list",
        )
        self.assertNotIn("radarr", book.rows)

    def test_a_separate_confirm_does_not_delete_the_files(self) -> None:
        book = Book()
        record_removal(
            book,
            actor="board",
            app_id="jellyfin",
            grants=["media_library"],
            tunnel_name="board.example",
        )
        asked = record_removal(
            book,
            actor="board",
            app_id="jellyfin",
            grants=["media_library"],
            delete_files=True,
            confirmed=True,
        )
        self.assertEqual(asked.reason, "files_need_their_own_confirm")
        self.assertIs(asked.deleted, False)
        self.assertEqual(book.rows["jellyfin"].grants, ("media_library",))
        fresh = record_removal(
            book,
            actor="board",
            app_id="sonarr",
            grants=["fetcher"],
            delete_files=True,
        )
        self.assertEqual(fresh.reason, "files_need_their_own_confirm")
        self.assertNotIn("sonarr", book.rows)
        confirmed = confirm_delete(book, actor="board", app_id="jellyfin", confirmed=True)
        self.assertEqual(confirmed.reason, "files_not_deleted")
        self.assertIs(confirmed.deleted, False)
        self.assertIs(confirmed.files_kept, True)
        self.assertIs(confirmed.library_kept, True)
        self.assertIs(confirmed.stopped, False)
        self.assertEqual(confirmed.grants, ("media_library",))
        self.assertEqual(book.rows["jellyfin"].tunnel_name, "board.example")
        self.assertEqual(confirm_delete(book, actor="chat", app_id="jellyfin").reason, "chat_cannot")
        self.assertEqual(confirm_delete(book, actor="board", app_id="missing").reason, "unknown_app")
        self.assertNotIn("missing", book.rows)
        self.assertEqual(
            record_removal(book, actor="board", app_id="plex", mark="adopted", grants=[]).reason,
            "not_managed",
        )
        self.assertNotIn("plex", book.rows)

    def test_a_credential_shaped_name_is_not_stored(self) -> None:
        book = Book()
        record_removal(
            book,
            actor="board",
            app_id="jellyfin",
            grants=["media_library"],
            tunnel_name=KEPT,
        )
        for name in ("token=abcd", "password is hunter22", "token%3Dabcd", "password+is+hunter22"):
            for call in (
                record_removal(book, actor="board", app_id=name, grants=["media_library"]),
                record_removal(book, actor="board", app_id="radarr", grants=[name]),
                record_removal(book, actor="board", app_id="radarr", grants=[], tunnel_name=name),
                confirm_delete(book, actor="board", app_id=name),
            ):
                self.assertEqual(call.reason, "credential")
                self.assertNotIn("abcd", repr(call))
                self.assertNotIn("hunter22", repr(call))
                self.assertEqual(call.app_id, "")
                self.assertEqual(call.grants, ())
        self.assertEqual(set(book.rows), {"jellyfin"})
        self.assertEqual(book.rows["jellyfin"].tunnel_name, KEPT)
        self.assertEqual(book.rows["jellyfin"].grants, ("media_library",))
        self.assertNotIn("hunter22", repr(book))
        self.assertEqual(record_removal(book, actor="board", app_id=" jellyfin", grants=[]).reason, "app_id")
        self.assertEqual(record_removal(book, actor="board", app_id="jellyfin\n", grants=[]).reason, "app_id")

    def test_ask_does_not_call_this_module(self) -> None:
        text = Path("friday/ask.py").read_text(encoding="utf-8")
        self.assertNotIn("record_removal", text)
        self.assertNotIn("confirm_delete", text)
        self.assertNotIn("guests", text)


if __name__ == "__main__":
    unittest.main()
