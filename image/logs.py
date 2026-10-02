"""Log bounds the image writes onto the disk. Nothing here starts Docker.

Container logs use the json-file driver, 10 MiB each, three files.
The journal is capped at 256 MiB when it is stored, and 64 MiB in
memory. The data partition floor stays 16 GiB in the disk rules.
This module does not read a disk, delete a log, or sample RAM.
"""

from __future__ import annotations

import json

from image.disks import DATA_MIN

DOCKER_MAX_SIZE = "10m"
DOCKER_MAX_FILE = 3
JOURNAL_SYSTEM_MAX = "256M"
JOURNAL_RUNTIME_MAX = "64M"


def docker_daemon() -> str:
    body = {
        "log-driver": "json-file",
        "log-opts": {
            "max-size": DOCKER_MAX_SIZE,
            "max-file": str(DOCKER_MAX_FILE),
        },
    }
    return json.dumps(body, indent=2) + "\n"


def journald_dropin() -> str:
    return (
        "[Journal]\n"
        f"SystemMaxUse={JOURNAL_SYSTEM_MAX}\n"
        f"RuntimeMaxUse={JOURNAL_RUNTIME_MAX}\n"
    )


def ceiling_text() -> str:
    return (
        f"data_floor_bytes={DATA_MIN}\n"
        f"docker_max_size={DOCKER_MAX_SIZE}\n"
        f"docker_max_file={DOCKER_MAX_FILE}\n"
        f"journal_system_max_use={JOURNAL_SYSTEM_MAX}\n"
        f"journal_runtime_max_use={JOURNAL_RUNTIME_MAX}\n"
    )


def shipped() -> dict[str, str]:
    return {
        "etc/docker/daemon.json": docker_daemon(),
        "etc/systemd/journald.conf.d/friday.conf": journald_dropin(),
        "etc/friday-log-ceiling": ceiling_text(),
    }
