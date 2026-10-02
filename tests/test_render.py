"""A caller-supplied render is judged and not installed."""

from __future__ import annotations

import unittest
from pathlib import Path

from catalog.discover import discover, review_install
from catalog.render import accept_render, apply_render, judge_render

PIN = Path("catalog/PIN")


def _over(**extra: object) -> dict:
    return {**CLEAN, **extra}


CLEAN = {
    "train": "stable",
    "catalog_pin": "a" * 40,
    "template_hash": "b" * 64,
    "rendered_digest": "c" * 64,
    "storage_disk": "/disks/apps",
    "storage_device": "disk-apps",
    "data_device": "disk-data",
    "declared": 512,
    "free": 2048,
    "image_arch": "amd64",
    "host_arch": "x86_64",
    "storage": [{"kind": "folder", "source": "/disks/apps/library/movies"}],
    "ports": [{"host": "127.0.0.1:8096", "container": 8096}],
}


class RenderTests(unittest.TestCase):
    def test_a_clean_description_is_recorded_and_not_installed(self) -> None:
        before = PIN.read_text(encoding="utf-8")
        decision = judge_render(
            " Jellyfin ",
            confirmed=True,
            train="Community",
            catalog_pin="a" * 40,
            template_hash="b" * 64,
            rendered_digest="c" * 64,
            storage_disk="/disks/apps",
            storage_device="disk-apps",
            data_device="disk-data",
            declared=512,
            free=2048,
            image_arch="amd64",
            host_arch="x86_64",
            storage=[{"kind": "host_path", "source": "/disks/apps/library"}],
            ports=[{"host": "127.0.0.1:8096"}],
            reviewed_devices=("/dev/dri",),
            devices=("/dev/dri",),
            reviewed_capabilities=("NET_BIND_SERVICE",),
            capabilities=("NET_BIND_SERVICE",),
        )
        self.assertEqual(decision.outcome, "recorded")
        self.assertEqual(decision.reason, "not_installed")
        self.assertEqual(decision.app, "jellyfin")
        self.assertEqual(decision.train, "community")
        self.assertIs(decision.listed, True)
        self.assertEqual(decision.install, "refused")
        self.assertIs(decision.applied, False)
        self.assertIs(decision.started, False)
        self.assertIs(decision.jinja, False)
        self.assertIs(decision.pin_written, False)
        self.assertIs(decision.wires_read, False)
        self.assertIs(decision.portable, True)
        self.assertEqual(decision.binds, ("127.0.0.1:8096",))
        self.assertEqual(decision.image_arch, "x86_64")
        self.assertEqual(decision.host_arch, "x86_64")
        self.assertIs(decision.arch_measured, False)
        self.assertEqual(decision.storage_disk, "/disks/apps")
        self.assertEqual(decision.ram, "within_free_ram")
        self.assertEqual(decision.measurement, "not_a_hardware_measurement")
        self.assertIs(decision.approval, False)
        self.assertEqual(decision.catalog_pin, "a" * 40)
        self.assertEqual(decision.template_hash, "b" * 64)
        self.assertEqual(decision.rendered_digest, "c" * 64)
        secret_pin = judge_render("jellyfin", **_over(catalog_pin="token=abcd"))
        self.assertEqual(secret_pin.reason, "version_incomplete")
        self.assertNotIn("token=abcd", repr(secret_pin))
        self.assertEqual(secret_pin.catalog_pin, "")
        hunter = judge_render("jellyfin", **_over(template_hash="password is hunter22"))
        self.assertEqual(hunter.reason, "version_incomplete")
        self.assertNotIn("hunter22", repr(hunter))
        prose = judge_render(
            "jellyfin",
            **_over(rendered_digest="The password is kept outside the machine"),
        )
        self.assertEqual(prose.reason, "version_incomplete")
        self.assertNotIn("outside", repr(prose))
        closed = apply_render(decision, confirmed=True)
        self.assertEqual(closed.reason, "catalog_install_closed")
        self.assertIs(closed.applied, False)
        self.assertIs(closed.started, False)
        self.assertEqual(accept_render("board", confirmed=True).reason, "catalog_install_closed")
        self.assertEqual(accept_render("chat", confirmed=True).reason, "actor_cannot_approve")
        self.assertEqual(accept_render("friday").reason, "actor_cannot_approve")
        self.assertEqual(PIN.read_text(encoding="utf-8"), before)
        self.assertEqual(discover().reason, "pin_empty")
        self.assertEqual(
            review_install(
                allowlisted=True,
                render_passed=True,
                declared=1,
                free=9,
                agent_path=True,
                confirmed=True,
            ).reason,
            "catalog_install_closed",
        )
        matched = judge_render("plex", **_over(image_arch="arm64", host_arch="aarch64"))
        self.assertEqual(matched.reason, "not_installed")
        self.assertEqual(matched.image_arch, "aarch64")
        self.assertIs(matched.arch_measured, False)

    def test_enterprise_and_other_trains_are_not_listed(self) -> None:
        enterprise = judge_render("secret-app", **_over(train="enterprise"))
        self.assertEqual(enterprise.reason, "enterprise_off")
        self.assertIs(enterprise.listed, False)
        self.assertIs(enterprise.started, False)
        other = judge_render("other", **_over(train="test"))
        self.assertEqual(other.reason, "train_refused")
        self.assertIs(other.listed, False)
        self.assertEqual(judge_render("", **_over()).reason, "app_id")
        self.assertEqual(judge_render("../jellyfin", **_over()).reason, "app_id")

    def test_middleware_stays_listed(self) -> None:
        needed = judge_render("nextcloud", **_over(middleware=True))
        self.assertEqual(needed.reason, "middleware_required")
        self.assertIs(needed.listed, True)
        self.assertIs(needed.started, False)
        named = judge_render("nextcloud", **_over(needs=["truenas"]))
        self.assertEqual(named.reason, "middleware_required")
        self.assertIs(named.listed, True)
        shaped = judge_render("nextcloud", **_over(needs=[{"name": "truenas"}]))
        self.assertEqual(shaped.reason, "middleware_required")
        self.assertIs(shaped.listed, True)

    def test_a_dataset_is_not_portable(self) -> None:
        dataset = judge_render(
            "jellyfin",
            **_over(storage=[{"kind": "dataset", "source": "pool/media"}]),
        )
        self.assertEqual(dataset.reason, "dataset_not_portable")
        self.assertIs(dataset.listed, True)
        self.assertIs(dataset.portable, False)
        self.assertIs(dataset.started, False)
        volume = judge_render(
            "jellyfin",
            **_over(storage=[{"kind": "ix_volume", "source": "pool/ix"}]),
        )
        self.assertEqual(volume.reason, "dataset_not_portable")
        stood_in = judge_render(
            "jellyfin",
            **_over(storage=[{"kind": "folder", "source": "/disks/apps/library", "substitutes_dataset": True}]),
        )
        self.assertEqual(stood_in.reason, "folder_is_not_a_dataset")
        self.assertIs(stood_in.portable, False)
        self.assertIs(stood_in.started, False)
        worded = judge_render(
            "jellyfin",
            **_over(storage=[{"kind": "folder", "source": "/disks/apps/library", "substitutes_dataset": "yes"}]),
        )
        self.assertEqual(worded.reason, "folder_is_not_a_dataset")

    def test_privileges_and_unlisted_devices_stay_listed(self) -> None:
        cases = [
            ({"host_network": True}, "host_network"),
            ({"network_mode": "host"}, "host_network"),
            ({"network_mode": "macvlan"}, "network_mode"),
            ({"host_pid": True}, "host_pid"),
            ({"pid_mode": "host"}, "host_pid"),
            ({"host_ipc": True}, "host_ipc"),
            ({"privileged": True}, "privileged"),
            ({"devices": ["/dev/dri"]}, "device_not_in_manifest"),
            ({"devices": ["/dev/dri"], "reviewed_devices": ["/dev/net/tun"]}, "device_not_in_manifest"),
            ({"devices": True}, "device_not_in_manifest"),
            ({"capabilities": ["NET_ADMIN"]}, "capability_not_in_manifest"),
            (
                {"capabilities": ["NET_ADMIN"], "reviewed_capabilities": ["NET_BIND_SERVICE"]},
                "capability_not_in_manifest",
            ),
            (
                {"devices": ["/dev/dri"], "reviewed_devices": ["/dev/dri"], "capabilities": ["SYS_ADMIN"]},
                "capability_not_in_manifest",
            ),
        ]
        for extra, reason in cases:
            decision = judge_render("jellyfin", **_over(**extra))
            self.assertEqual(decision.reason, reason, extra)
            self.assertIs(decision.listed, True)
            self.assertIs(decision.started, False)
            self.assertIs(decision.applied, False)

    def test_ports_arch_ram_and_version(self) -> None:
        public = judge_render("jellyfin", **_over(ports=[{"host": "0.0.0.0:8096"}]))
        self.assertEqual(public.reason, "bind_not_loopback")
        self.assertIs(public.listed, True)
        self.assertIs(public.started, False)
        self.assertEqual(
            judge_render("jellyfin", **_over(ports=["localhost:8096"])).reason,
            "bind_not_loopback",
        )
        mismatch = judge_render("jellyfin", **_over(image_arch="arm64", host_arch="x86_64"))
        self.assertEqual(mismatch.reason, "arch_mismatch")
        self.assertIs(mismatch.arch_measured, False)
        self.assertIs(mismatch.listed, True)
        missing = judge_render("jellyfin", **_over(host_arch=""))
        self.assertEqual(missing.reason, "arch_missing")
        self.assertEqual(
            judge_render("jellyfin", **_over(declared=4096, free=512)).reason,
            "ram_does_not_fit",
        )
        boolean = judge_render("jellyfin", **_over(declared=True, free=2048))
        self.assertEqual(boolean.reason, "ram_does_not_fit")
        self.assertIs(boolean.started, False)
        incomplete = judge_render("jellyfin", **_over(rendered_digest=""))
        self.assertEqual(incomplete.reason, "version_incomplete")
        self.assertIs(incomplete.listed, True)
        self.assertEqual(judge_render("jellyfin", **_over(catalog_pin="  ")).reason, "version_incomplete")

    def test_mounts_follow_the_app_disk(self) -> None:
        linked = judge_render(
            "jellyfin",
            **_over(
                links={"/disks/apps/link": "/etc/passwd"},
                storage=[{"kind": "folder", "source": "/disks/apps/link/secret"}],
            ),
        )
        self.assertEqual(linked.reason, "mount_forbidden")
        self.assertIs(linked.started, False)
        data = judge_render(
            "jellyfin",
            **_over(storage=[{"kind": "folder", "source": "/var/lib/friday/sqlite/db"}]),
        )
        self.assertEqual(data.reason, "storage_on_data_partition")
        same = judge_render(
            "jellyfin",
            **_over(storage_device=" disk-apps ", data_device="disk-apps"),
        )
        self.assertEqual(same.reason, "storage_on_data_partition")
        outside = judge_render(
            "jellyfin",
            **_over(storage=[{"kind": "folder", "source": "/disks/other/library"}]),
        )
        self.assertEqual(outside.reason, "mount_outside_disk")
        root = judge_render("jellyfin", **_over(storage=[{"kind": "folder", "source": "/"}]))
        self.assertEqual(root.reason, "mount_root")
        socket = judge_render(
            "jellyfin",
            **_over(storage=[{"kind": "folder", "source": "/var/run/docker.sock"}]),
        )
        self.assertEqual(socket.reason, "mount_forbidden")

    def test_ask_does_not_call_this_module(self) -> None:
        text = Path("friday/ask.py").read_text(encoding="utf-8")
        self.assertNotIn("catalog.render", text)
        self.assertNotIn("judge_render", text)


if __name__ == "__main__":
    unittest.main()
