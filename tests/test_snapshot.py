"""A snapshot lists stable and community. The git pin still lists nothing."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from catalog.discover import discover, request_install
from catalog.snapshot import copy_trains, drop_secret_content, list_apps, pin_text
from image.scan import CONTENT, MAX_TEXT


class Snapshot(unittest.TestCase):
    def test_copy_keeps_two_trains_and_drops_secret_names(self):
        with tempfile.TemporaryDirectory() as raw:
            src = Path(raw) / "src"
            dest = Path(raw) / "dest"
            app = src / "ix-dev" / "stable" / "jellyfin"
            app.mkdir(parents=True)
            (app / "app.yaml").write_text("name: jellyfin\n")
            (app / ".env").write_text("TOKEN=secret\n")
            (app / "id_ed25519").write_text("key\n")
            (src / "ix-dev" / "community" / "custom").mkdir(parents=True)
            (src / "ix-dev" / "community" / "custom" / "app.yaml").write_text("name: custom\n")
            (src / "ix-dev" / "enterprise" / "hidden").mkdir(parents=True)
            (src / "ix-dev" / "enterprise" / "hidden" / "app.yaml").write_text("name: hidden\n")
            (src / "ix-dev" / "dev" / "draft").mkdir(parents=True)
            (src / "ix-dev" / "dev" / "draft" / "app.yaml").write_text("name: draft\n")
            self.assertEqual(copy_trains(src, dest), 2)
            names = {row["name"] for row in list_apps(dest)}
            self.assertEqual(names, {"jellyfin", "custom"})
            self.assertFalse((dest / "ix-dev" / "enterprise").exists())
            self.assertFalse((dest / "ix-dev" / "dev").exists())
            self.assertFalse((dest / "ix-dev" / "stable" / "jellyfin" / ".env").exists())
            self.assertFalse((dest / "ix-dev" / "stable" / "jellyfin" / "id_ed25519").exists())
            listing = discover(pin_text("a" * 40), list_apps(dest))
            self.assertEqual(listing.reason, "listed")
            self.assertEqual(listing.names, ("jellyfin", "custom"))
            self.assertTrue(all(row.install == "refused" for row in listing.rows))
            self.assertEqual(request_install("jellyfin", confirmed=True).reason, "catalog_install_closed")

    def test_copy_drops_text_the_image_scan_rejects(self):
        with tempfile.TemporaryDirectory() as raw:
            src = Path(raw) / "src"
            dest = Path(raw) / "dest"
            app = src / "ix-dev" / "community" / "example"
            app.mkdir(parents=True)
            (app / "app.yaml").write_text("name: example\n")
            for index, phrase in enumerate(CONTENT):
                (app / f"bad-{index}.txt").write_bytes(phrase + b"\n")
            (app / "akia.txt").write_text("AKIA1234567890EXAMPLE\n")
            (app / "vendor.txt").write_text("ID_VENDOR_FROM_DATABASE=AKIA Corporation\n")
            (app / "binary.dat").write_bytes(b"\0BEGIN PRIVATE KEY")
            (app / "huge.txt").write_bytes(b"POSTGRES_PASSWORD=" + b"x" * MAX_TEXT)
            self.assertEqual(copy_trains(src, dest), 1)
            kept = dest / "ix-dev" / "community" / "example"
            self.assertTrue((kept / "app.yaml").is_file())
            self.assertTrue((kept / "vendor.txt").is_file())
            self.assertTrue((kept / "binary.dat").is_file())
            self.assertTrue((kept / "huge.txt").is_file())
            self.assertFalse((kept / "akia.txt").exists())
            for index in range(len(CONTENT)):
                self.assertFalse((kept / f"bad-{index}.txt").exists())
            names = {row["name"] for row in list_apps(dest)}
            self.assertEqual(names, {"example"})
            planted = kept / "templates"
            planted.mkdir()
            bad = planted / "https-values.yaml"
            bad.write_text("-----BEGIN PRIVATE KEY-----\n")
            self.assertEqual(drop_secret_content(dest), 1)
            self.assertFalse(bad.exists())
            self.assertTrue((kept / "app.yaml").is_file())

    def test_the_git_pin_still_lists_nothing(self):
        self.assertEqual(discover().reason, "pin_empty")
