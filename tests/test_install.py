"""Installer disk rules, setup screen, and the pre-release filesystem scan."""

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from image import VERSION
from image.console import InstallerConsole, SetupConsole
from image.disks import (
    BUNDLED,
    NOT_IN_IMAGE,
    SLOT_FILE,
    commands,
    data_bytes,
    fits,
    format_size,
    grub_installed,
    grub_installer,
    grub_stub,
    parent_disk,
    parse_parted,
    valid_kernel_name,
    Disk,
    choose,
)
from image.install import apply, write_installed
from image.main import data_mounted, root_device
from image.qdrant_bootstrap import plain_env
from image.starter import start_core
from image.provision import handle, serve
from image.scan import scan
from image.setup import (
    FakeRng,
    Iface,
    Store,
    observe,
    read_ifaces,
    reconcile_machine_id,
)

GiB = 1024**3
DISK = 64 * 1000**3


def _clean(root: Path) -> None:
    (root / "etc").mkdir(parents=True, exist_ok=True)
    (root / "etc/machine-id").write_text("")
    (root / "etc/friday-role").write_text("installer\n")
    (root / "etc/friday-arch").write_text("amd64\n")
    (root / "etc/shadow").write_text("root:!:19000:0:99999:7:::\n")
    (root / "var/lib/dpkg").mkdir(parents=True, exist_ok=True)
    (root / "var/lib/dpkg/status").write_text("Package: python3\nStatus: install ok installed\n\n")


