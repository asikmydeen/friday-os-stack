"""RAM fit is a decision about numbers the caller supplies."""

from __future__ import annotations

import unittest

from measure.ram import TARGET_BYTES, fits, measure

COMPLETE = {
    "idle": 100,
    "one_embedding": 120,
    "one_indexing_pass": 140,
    "two_overlapping_turns": 180,
    "image_pull": 200,
}


class RamTests(unittest.TestCase):
    def test_two_gigabytes_is_a_target(self) -> None:
        self.assertEqual(TARGET_BYTES, 2 * 1024 ** 3)

    def test_a_missing_sample_is_incomplete(self) -> None:
        samples = dict(COMPLETE)
        del samples["image_pull"]
        decision = measure(samples, disk_used=1, disk_ceiling=2, log_rotation=True)
        self.assertEqual(decision.outcome, "incomplete")
        self.assertEqual(decision.reason, "missing_sample")

    def test_none_is_a_missing_sample(self) -> None:
        decision = measure(None, disk_used=1, disk_ceiling=2, log_rotation=True)
        self.assertEqual(decision.reason, "missing_sample")

    def test_disk_above_the_ceiling_is_refused(self) -> None:
        decision = measure(COMPLETE, disk_used=11, disk_ceiling=10, log_rotation=True)
        self.assertEqual(decision.reason, "over_disk_ceiling")

    def test_disk_at_the_ceiling_can_be_recorded(self) -> None:
        decision = measure(COMPLETE, disk_used=10, disk_ceiling=10, log_rotation=True)
        self.assertEqual(decision.reason, "not_a_hardware_measurement")

    def test_unbounded_logs_are_refused(self) -> None:
        decision = measure(COMPLETE, disk_used=1, disk_ceiling=2, log_rotation=False)
        self.assertEqual(decision.outcome, "refused")
        self.assertEqual(decision.reason, "logs_unbounded")

    def test_a_complete_record_echoes_the_supplied_numbers(self) -> None:
        decision = measure(COMPLETE, disk_used=1, disk_ceiling=2, log_rotation=True)
        self.assertEqual(decision.outcome, "recorded")
        self.assertEqual(decision.reason, "not_a_hardware_measurement")
        self.assertEqual(decision.samples, tuple(COMPLETE.items()))

    def test_declared_memory_above_free_ram_does_not_fit(self) -> None:
        self.assertEqual(fits(declared=100, free=99).reason, "ram_does_not_fit")
        self.assertEqual(fits(declared=100, free=100).outcome, "fits")
        self.assertEqual(
            fits(declared=TARGET_BYTES + 1, free=TARGET_BYTES + 1).outcome,
            "fits",
        )

    def test_a_bool_is_not_a_byte_count(self) -> None:
        self.assertEqual(fits(declared=True, free=1).reason, "ram_does_not_fit")


if __name__ == "__main__":
    unittest.main()
