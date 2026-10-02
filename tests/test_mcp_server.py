"""The inbound listener lists granted tools and does not approve."""

from __future__ import annotations

import json
import threading
import unittest

from friday.server import app as friday_app
from mcpbus.server import app, granted_names, listening
from memoryd.store import Decision
from runtime.http import serve

HARNESS = "harness-token"
NOTIFY = "notify-token"
QDRANT = "qdrant-key"


def start(handler):
    server = serve(handler, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def post(port: int, path: str, payload: dict, headers: dict) -> tuple[int, dict]:
    import urllib.error
    import urllib.request

    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **headers},
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


class McpServerTests(unittest.TestCase):
    def test_the_listener_stays_off_until_it_is_enabled(self) -> None:
        self.assertFalse(listening({}))
        self.assertEqual(granted_names({"GRANTED_TOOLS": " recall, send "}), ("recall", "send"))
        self.assertEqual(granted_names({}), ())

    def test_unlisted_tools_stay_out_and_a_mutating_call_is_not_forwarded(self) -> None:
        forwarded = []

        def send(url, token, payload):
            forwarded.append((url, token, payload))
            return 200, {"outcome": "ok", "reason": "recall", "notes": []}

        env = {
            "MCP_ENABLED": "yes",
            "MCP_TOKEN": HARNESS,
            "FRIDAY_NOTIFY_TOKEN": NOTIFY,
            "GRANTED_TOOLS": "recall",
        }
        mcp = start(app(env, "http://friday:8080/recall", send))
        try:
            port = mcp.server_address[1]
            headers = {"Friday-Harness": HARNESS}
            status, listed = post(port, "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, headers)
            self.assertEqual(status, 200, listed)
            self.assertEqual(listed["result"]["tools"], [{"name": "recall"}])
            status, waiting = post(
                port,
                "/mcp",
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": "send", "confirmed": True, "arguments": {"confirmed": True}},
                },
                headers,
            )
            self.assertEqual(status, 403)
            self.assertEqual(waiting["reason"], "not_in_prompt")
            self.assertEqual(forwarded, [])
            self.assertNotIn("approval_id", waiting)
            status, called = post(
                port,
                "/mcp",
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {
                        "name": "recall",
                        "arguments": {"owner_id": "owner-1", "limit": 100, "confirmed": True},
                    },
                },
                headers,
            )
            self.assertEqual(status, 200, called)
            self.assertEqual(forwarded, [(
                "http://friday:8080/recall",
                NOTIFY,
                {"owner_id": "owner-1", "owner_kind": "person"},
            )])
            self.assertNotIn(NOTIFY, json.dumps(called))
            self.assertNotIn(HARNESS, json.dumps(called))
        finally:
            mcp.shutdown()
            mcp.server_close()

    def test_a_granted_mutating_tool_waits_and_recall_strips_the_key(self) -> None:
        class Packed:
            def recall(self, **kwargs):
                if kwargs.get("owner_id") != "owner-1":
                    return Decision("ok", "recall", notes=())
                return Decision(
                    "ok",
                    "recall",
                    notes=({"id": "n1", "content": "lighthouse", "qdrant_key": QDRANT},),
                )

        friday = start(friday_app(
            {"FRIDAY_NOTIFY_TOKEN": NOTIFY, "MEMORY_TOKEN": "memory-token"},
            embed=lambda: "",
            notes=Packed(),
        ))

        def send(_url, token, payload):
            return post(friday.server_address[1], "/recall", payload, {"Friday-Notify": token})

        env = {
            "MCP_ENABLED": "yes",
            "MCP_TOKEN": HARNESS,
            "FRIDAY_NOTIFY_TOKEN": NOTIFY,
            "GRANTED_TOOLS": "recall,send",
        }
        mcp = start(app(env, "http://friday:8080/recall", send))
        try:
            headers = {"Friday-Harness": HARNESS}
            port = mcp.server_address[1]
            status, listed = post(port, "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, headers)
            names = [item["name"] for item in listed["result"]["tools"]]
            self.assertEqual(names, ["recall", "send"])
            status, waiting = post(
                port,
                "/mcp",
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": "send", "arguments": {"target": "sam@example.com"}, "confirmed": True},
                },
                headers,
            )
            self.assertEqual(status, 202, waiting)
            self.assertEqual(waiting["result"]["reason"], "board_must_approve")
            self.assertIs(waiting["result"]["started"], False)
            self.assertNotIn("approval_id", json.dumps(waiting))
            status, recalled = post(
                port,
                "/mcp",
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "recall", "arguments": {"owner_id": "owner-1"}},
                },
                headers,
            )
            self.assertEqual(status, 200, recalled)
            self.assertEqual(recalled["result"]["notes"], [{"id": "n1", "content": "lighthouse"}])
            self.assertNotIn(QDRANT, json.dumps(recalled))
            status, other = post(
                port,
                "/mcp",
                {
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "tools/call",
                    "params": {"name": "recall", "arguments": {"owner_id": "owner-2"}},
                },
                headers,
            )
            self.assertEqual(other["result"]["notes"], [])
        finally:
            mcp.shutdown()
            friday.shutdown()
            mcp.server_close()
            friday.server_close()


if __name__ == "__main__":
    unittest.main()