class DiskTests(unittest.TestCase):
    def test_a_64_gb_disk_fits_and_one_byte_less_does_not(self):
        self.assertTrue(fits(DISK))
        self.assertFalse(fits(DISK - 1))
        self.assertGreaterEqual(data_bytes(DISK), 16 * GiB)
        overhead = GiB // 1024 + 512 * GiB // 1024 + 32 * GiB + GiB // 1024
        self.assertFalse(fits(overhead + 16 * GiB))

    def test_names_and_parents(self):
        self.assertEqual(parent_disk("sda1"), "sda")
        self.assertEqual(parent_disk("sda"), "sda")
        self.assertEqual(parent_disk("nvme0n1p2"), "nvme0n1")
        self.assertEqual(parent_disk("nvme0n1"), "nvme0n1")
        self.assertEqual(parent_disk("mmcblk0p1"), "mmcblk0")
        self.assertTrue(valid_kernel_name("nvme0n1"))
        self.assertTrue(valid_kernel_name("vda"))
        self.assertFalse(valid_kernel_name("sda1"))
        self.assertFalse(valid_kernel_name("/dev/sda"))
        self.assertFalse(valid_kernel_name("loop0"))
        self.assertFalse(valid_kernel_name("SDA"))

    def test_the_stick_and_a_short_disk_are_refused(self):
        disks = [Disk("sda", DISK, False), Disk("sdb", 4 * 1000**3, True)]
        self.assertEqual(choose(disks, "sdb", installer_known=True).reason, "installer_disk")
        self.assertTrue(choose(disks, "sda", installer_known=True).ok)
        self.assertEqual(choose(disks, "/dev/sda", installer_known=True).reason, "not_kernel_name")
        self.assertEqual(choose(disks, "sdc", installer_known=True).reason, "unknown_disk")
        self.assertEqual(choose(disks, "sda", installer_known=False).reason, "installer_unknown")
        small = [Disk("sda", 32 * 1000**3, False)]
        self.assertEqual(choose(small, "sda", installer_known=True).reason, "too_small")

    def test_partition_commands_name_slots_and_never_touch_another_disk(self):
        planned = commands("sda")
        text = [" ".join(cmd) for cmd in planned]
        self.assertIn("parted -s /dev/sda mklabel gpt", text)
        self.assertIn("parted -s /dev/sda mkpart friday-efi fat32 1MiB 513MiB", text)
        self.assertIn("parted -s /dev/sda set 1 esp on", text)
        self.assertTrue(any(line.endswith("/dev/sda2") and "friday-a" in line for line in text))
        self.assertTrue(any(line.endswith("/dev/sda3") and "friday-b" in line for line in text))
        self.assertTrue(any("friday-data" in line and line.endswith("100%") for line in text))
        rsync = next(cmd for cmd in planned if cmd[0] == "rsync")
        self.assertIn("--exclude=/mnt", rsync)
        self.assertIn("--exclude=/var/lib/friday", rsync)
        nvme = [" ".join(cmd) for cmd in commands("nvme0n1")]
        self.assertTrue(any("/dev/nvme0n1p1" in line for line in nvme))
        self.assertTrue(any("/dev/nvme0n1p2" in line and "friday-a" in line for line in nvme))
        self.assertFalse(any("/dev/sda" in line for line in nvme))
        with self.assertRaises(ValueError):
            commands("sda;rm")

    def test_partprobe_can_fail_without_skipping_the_format(self):
        calls = []

        def run(cmd):
            if cmd[0] == "partprobe":
                raise OSError("probe")
            calls.append(cmd)

        apply("sda", run)
        self.assertTrue(any(cmd[0] == "mkfs.ext4" for cmd in calls))

        def refuse(cmd):
            raise AssertionError(cmd)

        with self.assertRaises(ValueError):
            apply("../sda", refuse)

    def test_parted_machine_output_is_inclusive(self):
        text = (
            "BYT;\n"
            "/tmp/x:1000B:512:512:gpt:name:;\n"
            "1:1048576B:536870911B:535822336B:fat32:friday-efi:esp;\n"
            "2:536870912B:1073741823B:536870912B:ext4:friday-installer:;\n"
        )
        rows = parse_parted(text)
        self.assertEqual(rows[0]["start"], 1048576)
        self.assertEqual(rows[0]["size"], 535822336)
        self.assertEqual(rows[0]["name"], "friday-efi")
        self.assertIn("esp", rows[0]["flags"])
        self.assertLess(rows[0]["end"], rows[1]["start"])

    def test_boot_configs(self):
        installer = grub_installer()
        installed = grub_installed()
        self.assertIn(f"Friday {VERSION} test installer", installer)
        self.assertIn("friday-installer", installer)
        self.assertIn("console=ttyS0,115200", installer)
        self.assertIn("console=tty0", installer)
        self.assertIn("friday-a", installed)
        self.assertNotIn("friday-installer", installed)
        self.assertIn("installed system", installed)
        self.assertIn("/EFI/BOOT/grub.cfg", grub_stub())

    def test_installed_tree_clears_identity_and_records_slot_a(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "a"
            efi = Path(raw) / "efi"
            data = Path(raw) / "data"
            boot = Path(raw) / "BOOTX64.EFI"
            boot.write_bytes(b"MZ")
            (root / "etc/ssh").mkdir(parents=True)
            (root / "etc/ssh/ssh_host_rsa_key").write_text("nope")
            (root / "etc/machine-id").write_text("abcdef\n")
            write_installed(root, efi, data, boot)
            self.assertEqual((root / "etc/friday-role").read_text(), "installed\n")
            self.assertEqual((root / "etc/machine-id").read_text(), "")
            self.assertFalse((root / "etc/ssh/ssh_host_rsa_key").exists())
            self.assertIn("LABEL=friday-a", (root / "etc/fstab").read_text())
            self.assertIn("PARTLABEL=friday-efi", (root / "etc/fstab").read_text())
            self.assertIn("LABEL=friday-data", (root / "etc/fstab").read_text())
            self.assertIn("friday-a", (efi / "EFI/BOOT/grub.cfg").read_text())
            self.assertEqual((efi / "friday-slot.txt").read_text(), SLOT_FILE)
            self.assertEqual((efi / "EFI/BOOT/BOOTX64.EFI").read_bytes(), b"MZ")
            self.assertEqual((data / "secrets").stat().st_mode & 0o777, 0o700)
            self.assertTrue((data / "notes").is_dir())


class ConsoleTests(unittest.TestCase):
    def _disks(self):
        return [Disk("sda", DISK, False), Disk("sdb", 4 * 1000**3, True)]

    def test_erase_needs_the_same_name_twice_and_never_the_stick(self):
        console = InstallerConsole(self._disks(), installer_known=True, mem_total_kib=8 * 1024 * 1024)
        banner = console.banner()
        self.assertIn("sdb", banner)
        self.assertIn("installer", banner)
        self.assertIn("Docker Engine", banner)
        self.assertIn("nomic-embed-text", banner)
        self.assertIn("Nothing is downloaded", banner)
        self.assertIn(format_size(DISK), banner)
        self.assertNotIn("under 8 GB", banner)
        low = InstallerConsole(self._disks(), installer_known=True, mem_total_kib=2 * 1024 * 1024)
        self.assertIn("under 8 GB", low.banner())
        self.assertIn("not the internal disk", console.line("sdb"))
        self.assertFalse(console.ready)
        self.assertIn("Do not type", console.line("/dev/sda"))
        self.assertIn("again", console.line("sda"))
        self.assertFalse(console.ready)
        self.assertIn("Nothing was erased", console.line("vda"))
        self.assertFalse(console.ready)
        self.assertIn("again", console.line("sda"))
        self.assertIn("Erasing sda", console.line("sda"))
        self.assertTrue(console.ready)
        self.assertEqual(console.chosen, "sda")

    def test_unknown_stick_and_a_short_disk_erase_nothing(self):
        unknown = InstallerConsole([Disk("sda", 80 * 1000**3, False)], installer_known=False)
        self.assertIn("will not erase", unknown.line("sda"))
        self.assertFalse(unknown.ready)
        short = InstallerConsole([Disk("sda", 32 * 1000**3, False)], installer_known=True)
        self.assertIn("64 GB", short.line("sda"))
        self.assertFalse(short.ready)

    def test_mount_helpers(self):
        self.assertEqual(root_device("/dev/sda2 / ext4 rw 0 0\n"), "sda2")
        self.assertIsNone(root_device("overlay / overlay rw 0 0\n"))
        self.assertTrue(data_mounted("/dev/sda4 /var/lib/friday ext4 rw 0 0\n"))
        self.assertFalse(data_mounted("/dev/sda2 / ext4 rw 0 0\n"))


class BootstrapEnv(unittest.TestCase):
    def test_a_quoted_env_file_value_loses_the_quotes(self):
        self.assertEqual(plain_env('"abc123"'), "abc123")
        self.assertEqual(plain_env("abc123"), "abc123")
        self.assertEqual(plain_env("  'abc123'  "), "abc123")


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "data")
        self.store.omitted = [
            "friday",
            "board",
            "memory-mcp",
            "qdrant",
            "postgres",
            "ollama",
            "nomic-embed-text",
        ]
        self.assertEqual(self.store.load_or_mint(FakeRng(1)), "minted")

    def tearDown(self):
        self.tmp.cleanup()

    def test_two_machines_differ_and_a_power_loss_keeps_the_same_secrets(self):
        other = Store(Path(self.tmp.name) / "other")
        other.load_or_mint(FakeRng(2))
        self.assertNotEqual(self.store.board_password, other.board_password)
        self.assertNotEqual(self.store.machine_id, other.machine_id)
        self.assertNotEqual(self.store.notify_token, other.notify_token)
        password = self.store.board_password
        token = self.store.provision_token
        machine = self.store.machine_id
        notify = self.store.notify_token
        (self.store.root / "secrets" / "minted").unlink()
        again = Store(self.store.root)
        self.assertEqual(again.load_or_mint(FakeRng(99)), "reused")
        self.assertEqual(again.board_password, password)
        self.assertEqual(again.provision_token, token)
        self.assertEqual(again.machine_id, machine)
        self.assertEqual(again.notify_token, notify)
        self.assertEqual(again.memory_token, self.store.memory_token)
        self.assertEqual(again.qdrant_key, self.store.qdrant_key)
        self.assertEqual(again.webhook_jellyfin, self.store.webhook_jellyfin)
        self.assertEqual(again.webhook_radarr, self.store.webhook_radarr)
        self.assertEqual(again.webhook_sonarr, self.store.webhook_sonarr)

    def test_an_existing_machine_id_is_kept(self):
        adopted = Store(Path(self.tmp.name) / "adopted")
        adopted.load_or_mint(FakeRng(3), "abc123\n")
        self.assertEqual(adopted.machine_id, "abc123")
        later = Store(adopted.root)
        later.load_or_mint(FakeRng(4), "zzz")
        self.assertEqual(later.machine_id, "abc123")
        self.assertEqual(reconcile_machine_id("", "", "new"), ("new", "new"))
        self.assertEqual(reconcile_machine_id("etc\n", "", "new"), ("etc", "etc"))
        self.assertEqual(reconcile_machine_id("etc", "data", "new"), ("data", "data"))

    def test_secret_files_are_private(self):
        root = self.store.root
        self.assertEqual(root.stat().st_mode & 0o777, 0o700)
        self.assertEqual((root / "secrets").stat().st_mode & 0o777, 0o700)
        self.assertEqual((root / "secrets" / "board_password").stat().st_mode & 0o777, 0o600)
        self.assertEqual((root / "secrets" / "postgres_password").stat().st_mode & 0o777, 0o600)
        self.assertEqual((root / "secrets" / "approval_token").stat().st_mode & 0o777, 0o600)
        self.assertEqual((root / "provision.token").stat().st_mode & 0o777, 0o600)

    def test_status_shows_the_board_password_and_hides_the_other_secrets(self):
        self.store.save_wifi("House", "wpx-9k2m-not-shown")
        self.store.model_key = "sk-test-key-9f3a"
        text = self.store.status_text()
        self.assertIn(self.store.board_password, text)
        self.assertNotIn(self.store.notify_token, text)
        self.assertNotIn(self.store.memory_token, text)
        self.assertNotIn(self.store.qdrant_key, text)
        self.assertNotIn("sk-test-key-9f3a", text)
        self.assertNotIn("wpx-9k2m-not-shown", text)
        self.assertNotIn(self.store.postgres_password, text)
        self.assertNotIn(self.store.approval_token, text)
        self.assertNotIn(self.store.webhook_jellyfin, text)
        self.assertNotIn(self.store.webhook_radarr, text)
        self.assertNotIn(self.store.webhook_sonarr, text)
        self.assertIn("House", text)
        self.assertIn("does not join Wi-Fi", text)
        self.assertIn("Friday does not speak", text)
        self.assertIn("Catalog install is refused.", text)
        self.assertIn("not in this image", text)
        self.assertEqual((self.store.root / "secrets" / "wifi_psk").stat().st_mode & 0o777, 0o600)

    def test_create_server_records_the_gap_and_does_not_start_anything(self):
        outcome = self.store.confirm_server()
        self.assertEqual(outcome.reason, "core_not_in_image")
        self.assertTrue(self.store.server_confirmed)
        self.assertFalse(self.store.started)
        self.assertFalse(self.store.downloaded)
        self.assertIn("Nothing was started", self.store.status_text())

    def test_model_check_needs_a_real_reply_and_refuses_metadata(self):
        called = {"n": 0}

        def transport(url, key, model):
            called["n"] += 1
            self.assertNotIn("sk-test-key-9f3a", url)
            return 200, b'{"choices":[{"message":{"content":"ready"}}]}'

        self.store.transport = transport
        self.store.resolve = lambda _host: ["93.184.216.34"]
        self.store.model_base = "https://example.test/v1"
        self.store.model_fast = "fast"
        self.store.model_key = "sk-test-key-9f3a"
        self.assertEqual(self.store.check_model().reason, "no_route")
        self.assertEqual(called["n"], 0)
        self.store.ifaces = [Iface("enp0s1", True, "wired")]
        self.store.model_base = "http://169.254.169.254/latest"
        self.assertEqual(self.store.check_model().reason, "model_address")
        self.assertEqual(called["n"], 0)
        self.store.model_base = "http://evil.test/v1"
        self.store.resolve = lambda _host: ["169.254.1.1"]
        self.assertEqual(self.store.check_model().reason, "model_address")
        self.store.model_base = "https://example.test/v1?token=hidden"
        self.store.resolve = lambda _host: ["93.184.216.34"]
        self.assertEqual(self.store.check_model().reason, "model_url")
        self.store.model_base = "https://example.test/v1"
        self.store.transport = lambda url, key, model: (200, b'{"choices":[{"message":{"content":"  "}}]}')
        self.assertEqual(self.store.check_model().reason, "empty_reply")
        self.assertFalse(self.store.model_ok)
        seen = {}

        def good(url, key, model):
            seen["url"] = url
            return 200, b'{"choices":[{"message":{"content":"ready"}}]}'

        self.store.transport = good
        self.assertEqual(self.store.check_model().reason, "model_ok")
        self.assertEqual(seen["url"], "https://example.test/v1/chat/completions")
        self.assertTrue(self.store.model_ok)
        self.assertNotIn("sk-test-key-9f3a", self.store.status_text())

    def test_finish_stops_on_the_missing_embed_model(self):
        self._prepare()
        self.store.embed_transport = None
        outcome = self.store.finish()
        self.assertEqual(outcome.reason, "embed_not_in_image")
        self.assertEqual(self.store.provision_state, "open")
        self.assertTrue((self.store.root / "provision.token").is_file())

        def down():
            raise OSError("down")

        self.store.embed_transport = down
        self.assertEqual(self.store.finish().reason, "embed_not_in_image")
        self.store.embed_transport = lambda: (200, b'{"embedding":[1,2,3]}')
        self.assertEqual(self.store.check_embed().reason, "embed_dimensions")

    def test_a_768_vector_completes_setup_once(self):
        self._prepare()
        self.store.embed_transport = lambda: (200, json.dumps({"embedding": [0] * 768}).encode())
        password = self.store.board_password
        memory = self.store.memory_token
        outcome = self.store.finish()
        self.assertEqual(outcome.reason, "ok")
        self.assertEqual(self.store.provision_state, "complete")
        self.assertFalse((self.store.root / "provision.token").exists())
        self.assertNotIn(password, self.store.status_text())
        again = Store(self.store.root)
        again.load_or_mint(FakeRng(8))
        self.assertEqual(again.provision_token, "")
        self.assertEqual(again.board_password, password)
        self.assertEqual(again.memory_token, memory)
        weak = again.recover("short", local_console=True)
        self.assertEqual(weak.reason, "password_weak")
        self.assertEqual(again.board_password, password)
        replaced = again.recover("a-new-board-password", local_console=True)
        self.assertEqual(replaced.reason, "password_replaced")
        self.assertEqual(again.board_password, "a-new-board-password")
        self.assertEqual(again.memory_token, memory)
        self.assertEqual(again.notify_token, self.store.notify_token)
        remote = again.recover("another-password-value", local_console=False)
        self.assertEqual(remote.reason, "console_only")
        self.assertEqual(again.board_password, "a-new-board-password")

    def test_recovery_waits_until_setup_is_complete(self):
        outcome = self.store.recover("a-new-board-password", local_console=True)
        self.assertEqual(outcome.reason, "still_provisioning")
        self.assertNotEqual(self.store.board_password, "a-new-board-password")

    def test_saved_link_does_not_invent_a_route(self):
        self.store.ifaces = [Iface("enp0s1", True, "wired")]
        self.store.save_link()
        self.store.ifaces = []
        text = self.store.status_text()
        self.assertIn("wired saved", text)
        self.assertIn("no route", text)
        self.assertEqual(self.store.finish().reason, "no_route")

    def test_names_and_zones(self):
        self.assertEqual(self.store.set_name("Ada Lovelace").reason, "name_set")
        self.assertEqual(self.store.set_name("Ada\nLovelace").reason, "name_invalid")
        self.assertEqual(self.store.set_timezone("../UTC").reason, "timezone_invalid")
        self.store.zone_exists = lambda _name: False
        self.assertEqual(self.store.set_timezone("UTC").reason, "timezone_unknown")

    def test_interfaces(self):
        net = Path(self.tmp.name) / "net"
        wired = net / "enp0s1"
        wired.mkdir(parents=True)
        (wired / "carrier").write_text("1\n")
        wireless = net / "wlan0"
        wireless.mkdir()
        (wireless / "carrier").write_text("0\n")
        (wireless / "wireless").mkdir()
        loop = net / "lo"
        loop.mkdir()
        (loop / "carrier").write_text("1\n")
        self.assertEqual(observe(read_ifaces(net)), "wired")
        (wired / "carrier").write_text("0\n")
        (wireless / "carrier").write_text("1\n")
        self.assertEqual(observe(read_ifaces(net)), "wireless")
        (wireless / "carrier").write_text("0\n")
        self.assertEqual(observe(read_ifaces(net)), "no_route")

    def _prepare(self):
        self.store.ifaces = [Iface("enp0s1", True, "wired")]
        self.store.resolve = lambda _host: ["93.184.216.34"]
        self.store.transport = lambda url, key, model: (
            200,
            b'{"choices":[{"message":{"content":"ready"}}]}',
        )
        self.store.confirm_server()
        self.store.set_name("Ada")
        self.store.set_timezone("UTC")
        self.store.set_model("https://example.test/v1", "fast", "", "sk-test-key-9f3a")
        self.store.confirm_password(self.store.board_password, self.store.board_password)

    def _headers(self, token=None, board=None):
        headers = {}
        if token is not None:
            headers["Friday-Provision"] = token
        if board is not None:
            headers["Friday-Board"] = board
        return headers

    def test_provision_page_rules(self):
        token = self.store.provision_token
        password = self.store.board_password
        (self.store.root / "notes" / "n.txt").write_text("household-secret-note")
        status, body = handle(self.store, "GET", "/provision", {}, b"", local=True)
        self.assertEqual(status, 401)
        self.assertNotIn(password, body)
        status, body = handle(
            self.store, "GET", "/provision", self._headers(token=token), b"", local=False
        )
        self.assertEqual(status, 403)
        self.assertIn("not_local", body)
        self.assertNotIn(password, body)
        status, body = handle(
            self.store, "GET", "/provision", self._headers(token=token), b"", local=True
        )
        self.assertEqual(status, 200)
        self.assertIn(password, body)
        self.assertIn("Friday does not speak", body)
        status, body = handle(
            self.store, "GET", "/", self._headers(board=password), b"", local=True
        )
        self.assertEqual(status, 200)
        self.assertIn("The Board is not in this image.", body)
        body_bytes = urllib.parse.urlencode({"action": "install", "confirmed": "true"}).encode()
        status, body = handle(
            self.store, "POST", "/provision", self._headers(token=token), body_bytes, local=True
        )
        self.assertEqual(status, 403)
        self.assertIn("catalog_install_closed", body)
        self.assertFalse(self.store.password_confirmed)
        self.assertFalse((self.store.root / "confirmed").exists())
        status, body = handle(self.store, "GET", "/install", {}, b"", local=True)
        self.assertEqual(status, 401)
        status, body = handle(
            self.store, "GET", "/install", self._headers(board=password), b"", local=True
        )
        self.assertEqual(status, 403)
        self.assertIn("catalog_install_closed", body)
        status, body = handle(
            self.store, "GET", "/memory", self._headers(board=password), b"", local=True
        )
        self.assertIn("memory_unreadable", body)
        self.assertNotIn("household-secret-note", body)
        status, body = handle(
            self.store, "POST", "/grant", self._headers(board=password), b"action=grant", local=True
        )
        self.assertIn("grant_closed", body)
        status, body = handle(
            self.store,
            "POST",
            "/provision",
            self._headers(token=token),
            b"action=recover",
            local=True,
        )
        self.assertEqual(status, 403)
        self.assertIn("console_only", body)
        mismatch = urllib.parse.urlencode(
            {"action": "password", "typed": "not-the-password", "again": "not-the-password"}
        ).encode()
        status, body = handle(
            self.store, "POST", "/provision", self._headers(token=token), mismatch, local=True
        )
        self.assertIn("password_mismatch", body)
        self.assertFalse(self.store.password_confirmed)

    def test_console_commands(self):
        console = SetupConsole(self.store)
        self.assertIn("catalog_install_closed", console.line("install jellyfin"))
        self.assertIn("memory_unreadable", console.line("memory"))
        self.assertIn("ignored", console.line("confirmed true"))
        self.assertFalse(self.store.password_confirmed)
        self.assertEqual(console.line("wifi"), "Wi-Fi name.\n")
        self.assertIn("not shown", console.line("House"))
        shown = console.line("wpx-9k2m-not-shown")
        self.assertNotIn("wpx-9k2m-not-shown", shown)
        self.assertIn("House", shown)
        recorded = console.line("server")
        self.assertIn("core_not_in_image", recorded)
        self.assertIn("Nothing was started", recorded)
        self.assertFalse(self.store.started)

    def test_create_server_starts_the_bundled_core_without_downloading(self):
        calls = []
        loaded = {"ok": False}

        def run(argv):
            calls.append(list(argv))
            if argv[:3] == ["docker", "image", "inspect"] and not loaded["ok"]:
                raise OSError("missing")
            if argv[:2] == ["docker", "load"]:
                loaded["ok"] = True

        root = Path(self.tmp.name) / "image-root"
        models = (
            root
            / "usr/lib/friday/ollama-models/models/manifests/registry.ollama.ai/library/nomic-embed-text"
        )
        models.mkdir(parents=True)
        (models / "latest").write_text("{}\n")
        (root / "usr/lib/friday/images").mkdir(parents=True)
        (root / "usr/lib/friday/images/core-images.tar").write_bytes(b"tar")
        (root / "usr/lib/friday/qdrant_bootstrap.py").write_text("print('ok')\n")
        (root / "usr/lib/friday/compose.yml").write_text("name: friday\n")
        self.store.omitted = list(NOT_IN_IMAGE)
        self.store.starter = lambda store: start_core(
            store, run, root, embed_check=lambda: None
        )
        outcome = self.store.confirm_server()
        self.assertEqual(outcome.reason, "started")
        self.assertTrue(self.store.started)
        self.assertFalse(self.store.downloaded)
        text = self.store.status_text()
        self.assertIn("The core on this computer was started", text)
        self.assertIn("Nothing was downloaded", text)
        self.assertNotIn("Nothing was started", text)
        self.assertNotIn(self.store.postgres_password, text)
        env = (self.store.root / "core.env").read_text()
        self.assertIn(self.store.postgres_password, env)
        self.assertIn(self.store.webhook_jellyfin, env)
        self.assertNotIn(self.store.webhook_jellyfin, text)
        self.assertEqual((self.store.root / "core.env").stat().st_mode & 0o777, 0o600)
        self.assertNotIn(self.store.postgres_password, (self.store.root / "start.log").read_text())
        up = next(argv for argv in calls if "up" in argv)
        self.assertEqual(up[up.index("-p") + 1], "friday")
        self.assertIn("--pull", up)
        self.assertIn("never", up)
        self.assertNotIn("friday-os-stack", up)
        self.assertTrue(loaded["ok"])
        self.assertTrue(
            (
                self.store.root
                / "ollama/models/manifests/registry.ollama.ai/library/nomic-embed-text/latest"
            ).is_file()
        )

    def test_a_start_error_does_not_claim_the_core_is_up(self):
        self.store.omitted = []

        def bad(_store):
            raise OSError("boom")

        self.store.starter = bad
        outcome = self.store.confirm_server()
        self.assertEqual(outcome.reason, "start_failed")
        self.assertFalse(self.store.started)
        self.assertFalse(self.store.downloaded)
        self.assertIn("The core did not start", self.store.status_text())
        self.assertIn("Nothing was downloaded", self.store.status_text())

    def test_a_present_core_without_a_starter_does_not_pretend_to_start(self):
        self.store.omitted = list(NOT_IN_IMAGE)
        outcome = self.store.confirm_server()
        self.assertEqual(outcome.reason, "start_not_wired")
        self.assertFalse(self.store.started)
        self.assertFalse(self.store.downloaded)
        self.assertIn("Nothing was started", self.store.status_text())

    def test_omitted_file_lists_only_what_this_tree_does_not_ship(self):
        lines = [
            line
            for line in Path("image/assets/friday-omitted").read_text().splitlines()
            if line
        ]
        self.assertEqual(lines, list(NOT_IN_IMAGE))
        self.assertFalse(set(lines) & set(BUNDLED))
        compose = Path("image/assets/core-compose.yml").read_text()
        board = Path("image/assets/compose.board.yml").read_text()
        self.assertNotIn("build:", compose)
        # BIND_HOST 0.0.0.0 is the address inside the container. A published
        # host address stays on loopback.
        for line in compose.splitlines() + board.splitlines():
            stripped = line.strip()
            if stripped.startswith("- ") or stripped.startswith("ports:"):
                self.assertNotIn("0.0.0.0", line)
        self.assertIn("BIND_HOST: 0.0.0.0", compose)
        self.assertIn("127.0.0.1:11434:11434", compose)
        self.assertEqual(compose.count("pull_policy: never"), 9)
        self.assertIn("networks: [core]\n", compose)
        self.assertIn("networks: [apps]\n", compose)
        self.assertIn("internal: true", compose)
        self.assertEqual(compose.count("ports:"), 1)
        self.assertNotIn("8090:8090", compose)
        self.assertNotIn("127.0.0.1:8080", compose)
        self.assertIn("friday-os-stack/webhooks:0.1.0-amd64", compose)
        self.assertIn("friday-os-stack/gateway:0.1.0-amd64", compose)
        friday = compose.split("  friday:", 1)[1].split("  board:", 1)[0]
        self.assertIn("networks: [core]", friday)
        self.assertNotIn("apps", friday)
        kiosk = Path("image/assets/friday-kiosk.service").read_text()
        self.assertIn("ConditionPathExists=/dev/dri/card0", kiosk)
        self.assertIn("http://127.0.0.1:8080", kiosk)
        self.assertIn("/usr/bin/cage", kiosk)
        self.assertIn("/usr/bin/chromium", kiosk)
        self.assertIn("127.0.0.1:8080:8080", board)
        self.assertNotIn("0.0.0.0", board)


