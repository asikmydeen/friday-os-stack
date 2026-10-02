"""RAM and disk decisions from numbers the caller supplies.

This package does not read the machine.
"""

from measure.ram import TARGET_BYTES, Decision, Measurement, fits, measure, room_for

__all__ = [
    "TARGET_BYTES",
    "Decision",
    "Measurement",
    "fits",
    "measure",
    "room_for",
]
