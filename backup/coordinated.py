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
pending item has asked the provider.

A blank host is a new box. It loads a caller-supplied manifest and
returns the same memory. A pending delivery stays pending until the
provider is asked. Accepting one delivery leaves any other delivery
pending, and the workers stay paused. An idempotency key is kept and
is not sent. A 40- or 64-character hex catalog pin is kept. A sha256
digest of 64 hex characters is kept. Restarting the box that sealed
the manifest is not that restore.
Nothing is copied and no container is started. Chat cannot run any of this.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from memoryd.store import credential_shape

ACTORS = frozenset({"executor"})
MUTATIONS = frozenset({"install", "start", "stop", "disconnect"})
STORES = ("postgres", "qdrant", "sqlite")
SQLITE_METHODS = frozenset({"backup_api", "clean_shutdown"})
MARKS = frozenset({"managed", "adopted"})
EXCLUDED = frozenset({"jellyfin_config", "movies", "optional_apps"})
SLOTS = frozenset({"A", "B"})
LEDGER_STATES = frozenset({"pending", "uncertain", "delivered", "held"})
COLLECTIONS = (
    "friday_profile",
    "friday_episodes",
    "friday_findings",
    "friday_persona",
    "knowledge",
    "cabinet_working",
)
_HEX = frozenset("0123456789abcdefABCDEF")


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
        self.memory: list[dict] = []
        self.points: tuple[str, ...] = ()
        self.collections: tuple[str, ...] = ()
        self.created: tuple[str, ...] = ()
        self.wiped = False
        self.started = False
        self.copied = False
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
        if all(row["status"] == "delivered" for row in box.ledger):
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


def restore_host(
    box: Box,
    *,
    actor: str,
    approval_exchanged: bool,
    manifest: object,
    memory: object,
    ledger: object,
    points: object = None,
    collections: object = None,
    containers_running: bool = False,
    wipe: object = False,
    confirmed: bool = False,
) -> Outcome:
    """Load one manifest onto a new box. Does not copy a disk or start one."""
    del confirmed, containers_running
    if actor not in ACTORS:
        return Outcome("refused", "actor_cannot_backup")
    if approval_exchanged is not True:
        return Outcome("refused", "approval_required")
    if wipe is not False:
        return Outcome("refused", "points_stay")
    if not _blank(box):
        return Outcome("refused", "not_a_blank_host")
    sealed = _manifest(manifest)
    if isinstance(sealed, str):
        return Outcome("refused", sealed)
    notes = _memory(memory)
    if isinstance(notes, str):
        return Outcome("refused", notes)
    deliveries = _ledger(ledger)
    if isinstance(deliveries, str):
        return Outcome("refused", deliveries)
    kept_points = _points(points)
    if isinstance(kept_points, str):
        return Outcome("refused", kept_points)
    kept = _collections(collections)
    if isinstance(kept, str):
        return Outcome("refused", kept)
    box.manifest = sealed
    box.manifest_fresh = False
    box.memory = notes
    box.ledger = deliveries
    box.points = kept_points
    box.collections = kept
    box.created = ()
    box.wiped = False
    box.started = False
    box.copied = False
    box.writers = "paused"
    box.workers = "paused"
    box.restored = True
    box.data_generation = sealed["data_generation"]
    box.events.append("restore_blank")
    box.events.append("ledger_pending")
    return Outcome("restored", "blank_host", manifest_id=sealed["id"])


def _blank(box: Box) -> bool:
    return (
        box.manifest is None
        and not box.events
        and not box.ledger
        and not box.memory
        and not box.captures
        and box.writers == "running"
        and box.workers == "running"
        and box.restored is False
        and box.data_generation == 0
        and box.uncommitted is None
        and box.started is False
        and box.copied is False
        and box.wiped is False
    )


def _hex_token(value: str, size: int) -> bool:
    return len(value) == size and all(char in _HEX for char in value)


def _hex_pin(value: str) -> bool:
    return _hex_token(value, 40) or _hex_token(value, 64)


def _kept_digest(value: str) -> bool:
    if value.startswith("sha256:") and _hex_token(value[7:], 64):
        return True
    if _hex_pin(value):
        return True
    return not credential_shape(value)


