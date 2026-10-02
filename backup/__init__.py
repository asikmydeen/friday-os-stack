"""Coordinated backup and the upgrade that uses it.

Writers pause before the stores are copied. A byte copy of a live SQLite
file is not a backup. backup.sqlite copies one open connection, including
one named file-backed connection, with the SQLite backup API into a
destination the executor already opened. A path is not opened. An unnamed
temporary disk database stays refused. The
passphrase stays out of the manifest. An upgrade that does not become
ready restores that backup before the old slot boots.

A blank host loads a caller-supplied manifest and does not restart the
box that sealed it. This package does not copy disks and does not start
containers. With POSTGRES_HOST set, backup.sqlstore writes one manifest
through backup_store. Without that host the manifest stays in memory.
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
    restore_host,
    resume_writers,
    seal_manifest,
    send,
)
from backup.sqlite import Decision, copy_store

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
    "restore_host",
    "resume_writers",
    "seal_manifest",
    "send",
    "Decision",
    "copy_store",
]
