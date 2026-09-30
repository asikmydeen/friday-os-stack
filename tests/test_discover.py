"""An empty pin lists nothing, and every install stays closed."""

from __future__ import annotations

import unittest

from catalog.discover import discover, draft_ids, request_install, review_install

COMMIT = "a" * 40
PIN = f"commit: {COMMIT}\ntrains: [stable, community]\npinned_at: 2026-09-29\n"


class DiscoverTests(unittest.TestCase):
    def test_repository_pin_is_empty(self) -> None:
        listing = discover()
        self.assertEqual(listing.outcome, "empty")
        self.assertEqual(listing.reason, "pin_empty")
        self.assertEqual(listing.names, ())

    def test_entries_without_a_pin_stay_unlisted(self) -> None:
        listing = discover("# comments only\n", [{"name": "jellyfin", "train": "stable"}])
        self.assertEqual(listing.reason, "pin_empty")
        self.assertEqual(listing.names, ())

    def test_stable_and_community_are_listed_and_install_is_refused(self) -> None:
        listing = discover(PIN, [
            {"name": "jellyfin", "train": "stable"},
            {"name": "plex", "train": "community"},
            {"name": "secret-app", "train": "enterprise"},
            {"name": "other", "train": "test"},
            {"name": "jellyfin", "train": "stable"},
        ])
        self.assertEqual(listing.outcome, "listed")
        self.assertEqual(listing.reason, "listed")
        self.assertEqual(listing.names, ("jellyfin", "plex"))
        self.assertTrue(all(row.install == "refused" for row in listing.rows))

    def test_a_pin_without_entries_does_not_fetch_upstream(self) -> None:
        listing = discover(PIN)
        self.assertEqual(listing.reason, "upstream_not_copied")
        self.assertEqual(listing.names, ())

    def test_a_short_commit_is_invalid(self) -> None:
        listing = discover("commit: abc\n", [{"name": "jellyfin", "train": "stable"}])
        self.assertEqual(listing.reason, "pin_invalid")
        self.assertEqual(listing.names, ())

    def test_a_train_outside_the_pin_is_omitted(self) -> None:
        pin = f"commit: {COMMIT}\ntrains: [stable]\n"
        listing = discover(pin, [{"name": "plex", "train": "community"}])
        self.assertEqual(listing.names, ())

    def test_draft_wires_are_not_the_catalog(self) -> None:
        self.assertEqual(
            set(draft_ids()),
            {
                "bazarr",
                "home-assistant",
                "jellyfin",
                "movies-tv",
                "plex",
                "prowlarr",
                "qbittorrent",
                "radarr",
                "sonarr",
            },
        )
        listing = discover()
        for draft in draft_ids():
            self.assertNotIn(draft, listing.names)

    def test_request_install_drops_confirmed(self) -> None:
        decision = request_install("jellyfin", confirmed=True)
        self.assertEqual(decision.outcome, "refused")
        self.assertEqual(decision.reason, "catalog_install_closed")
        self.assertEqual(decision.__dict__.keys(), {"outcome", "reason"})

    def test_review_order_stays_closed(self) -> None:
        self.assertEqual(
            review_install(middleware=True, allowlisted=True, render_passed=True, agent_path=True).reason,
            "middleware_required",
        )
        self.assertEqual(review_install().reason, "not_allowlisted")
        self.assertEqual(
            review_install(allowlisted=True).reason,
            "render_unproven",
        )
        self.assertEqual(
            review_install(allowlisted=True, render_passed=True, declared=10, free=9, agent_path=True).reason,
            "ram_does_not_fit",
        )
        self.assertEqual(
            review_install(allowlisted=True, render_passed=True, declared=1, free=9).reason,
            "agent_path_closed",
        )
        decision = review_install(
            allowlisted=True,
            render_passed=True,
            declared=1,
            free=9,
            agent_path=True,
            confirmed=True,
        )
        self.assertEqual(decision.reason, "catalog_install_closed")


if __name__ == "__main__":
    unittest.main()
