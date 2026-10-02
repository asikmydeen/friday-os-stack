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
    restore_host,
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

    def test_a_blank_host_holds_the_pending_delivery_and_returns_the_memory(self):
        source, _ = _pause()
        _seal(source)
        manifest = dict(source.manifest)
        memory = [
            {
                "id": "n1",
                "owner_id": "owner",
                "owner_kind": "person",
                "content": "The password is kept outside the machine",
            }
        ]
        ledger = [
            {
                "id": "m1",
                "status": "pending",
                "idempotency_key": "delivery-m1",
                "sent_again": True,
            },
            {"id": "m2", "status": "uncertain", "idempotency_key": "delivery-m2"},
        ]
        host = Box()
        out = restore_host(
            host,
            actor="executor",
            approval_exchanged=True,
            manifest=manifest,
            memory=memory,
            ledger=ledger,
            points=["note-1"],
            collections=["friday_profile", "knowledge"],
            containers_running=True,
            confirmed=True,
        )
        self.assertEqual(out.reason, "blank_host")
        self.assertEqual(host.memory, memory)
        self.assertEqual(host.ledger[0]["status"], "pending")
        self.assertEqual(host.ledger[1]["status"], "uncertain")
        self.assertEqual(host.ledger[0]["idempotency_key"], "delivery-m1")
        self.assertFalse(host.ledger[0]["sent_again"])
        self.assertFalse(host.ledger[1]["sent_again"])
        self.assertFalse(host.started)
        self.assertFalse(host.copied)
        self.assertFalse(host.wiped)
        self.assertEqual(host.created, ())
        self.assertEqual(host.points, ("note-1",))
        self.assertEqual(host.collections, ("friday_profile", "knowledge"))
        self.assertNotIn("passphrase", host.manifest)
        self.assertEqual(send(host).reason, "workers_paused")
        self.assertEqual(mutate(host, "install").reason, "writers_paused")
        self.assertNotIn("boot_old_slot", host.events)
        self.assertNotIn("delivery-m1", host.events)
        manifest["catalog_pin"] = "changed-after"
        self.assertNotEqual(host.manifest["catalog_pin"], "changed-after")

        asked = reconcile(host, "m1", "unknown")
        self.assertEqual(asked.reason, "owner_asked")
        self.assertEqual(host.ledger[0]["status"], "held")
        self.assertFalse(host.ledger[0]["sent_again"])
        self.assertEqual(host.ledger[0]["idempotency_key"], "delivery-m1")
        self.assertEqual(send(host).reason, "workers_paused")

        other = Box()
        restore_host(
            other,
            actor="executor",
            approval_exchanged=True,
            manifest=source.manifest,
            memory=memory,
            ledger=[{"id": "m1", "status": "pending", "idempotency_key": "delivery-m1"}],
            confirmed=True,
        )
        never = reconcile(other, "m1", "never_accepted")
        self.assertEqual(never.reason, "owner_asked")
        self.assertFalse(other.ledger[0]["sent_again"])
        self.assertEqual(other.ledger[0]["idempotency_key"], "delivery-m1")
        self.assertEqual(send(other).reason, "workers_paused")

        restarted = restore_host(
            source,
            actor="executor",
            approval_exchanged=True,
            manifest=source.manifest,
            memory=memory,
            ledger=ledger,
            confirmed=True,
        )
        self.assertEqual(restarted.reason, "not_a_blank_host")
        self.assertNotIn("restore_blank", source.events)
        self.assertEqual(source.memory, [])

        pinned = dict(source.manifest)
        pinned["catalog_pin"] = "a" * 40
        pinned["image_digests"] = ["sha256:" + ("ab" * 32)]
        pin_host = Box()
        pin_out = restore_host(
            pin_host,
            actor="executor",
            approval_exchanged=True,
            manifest=pinned,
            memory=memory,
            ledger=ledger,
        )
        self.assertEqual(pin_out.reason, "blank_host")
        self.assertEqual(pin_host.manifest["catalog_pin"], "a" * 40)
        self.assertEqual(pin_host.manifest["image_digests"], ["sha256:" + ("ab" * 32)])
        self.assertNotIn("a" * 40, pin_host.events)

        pair = Box()
        restore_host(
            pair,
            actor="executor",
            approval_exchanged=True,
            manifest=source.manifest,
            memory=memory,
            ledger=ledger,
        )
        first = reconcile(pair, "m1", "accepted")
        self.assertEqual(first.reason, "delivered")
        self.assertEqual(pair.ledger[1]["status"], "uncertain")
        self.assertFalse(pair.ledger[1]["sent_again"])
        self.assertEqual(send(pair).reason, "workers_paused")
        second = reconcile(pair, "m2", "accepted")
        self.assertEqual(second.reason, "delivered")
        self.assertEqual(send(pair).outcome, "sent")
        self.assertNotIn("delivery-m1", pair.events)
        self.assertNotIn("delivery-m2", pair.events)

    def test_blank_host_refuses_chat_a_credential_and_a_wipe(self):
        source, _ = _pause()
        _seal(source)
        manifest = source.manifest
        memory = [
            {
                "id": "n1",
                "owner_id": "owner",
                "owner_kind": "person",
                "content": "The password is kept outside the machine",
            }
        ]
        ledger = [{"id": "m1", "status": "pending"}]
        host = Box()
        chat = restore_host(
            host,
            actor="chat",
            approval_exchanged=True,
            manifest=manifest,
            memory=memory,
            ledger=ledger,
            confirmed=True,
        )
        self.assertEqual(chat.reason, "actor_cannot_backup")
        self.assertEqual(host.events, [])
        self.assertIsNone(host.manifest)

        unapproved = restore_host(
            host,
            actor="executor",
            approval_exchanged=False,
            manifest=manifest,
            memory=memory,
            ledger=ledger,
            confirmed=True,
        )
        self.assertEqual(unapproved.reason, "approval_required")
        self.assertIsNone(host.manifest)

        wiped = restore_host(
            host,
            actor="executor",
            approval_exchanged=True,
            manifest=manifest,
            memory=memory,
            ledger=ledger,
            points=["note-1"],
            wipe=True,
        )
        self.assertEqual(wiped.reason, "points_stay")
        self.assertEqual(host.points, ())
        self.assertFalse(host.wiped)

        secret = restore_host(
            host,
            actor="executor",
            approval_exchanged=True,
            manifest=manifest,
            memory=[
                {
                    "id": "n1",
                    "owner_id": "owner",
                    "owner_kind": "person",
                    "content": "token=abcd",
                }
            ],
            ledger=ledger,
        )
        self.assertEqual(secret.reason, "credential")
        self.assertEqual(host.memory, [])
        self.assertIsNone(host.manifest)

        hunter = restore_host(
            host,
            actor="executor",
            approval_exchanged=True,
            manifest=manifest,
            memory=[
                {
                    "id": "n1",
                    "owner_id": "owner",
                    "owner_kind": "person",
                    "content": "password is hunter22",
                }
            ],
            ledger=[{"id": "m1", "status": "pending", "idempotency_key": "token=abcd"}],
        )
        self.assertEqual(hunter.reason, "credential")
        self.assertEqual(host.memory, [])
        self.assertNotIn("hunter22", host.events)

        shaped = dict(manifest)
        shaped["passphrase"] = "kept-outside"
        leaked = restore_host(
            host,
            actor="executor",
            approval_exchanged=True,
            manifest=shaped,
            memory=memory,
            ledger=ledger,
        )
        self.assertEqual(leaked.reason, "passphrase_in_manifest")
        self.assertIsNone(host.manifest)
        self.assertNotIn("kept-outside", host.events)

        odd = restore_host(
            host,
            actor="executor",
            approval_exchanged=True,
            manifest=manifest,
            memory="the notes",
            ledger=ledger,
        )
        self.assertEqual(odd.reason, "missing_memory")

        closed = restore_host(
            host,
            actor="executor",
            approval_exchanged=True,
            manifest=manifest,
            memory=memory,
            ledger=ledger,
            collections=["family_shared"],
        )
        self.assertEqual(closed.reason, "collection_closed")
        self.assertEqual(host.collections, ())
        self.assertEqual(host.created, ())

        newline = restore_host(
            host,
            actor="executor",
            approval_exchanged=True,
            manifest=manifest,
            memory=[
                {
                    "id": "n1",
                    "owner_id": "owner\n",
                    "owner_kind": "person",
                    "content": "The password is kept outside the machine",
                }
            ],
            ledger=ledger,
        )
        self.assertEqual(newline.reason, "missing_owner")
        self.assertEqual(host.memory, [])

        token_pin = dict(manifest)
        token_pin["catalog_pin"] = "token=abcd"
        refused_pin = restore_host(
            host,
            actor="executor",
            approval_exchanged=True,
            manifest=token_pin,
            memory=memory,
            ledger=ledger,
        )
        self.assertEqual(refused_pin.reason, "credential")
        self.assertIsNone(host.manifest)
        self.assertNotIn("abcd", host.events)

        token_digest = dict(manifest)
        token_digest["image_digests"] = ["token=abcd"]
        refused_digest = restore_host(
            host,
            actor="executor",
            approval_exchanged=True,
            manifest=token_digest,
            memory=memory,
            ledger=ledger,
        )
        self.assertEqual(refused_digest.reason, "credential")
        self.assertIsNone(host.manifest)
        self.assertNotIn("abcd", host.events)


if __name__ == "__main__":
    unittest.main()
