"""Outbound MCP calls only a granted server. Mutating calls wait."""

from __future__ import annotations

import json
import threading
import unittest
import urllib.error
import urllib.request

from mcpbus.outbound import app, granted_servers, listening, vet_server
from runtime.forward import listen_host
from runtime.http import serve

TOKEN = "outbound-token"
SECRET = "vault-secret-marker"
PEER = "https://peer.example/mcp"


def start(handler):
    server = serve(handler, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def stop(server) -> None:
    server.shutdown()
    server.server_close()


def post(port: int, path: str, payload: dict, headers: dict | None = None) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read())
        finally:
            exc.close()
        return exc.code, body


class OutboundTests(unittest.TestCase):
    def env(self) -> dict[str, str]:
        return {
            "OUTBOUND_ENABLED": "yes",
            "OUTBOUND_TOKEN": TOKEN,
            "GRANTED_TOOLS": "status,send",
            "GRANTED_SERVERS": PEER,
        }

    def handler(self, rpc, resolve=None):
        calls = []

        def wrapped(url: str, secret: str, method: str, params: dict) -> dict:
            calls.append({"url": url, "secret": secret, "method": method, "params": params})
            return rpc(url, secret, method, params)

        resolved = resolve or (lambda host: ["93.184.216.34"])
        return app(self.env(), wrapped, resolved), calls

    def test_outbound_stays_off_until_it_is_enabled(self) -> None:
        self.assertFalse(listening({}))
        self.assertTrue(listening({"OUTBOUND_ENABLED": "yes"}))
        self.assertEqual(granted_servers({"GRANTED_SERVERS": f" {PEER}, "}), (PEER,))
        self.assertEqual(listen_host({}), "0.0.0.0")
        with self.assertRaises(OSError) as caught:
            listen_host({"BIND_HOST": "core"})
        self.assertEqual(str(caught.exception), "core_address")
        handler = app({}, lambda *args: {}, lambda host: ["93.184.216.34"])
        server = start(handler)
        try:
            status, body = post(server.server_address[1], "/call", {"server": PEER, "tool": "status"}, {"Friday-Outbound": TOKEN})
        finally:
            stop(server)
        self.assertEqual((status, body["reason"]), (403, "outbound_off"))

    def test_tools_lists_only_the_granted_intersection(self) -> None:
        def rpc(url: str, secret: str, method: str, params: dict) -> dict:
            return {"tools": [{"name": "status"}, {"name": "send"}, {"name": "qdrant"}]}

        handler, calls = self.handler(rpc)
        server = start(handler)
        try:
            status, body = post(
                server.server_address[1],
                "/tools",
                {"server": PEER, "secret": SECRET, "confirmed": True},
                {"Friday-Outbound": TOKEN},
            )
        finally:
            stop(server)
        names = [tool["name"] for tool in body["tools"]]
        self.assertEqual((status, names), (200, ["send", "status"]))
        self.assertNotIn(SECRET, json.dumps(body))
        self.assertEqual(calls[0]["method"], "tools/list")
        self.assertNotIn(SECRET, calls[0]["url"])

    def test_a_granted_read_is_forwarded_and_the_secret_is_stripped(self) -> None:
        def rpc(url: str, secret: str, method: str, params: dict) -> dict:
            if method == "tools/list":
                return {"tools": [{"name": "status"}, {"name": "send"}]}
            return {"text": f"lighthouse {secret}", "qdrant_key": "marker", "approval_id": "nope"}

        handler, calls = self.handler(rpc)
        server = start(handler)
        try:
            status, body = post(
                server.server_address[1],
                "/call",
                {
                    "server": PEER,
                    "tool": "status",
                    "arguments": {"owner_id": "one", "confirmed": True},
                    "secret": SECRET,
                    "confirmed": True,
                    "approval_id": "should-not-echo",
                },
                {"Friday-Outbound": TOKEN},
            )
        finally:
            stop(server)
        raw = json.dumps(body)
        self.assertEqual(status, 200)
        self.assertEqual(body["reason"], "called")
        self.assertIn("lighthouse", body["result"]["text"])
        self.assertNotIn(SECRET, raw)
        self.assertNotIn("qdrant_key", raw)
        self.assertNotIn("approval_id", raw)
        sent = [call for call in calls if call["method"] == "tools/call"]
        self.assertEqual(len(sent), 1)
        self.assertNotIn("confirmed", sent[0]["params"]["arguments"])

    def test_a_mutating_call_waits_and_is_not_forwarded(self) -> None:
        def rpc(url: str, secret: str, method: str, params: dict) -> dict:
            return {"tools": [{"name": "status"}, {"name": "send"}]}

        handler, calls = self.handler(rpc)
        server = start(handler)
        try:
            status, body = post(
                server.server_address[1],
                "/call",
                {"server": PEER, "tool": "send", "secret": SECRET, "confirmed": True},
                {"Friday-Outbound": TOKEN},
            )
        finally:
            stop(server)
        self.assertEqual((status, body["outcome"], body["reason"], body["started"]), (202, "waiting", "board_must_approve", False))
        self.assertNotIn("approval_id", json.dumps(body))
        self.assertNotIn(SECRET, json.dumps(body))
        self.assertEqual([call["method"] for call in calls], ["tools/list"])

    def test_an_ungranted_or_core_server_is_not_called(self) -> None:
        handler, calls = self.handler(lambda *args: {"tools": []})
        server = start(handler)
        try:
            missing, body = post(
                server.server_address[1],
                "/call",
                {"server": "https://other.example/mcp", "tool": "status"},
                {"Friday-Outbound": TOKEN},
            )
            core_env = self.env()
            core_env["GRANTED_SERVERS"] = "http://postgres:5432/mcp"
            core = app(core_env, lambda *args: {"tools": []}, lambda host: ["10.0.0.1"])
            core_server = start(core)
            try:
                refused, core_body = post(
                    core_server.server_address[1],
                    "/call",
                    {"server": "http://postgres:5432/mcp", "tool": "status"},
                    {"Friday-Outbound": TOKEN},
                )
            finally:
                stop(core_server)
        finally:
            stop(server)
        self.assertEqual((missing, body["reason"]), (403, "unknown_server"))
        self.assertEqual((refused, core_body["reason"]), (403, "core_closed"))
        self.assertEqual(calls, [])
        self.assertEqual(vet_server("http://127.0.0.1/mcp", lambda host: ["127.0.0.1"]), "loopback")
        self.assertIsNone(vet_server(PEER, lambda host: ["93.184.216.34"]))
