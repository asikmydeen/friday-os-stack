"""The monitor setup form and the launcher that carries its token."""

import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from image.kiosk import (
    board_ready,
    chromium_command,
    forwarded_headers,
    opening,
    place_token,
    read_token,
    safe_path,
    serve_proxy,
    setup_finished,
)
from image.provision import handle
from image.setup import FakeRng, Iface, Store


class TokenTests(unittest.TestCase):
    def test_the_kiosk_file_is_private_and_one_line(self):
        with tempfile.TemporaryDirectory() as raw:
            dest = Path(raw) / "provision.token"
            place_token("ab" * 32, dest)
            self.assertEqual(read_token(dest), "ab" * 32)
            self.assertEqual(dest.stat().st_mode & 0o777, 0o600)
            place_token("", dest)
            self.assertFalse(dest.exists())
            self.assertEqual(read_token(dest), "")
            with self.assertRaises(OSError):
                place_token("has\nline", dest)
            self.assertFalse(dest.exists())
            dest.write_text("one\ntwo\n")
            self.assertEqual(read_token(dest), "")

    def test_the_command_line_does_not_carry_the_token(self):
        token = "c" * 64
        argv = chromium_command(token)
        self.assertTrue(any(part.endswith("/provision") for part in argv))
        self.assertIn("/usr/bin/cage", argv)
        self.assertIn("/usr/bin/chromium", argv)
        self.assertNotIn(token, "\n".join(argv))
        board = chromium_command("")
        self.assertIn("http://127.0.0.1:8080/", board)
        self.assertNotIn("/provision", board[-1])
        self.assertNotIn(":8081", "\n".join(board))

    def test_the_header_is_only_added_for_provision(self):
        token = "d" * 40
        incoming = {"Friday-Provision": "from-the-page", "Accept": "text/html"}
        self.assertEqual(forwarded_headers("/provision", incoming, token)["Friday-Provision"], token)
        self.assertNotIn("Friday-Provision", forwarded_headers("/", incoming, token))
        self.assertNotIn("Friday-Provision", forwarded_headers("/install", incoming, token))
        self.assertNotIn("Friday-Provision", forwarded_headers("/provision/", incoming, token))
        self.assertIsNone(safe_path("//other/provision"))
        self.assertIsNone(safe_path("http://127.0.0.1:8080/provision"))

    def test_opening_waits_until_the_right_server_answers(self):
        token = "e" * 16
        board = b"<title>Friday</title><button>Let Friday speak first</button>"
        self.assertEqual(opening("", 0, 0, b""), "wait")
        self.assertEqual(opening("", 401, 401, b"unauthenticated\n"), "wait")
        self.assertEqual(opening(token, 0, 0, b""), "wait")
        self.assertEqual(opening(token, 401, 401, b"unauthenticated\n"), "setup")
        self.assertEqual(opening("", 404, 200, board), "board")
        self.assertFalse(board_ready(401, board))
        self.assertFalse(board_ready(200, b"Friday setup"))
        self.assertFalse(setup_finished("/provision", b"Name: Provision: complete\nProvision: open\n"))
        self.assertTrue(setup_finished("/provision", b"Name: Ada\nProvision: complete\n"))
        self.assertFalse(setup_finished("/", b"Provision: complete\n"))
        self.assertFalse(setup_finished("/provision", "Provision: complete\n".encode("utf-16")))