class PageTests(unittest.TestCase):
    def test_localhost_page(self):
        with tempfile.TemporaryDirectory() as raw:
            store = Store(Path(raw) / "data")
            store.load_or_mint(FakeRng(7))
            password = store.board_password
            token = store.provision_token
            httpd = serve(store, 0)
            thread = threading.Thread(target=httpd.serve_forever)
            thread.start()
            port = httpd.server_address[1]

            def fetch(path, headers=None, data=None):
                request = urllib.request.Request(
                    f"http://127.0.0.1:{port}{path}",
                    data=data,
                    headers=headers or {},
                )
                try:
                    with urllib.request.urlopen(request, timeout=5) as response:
                        return response.status, response.read().decode()
                except urllib.error.HTTPError as exc:
                    try:
                        return exc.code, exc.read().decode()
                    finally:
                        exc.close()

            try:
                status, body = fetch("/provision")
                self.assertEqual(status, 401)
                self.assertNotIn(password, body)
                status, body = fetch("/provision", {"Friday-Provision": token})
                self.assertEqual(status, 200)
                self.assertIn(password, body)
                status, body = fetch("/", {"Friday-Board": password})
                self.assertEqual(status, 200)
                self.assertIn("Setup stays on this page until it is finished.", body)
                status, body = fetch(
                    "/provision",
                    {"Friday-Provision": token},
                    b"a" * (40 * 1024),
                )
                self.assertEqual(status, 413)
            finally:
                httpd.shutdown()
                httpd.server_close()
                thread.join(timeout=5)


