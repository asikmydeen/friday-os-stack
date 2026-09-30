"""Coordinated backup and the upgrade that uses it.

Writers pause before the stores are copied. A live SQLite file is not a
backup. The passphrase stays out of the manifest. An upgrade that does
not become ready restores that backup before the old slot boots.

This package does not copy disks and does not start containers.
"""

from backup.coordinated import (
    Box,
    Outcome,
    begin_pause,
    boot_crash,
    capture,
    mutate,
    plan_upgrade,
    ready,
    reconcile,
    resume_writers,
    seal_manifest,
    send,
)

__all__ = [
    "Box",
    "Outcome",
    "begin_pause",
    "boot_crash",
    "capture",
    "mutate",
    "plan_upgrade",
    "ready",
    "reconcile",
    "resume_writers",
    "seal_manifest",
    "send",
]
