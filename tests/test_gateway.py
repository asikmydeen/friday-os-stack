"""The gateway forwards a wire health URL and refuses everything else."""

from __future__ import annotations

import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from gateway.proxy import allows_from_dir, allows_from_text, match
from gateway.server import serve


class AllowList(unittest.TestCase):
    def test_health_urls_are_allowed_and_webhook_targets_are_not(self):
        allows = allows_from_dir(Path("catalog/wires"))
        hosts = {item.host for item in allows}
        self.assertIn("jellyfin", hosts)
        self.assertIn("home-assistant", hosts)
        self.assertIn("qbittorrent", hosts)
        self.assertNotIn("webhooks", hosts)
        self.assertNotIn("postgres", hosts)
        self.assertNotIn("friday", hosts)
        jellyfin = match("GET", "/jellyfin/health", allows)
        self.assertIsNotNone(jellyfin)
        self.assertEqual(jellyfin.port, 8096)
        self.assertIsNone(match("POST", "/jellyfin/health", allows))
        self.assertIsNone(match("GET", "/webhooks/arr", allows))
        self.assertIsNone(match("GET", "/postgres/health", allows))
        self.assertIsNone(match("GET", "/jellyfin/secret", allows))

    def test_a_core_health_url_is_dropped(self):
        allows = allows_from_text("health: { url: http://postgres:5432/health }\n")
        self.assertEqual(allows, ())


class Proxy(unittest.TestCase):
    def test_a_named_health_url_is_forwarded_and_other_calls_are_refused(self):
        class Upstream(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                return

            def do_GET(self):
                if self.path != "/health":
                    self.send_response(404)
                    self.end_headers()
                    return
                raw = b'{"upstream":"ok"}'
                self.send_response(200)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
        thread = threading.Thread(target=upstream.serve_forever)
        thread.start()
        port = upstream.server_address[1]
        text = f"health: {{ url: http://127.0.0.1:{port}/health }}\n"
        httpd = serve(allows_from_text(text), "127.0.0.1", 0)
        front = threading.Thread(target=httpd.serve_forever)
        front.start()
        gateway = httpd.server_address[1]

        def fetch(path, method="GET"):
            request = urllib.request.Request(f"http://127.0.0.1:{gateway}{path}", method=method)
            try:
                with urllib.request.urlopen(request, timeout=5) as response:
                    return response.status, response.read()
            except urllib.error.HTTPError as exc:
                try:
                    return exc.code, exc.read()
                finally:
                    exc.close()

        try:
            status, body = fetch("/health")
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)["outcome"], "ok")
            status, body = fetch(f"/127.0.0.1/health")
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)["upstream"], "ok")
            status, body = fetch("/jellyfin/health")
            self.assertEqual(status, 403)
            self.assertIn(b"not_allowed", body)
            status, body = fetch(f"/127.0.0.1/health", method="POST")
            self.assertEqual(status, 403)
            missing = serve(allows_from_text("health: { url: http://127.0.0.1:1/health }\n"), "127.0.0.1", 0)
            side = threading.Thread(target=missing.serve_forever)
            side.start()
            try:
                status, body = fetch_port(missing.server_address[1], "/127.0.0.1/health")
                self.assertEqual(status, 502)
                self.assertIn(b"upstream_unavailable", body)
            finally:
                missing.shutdown()
                missing.server_close()
                side.join(timeout=5)
        finally:
            httpd.shutdown()
            httpd.server_close()
            upstream.shutdown()
            upstream.server_close()
            front.join(timeout=5)
            thread.join(timeout=5)


def fetch_port(port, path):
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, exc.read()
        finally:
            exc.close()
