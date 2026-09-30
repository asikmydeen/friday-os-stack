"""Guest install stays closed. Adopt does not start a second copy."""

from __future__ import annotations

import unittest

from guests.lifecycle import adopt, bundle, disconnect, install_guest, uninstall


class GuestTests(unittest.TestCase):
    def test_install_and_the_bundle_stay_closed(self) -> None:
        for app_id in ("jellyfin", "plex", "home-assistant", "radarr"):
            decision = install_guest(app_id, confirmed=True)
            self.assertEqual(decision.reason, "catalog_install_closed")
        self.assertEqual(bundle("jellyfin", confirmed=True).reason, "catalog_install_closed")
        self.assertEqual(bundle("plex").reason, "catalog_install_closed")
        self.assertEqual(bundle("home-assistant").reason, "not_in_bundle")

    def test_adopt_records_the_app_and_does_not_start_it_here(self) -> None:
        decision = adopt("plex")
        self.assertEqual(decision.reason, "adopted")
        self.assertEqual(decision.mark, "adopted")
        self.assertIs(decision.running_here, False)

    def test_disconnect_leaves_an_adopted_app_running(self) -> None:
        decision = disconnect("adopted")
        self.assertEqual(decision.reason, "left_running")
        self.assertIs(decision.running_here, True)
        self.assertEqual(disconnect("managed").reason, "not_adopted")

    def test_a_managed_uninstall_keeps_the_files(self) -> None:
        self.assertEqual(uninstall("managed").reason, "files_kept")
        self.assertEqual(
            uninstall("managed", delete_files=True).reason,
            "files_need_their_own_confirm",
        )
        self.assertEqual(uninstall("adopted", delete_files=True).reason, "not_managed")


if __name__ == "__main__":
    unittest.main()
