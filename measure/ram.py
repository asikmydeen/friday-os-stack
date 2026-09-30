"""Decide whether a supplied measurement is complete, and whether it fits.

The samples are idle, one embedding, one indexing pass, two overlapping
turns, and an image pull, plus a disk ceiling and log rotation. Two
gigabytes is the measurement target. It is not a promise, and fits()
does not compare against it.

Numbers come from the caller. This module does not read /proc, does not
sample the machine, and does not start a container.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

SAMPLES = (
    "idle",
    "one_embedding",
    "one_indexing_pass",
    "two_overlapping_turns",
    "image_pull",
)

# Measurement target. Not a size this module claims the machine fits.
TARGET_BYTES = 2 * 1024 ** 3


@dataclass(frozen=True)
class Decision:
    outcome: str
    reason: str


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