class ScanTests(unittest.TestCase):
    def test_clean_tree_passes_and_planted_secrets_fail(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "tree"
            _clean(root)
            self.assertEqual(scan(root), [])
            (root / "etc/machine-id").write_text("0123456789abcdef0123456789abcdef\n")
            self.assertIn("machine-id", scan(root))
            (root / "etc/machine-id").write_text("")
            (root / "etc/ssh").mkdir()
            (root / "etc/ssh/ssh_host_ed25519_key").write_text("secret\n")
            self.assertIn("secret-file", scan(root))
            (root / "etc/ssh/ssh_host_ed25519_key").unlink()
            (root / "etc/note").write_text("key AKIA1234567890EXAMPLE\n")
            self.assertIn("secret-content", scan(root))
            (root / "etc/note").write_text("ID_VENDOR_FROM_DATABASE=AKIA Corporation\n")
            self.assertNotIn("secret-content", scan(root))
            (root / "etc/note").unlink()
            (root / "etc/bin.dat").write_bytes(b"\0AKIA1234567890EXAMPLE")
            self.assertNotIn("secret-content", scan(root))
            (root / "etc/bin.dat").unlink()
            (root / "var/lib/dpkg/status").write_text(
                "Package: openssh-server\nStatus: install ok installed\n\n"
            )
            self.assertIn("openssh-server", scan(root))
            (root / "var/lib/dpkg/status").write_text(
                "Package: python3\nStatus: install ok installed\n\n"
            )
            (root / "etc/shadow").write_text("root::19000:0:99999:7:::\n")
            self.assertIn("root-password", scan(root))
            (root / "etc/shadow").write_text("root:!$6$abc:19000:0:99999:7:::\n")
            self.assertNotIn("root-password", scan(root))
            (root / "etc/friday-role").write_text("installed\n")
            self.assertIn("role", scan(root))
            (root / "etc/friday-role").write_text("installer\n")
            (root / "etc/friday-arch").write_text("arm64\n")
            self.assertIn("arch", scan(root))
            (root / "etc/friday-arch").write_text("amd64\n")
            secret = root / "var/lib/friday/secrets"
            secret.mkdir(parents=True)
            (secret / "board_password").write_text("x\n")
            self.assertIn("baked-secret", scan(root))
            (secret / "board_password").unlink()
            (root / "etc/hosts").write_text("1.2.3.4 files.asikmydeen.com\n")
            self.assertIn("secret-content", scan(root))
            (root / "etc/hosts").unlink()
            outside = Path(raw) / "outside.txt"
            outside.write_text("AKIASECRET")
            (root / "etc/link").symlink_to(outside)
            self.assertNotIn("secret-content", scan(root))
            layer = root / "var/lib/docker/overlay2/abc"
            layer.mkdir(parents=True)
            (layer / "note").write_text("POSTGRES_PASSWORD=from-an-image-layer\n")
            self.assertNotIn("secret-content", scan(root))
            (layer / "id_ed25519").write_text("secret\n")
            self.assertIn("secret-file", scan(root))


if __name__ == "__main__":
    unittest.main()
