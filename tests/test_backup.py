"""Coordinated backup: pause, manifest, upgrade, restore."""

import unittest

from backup.coordinated import (
    begin_pause,
    boot_crash,
    capture,
    mutate,
    plan_upgrade,
    ready,
    reconcile,
    restore_ledger,
    resume_writers,
    seal_manifest,
    send,
)
from backup.coordinated import Box


def _pause(box=None, **overrides):
    box = box or Box()
    fields = dict(
        actor="executor",
        approval_exchanged=True,
        confirmed=False,
        free_bytes=20,
        live_bytes=10,
        passphrase_outside=True,
        inflight="finished",
    )
    fields.update(overrides)
    return box, begin_pause(box, **fields)


def _seal(box):
    for store, method in (
        ("postgres", "dump"),
        ("qdrant", "snapshot"),
        ("sqlite", "backup_api"),
    ):
        capture(box, store, method=method)
    return seal_manifest(
        box,
        registry=[{"id": "jellyfin", "mark": "adopted"}],
        catalog_pin="pin-1",
        image_digests=["sha256:abc"],
        include_journal=True,
        include_soul=True,
        include_secrets=True,
        passphrase_in_manifest=False,
        include_names=[],
    )


class BackupTests(unittest.TestCase):
    def test_chat_cannot_pause_even_with_a_flag(self):
        box, out = _pause(actor="chat", confirmed=True)
        self.assertEqual(out.reason, "actor_cannot_backup")
        self.assertEqual(box.writers, "running")

    def test_confirmed_flag_does_not_replace_the_approval(self):
        _, out = _pause(approval_exchanged=False, confirmed=True)
        self.assertEqual(out.reason, "approval_required")

    def test_no_room_and_missing_passphrase_refuse(self):
        _, tight = _pause(free_bytes=9, live_bytes=10)
        self.assertEqual(tight.reason, "no_backup_room")
        _, secret = _pause(passphrase_outside=False)
        self.assertEqual(secret.reason, "passphrase_outside")

    def test_ambiguous_step_and_live_sqlite_store_nothing(self):
        box, out = _pause(inflight="ambiguous")
        self.assertEqual(out.reason, "step_ambiguous")
        box, paused = _pause()
        self.assertEqual(paused.outcome, "paused")
        live = capture(box, "sqlite", method="live_file")
        self.assertEqual(live.reason, "live_sqlite")
        self.assertNotIn("sqlite", box.captures)
        movies = capture(box, "movies", method="dump")
        self.assertEqual(movies.reason, "optional_app_excluded")

    def test_capture_before_pause_is_refused(self):
        box = Box()
        out = capture(box, "postgres", method="dump")
        self.assertEqual(out.reason, "not_paused")
        self.assertEqual(box.captures, {})

    def test_mutation_waits_until_writers_resume(self):
        box, _ = _pause()
        self.assertEqual(mutate(box, "install").reason, "writers_paused")
        self.assertEqual(mutate(box, "disconnect").reason, "writers_paused")
        _seal(box)
        self.assertEqual(resume_writers(box).outcome, "resumed")
        self.assertEqual(mutate(box, "install").outcome, "allowed")

    def test_manifest_keeps_the_passphrase_out_and_names_the_pause(self):
        box, _ = _pause()
        out = _seal(box)
        self.assertEqual(out.outcome, "manifested")
        self.assertFalse(box.manifest["passphrase_in_manifest"])
        self.assertNotIn("passphrase", box.manifest)
        self.assertEqual(box.manifest["excluded"], ["jellyfin_config", "movies", "optional_apps"])
        self.assertEqual(box.manifest["registry"][0]["mark"], "adopted")
        self.assertLess(box.events.index("pause"), box.events.index("capture:postgres"))
        self.assertLess(box.events.index("capture:sqlite"), box.events.index("manifest"))

    def test_manifest_refuses_a_missing_journal_or_a_bad_mark(self):
        box, _ = _pause()
        capture(box, "postgres", method="dump")
        capture(box, "qdrant", method="snapshot")
        capture(box, "sqlite", method="backup_api")
        missing = seal_manifest(
            box,
            registry=[{"id": "jellyfin", "mark": "adopted"}],
            catalog_pin="pin-1",
            image_digests=["sha256:abc"],
            include_journal=False,
            include_soul=True,
            include_secrets=True,
            passphrase_in_manifest=False,
            include_names=[],
        )
        self.assertEqual(missing.reason, "journal_required")
        movies = seal_manifest(
            box,
            registry=[{"id": "jellyfin", "mark": "adopted"}],
            catalog_pin="pin-1",
            image_digests=["sha256:abc"],
            include_journal=True,
            include_soul=True,
            include_secrets=True,
            passphrase_in_manifest=False,
            include_names=["movies"],
        )
        self.assertEqual(movies.reason, "optional_app_excluded")
        marked = seal_manifest(
            box,
            registry=[{"id": "jellyfin", "mark": "guest"}],
            catalog_pin="pin-1",
            image_digests=["sha256:abc"],
            include_journal=True,
            include_soul=True,
            include_secrets=True,
            passphrase_in_manifest=True,
            include_names=[],
        )
        self.assertEqual(marked.reason, "passphrase_in_manifest")
        marked = seal_manifest(
            box,
            registry=[{"id": "jellyfin", "mark": "guest"}],
            catalog_pin="pin-1",
            image_digests=["sha256:abc"],
            include_journal=True,
            include_soul=True,
            include_secrets=True,
            passphrase_in_manifest=False,
            include_names=[],
        )
        self.assertEqual(marked.reason, "registry_mark")

    def test_upgrade_writes_the_inactive_slot_only(self):
        box, _ = _pause()
        _seal(box)
        same = plan_upgrade(
            box,
            actor="executor",
            approval_exchanged=True,
            target_slot="A",
            free_bytes=20,
            live_bytes=10,
        )
        self.assertEqual(same.reason, "running_slot")
        out = plan_upgrade(
            box,
            actor="chat",
            approval_exchanged=True,
            target_slot="B",
            free_bytes=20,
            live_bytes=10,
        )
        self.assertEqual(out.reason, "actor_cannot_backup")
        out = plan_upgrade(
            box,
            actor="executor",
            approval_exchanged=True,
            target_slot="B",
            free_bytes=20,
            live_bytes=10,
        )
        self.assertEqual(out.reason, "uncommitted")
        self.assertEqual(box.slot_image["A"], "running-image")
        self.assertEqual(box.slot_image["B"], "new-image")
        self.assertEqual(box.running_slot, "A")
        self.assertEqual(box.data_generation, 1)

    def test_failed_ready_restores_before_the_old_slot_boots(self):
        box, _ = _pause()
        _seal(box)
        plan_upgrade(
            box,
            actor="executor",
            approval_exchanged=True,
            target_slot="B",
            free_bytes=20,
            live_bytes=10,
        )
        out = ready(box, ok=False)
        self.assertEqual(out.reason, "ready_failed")
        restore_at = box.events.index("restore_backup")
        boot_at = box.events.index("boot_old_slot")
        release_at = box.events.index("release_writers")
        self.assertLess(restore_at, boot_at)
        self.assertLess(boot_at, release_at)
        self.assertEqual(box.running_slot, "A")
        self.assertEqual(box.committed_slot, "A")
        self.assertEqual(box.data_generation, 0)
        self.assertEqual(box.slot_image["A"], "running-image")
        self.assertEqual(box.writers, "running")
        self.assertEqual(box.workers, "paused")
        self.assertEqual(send(box).reason, "workers_paused")

    def test_power_loss_and_exhausted_attempts_use_the_same_restore(self):
        box, _ = _pause()
        _seal(box)
        plan_upgrade(
            box,
            actor="executor",
            approval_exchanged=True,
            target_slot="B",
            free_bytes=20,
            live_bytes=10,
        )
        self.assertEqual(ready(box, ok=True, power_lost=True).reason, "power_lost")
        self.assertEqual(box.data_generation, 0)
        self.assertLess(
            box.events.index("restore_backup"),
            box.events.index("boot_old_slot"),
        )

        box, _ = _pause()
        _seal(box)
        plan_upgrade(
            box,
            actor="executor",
            approval_exchanged=True,
            target_slot="B",
            free_bytes=20,
            live_bytes=10,
        )
        self.assertEqual(boot_crash(box).reason, "attempts_left")
        self.assertEqual(boot_crash(box).reason, "attempts_left")
        self.assertEqual(box.data_generation, 1)
        self.assertEqual(boot_crash(box).reason, "attempts_exhausted")
        self.assertEqual(box.data_generation, 0)
        self.assertEqual(box.running_slot, "A")

    def test_a_ready_slot_is_committed_and_the_old_image_remains(self):
        box, _ = _pause()
        _seal(box)
        plan_upgrade(
            box,
            actor="executor",
            approval_exchanged=True,
            target_slot="B",
            free_bytes=20,
            live_bytes=10,
        )
        out = ready(box, ok=True)
        self.assertEqual(out.reason, "committed")
        self.assertEqual(box.running_slot, "B")
        self.assertEqual(box.committed_slot, "B")
        self.assertEqual(box.slot_image["A"], "running-image")
        self.assertEqual(box.writers, "running")
        self.assertEqual(send(box).outcome, "sent")

    def test_restored_10_00_ledger_does_not_send_the_10_05_delivery_again(self):
        box, _ = _pause()
        _seal(box)
        saved = [{"id": "m1", "status": "pending", "sent_again": False}]
        restore_ledger(box, saved)
        self.assertEqual(box.ledger[0]["status"], "pending")
        self.assertEqual(send(box).reason, "workers_paused")
        accepted = reconcile(box, "m1", "accepted")
        self.assertEqual(accepted.reason, "delivered")
        self.assertFalse(box.ledger[0]["sent_again"])
        self.assertEqual(send(box).outcome, "sent")

        box, _ = _pause()
        _seal(box)
        restore_ledger(box, [{"id": "m1", "status": "pending", "sent_again": False}])
        unknown = reconcile(box, "m1", "unknown")
        self.assertEqual(unknown.reason, "owner_asked")
        self.assertEqual(box.ledger[0]["status"], "held")
        self.assertFalse(box.ledger[0]["sent_again"])
        self.assertEqual(send(box).reason, "workers_paused")

        box, _ = _pause()
        _seal(box)
        restore_ledger(box, [{"id": "m1", "status": "pending", "sent_again": False}])
        rejected = reconcile(box, "m1", "rejected")
        self.assertEqual(rejected.reason, "owner_asked")
        self.assertFalse(box.ledger[0]["sent_again"])


if __name__ == "__main__":
    unittest.main()