def _manifest(value: object) -> dict | str:
    if not isinstance(value, dict):
        return "manifest_missing"
    if "passphrase" in value or value.get("passphrase_in_manifest") is not False:
        return "passphrase_in_manifest"
    stores = value.get("stores")
    if not isinstance(stores, dict):
        return "capture_missing"
    if any(name in EXCLUDED for name in stores):
        return "optional_app_excluded"
    for store in STORES:
        if store not in stores:
            return "capture_missing"
    method = stores.get("sqlite")
    if method == "live_file":
        return "live_sqlite"
    if method not in SQLITE_METHODS:
        return "sqlite_method"
    if value.get("journal") is not True:
        return "journal_required"
    if value.get("soul") is not True:
        return "soul_required"
    if value.get("secrets_encrypted") is not True:
        return "secrets_required"
    excluded = value.get("excluded")
    if not isinstance(excluded, list) or any(name not in excluded for name in EXCLUDED):
        return "optional_app_excluded"
    registry = value.get("registry")
    if not isinstance(registry, list) or not registry:
        return "registry_mark"
    rows = []
    for row in registry:
        if not isinstance(row, dict) or row.get("mark") not in MARKS:
            return "registry_mark"
        app_id = row.get("id")
        if not isinstance(app_id, str) or app_id.strip() == "" or app_id != app_id.strip():
            return "registry_mark"
        if credential_shape(app_id):
            return "credential"
        rows.append({"id": app_id, "mark": row["mark"]})
    manifest_id = value.get("id")
    if not isinstance(manifest_id, str) or manifest_id.strip() == "":
        return "manifest_missing"
    if credential_shape(manifest_id):
        return "credential"
    generation = value.get("data_generation")
    if not isinstance(generation, int) or isinstance(generation, bool) or generation < 0:
        return "manifest_missing"
    pin = value.get("catalog_pin", "")
    if not isinstance(pin, str):
        return "manifest_missing"
    if not _hex_pin(pin) and credential_shape(pin):
        return "credential"
    digests = value.get("image_digests", [])
    if not isinstance(digests, list):
        return "manifest_missing"
    kept_digests: list[str] = []
    for item in digests:
        if not isinstance(item, str):
            return "manifest_missing"
        if not _kept_digest(item):
            return "credential"
        kept_digests.append(item)
    return {
        "id": manifest_id,
        "stores": {store: stores[store] for store in STORES},
        "journal": True,
        "soul": True,
        "secrets_encrypted": True,
        "passphrase_in_manifest": False,
        "registry": rows,
        "catalog_pin": pin,
        "image_digests": kept_digests,
        "excluded": sorted(EXCLUDED),
        "data_generation": generation,
    }


def _memory(value: object) -> list[dict] | str:
    if isinstance(value, str) or not isinstance(value, list):
        return "missing_memory"
    rows = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            return "missing_memory"
        owner = item.get("owner_id")
        kind = item.get("owner_kind")
        content = item.get("content")
        note_id = item.get("id")
        if (
            not isinstance(owner, str)
            or owner == ""
            or owner != owner.strip()
            or "\n" in owner
            or kind not in {"person", "role"}
        ):
            return "missing_owner"
        if not isinstance(note_id, str) or note_id == "" or note_id != note_id.strip():
            return "missing_memory"
        if note_id in seen:
            return "duplicate"
        if not isinstance(content, str) or content.strip() == "":
            return "empty_memory"
        if any(credential_shape(text) for text in (owner, note_id, content)):
            return "credential"
        seen.add(note_id)
        rows.append(
            {
                "id": note_id,
                "owner_id": owner,
                "owner_kind": kind,
                "content": content,
            }
        )
    return rows


def _ledger(value: object) -> list[dict] | str:
    if isinstance(value, str) or not isinstance(value, list):
        return "missing_ledger"
    rows = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            return "missing_ledger"
        item_id = item.get("id")
        status = item.get("status")
        if not isinstance(item_id, str) or item_id == "" or item_id != item_id.strip():
            return "missing_ledger"
        if item_id in seen:
            return "duplicate"
        if status not in LEDGER_STATES:
            return "ledger_status"
        key = item.get("idempotency_key")
        if key is not None and (not isinstance(key, str) or key.strip() == ""):
            return "idempotency_key"
        if credential_shape(item_id) or (isinstance(key, str) and credential_shape(key)):
            return "credential"
        seen.add(item_id)
        row = {"id": item_id, "status": status, "sent_again": False}
        if isinstance(key, str):
            row["idempotency_key"] = key
        rows.append(row)
    return rows


def _points(value: object) -> tuple[str, ...] | str:
    if value is None:
        return ()
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        return "missing_points"
    found = []
    for item in value:
        if not isinstance(item, str) or item == "" or item != item.strip():
            return "missing_points"
        if credential_shape(item):
            return "credential"
        found.append(item)
    return tuple(found)


def _collections(value: object) -> tuple[str, ...] | str:
    if value is None:
        return ()
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        return "missing_collections"
    names = []
    for item in value:
        if not isinstance(item, str) or item not in COLLECTIONS:
            return "collection_closed"
        names.append(item)
    return tuple(names)


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
