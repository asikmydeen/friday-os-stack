"""The Movies and TV plan is recorded. It is not applied."""

from __future__ import annotations

import unittest
from pathlib import Path

from guests.bundle import (
    add_bazarr,
    add_other_player,
    apply_plan,
    from_add_call,
    offer_tautulli,
    plan_bundle,
    publish_name,
    tools_for,
    wired_probe,
)
from netpolicy.paths import app_can_open

DISK = {
    "storage_disk": "/disks/apps",
    "storage_device": "disk-apps",
    "data_device": "disk-data",
}


class BundlePlanTests(unittest.TestCase):
    def test_jellyfin_is_one_player_and_nothing_is_applied(self) -> None:
        decision = plan_bundle("jellyfin", confirmed=True, claim_token="token=abcd", **DISK)
        self.assertEqual(decision.reason, "not_applied")
        self.assertEqual(decision.player, "jellyfin")
        self.assertEqual(decision.primary, "jellyfin")
        self.assertEqual(decision.apps, ("qbittorrent", "prowlarr", "radarr", "sonarr", "jellyfin"))
        self.assertIn("plex", decision.omitted)
        self.assertIn("home-assistant", decision.omitted)
        self.assertIn("bazarr", decision.omitted)
        self.assertNotIn("plex", decision.apps)
        self.assertIs(decision.claim_asked, False)
        self.assertNotIn("PLEX_CLAIM_TOKEN", decision.secrets)
        self.assertNotIn("token=abcd", repr(decision))
        self.assertEqual(decision.quality, "worst-first")
        self.assertIs(decision.unknown_first, True)
        self.assertIs(decision.unknown_disallowed, True)
        self.assertEqual(decision.steps[4], "quality_profile")
        self.assertEqual(decision.webhooks, ("http://webhooks:8080/arr", "http://webhooks:8080/media"))
        self.assertIs(decision.posted, False)
        self.assertEqual(decision.library[0][0], "library/downloads")
        self.assertEqual(decision.library[1][2], ("jellyfin",))
        self.assertEqual(decision.categories, (("radarr", "radarr"), ("sonarr", "sonarr")))
        self.assertEqual(decision.storage_disk, "/disks/apps")
        self.assertIn("127.0.0.1:8081", decision.binds)
        self.assertNotIn("127.0.0.1:8080", decision.binds)
        self.assertIn("127.0.0.1:8096", decision.binds)
        self.assertEqual(decision.indexers, ())
        self.assertIs(decision.full_sync, True)
        self.assertIn("http://jellyfin:8096/health", decision.probes)
        self.assertIs(decision.probed, False)
        self.assertEqual(decision.grants[0][0], "fetcher")
        self.assertEqual(decision.grants[1], ("media", ("jellyfin",)))
        self.assertIs(decision.tools_on, False)
        self.assertIs(decision.applied, False)
        self.assertIs(decision.started, False)
        self.assertIs(decision.swarm_stopped, False)
        self.assertIs(decision.calls_stopped, False)
        self.assertEqual(apply_plan(decision, confirmed=True).reason, "catalog_install_closed")
        self.assertIs(apply_plan(decision).applied, False)
        self.assertIs(apply_plan(decision).started, False)
        self.assertEqual(app_can_open("friday", 8080).reason, "core_closed")
        self.assertEqual(app_can_open("webhooks", 8080).reason, "webhook")

    def test_plex_asks_for_the_claim_name_and_not_the_value(self) -> None:
        secret = "password is hunter22"
        decision = plan_bundle(" Plex ", claim_token=secret, **DISK)
        self.assertEqual(decision.player, "plex")
        self.assertIs(decision.claim_asked, True)
        self.assertIn("PLEX_CLAIM_TOKEN", decision.secrets)
        self.assertIn("PLEX_SERVER_TOKEN", decision.secrets)
        self.assertNotIn("JELLYFIN_API_KEY", decision.secrets)
        self.assertNotIn("jellyfin", decision.apps)
        self.assertNotIn(secret, repr(decision))
        self.assertNotIn("hunter22", repr(decision))
        self.assertEqual(decision.webhooks, ("http://webhooks:8080/arr",))
        self.assertEqual(decision.library[2][2], ("plex",))
        self.assertIs(decision.applied, False)
        self.assertEqual(plan_bundle(confirmed=True, **DISK).player, "jellyfin")

    def test_a_best_first_list_or_the_data_disk_is_refused(self) -> None:
        best = plan_bundle("jellyfin", quality="best-first", **DISK)
        self.assertEqual(best.reason, "best_first_refused")
        self.assertEqual(best.apps, ())
        self.assertIs(best.applied, False)
        self.assertEqual(plan_bundle("jellyfin", quality="best", **DISK).reason, "quality_order")
        self.assertEqual(plan_bundle("home-assistant", **DISK).reason, "not_in_bundle")
        same = plan_bundle("jellyfin", storage_disk="/disks/apps", storage_device="disk-data", data_device="disk-data")
        self.assertEqual(same.reason, "storage_on_data_partition")
        data = plan_bundle(
            "jellyfin",
            storage_disk="/var/lib/friday",
            storage_device="disk-apps",
            data_device="disk-data",
        )
        self.assertEqual(data.reason, "storage_on_data_partition")
        linked = plan_bundle(
            "jellyfin",
            storage_disk="/disks/apps/link",
            storage_device="disk-apps",
            data_device="disk-data",
            links={"/disks/apps/link": "/etc"},
        )
        self.assertEqual(linked.reason, "mount_forbidden")
        walked = plan_bundle(
            "jellyfin",
            storage_disk="/disks/apps/link/library",
            storage_device="disk-apps",
            data_device="disk-data",
            links={"/disks/apps/link": "/var/lib/friday"},
        )
        self.assertEqual(walked.reason, "storage_on_data_partition")
        self.assertEqual(plan_bundle("jellyfin", storage_disk="/disks/apps", storage_device="", data_device="disk-data").reason, "storage_device")
        padded = plan_bundle(
            "jellyfin",
            storage_disk="/disks/apps",
            storage_device=" disk-data ",
            data_device="disk-data",
        )
        self.assertEqual(padded.reason, "storage_on_data_partition")
        self.assertEqual(
            plan_bundle("jellyfin", storage_disk="/disks/apps", storage_device="disk-apps", data_device="disk-data", links="nope").reason,
            "mount_not_absolute",
        )

    def test_grants_stay_named_and_the_optional_apps_are_not_applied(self) -> None:
        self.assertEqual(tools_for("fetcher", "download").reason, "fetcher")
        self.assertIs(tools_for("fetcher", "download").tools_on, False)
        self.assertEqual(tools_for("media", "player", "plex").grants, (("media", ("plex",)),))
        self.assertEqual(tools_for("family", "download").reason, "family_blocked")
        self.assertEqual(tools_for("chief", "download").reason, "not_that_advisor")
        self.assertEqual(tools_for("cto", "player").reason, "not_that_advisor")
        self.assertEqual(tools_for("home", "player", "jellyfin").grants, ())
        bazarr = add_bazarr(confirmed=True, **DISK)
        self.assertEqual(bazarr.reason, "not_applied")
        self.assertEqual(bazarr.apps, ("bazarr",))
        self.assertEqual(bazarr.player, "jellyfin")
        self.assertEqual(bazarr.library[0], ("library/movies", ("bazarr",), ("jellyfin",)))
        self.assertEqual(bazarr.library[1][2], ("jellyfin",))
        self.assertEqual(bazarr.attaches, ("radarr", "sonarr"))
        self.assertIs(bazarr.read_write, True)
        self.assertEqual(bazarr.binds, ("127.0.0.1:6767",))
        self.assertIs(bazarr.applied, False)
        self.assertIs(bazarr.started, False)
        plex_subs = add_bazarr(player=" Plex ", **DISK)
        self.assertEqual(plex_subs.library[1][2], ("plex",))
        self.assertEqual(add_bazarr(player="home-assistant", **DISK).reason, "not_in_bundle")
        self.assertEqual(add_bazarr(storage_disk="/etc", storage_device="disk-apps", data_device="disk-data").reason, "mount_forbidden")
        self.assertEqual(offer_tautulli("jellyfin", confirmed=True).reason, "not_plex_primary")
        tautulli = offer_tautulli(" Plex ")
        self.assertEqual(tautulli.reason, "not_applied")
        self.assertEqual(tautulli.apps, ("tautulli",))
        self.assertEqual(tautulli.primary, "plex")
        self.assertIs(tautulli.applied, False)
        later = add_other_player("jellyfin", confirmed=True)
        self.assertEqual(later.player, "plex")
        self.assertEqual(later.primary, "jellyfin")
        self.assertIs(later.claim_asked, True)
        self.assertIn("PLEX_CLAIM_TOKEN", later.secrets)
        self.assertEqual(later.library[0], ("library/movies", ("radarr",), ("jellyfin", "plex")))
        self.assertEqual(later.library[1][1], ("sonarr",))
        self.assertEqual(later.binds, ("127.0.0.1:32400",))
        self.assertEqual(later.probes, ("http://plex:32400/identity",))
        self.assertEqual(later.grants, ())
        self.assertIs(later.read_write, False)
        self.assertIs(later.started, False)
        self.assertNotIn("hunter22", repr(later))
        second = add_other_player(" Plex ")
        self.assertEqual(second.player, "jellyfin")
        self.assertEqual(second.primary, "plex")
        self.assertIs(second.claim_asked, False)
        self.assertEqual(second.secrets, ("JELLYFIN_URL", "JELLYFIN_API_KEY"))
        self.assertEqual(second.binds, ("127.0.0.1:8096",))
        self.assertEqual(second.probes, ("http://jellyfin:8096/health",))
        self.assertEqual(second.grants, ())
        self.assertEqual(add_other_player("home-assistant").reason, "not_in_bundle")
        quiet = publish_name("qbittorrent", confirmed=True)
        self.assertEqual(quiet.reason, "public_name_off")
        self.assertIs(quiet.public_name, False)
        self.assertIs(quiet.swarm_stopped, False)
        self.assertIs(quiet.calls_stopped, False)

    def test_a_fixed_probe_is_replaced_and_an_add_is_not_a_download(self) -> None:
        probe = wired_probe("radarr", "http://203.0.113.8:7878/ping")
        self.assertEqual(probe.reason, "wired_url")
        self.assertEqual(probe.health, "http://radarr:7878/ping")
        self.assertNotIn("203.0.113.8", repr(probe))
        self.assertIs(probe.probed, False)
        self.assertEqual(wired_probe("friday", "http://friday:8080/health").reason, "unknown_app")
        said = from_add_call("downloading")
        self.assertEqual(said.reason, "not_from_the_add_call")
        self.assertEqual(said.said, "")
        self.assertIs(said.posted, False)

    def test_ask_does_not_call_this_module(self) -> None:
        text = Path("friday/ask.py").read_text(encoding="utf-8")
        self.assertNotIn("guests", text)
        self.assertNotIn("plan_bundle", text)


if __name__ == "__main__":
    unittest.main()
