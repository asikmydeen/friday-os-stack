"""Home Assistant is its own catalog entry. The plan is not applied."""

from __future__ import annotations

import unittest
from pathlib import Path

from guests.bundle import plan_bundle
from guests.home import accept_tool, apply_plan, plan_home, publish_name, tools_for, wired_probe

DISK = {
    "storage_disk": "/disks/apps",
    "storage_device": "disk-apps",
    "data_device": "disk-data",
    "declared": 512,
    "free": 2048,
}


class HomePlanTests(unittest.TestCase):
    def test_the_entry_is_separate_and_nothing_is_applied(self) -> None:
        secret = "password is hunter22"
        decision = plan_home(
            confirmed=True,
            url="http://203.0.113.9:8123",
            token="token=abcd",
            **DISK,
        )
        self.assertEqual(decision.reason, "not_applied")
        self.assertEqual(decision.app, "home-assistant")
        self.assertIs(decision.separate, True)
        self.assertIs(decision.in_bundle, False)
        self.assertEqual(decision.apps, ("home-assistant",))
        self.assertNotIn("jellyfin", decision.apps)
        self.assertNotIn("plex", decision.apps)
        self.assertEqual(decision.charter, "home")
        self.assertIs(decision.charter_on, False)
        self.assertEqual(decision.secrets, ("HOME_ASSISTANT_URL", "HOME_ASSISTANT_TOKEN"))
        self.assertEqual(decision.url, "http://home-assistant:8123")
        self.assertNotIn("203.0.113.9", repr(decision))
        self.assertNotIn("token=abcd", repr(decision))
        self.assertNotIn(secret, repr(decision))
        self.assertEqual(decision.grants, (("home", ("home_status", "home_control")),))
        self.assertIs(decision.tools_on, False)
        self.assertEqual(decision.storage_disk, "/disks/apps")
        self.assertEqual(decision.volume, "home_assistant_config")
        self.assertEqual(decision.mount, "/config")
        self.assertEqual(decision.binds, ("127.0.0.1:8123",))
        self.assertEqual(decision.health, "http://home-assistant:8123/api/")
        self.assertIs(decision.probed, False)
        self.assertEqual(decision.auth, "bearer")
        self.assertEqual(decision.ram, "within_free_ram")
        self.assertEqual(decision.measurement, "not_a_hardware_measurement")
        self.assertIs(decision.applied, False)
        self.assertIs(decision.started, False)
        self.assertIs(decision.approval, False)
        closed = apply_plan(decision, confirmed=True)
        self.assertEqual(closed.reason, "catalog_install_closed")
        self.assertIs(closed.applied, False)
        self.assertIs(closed.started, False)
        media = plan_bundle("jellyfin", storage_disk="/disks/apps", storage_device="disk-apps", data_device="disk-data")
        self.assertIn("home-assistant", media.omitted)

    def test_a_token_value_is_not_stored(self) -> None:
        decision = plan_home(token="password is hunter22", url="token=abcd", **DISK)
        self.assertNotIn("hunter22", repr(decision))
        self.assertNotIn("token=abcd", repr(decision))
        self.assertIn("HOME_ASSISTANT_TOKEN", decision.secrets)

    def test_only_the_home_role_is_named_and_tools_start_off(self) -> None:
        home = tools_for("home")
        self.assertEqual(home.reason, "home")
        self.assertEqual(home.grants, (("home", ("home_status", "home_control")),))
        self.assertIs(home.tools_on, False)
        self.assertEqual(tools_for("media").reason, "not_that_advisor")
        self.assertEqual(tools_for("fetcher").reason, "not_that_advisor")
        self.assertEqual(tools_for("family").reason, "family_blocked")
        self.assertEqual(tools_for("cto").grants, ())

    def test_the_board_accepts_one_manifest_name_at_a_time(self) -> None:
        one = accept_tool("board", "home_status", confirmed=True)
        self.assertEqual(one.reason, "owner_accepted")
        self.assertEqual(one.on, ("home_status",))
        self.assertNotIn("home_control", one.on)
        self.assertIs(one.tools_on, True)
        self.assertIs(one.approval, False)
        self.assertIs(one.started, False)
        both = accept_tool("board", "home_control", already=("home_status",))
        self.assertEqual(both.on, ("home_status", "home_control"))
        offered = accept_tool("board", "home_scenes", already=("home_status",))
        self.assertEqual(offered.reason, "not_in_manifest")
        self.assertEqual(offered.on, ("home_status",))
        self.assertNotIn("home_scenes", offered.on)
        self.assertIs(offered.tools_on, False)
        chat = accept_tool("chat", "home_status", already=("home_status",), confirmed=True)
        self.assertEqual(chat.reason, "actor_cannot_approve")
        self.assertEqual(chat.on, ("home_status",))
        self.assertIs(chat.tools_on, False)
        self.assertIs(chat.approval, False)
        again = accept_tool("board", "home_status", already=("home_status",))
        self.assertEqual(again.on, ("home_status",))
        flipped = accept_tool("board", "home_status", already=("home_control",))
        self.assertEqual(flipped.on, ("home_status", "home_control"))
        self.assertEqual(accept_tool("board", "home_status", already="home_status").reason, "already")

    def test_a_supplied_probe_is_replaced_and_a_public_name_stays_off(self) -> None:
        probe = wired_probe("http://203.0.113.9:8123/api/")
        self.assertEqual(probe.reason, "wired_url")
        self.assertEqual(probe.health, "http://home-assistant:8123/api/")
        self.assertNotIn("203.0.113.9", repr(probe))
        self.assertIs(probe.probed, False)
        named = publish_name(confirmed=True)
        self.assertEqual(named.reason, "public_name_off")
        self.assertIs(named.public_name, False)
        self.assertIs(named.started, False)

    def test_host_modes_devices_and_a_public_bind_are_refused(self) -> None:
        self.assertEqual(plan_home(host_network=True, **DISK).reason, "host_network")
        self.assertEqual(plan_home(network_mode="host", **DISK).reason, "host_network")
        self.assertEqual(plan_home(host_pid=True, **DISK).reason, "host_pid")
        self.assertEqual(plan_home(pid_mode="host", **DISK).reason, "host_pid")
        self.assertEqual(plan_home(host_ipc=True, **DISK).reason, "host_ipc")
        self.assertEqual(plan_home(ipc_mode="host", **DISK).reason, "host_ipc")
        self.assertEqual(plan_home(network_mode="none", **DISK).reason, "network_mode")
        self.assertEqual(plan_home(pid_mode="container:app", **DISK).reason, "pid_mode")
        self.assertEqual(plan_home(ipc_mode="shareable", **DISK).reason, "ipc_mode")
        self.assertEqual(plan_home(devices="/dev/ttyUSB0", **DISK).reason, "device_not_in_manifest")
        self.assertEqual(plan_home(devices=("/dev/ttyUSB0",), **DISK).reason, "device_not_in_manifest")
        self.assertEqual(plan_home(capabilities=("SYS_ADMIN",), **DISK).reason, "capability_not_in_manifest")
        self.assertEqual(plan_home(bind="0.0.0.0:8123", **DISK).reason, "bind_not_loopback")
        self.assertIs(plan_home(host_network=True, confirmed=True, **DISK).started, False)

    def test_storage_stays_off_the_data_partition(self) -> None:
        self.assertEqual(
            plan_home(storage_disk="/var/lib/friday/ha", storage_device="disk-apps", data_device="disk-data", declared=1, free=2).reason,
            "storage_on_data_partition",
        )
        self.assertEqual(
            plan_home(storage_disk="/disks/apps", storage_device=" disk-data ", data_device="disk-data", declared=1, free=2).reason,
            "storage_on_data_partition",
        )
        linked = plan_home(
            storage_disk="/disks/link",
            storage_device="disk-apps",
            data_device="disk-data",
            links={"/disks/link": "/etc"},
            declared=1,
            free=2,
        )
        self.assertEqual(linked.reason, "mount_forbidden")
        self.assertEqual(
            plan_home(storage_disk="/disks/apps", storage_device="disk-apps", data_device="disk-data", declared=4096, free=512).reason,
            "ram_does_not_fit",
        )
        self.assertEqual(
            plan_home(storage_disk="/disks/apps", storage_device="disk-apps", data_device="disk-data", declared=True, free=2048).reason,
            "ram_does_not_fit",
        )
        self.assertIs(
            plan_home(storage_disk="/disks/apps", storage_device="disk-apps", data_device="disk-data", declared=4096, free=512).started,
            False,
        )

    def test_ask_does_not_call_this_module(self) -> None:
        text = Path("friday/ask.py").read_text(encoding="utf-8")
        self.assertNotIn("guests", text)
        self.assertNotIn("plan_home", text)


if __name__ == "__main__":
    unittest.main()
