"""Decide whether a supplied measurement is complete, and whether it fits.

The samples are idle, one embedding, one indexing pass, two overlapping
turns, and an image pull, plus a disk ceiling and log rotation. Two
gigabytes is the measurement target. It is not a promise, and fits()
does not compare against it.

When declared memory is above the caller's free RAM, room_for names one
other guest whose declared size would free enough, or says the machine
is too small. A core service is never that name. A core flag other than
false keeps that guest off the list. A credential-shaped name is not
repeated. The function does not stop the guest and does not pull an image.

Numbers come from the caller. This module does not read /proc, does not
sample the machine, and does not start a container.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from memoryd.store import credential_shape

SAMPLES = (
    "idle",
    "one_embedding",
    "one_indexing_pass",
    "two_overlapping_turns",
    "image_pull",
)

# Measurement target. Not a size this module claims the machine fits.
TARGET_BYTES = 2 * 1024 ** 3

# Locked rows. Stopping one of these is not how an optional app gets room.
CORE = frozenset({
    "friday",
    "board",
    "qdrant",
    "ollama",
    "postgres",
    "memory-mcp",
    "executor",
    "gateway",
})


@dataclass(frozen=True)
class Decision:
    outcome: str
    reason: str
    which: str | None = None
    declared: int | None = None
    free: int | None = None
    said: str = ""
    stopped: bool = False
    pulled: bool = False


@dataclass(frozen=True)
class Measurement:
    outcome: str
    reason: str
    samples: tuple[tuple[str, int], ...] = ()


def _whole(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def measure(
    samples: Mapping[str, int] | None,
    *,
    disk_used: int,
    disk_ceiling: int,
    log_rotation: bool,
) -> Measurement:
    if not isinstance(log_rotation, bool) or not _whole(disk_used) or not _whole(disk_ceiling):
        return Measurement("incomplete", "missing_sample")
    if samples is None:
        return Measurement("incomplete", "missing_sample")
    taken: list[tuple[str, int]] = []
    for name in SAMPLES:
        if name not in samples:
            return Measurement("incomplete", "missing_sample")
        value = samples[name]
        if not _whole(value) or value < 0:
            return Measurement("incomplete", "missing_sample")
        taken.append((name, value))
    if disk_used > disk_ceiling:
        return Measurement("refused", "over_disk_ceiling", tuple(taken))
    if not log_rotation:
        return Measurement("refused", "logs_unbounded", tuple(taken))
    return Measurement("recorded", "not_a_hardware_measurement", tuple(taken))


def fits(*, declared: int, free: int) -> Decision:
    if not _whole(declared) or not _whole(free) or declared < 0 or free < 0:
        return Decision("refused", "ram_does_not_fit")
    if declared > free:
        return Decision("refused", "ram_does_not_fit")
    return Decision("fits", "within_free_ram")


def room_for(
    *,
    declared: object,
    free: object,
    running: object = (),
    app_id: object = "",
    confirmed: bool = False,
) -> Decision:
    """Say which guest would free enough room. Do not stop it or pull."""
    del confirmed  # a model flag never stops a guest or pulls an image
    if not _whole(declared) or not _whole(free) or declared < 0 or free < 0:
        return _quiet("refused", "ram_does_not_fit")
    if declared <= free:
        return _said("fits", "within_free_ram", None, declared, free)
    rows, reason = _rows(running)
    if reason:
        return _quiet("refused", reason, declared, free)
    skip, reason = _skip(app_id)
    if reason:
        return _quiet("refused", reason, declared, free)
    deficit = declared - free
    best: tuple[int, str, str] | None = None
    seen: set[str] = set()
    for name, size, locked in rows:
        key = name.casefold()
        if key in seen:
            return _quiet("refused", "duplicate_app", declared, free)
        seen.add(key)
        if locked or key == skip:
            continue
        if size >= deficit and (best is None or (size, key) < (best[0], best[1])):
            best = (size, key, name)
    if best is None:
        return _said("said", "machine_larger", None, declared, free)
    return _said("said", "stop_other", best[2], declared, free)


def _quiet(
    outcome: str,
    reason: str,
    declared: int | None = None,
    free: int | None = None,
) -> Decision:
    return Decision(
        outcome,
        reason,
        declared=declared,
        free=free,
        stopped=False,
        pulled=False,
    )


def _said(
    outcome: str,
    reason: str,
    which: str | None,
    declared: int,
    free: int,
) -> Decision:
    if reason == "stop_other":
        lead = f"Stop {which}."
    elif reason == "machine_larger":
        lead = "The machine is too small."
    else:
        lead = "It fits."
    said = (
        f"{lead} Declared {declared}. Free {free}. "
        "These numbers are not a hardware measurement."
    )
    return Decision(
        outcome,
        reason,
        which=which,
        declared=declared,
        free=free,
        said=said,
        stopped=False,
        pulled=False,
    )


def _skip(app_id: object) -> tuple[str, str | None]:
    if app_id == "":
        return "", None
    if not isinstance(app_id, str) or app_id.strip() == "":
        return "", "missing_app"
    text = app_id.strip()
    if credential_shape(text):
        return "", "credential"
    return text.casefold(), None


def _rows(running: object) -> tuple[list[tuple[str, int, bool]] | None, str | None]:
    if isinstance(running, (str, bytes)) or not isinstance(running, (list, tuple)):
        return None, "missing_declared"
    found: list[tuple[str, int, bool]] = []
    for item in running:
        if not isinstance(item, Mapping):
            return None, "missing_declared"
        name, reason = _name(item)
        if reason or name is None:
            return None, reason or "missing_declared"
        size = item.get("declared")
        if not _whole(size) or size < 0:
            return None, "missing_declared"
        if "core" in item and item.get("core") is not False:
            locked = True
        else:
            locked = False
        locked = locked or name.casefold() in CORE
        found.append((name, size, locked))
    return found, None


def _name(item: Mapping) -> tuple[str | None, str | None]:
    has_id = "id" in item
    has_app = "app_id" in item
    if has_id and has_app and item.get("id") != item.get("app_id"):
        return None, "missing_declared"
    raw = item.get("id") if has_id else item.get("app_id")
    if not isinstance(raw, str) or raw.strip() == "":
        return None, "missing_declared"
    text = raw.strip()
    if credential_shape(text):
        return None, "credential"
    return text, None