class ProxyTests(unittest.TestCase):
    def test_a_browser_without_the_header_still_reaches_only_provision(self):
        seen = []

        class Recorder(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                return

            def do_GET(self):
                seen.append((self.path, self.headers.get("Friday-Provision")))
                body = b"ok\n"
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        upstream = ThreadingHTTPServer(("127.0.0.1", 0), Recorder)
        proxy = serve_proxy("f" * 32, upstream.server_address[1])
        threads = [
            threading.Thread(target=upstream.serve_forever, daemon=True),
            threading.Thread(target=proxy.serve_forever, daemon=True),
        ]
        for thread in threads:
            thread.start()
        port = proxy.server_address[1]

        def fetch(path, headers=None):
            request = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers=headers or {})
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, response.read()

        try:
            fetch("/provision")
            fetch("/provision", {"Friday-Provision": "from-the-page"})
            fetch("/")
            fetch("/memory")
        finally:
            proxy.shutdown()
            upstream.shutdown()
            proxy.server_close()
            upstream.server_close()
            for thread in threads:
                thread.join(timeout=5)
        self.assertEqual(
            seen,
            [
                ("/provision", "f" * 32),
                ("/provision", "f" * 32),
                ("/", None),
                ("/memory", None),
            ],
        )

    def test_the_monitor_page_is_a_form_and_hides_secrets(self):
        with tempfile.TemporaryDirectory() as raw:
            store = Store(Path(raw) / "data")
            store.omitted = ["friday", "nomic-embed-text"]
            store.load_or_mint(FakeRng(4))
            store.ifaces = [Iface("enp0s1", True, "wired")]
            token = store.provision_token
            password = store.board_password
            upstream = _serve(store)
            proxy = serve_proxy(token, upstream.server_address[1])
            threads = [
                threading.Thread(target=upstream.serve_forever, daemon=True),
                threading.Thread(target=proxy.serve_forever, daemon=True),
            ]
            for thread in threads:
                thread.start()
            port = proxy.server_address[1]

            def fetch(path, data=None, headers=None):
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
                self.assertEqual(status, 200)
                self.assertTrue(body.startswith("<!DOCTYPE html>"))
                self.assertIn(password, body)
                self.assertIn("Create the server on this computer", body)
                self.assertIn('action="/provision"', body)
                self.assertNotIn(token, body)
                self.assertNotIn(store.notify_token, body)
                self.assertNotIn(store.postgres_password, body)
                self.assertNotIn('name="confirmed"', body)
                self.assertNotIn('value="install"', body)
                self.assertIn("Friday does not speak", body)
                wifi = urllib.parse.urlencode(
                    {"action": "wifi", "ssid": "House", "password": "wpx-9k2m-not-shown"}
                ).encode()
                status, body = fetch("/provision", wifi)
                self.assertEqual(status, 200)
                self.assertNotIn("wpx-9k2m-not-shown", body)
                self.assertIn("House", body)
                model = urllib.parse.urlencode(
                    {
                        "action": "model",
                        "base": "https://example.test/v1",
                        "fast": "fast",
                        "think": "",
                        "key": "sk-test-key-9f3a",
                    }
                ).encode()
                status, body = fetch("/provision", model)
                self.assertNotIn("sk-test-key-9f3a", body)
                self.assertIn("model_address", body)
                named = store
                named.set_name("Provision: complete")
                status, plain = handle(
                    store,
                    "GET",
                    "/provision",
                    {"Friday-Provision": token},
                    b"",
                    local=True,
                )
                self.assertEqual(status, 200)
                self.assertFalse(setup_finished("/provision", plain.encode()))
            finally:
                proxy.shutdown()
                upstream.shutdown()
                proxy.server_close()
                upstream.server_close()
                for thread in threads:
                    thread.join(timeout=5)


def _serve(store):
    from image.provision import serve

    return serve(store, 0)


class PackTests(unittest.TestCase):
    def test_the_image_build_copies_the_launcher(self):
        script = Path("image/build-inside.sh").read_text()
        unit = Path("image/assets/friday-kiosk.service").read_text()
        self.assertIn("kiosk.py", script)
        self.assertIn("python3 -m image.kiosk", unit)
        self.assertIn("http://127.0.0.1:8080", unit)
        self.assertIn("/usr/bin/cage", unit)
        self.assertIn("/usr/bin/chromium", unit)
        self.assertIn("ConditionPathExists=/dev/dri/card0", unit)


if __name__ == "__main__":
    unittest.main()
