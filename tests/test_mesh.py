"""Mesh choice at setup. These tests do not call Docker or start Headscale."""

import subprocess
import sys
import tempfile
import unittest
import urllib.parse
from pathlib import Path

from image.mesh import (
    choose_create,
    choose_join,
    choose_local,
    images_for,
    preauth_argv,
    render_headscale_config,
    serve_argv,
    take_key,
    user_create_argv,
    user_id,
)
from image.provision import handle
from image.setup import FakeRng, Iface, Store
from image.starter import _mint_mesh, _redact, start_core
from memoryd.store import credential_shape

JOIN_KEY = "tskey-auth-examplevalue99"
BOX = "tskey-auth-boxkeyvalue1"
PHONE = "tskey-auth-phonekeyvalue1"
LAPTOP = "tskey-auth-laptopkeyval1"
ROOT = Path(__file__).resolve().parents[1]


class ChoiceTests(unittest.TestCase):
    def test_local_is_a_complete_choice(self):
        choice = choose_local()
        self.assertEqual(choice.mode, "local")
        self.assertEqual(choice.reason, "")
        self.assertEqual(choice.key, "")
        self.assertEqual(choice.port, "8443")

    def test_join_keeps_a_real_key_and_a_loopback_control_url(self):
        choice = choose_join("http://127.0.0.1:8080", JOIN_KEY)
        self.assertEqual(choice.reason, "")
        self.assertEqual(choice.url, "http://127.0.0.1:8080")
        self.assertEqual(choice.key, JOIN_KEY)
        self.assertEqual(images_for("join"), ("friday-os-stack/tailscale:1.82.5-amd64",))

    def test_a_long_key_is_not_refused_for_looking_like_a_secret(self):
        key = "A" * 60
        self.assertTrue(credential_shape(key))
        choice = choose_join("http://10.1.1.8:443", key)
        self.assertEqual(choice.reason, "")
        self.assertEqual(choice.key, key)

    def test_join_refuses_a_credential_shaped_key_and_a_hidden_query(self):
        self.assertEqual(choose_join("http://10.1.1.8:443", "token=abcd").reason, "mesh_key_missing")
        self.assertEqual(
            choose_join("http://10.1.1.8:443", "password is hunter22").reason,
            "mesh_key_missing",
        )
        self.assertEqual(choose_join("http://10.1.1.8:443", "").reason, "mesh_key_missing")
        self.assertEqual(choose_join("http://10.1.1.8:443", "tskey\nauth").reason, "mesh_key_missing")
        hidden = "http%3A%2F%2F10.1.1.8%3A443%3Ftoken%3Dabcd"
        self.assertEqual(choose_join(hidden, JOIN_KEY).reason, "mesh_url")
        self.assertEqual(
            choose_join("http://user:secret@10.1.1.8:443", JOIN_KEY).reason,
            "mesh_url",
        )
        self.assertEqual(choose_join("http://postgres:443", JOIN_KEY).reason, "mesh_url")

    def test_create_uses_the_typed_url_and_refuses_the_board_port(self):
        choice = choose_create("HTTP://192.168.1.20:8443/")
        self.assertEqual(choice.reason, "")
        self.assertEqual(choice.url, "http://192.168.1.20:8443")
        self.assertEqual(choice.key, "")
        self.assertEqual(choice.port, "8443")
        self.assertEqual(choose_create("http://192.168.1.20:8080").reason, "mesh_port")
        self.assertEqual(choose_create("http://192.168.1.20").reason, "mesh_port")
        self.assertEqual(choose_create("http://127.0.0.1:8443").reason, "mesh_url")
        self.assertEqual(choose_create("http://localhost:8443").reason, "mesh_url")
        self.assertEqual(choose_create("http://friday.mesh:8443").reason, "mesh_url")
        self.assertEqual(choose_create("http://box.friday.mesh:8443").reason, "mesh_url")
        self.assertEqual(choose_create("http://qdrant:8443").reason, "mesh_url")
        self.assertEqual(images_for("create")[0], "friday-os-stack/headscale:0.26.1-amd64")
        self.assertEqual(images_for(""), ())

    def test_config_names_the_typed_url_and_leaves_the_key_out(self):
        text = render_headscale_config("http://192.168.1.20:8443", 8443)
        self.assertIn('server_url: "http://192.168.1.20:8443"', text)
        self.assertIn("listen_addr: 0.0.0.0:8443", text)
        self.assertIn("metrics_listen_addr: 127.0.0.1:9090", text)
        self.assertIn("grpc_listen_addr: 127.0.0.1:50443", text)
        self.assertIn("enabled: false", text)
        self.assertIn("https://controlplane.tailscale.com/derpmap/default", text)
        self.assertIn("path: /var/lib/headscale/db.sqlite", text)
        self.assertIn("mode: database", text)
        self.assertIn("base_domain: friday.mesh", text)
        self.assertIn("magic_dns: true", text)
        self.assertIn("enabled: false", text)
        self.assertIn("disable_check_updates: true", text)
        self.assertIn("unix_socket: /var/run/headscale/headscale.sock", text)
        self.assertNotIn(JOIN_KEY, text)
        self.assertNotIn("1.2.3.4", text)

    def test_the_mint_commands_use_a_numeric_user_and_one_time_keys(self):
        self.assertEqual(user_id('noise\n{"id": 1, "name": "friday"}\n'), "1")
        self.assertEqual(user_id('[{"id": "2", "name": "friday"}]'), "2")
        self.assertEqual(user_id('{"id": 9, "name": "other"}'), "")
        self.assertEqual(user_id("User created"), "")
        self.assertIn("--user", preauth_argv("1"))
        self.assertIn("1", preauth_argv("1"))
        self.assertIn("--reusable=false", preauth_argv("1"))
        self.assertIn("168h", preauth_argv("1"))
        self.assertIn("friday", user_create_argv())
        self.assertEqual(
            take_key("2026-10-02T00:00:00Z false\ntskey-auth-phonekeyvalue1\n"),
            PHONE,
        )
        self.assertEqual(serve_argv()[-4:], ["serve", "--bg", "--http=80", "8080"])


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "data")
        self.store.load_or_mint(FakeRng(4))
        self.store.ifaces = [Iface("enp0s1", True, "wired")]

    def tearDown(self):
        self.tmp.cleanup()

    def _headers(self):
        return {"Friday-Provision": self.store.provision_token}

    def test_unset_mesh_still_finishes(self):
        self._ready()
        self.store.embed_transport = lambda: (
            200,
            b'{"model":"nomic-embed-text","embeddings":[[0,0,0]]}',
        )
        # The vector above is short on purpose only when we replace it.
        self.store.embed_transport = lambda: _embed()
        outcome = self.store.finish()
        self.assertEqual(outcome.reason, "ok")
        self.assertIn("Mesh: this computer only", self.store.status_text())
        self.assertIn("Catalog install is refused.", self.store.status_text())

    def test_join_stores_the_key_privately_and_the_page_does_not_echo_it(self):
        body = urllib.parse.urlencode(
            {
                "action": "mesh_join",
                "url": "http://10.1.1.8:443",
                "key": JOIN_KEY,
                "confirmed": "true",
            }
        ).encode()
        status, page = handle(self.store, "POST", "/provision", self._headers(), body, local=True)
        self.assertEqual(status, 200)
        self.assertEqual(self.store.mesh_mode, "join")
        self.assertIn("Mesh: joining http://10.1.1.8:443", page)
        self.assertNotIn(JOIN_KEY, page)
        self.assertNotIn(JOIN_KEY, self.store.status_text())
        secret = self.store.root / "secrets" / "mesh_auth_key"
        self.assertEqual(secret.read_text().strip(), JOIN_KEY)
        self.assertEqual(secret.stat().st_mode & 0o777, 0o600)
        again = Store(self.store.root)
        again.load_or_mint(FakeRng(5))
        self.assertEqual(again.mesh_auth_key, JOIN_KEY)
        self.assertEqual(again.mesh_mode, "join")

    def test_local_deletes_a_stored_join_key(self):
        self.store.set_mesh("join", "http://10.1.1.8:443", JOIN_KEY)
        outcome = self.store.set_mesh("local")
        self.assertEqual(outcome.reason, "mesh_set")
        self.assertFalse((self.store.root / "secrets" / "mesh_auth_key").exists())
        self.assertNotIn(JOIN_KEY, self.store.status_text())
        self.assertIn("Mesh: this computer only", self.store.status_text())

    def test_create_does_not_keep_a_caller_key_and_shows_minted_keys_until_finish(self):
        body = urllib.parse.urlencode(
            {
                "action": "mesh_create",
                "url": "http://192.168.1.20:8443",
                "key": JOIN_KEY,
            }
        ).encode()
        _status, page = handle(self.store, "POST", "/provision", self._headers(), body, local=True)
        self.assertIn("Phone and laptop keys appear after the server starts.", page)
        self.assertNotIn(JOIN_KEY, page)
        self.assertFalse((self.store.root / "secrets" / "mesh_auth_key").exists())
        self.store.save_mesh_keys(BOX, PHONE, LAPTOP)
        shown = self.store.status_text()
        self.assertIn(PHONE, shown)
        self.assertIn(LAPTOP, shown)
        self.assertNotIn(BOX, shown)
        self.assertEqual((self.store.root / "headscale" / "phone.key").stat().st_mode & 0o777, 0o600)
        self._ready()
        self.store.embed_transport = _embed
        self.assertEqual(self.store.finish().reason, "ok")
        hidden = self.store.status_text()
        self.assertNotIn(PHONE, hidden)
        self.assertNotIn(LAPTOP, hidden)
        self.assertNotIn(BOX, hidden)
        self.assertEqual(self.store.set_mesh("local").reason, "still_provisioning")

    def test_chat_cannot_set_the_mesh(self):
        body = urllib.parse.urlencode(
            {"action": "mesh_join", "url": "http://10.1.1.8:443", "key": JOIN_KEY}
        ).encode()
        handle(
            self.store,
            "POST",
            "/",
            {"Friday-Board": self.store.board_password},
            body,
            local=True,
        )
        self.assertEqual(self.store.mesh_mode, "")
        self.assertFalse((self.store.root / "secrets" / "mesh_auth_key").exists())

    def test_the_form_offers_the_three_choices_before_the_server_button(self):
        _status, page = handle(self.store, "GET", "/provision", self._headers(), b"", local=True)
        self.assertLess(page.index("mesh_local"), page.index('value="server"'))
        self.assertLess(page.index("mesh_join"), page.index('value="server"'))
        self.assertLess(page.index("mesh_create"), page.index('value="server"'))
        self.assertIn('type="password"', page)
        self.assertIn("Catalog install stays closed.", page)

    def _ready(self):
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


