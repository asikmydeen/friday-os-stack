"""RAM fit is a decision about numbers the caller supplies."""

from __future__ import annotations

import unittest
from pathlib import Path

from measure.ram import TARGET_BYTES, fits, measure, room_for

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

    def test_room_that_fits_names_nobody(self) -> None:
        decision = room_for(declared=100, free=100, running="not-a-list", confirmed=True)
        self.assertEqual(decision.outcome, "fits")
        self.assertEqual(decision.reason, "within_free_ram")
        self.assertIsNone(decision.which)
        self.assertFalse(decision.stopped)
        self.assertFalse(decision.pulled)
        self.assertIn("not a hardware measurement", decision.said)
        self.assertIn("Declared 100", decision.said)

    def test_the_smallest_guest_that_covers_the_gap_is_named(self) -> None:
        rows = [
            {"id": "plex", "declared": 400},
            {"id": "jellyfin", "declared": 150},
            {"id": "sonarr", "declared": 80},
        ]
        decision = room_for(declared=250, free=100, running=rows, confirmed=True)
        self.assertEqual(decision.outcome, "said")
        self.assertEqual(decision.reason, "stop_other")
        self.assertEqual(decision.which, "jellyfin")
        self.assertEqual(rows, [
            {"id": "plex", "declared": 400},
            {"id": "jellyfin", "declared": 150},
            {"id": "sonarr", "declared": 80},
        ])
        self.assertFalse(decision.stopped)
        self.assertFalse(decision.pulled)
        self.assertTrue(decision.said.startswith("Stop jellyfin."))
        self.assertIn("Declared 250", decision.said)
        self.assertIn("Free 100", decision.said)

    def test_a_tie_names_the_earlier_id(self) -> None:
        decision = room_for(
            declared=200,
            free=50,
            running=(
                {"app_id": "sonarr", "declared": 200},
                {"app_id": "plex", "declared": 200},
            ),
        )
        self.assertEqual(decision.which, "plex")

    def test_a_core_service_is_not_the_one_to_stop(self) -> None:
        decision = room_for(
            declared=500,
            free=100,
            running=[
                {"id": "postgres", "declared": 900, "core": False},
                {"id": "Plex", "declared": 400, "core": True},
                {"id": "gateway", "declared": 900},
            ],
        )
        self.assertEqual(decision.reason, "machine_larger")
        self.assertIsNone(decision.which)
        self.assertNotIn("postgres", decision.said)
        self.assertNotIn("Plex", decision.said)
        self.assertIn("The machine is too small.", decision.said)
        self.assertFalse(decision.stopped)
        self.assertFalse(decision.pulled)

    def test_the_app_being_added_is_not_stopped_to_make_its_own_room(self) -> None:
        decision = room_for(
            declared=300,
            free=100,
            running=[{"id": "plex", "declared": 400}, {"id": "radarr", "declared": 50}],
            app_id="plex",
        )
        self.assertEqual(decision.reason, "machine_larger")
        self.assertIsNone(decision.which)

    def test_a_core_flag_other_than_false_is_not_the_one_to_stop(self) -> None:
        decision = room_for(
            declared=200,
            free=50,
            running=[
                {"id": "jellyfin", "declared": 300, "core": "yes"},
                {"id": "sonarr", "declared": 200, "core": False},
            ],
            confirmed=True,
        )
        self.assertEqual(decision.which, "sonarr")
        self.assertNotIn("jellyfin", decision.said)
        self.assertFalse(decision.stopped)
        kept = room_for(
            declared=200,
            free=50,
            running=[{"id": "The password is kept outside the machine", "declared": 300}],
        )
        self.assertEqual(kept.which, "The password is kept outside the machine")
        secret = room_for(
            declared=200,
            free=50,
            running=[{"id": "token=abcd", "declared": 300}, {"id": "sonarr", "declared": 200}],
        )
        self.assertEqual(secret.reason, "credential")
        self.assertIsNone(secret.which)
        self.assertEqual(secret.said, "")
        self.assertNotIn("abcd", str(secret))

    def test_a_bad_row_names_nobody(self) -> None:
        decision = room_for(
            declared=200,
            free=50,
            running=[{"id": "jellyfin", "declared": 900}, {"id": "plex", "declared": True}],
        )
        self.assertEqual(decision.reason, "missing_declared")
        self.assertIsNone(decision.which)
        self.assertEqual(decision.said, "")
        self.assertFalse(decision.stopped)
        text = room_for(declared=200, free=50, running="plex")
        self.assertEqual(text.reason, "missing_declared")
        self.assertIsNone(text.which)
        self.assertEqual(text.said, "")

    def test_a_bool_and_a_duplicate_do_not_name_a_guest(self) -> None:
        self.assertEqual(room_for(declared=True, free=10).reason, "ram_does_not_fit")
        self.assertIsNone(room_for(declared=True, free=10).which)
        decision = room_for(
            declared=200,
            free=10,
            running=({"id": "plex", "declared": 300}, {"id": "Plex", "declared": 300}),
        )
        self.assertEqual(decision.reason, "duplicate_app")
        self.assertIsNone(decision.which)
        self.assertFalse(decision.pulled)

    def test_ask_does_not_call_this_module(self) -> None:
        text = Path("friday/ask.py").read_text(encoding="utf-8")
        self.assertNotIn("room_for", text)
        self.assertNotIn("measure", text)
        page = Path("board/server.js").read_text(encoding="utf-8")
        self.assertNotIn("room_for", page)
        self.assertNotIn("measure/ram", page)
        self.assertIn("/api/room", page)
        self.assertIn("These numbers are not a hardware measurement.", page)


if __name__ == "__main__":
    unittest.main()
