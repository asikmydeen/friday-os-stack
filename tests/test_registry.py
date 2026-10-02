"""The app registry reads rows. It does not install or stop anything."""

from __future__ import annotations

import unittest

from guests.registry import Book, check_service, install, memory_use, observe, restore, stop, whats_running


def _plex(**overrides) -> dict:
    row = {
        "id": "plex",
        "train": "stable",
        "version": "1.40.0",
        "status": "running",
        "image": "plexinc/pms-docker:1.40.0",
        "ports": ["127.0.0.1:32400"],
        "folders": ["/disks/apps/library/movies"],
        "storage_disk": "/disks/apps",
        "storage_device": "disk-apps",
        "data_device": "disk-data",
        "health_url": "http://192.168.1.20:32400/identity",
        "memory_limit": 512,
        "wire_level": "known",
        "mark": "adopted",
    }
    row.update(overrides)
    return row


class RegistryTests(unittest.TestCase):
    def test_observe_records_an_adopted_app_and_does_not_start_it(self) -> None:
        book = Book()
        decision = observe(book, _plex(), confirmed=True)
        self.assertEqual(decision.reason, "adopted")
        self.assertEqual(book.apps["plex"].mark, "adopted")
        self.assertEqual(book.apps["plex"].status, "running")
        self.assertIs(decision.stopped, False)

    def test_install_writes_nothing(self) -> None:
        book = Book()
        observe(book, _plex())
        before = dict(book.apps)
        decision = install(book, _plex(mark="managed"), confirmed=True)
        self.assertEqual(decision.reason, "catalog_install_closed")
        self.assertEqual(book.apps, before)
        self.assertNotIn("jellyfin", book.apps)

    def test_check_and_running_read_the_row_and_do_not_probe(self) -> None:
        book = Book()
        observe(book, _plex())
        observe(book, _plex(id="sonarr", status="stopped", ports=["127.0.0.1:8989"]))
        checked = check_service(book, "plex")
        self.assertEqual(checked.reason, "not_probed")
        self.assertEqual(checked.status, "running")
        self.assertEqual(checked.health_url, "http://192.168.1.20:32400/identity")
        self.assertEqual(checked.wire_level, "known")
        self.assertIs(checked.tools_on, False)
        self.assertEqual(whats_running(book).running, ("plex",))
        self.assertEqual(check_service(book, "missing").reason, "unknown_app")
        self.assertEqual(check_service(book, "postgres").reason, "core_locked")

    def test_memory_is_the_declared_limit(self) -> None:
        book = Book()
        observe(book, _plex())
        decision = memory_use(book, "plex")
        self.assertEqual((decision.reason, decision.memory_limit), ("declared_not_measured", 512))
        self.assertEqual(memory_use(book, "postgres").reason, "core_locked")

    def test_stopping_adopted_plex_leaves_it_running(self) -> None:
        book = Book()
        observe(book, _plex())
        decision = stop(book, "plex", actor="chat", confirmed=True)
        self.assertEqual(decision.reason, "left_running")
        self.assertIs(decision.stopped, False)
        self.assertEqual(book.apps["plex"].status, "running")
        self.assertEqual(whats_running(book).running, ("plex",))
        self.assertEqual(stop(book, "plex", actor="board").reason, "left_running")

    def test_a_managed_stop_does_not_change_the_row(self) -> None:
        book = Book()
        observe(book, _plex(id="jellyfin"))
        restored = restore(book, [_plex(mark="managed")])
        self.assertEqual(restored.reason, "restored")
        before = book.apps["plex"].status
        decision = stop(book, "plex", actor="board", confirmed=True)
        self.assertEqual((decision.outcome, decision.reason), ("waiting", "not_stopped"))
        self.assertEqual(book.apps["plex"].status, before)
        self.assertIs(decision.stopped, False)
        self.assertNotIn("jellyfin", book.apps)
        chat = stop(book, "plex", actor="chat", confirmed=True)
        self.assertEqual(chat.reason, "actor_cannot_approve")
        self.assertEqual(book.apps["plex"].status, before)
        self.assertIs(chat.stopped, False)

    def test_a_bad_restore_leaves_the_book_in_place(self) -> None:
        book = Book()
        observe(book, _plex())
        decision = restore(book, [_plex(id="postgres")])
        self.assertEqual(decision.reason, "core_locked")
        self.assertIn("plex", book.apps)
        self.assertEqual(restore(book, [_plex(), _plex()]).reason, "duplicate")
        self.assertEqual(tuple(book.apps), ("plex",))
        self.assertEqual(restore(book, []).reason, "empty")
        self.assertIn("plex", book.apps)
        bare = _plex(mark="managed")
        bare.pop("storage_device")
        bare.pop("data_device")
        self.assertEqual(restore(book, [bare]).reason, "storage_device")
        self.assertEqual(book.apps["plex"].mark, "adopted")

    def test_folders_on_the_data_partition_or_through_a_symlink_are_refused(self) -> None:
        book = Book()
        data = observe(book, _plex(folders=["/var/lib/friday/library/movies"], storage_disk=None))
        self.assertEqual(data.reason, "data_partition")
        linked = observe(
            book,
            _plex(folders=["/disks/apps/link"], storage_disk="/disks/apps"),
            links={"/disks/apps/link": "/etc"},
        )
        self.assertEqual(linked.reason, "mount_forbidden")
        same_disk = observe(book, _plex(storage_device="disk-data", data_device="disk-data"))
        self.assertEqual(same_disk.reason, "storage_on_data_partition")
        public = observe(book, _plex(ports=["0.0.0.0:32400"]))
        self.assertEqual(public.reason, "ports")
        closed = observe(book, _plex(health_url="http://postgres:5432/"))
        self.assertEqual(closed.reason, "core_closed")
        named = observe(book, _plex(health_url="http://example.com/identity"))
        self.assertEqual(named.reason, "resolved")
        linked = observe(
            book,
            _plex(health_url="http://example.com/identity"),
            resolved={"example.com": ["169.254.169.254"]},
        )
        self.assertEqual(linked.reason, "link_local")
        kept = observe(
            book,
            _plex(health_url="http://example.com/identity"),
            resolved={"Example.com": ["192.168.1.20"]},
        )
        self.assertEqual(kept.reason, "adopted")
        self.assertEqual(tuple(book.apps), ("plex",))

    def test_enterprise_and_a_managed_observe_are_refused(self) -> None:
        book = Book()
        self.assertEqual(observe(book, _plex(train="enterprise")).reason, "train")
        self.assertEqual(observe(book, _plex(mark="managed")).reason, "not_adopted")
        self.assertEqual(observe(book, _plex(memory_limit=True)).reason, "memory_limit")
        self.assertEqual(book.apps, {})


if __name__ == "__main__":
    unittest.main()
