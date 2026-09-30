"""Wi-Fi join stores the passphrase and does not print it."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from image.setup import FakeRng, Store
from image.wifi import join_wifi


class Join(unittest.TestCase):
    def test_a_wireless_device_gets_a_private_file(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            sysfs = root / "sys"
            (sysfs / "wlan0" / "wireless").mkdir(parents=True)
            calls = []

            def run(argv):
                calls.append(list(argv))

            join_wifi("House", "wpx-9k2m-not-shown", sysfs=sysfs, iwd_dir=root / "iwd", run=run)
            stored = root / "iwd" / "House.psk"
            self.assertEqual(stored.stat().st_mode & 0o777, 0o600)
            self.assertIn("wpx-9k2m-not-shown", stored.read_text())
            self.assertNotIn("wpx-9k2m-not-shown", str(calls))
            self.assertEqual(calls[0][:3], ["systemctl", "start", "iwd"])
            self.assertEqual(calls[1][:4], ["iwctl", "station", "wlan0", "connect"])

    def test_no_device_does_not_write_the_password(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "sys").mkdir()

            def run(_argv):
                raise AssertionError("iwctl should not run")

            with self.assertRaises(OSError) as caught:
                join_wifi("House", "wpx-9k2m-not-shown", sysfs=root / "sys", iwd_dir=root / "iwd", run=run)
            self.assertEqual(str(caught.exception), "wifi_no_device")
            self.assertFalse((root / "iwd").exists())

    def test_the_setup_screen_joins_only_when_a_joiner_is_set(self):
        with tempfile.TemporaryDirectory() as raw:
            store = Store(Path(raw) / "data")
            store.load_or_mint(FakeRng(1))
            store.save_wifi("House", "wpx-9k2m-not-shown")
            self.assertIn("does not join Wi-Fi", store.status_text())
            seen = {}

            def joiner(ssid, password):
                seen["ssid"] = ssid
                seen["password"] = password

            store.joiner = joiner
            outcome = store.save_wifi("House", "wpx-9k2m-not-shown")
            self.assertEqual(outcome.reason, "wifi_joined")
            self.assertEqual(seen["password"], "wpx-9k2m-not-shown")
            text = store.status_text()
            self.assertIn("Wi-Fi: joined House", text)
            self.assertNotIn("does not join Wi-Fi", text)
            self.assertNotIn("wpx-9k2m-not-shown", text)

            def missing(_ssid, _password):
                raise OSError("wifi_no_device")

            store.joiner = missing
            refused = store.save_wifi("Cabin", "another-secret-value")
            self.assertEqual(refused.reason, "wifi_no_device")
            again = store.status_text()
            self.assertIn("was not joined", again)
            self.assertNotIn("another-secret-value", again)
            self.assertNotIn("does not join Wi-Fi", again)