def _embed():
    import json

    return 200, json.dumps({"model": "nomic-embed-text", "embeddings": [[0] * 768]}).encode()


class StartTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "data")
        self.store.load_or_mint(FakeRng(6))
        self.store.omitted = []
        self.root = Path(self.tmp.name) / "image-root"
        models = (
            self.root
            / "usr/lib/friday/ollama-models/models/manifests/registry.ollama.ai/library/nomic-embed-text"
        )
        models.mkdir(parents=True)
        (models / "latest").write_text("{}\n")
        (self.root / "usr/lib/friday/images").mkdir(parents=True)
        (self.root / "usr/lib/friday/images/core-images.tar").write_bytes(b"tar")
        (self.root / "usr/lib/friday/qdrant_bootstrap.py").write_text("print('ok')\n")
        (self.root / "usr/lib/friday/compose.yml").write_text("name: friday\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_local_start_passes_no_profile(self):
        calls = []

        def run(argv):
            calls.append(list(argv))
            return ""

        start_core(self.store, run, self.root, embed_check=lambda: _embed()[1], pause=lambda _s: None)
        ups = [argv for argv in calls if "up" in argv]
        self.assertEqual(len(ups), 1)
        self.assertNotIn("--profile", ups[0])
        self.assertNotIn("reach", ups[0])
        env = (self.store.root / "core.env").read_text()
        self.assertIn('MESH_MODE="local"', env)
        self.assertIn('MESH_PORT="8443"', env)
        self.assertIn('MESH_AUTHKEY=""', env)

    def test_join_starts_only_the_client_and_hides_the_key(self):
        self.store.set_mesh("join", "http://10.1.1.8:443", JOIN_KEY)
        calls = []

        def run(argv):
            calls.append(list(argv))
            if argv[:3] == ["docker", "ps"]:
                return "friday-friday-1\n"
            return ""

        start_core(self.store, run, self.root, embed_check=lambda: _embed()[1], pause=lambda _s: None)
        ups = [argv for argv in calls if "up" in argv]
        self.assertEqual(len(ups), 1)
        self.assertIn("--profile", ups[0])
        self.assertIn("mesh", ups[0])
        self.assertNotIn("mesh-server", ups[0])
        self.assertNotIn("reach", ups[0])
        self.assertNotIn("headscale", " ".join(ups[0]))
        self.assertIn(serve_argv(), calls)
        env = (self.store.root / "core.env").read_text()
        self.assertIn(JOIN_KEY, env)
        self.assertNotIn(JOIN_KEY, self.store.status_text())
        self.assertNotIn(JOIN_KEY, (self.store.root / "start.log").read_text())
        redacted = _redact(self.store, f"failed {JOIN_KEY}")
        self.assertNotIn(JOIN_KEY, redacted)

    def test_create_mints_keys_before_the_client_starts(self):
        self.store.set_mesh("create", "http://192.168.1.20:8443")
        calls = []
        minted = {"n": 0}

        def run(argv):
            calls.append(list(argv))
            if argv[:3] == ["docker", "ps"]:
                return "friday-friday-1\nfriday-headscale-1\n"
            if argv == user_create_argv():
                return '{"id": 1, "name": "friday"}\n'
            if "preauthkeys" in argv:
                minted["n"] += 1
                return [BOX, PHONE, LAPTOP][minted["n"] - 1] + "\n"
            return ""

        start_core(self.store, run, self.root, embed_check=lambda: _embed()[1], pause=lambda _s: None)
        ups = [argv for argv in calls if "up" in argv]
        self.assertEqual(_profiles(ups[0]), ["mesh-server"])
        self.assertEqual(_profiles(ups[1]), ["mesh"])
        create_at = calls.index(user_create_argv())
        first_key = next(i for i, argv in enumerate(calls) if "preauthkeys" in argv)
        server_up = calls.index(ups[0])
        client_up = calls.index(ups[1])
        serve_at = calls.index(serve_argv())
        self.assertLess(server_up, create_at)
        self.assertLess(create_at, first_key)
        self.assertLess(first_key, client_up)
        self.assertLess(client_up, serve_at)
        self.assertEqual(minted["n"], 3)
        env = (self.store.root / "core.env").read_text()
        self.assertIn(BOX, env)
        self.assertNotIn(BOX, self.store.status_text())
        self.assertIn(PHONE, self.store.status_text())
        config = (self.store.root / "headscale" / "config" / "config.yaml").read_text()
        self.assertIn("0.0.0.0:8443", config)
        self.assertIn("logtail:\n  enabled: false", config)
        self.assertNotIn(BOX, config)
        self.assertNotIn(PHONE, config)
        self.assertNotIn("reach", ups[0])
        self.assertNotIn("core", (ROOT / "image/assets/core-compose.yml").read_text().split("  headscale:")[1].split("networks:")[0])

    def test_a_second_create_reuses_minted_keys(self):
        self.store.set_mesh("create", "http://192.168.1.20:8443")
        self.store.save_mesh_keys(BOX, PHONE, LAPTOP)
        calls = []

        def run(argv):
            calls.append(list(argv))
            return ""

        start_core(self.store, run, self.root, embed_check=lambda: _embed()[1], pause=lambda _s: None)
        self.assertFalse(any("preauthkeys" in argv for argv in calls))
        self.assertIn(serve_argv(), calls)

    def test_missing_mesh_images_do_not_start_compose(self):
        self.store.set_mesh("join", "http://10.1.1.8:443", JOIN_KEY)
        calls = []

        def run(argv):
            calls.append(list(argv))
            if argv[:3] == ["docker", "image", "inspect"] and "tailscale" in argv[-1]:
                raise OSError("missing")
            return ""

        with self.assertRaises(OSError) as caught:
            start_core(self.store, run, self.root, embed_check=lambda: _embed()[1], pause=lambda _s: None)
        self.assertEqual(str(caught.exception), "mesh_images_missing")
        self.assertFalse(any("up" in argv for argv in calls))

    def test_mint_retries_until_the_server_answers(self):
        self.store.set_mesh("create", "http://192.168.1.20:8443")
        state = {"n": 0}

        def run(argv):
            state["n"] += 1
            if state["n"] < 3:
                raise OSError("down")
            if argv == user_create_argv():
                return '{"id": 7, "name": "friday"}'
            if "preauthkeys" in argv:
                state["keys"] = state.get("keys", 0) + 1
                return [BOX, PHONE, LAPTOP][state["keys"] - 1]
            return ""

        _mint_mesh(self.store, run, lambda _seconds: None, attempts=4)
        self.assertEqual(self.store.mesh_auth_key, BOX)
        self.assertEqual(self.store.mesh_phone_key, PHONE)
        self.assertNotIn(BOX, self.store.status_text())

    def test_ask_does_not_import_the_mesh_module(self):
        proc = subprocess.run(
            [
                sys.executable,
                "-c",
                "import friday.ask, sys; raise SystemExit(0 if 'image.mesh' not in sys.modules else 1)",
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("image.mesh", (ROOT / "friday/ask.py").read_text())


def _profiles(argv: list[str]) -> list[str]:
    found = []
    for index, item in enumerate(argv):
        if item == "--profile":
            found.append(argv[index + 1])
    return found


class ComposeTests(unittest.TestCase):
    def test_the_image_compose_keeps_headscale_off_core(self):
        text = (ROOT / "image/assets/core-compose.yml").read_text()
        headscale = text.split("  headscale:", 1)[1].split("\nnetworks:", 1)[0]
        tailscale = text.split("  tailscale:", 1)[1].split("  headscale:", 1)[0]
        self.assertIn("profiles: [mesh-server]", headscale)
        self.assertIn("networks: [mesh]", headscale)
        self.assertNotIn("core", headscale)
        self.assertIn("pull_policy: never", headscale)
        self.assertIn("profiles: [mesh]", tailscale)
        self.assertIn("network_mode: host", tailscale)
        self.assertIn("pull_policy: never", tailscale)
        self.assertNotIn("networks: [core]", tailscale)
        self.assertIn("\n  mesh:\n", text)

    def test_the_installer_copies_mesh(self):
        script = (ROOT / "image/build-inside.sh").read_text()
        loop = [line for line in script.splitlines() if line.startswith("for name in ")]
        self.assertEqual(loop, [
            "for name in __init__.py disks.py install.py setup.py provision.py console.py main.py starter.py mesh.py qdrant_bootstrap.py wifi.py kiosk.py logs.py; do",
        ])
        self.assertIn("usr/lib/friday/image/mesh.py", script)


if __name__ == "__main__":
    unittest.main()
