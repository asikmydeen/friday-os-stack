"""Pause, copy, and restore as one backup.

Delivery workers, the index reconciler, and executor mutations stop
before Postgres, Qdrant, and SQLite are copied. SQLite uses the backup
API or a clean shutdown. The manifest includes the executor journal,
the soul, the app registry, and the secrets volume. The passphrase is
not stored. Jellyfin config and movie files are excluded.

An upgrade writes the inactive slot only, with writers still paused.
If /ready fails, the boot attempts run out, or power is lost, the
pre-upgrade backup is restored, then the old slot boots, then machine
writers are released. Delivery workers stay paused until each restored
pending item has asked the provider. Chat cannot run any of this.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

ACTORS = frozenset({"executor"})
MUTATIONS = frozenset({"install", "start", "stop", "disconnect"})
STORES = ("postgres", "qdrant", "sqlite")
SQLITE_METHODS = frozenset({"backup_api", "clean_shutdown"})
MARKS = frozenset({"managed", "adopted"})
EXCLUDED = frozenset({"jellyfin_config", "movies", "optional_apps"})
SLOTS = frozenset({"A", "B"})


@dataclass(frozen=True)
class Outcome:
    outcome: str
    reason: str
    manifest_id: str | None = None


class Box:
    def __init__(self) -> None:
        self.writers = "running"
        self.workers = "running"
        self.running_slot = "A"
        self.committed_slot = "A"
        self.slot_image = {"A": "running-image", "B": None}
        self.uncommitted: str | None = None
        self.attempts_left: int | None = None
        self.inflight: str | None = None
        self.captures: dict[str, str] = {}
        self.manifest: dict | None = None
        self.manifest_fresh = False
        self.data_generation = 0
        self.restored = False
        self.ledger: list[dict] = []
        self.events: list[str] = []


def begin_pause(
    box: Box,
    *,
    actor: str,
    approval_exchanged: bool,
    confirmed: bool,
    free_bytes: int,
    live_bytes: int,
    passphrase_outside: bool,
    inflight: str | None,
) -> Outcome:
    del confirmed  # a model flag never counts as the approval
    if actor not in ACTORS:
        return Outcome("refused", "actor_cannot_backup")
    if not approval_exchanged:
        return Outcome("refused", "approval_required")
    if free_bytes < live_bytes:
        return Outcome("refused", "no_backup_room")
    if not passphrase_outside:
        return Outcome("refused", "passphrase_outside")
    if inflight == "ambiguous":
        return Outcome("refused", "step_ambiguous")
    box.inflight = inflight
    box.captures = {}
    box.manifest_fresh = False
    box.writers = "paused"
    box.workers = "paused"
    box.events.append("pause")
    return Outcome("paused", "paused")


def mutate(box: Box, operation: str) -> Outcome:
    if operation in MUTATIONS and box.writers == "paused":
        return Outcome("refused", "writers_paused")
    return Outcome("allowed", "allowed")


def capture(box: Box, store: str, *, method: str) -> Outcome:
    if box.writers != "paused":
        return Outcome("refused", "not_paused")
    if store in EXCLUDED:
        return Outcome("refused", "optional_app_excluded")
    if store not in STORES:
        return Outcome("refused", "unknown_store")
    if method == "live_file":
        return Outcome("refused", "live_sqlite")
    if store == "sqlite" and method not in SQLITE_METHODS:
        return Outcome("refused", "sqlite_method")
    box.captures[store] = method
    box.events.append(f"capture:{store}")
    return Outcome("captured", "captured")


def seal_manifest(
    box: Box,
    *,
    registry: list[dict],
    catalog_pin: str,
    image_digests: list[str],
    include_journal: bool,
    include_soul: bool,
    include_secrets: bool,
    passphrase_in_manifest: bool,
    include_names: list[str],
) -> Outcome:
    if box.writers != "paused":
        return Outcome("refused", "not_paused")
    if any(name in EXCLUDED for name in include_names):
        return Outcome("refused", "optional_app_excluded")
    if any(store not in box.captures for store in STORES):
        return Outcome("refused", "capture_missing")
    if box.captures["sqlite"] not in SQLITE_METHODS:
        return Outcome("refused", "live_sqlite")
    if not include_journal:
        return Outcome("refused", "journal_required")
    if not include_soul:
        return Outcome("refused", "soul_required")
    if not include_secrets:
        return Outcome("refused", "secrets_required")
    if passphrase_in_manifest:
        return Outcome("refused", "passphrase_in_manifest")
    if not registry or any(row.get("mark") not in MARKS for row in registry):
        return Outcome("refused", "registry_mark")
    manifest_id = str(uuid.uuid4())
    box.manifest = {
        "id": manifest_id,
        "stores": dict(box.captures),
        "journal": True,
        "soul": True,
        "secrets_encrypted": True,
        "passphrase_in_manifest": False,
        "registry": [dict(row) for row in registry],
        "catalog_pin": catalog_pin,
        "image_digests": list(image_digests),
        "excluded": sorted(EXCLUDED),
        "data_generation": box.data_generation,
    }
    box.manifest_fresh = True
    box.events.append("manifest")
    return Outcome("manifested", "manifested", manifest_id=manifest_id)


def resume_writers(box: Box) -> Outcome:
    if not box.manifest_fresh:
        return Outcome("refused", "manifest_missing")
    if box.uncommitted is not None:
        return Outcome("refused", "slot_uncommitted")
    box.writers = "running"
    box.manifest_fresh = False
    if not box.restored:
        box.workers = "running"
    box.events.append("resume")
    return Outcome("resumed", "resumed")


def plan_upgrade(
    box: Box,
    *,
    actor: str,
    approval_exchanged: bool,
    target_slot: str,
    free_bytes: int,
    live_bytes: int,
) -> Outcome:
    if actor not in ACTORS:
        return Outcome("refused", "actor_cannot_backup")
    if not approval_exchanged:
        return Outcome("refused", "approval_required")
    if not box.manifest_fresh or box.manifest is None:
        return Outcome("refused", "backup_required")
    if target_slot == box.running_slot:
        return Outcome("refused", "running_slot")
    if target_slot not in SLOTS:
        return Outcome("refused", "unknown_slot")
    if free_bytes < live_bytes:
        return Outcome("refused", "no_backup_room")
    if box.writers != "paused":
        return Outcome("refused", "not_paused")
    box.slot_image[target_slot] = "new-image"
    box.uncommitted = target_slot
    box.attempts_left = 3
    box.data_generation += 1
    box.events.append("write_inactive")
    box.events.append("migrate")
    return Outcome("upgraded", "uncommitted")


def ready(box: Box, *, ok: bool, power_lost: bool = False) -> Outcome:
    if box.uncommitted is None:
        return Outcome("refused", "no_upgrade")
    if power_lost:
        return _rollback(box, "power_lost")
    if not ok:
        return _rollback(box, "ready_failed")
    box.committed_slot = box.uncommitted
    box.running_slot = box.uncommitted
    box.uncommitted = None
    box.attempts_left = None
    box.manifest_fresh = False
    box.writers = "running"
    box.workers = "running"
    box.restored = False
    box.events.append("commit_slot")
    box.events.append("release_writers")
    return Outcome("committed", "committed")


def boot_crash(box: Box) -> Outcome:
    if box.uncommitted is None or box.attempts_left is None:
        return Outcome("refused", "no_upgrade")
    box.attempts_left -= 1
    box.events.append("boot_attempt")
    if box.attempts_left <= 0:
        return _rollback(box, "attempts_exhausted")
    return Outcome("retry", "attempts_left")


def send(box: Box) -> Outcome:
    if box.workers == "paused":
        return Outcome("refused", "workers_paused")
    return Outcome("sent", "sent")


def reconcile(box: Box, item_id: str, provider: str) -> Outcome:
    if box.workers != "paused":
        return Outcome("refused", "not_held")
    item = next(row for row in box.ledger if row["id"] == item_id)
    box.events.append("asked_provider")
    if provider == "accepted":
        item["status"] = "delivered"
        item["sent_again"] = False
        box.workers = "running"
        return Outcome("reconciled", "delivered")
    item["status"] = "held"
    item["sent_again"] = False
    return Outcome("held", "owner_asked")


def restore_ledger(box: Box, saved: list[dict]) -> Outcome:
    if box.manifest is None:
        return Outcome("refused", "manifest_missing")
    box.ledger = [dict(row) for row in saved]
    box.workers = "paused"
    box.events.append("ledger_restored")
    return Outcome("restored", "ledger_pending")


def _rollback(box: Box, reason: str) -> Outcome:
    assert box.manifest is not None
    box.data_generation = box.manifest["data_generation"]
    box.restored = True
    box.events.append("restore_backup")
    box.events.append("boot_old_slot")
    box.uncommitted = None
    box.attempts_left = None
    box.manifest_fresh = False
    box.writers = "running"
    box.workers = "paused"
    box.events.append("release_writers")
    return Outcome("restored", reason)
