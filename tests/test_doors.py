"""The adapter delivers a turn. The tunnel stays off."""

from __future__ import annotations

import json
import threading
import unittest

from doors.reach import (
    PERMANENT,
    THREE_HOURS,
    adapter_touch,
    deliver,
    join_mesh,
    mesh_open,
    remove_node,
    tunnel,
)
from doors.server import app, friday_base, listen_host, listening
from friday.server import app as friday_app
from gate.rules import MemoryStore
from runtime.forward import friday_base as shared_base
from runtime.http import serve

DOOR = "door-token"
NOTIFY = "notify-token"


class DoorTests(unittest.TestCase):
    def test_the_adapter_delivers_a_turn_and_cannot_approve(self) -> None:
        decision = deliver("adapter", confirmed=True)
        self.assertEqual((decision.outcome, decision.reason), ("delivered", "turn"))
        self.assertEqual(deliver("chat").reason, "not_an_adapter")
        for target in ("approve", "executor", "postgres"):
            decision = adapter_touch(target, confirmed=True)
            self.assertEqual(decision.reason, "adapter_cannot_approve")
            self.assertEqual(decision.__dict__.keys(), {"outcome", "reason"})

    def test_the_mesh_opens_the_board_and_does_not_join_core(self) -> None:
        self.assertEqual(join_mesh().reason, "not_core")
        self.assertEqual(mesh_open("board").reason, "board")
        self.assertEqual(mesh_open("mcp").reason, "mcp_listener")
        for name in ("postgres", "qdrant", "executor"):
            self.assertEqual(mesh_open(name).reason, "mesh_not_core")

    def test_the_tunnel_stays_off(self) -> None:
        self.assertEqual(tunnel().reason, "tunnel_off")
        self.assertEqual(
            tunnel(enabled=False, target="board", access_checked=True).reason,
            "tunnel_off",
        )

    def test_an_enabled_tunnel_is_the_board_after_an_access_check(self) -> None:
        self.assertEqual(
            tunnel(enabled=True, target="board", access_checked=False).reason,
            "access_unchecked",
        )
        decision = tunnel(enabled=True, target="board", access_checked=True)
        self.assertEqual((decision.outcome, decision.reason), ("allowed", "board"))
        self.assertEqual(tunnel(enabled=True, target="postgres").reason, "not_publishable")
        self.assertEqual(tunnel(enabled=True, target="qdrant").reason, "not_publishable")
        self.assertEqual(tunnel(enabled=True, target="memory-mcp").reason, "not_publishable")
        self.assertEqual(tunnel(enabled=True, target="taskrunner").reason, "not_publishable")
        self.assertEqual(tunnel(enabled=True, target="radarr").reason, "not_publishable")
        self.assertEqual(tunnel(enabled=True, target="sonarr").reason, "not_publishable")
        self.assertEqual(tunnel(enabled=True, target="prowlarr").reason, "not_publishable")
        self.assertEqual(tunnel(enabled=True, target="qbittorrent").reason, "not_publishable")
        self.assertEqual(tunnel(enabled=True, target="jellyfin").reason, "board_only")
        self.assertEqual(tunnel(enabled=True, target="friday").reason, "board_only")

    def test_cleanup_skips_while_headscale_is_absent_and_keeps_permanent_peers(self) -> None:
        self.assertEqual(PERMANENT, frozenset({"phone", "laptop", "nas"}))
        self.assertEqual(THREE_HOURS, 3 * 60 * 60)
        for name in ("phone", "Laptop", "NAS", "friday", "coder-", "Coder-job", "coder-job/phone"):
            decision = remove_node(
                name,
                mesh_on=True,
                workspace_gone=True,
                confirmed=True,
            )
            self.assertEqual((decision.outcome, decision.reason), ("refused", "permanent_peer"), name)
            self.assertEqual(decision.__dict__.keys(), {"outcome", "reason"})
        decision = remove_node("coder-job", confirmed=True)
        self.assertEqual((decision.outcome, decision.reason), ("skipped", "headscale_absent"))
        decision = remove_node("coder-job", mesh_on=True, confirmed=True)
        self.assertEqual((decision.outcome, decision.reason), ("kept", "workspace_still_here"))
        decision = remove_node(
            "coder-job",
            mesh_on=True,
            workspace_gone=True,
            failed_at=1_000,
            now=1_000 + THREE_HOURS - 1,
            confirmed=True,
        )
        self.assertEqual((decision.outcome, decision.reason), ("kept", "failed_work_kept"))
        decision = remove_node(
            "coder-job",
            mesh_on=True,
            workspace_gone=True,
            failed_at=1_000,
            now=500,
        )
        self.assertEqual(decision.reason, "failed_work_kept")
        decision = remove_node("coder-job", mesh_on=True, workspace_gone=True, failed_at=True, now=THREE_HOURS)
        self.assertEqual(decision.reason, "failed_work_kept")
        decision = remove_node(
            "coder-job",
            mesh_on=True,
            workspace_gone=True,
            failed_at=1_000,
            now=1_000 + THREE_HOURS,
            permanent=("coder-job",),
            confirmed=True,
        )
        self.assertEqual(decision.reason, "permanent_peer")
        decision = remove_node(
            "coder-job",
            mesh_on=True,
            workspace_gone=True,
            failed_at=1_000,
            now=1_000 + THREE_HOURS,
            confirmed=True,
        )
        self.assertEqual((decision.outcome, decision.reason), ("remove", "coder_workspace_gone"))
        decision = remove_node("coder-phone", mesh_on=True, workspace_gone=True)
        self.assertEqual(decision.reason, "coder_workspace_gone")


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


class DoorServerTests(unittest.TestCase):
    def test_the_door_stays_off_until_it_is_enabled(self) -> None:
        self.assertFalse(listening({}))
        self.assertTrue(listening({"DOOR_ENABLED": "yes"}))
        self.assertEqual(listen_host({}), "0.0.0.0")
        with self.assertRaises(OSError) as caught:
            listen_host({"BIND_HOST": "core"})
        self.assertEqual(str(caught.exception), "core_address")
        self.assertEqual(friday_base("http://friday:8080"), "http://friday:8080")
        self.assertIs(friday_base, shared_base)
        for raw in ("http://postgres:5432", "http://friday:80", "https://friday:8080", "http://executor:8080"):
            with self.assertRaises(OSError):
                friday_base(raw)

    def test_a_turn_reaches_friday_and_an_approval_does_not(self) -> None:
        seen = []

        def send(url, token, payload):
            seen.append((url, token, payload))
            return 200, {
                "outcome": "spoken",
                "reason": "model",
                "reply": "Ready.",
                "role": "friday",
                "approval_id": "not-for-the-door",
                "secret": NOTIFY,
            }

        env = {
            "DOOR_ENABLED": "yes",
            "DOOR_TOKEN": DOOR,
            "FRIDAY_NOTIFY_TOKEN": NOTIFY,
        }
        door = start(app(env, "http://friday:8080/ask", send))
        try:
            port = door.server_address[1]
            status, health = _get(port, "/health")
            self.assertEqual(status, 200)
            self.assertEqual(health["reason"], "health")
            status, body = post(
                port,
                "/turn",
                {
                    "text": "hello",
                    "owner_id": "owner-1",
                    "confirmed": True,
                    "approval_id": "minted-by-the-caller",
                },
                {"Friday-Door": DOOR},
            )
            self.assertEqual(status, 200, body)
            self.assertEqual(body["reply"], "Ready.")
            self.assertNotIn("approval_id", body)
            self.assertNotIn(NOTIFY, json.dumps(body))
            self.assertNotIn(DOOR, json.dumps(body))
            self.assertEqual(seen, [(
                "http://friday:8080/ask",
                NOTIFY,
                {"text": "hello", "owner_id": "owner-1", "owner_kind": "person"},
            )])
            status, closed = post(port, "/approvals", {"text": "approve"}, {"Friday-Door": DOOR})
            self.assertEqual(status, 404)
            self.assertEqual(closed["reason"], "unknown_path")
            self.assertEqual(len(seen), 1)
            status, denied = post(port, "/turn", {"text": "hello", "owner_id": "owner-1"}, {})
            self.assertEqual(status, 401)
            off = app({"DOOR_ENABLED": "no", "DOOR_TOKEN": DOOR}, "http://friday:8080/ask", send)
            status, body = off(
                "POST",
                "/turn",
                {"Friday-Door": DOOR},
                {"text": "hello", "owner_id": "owner-1"},
            )
            self.assertEqual(body["reason"], "door_off")
        finally:
            door.shutdown()
            door.server_close()

    def test_a_sensitive_turn_waits_and_creates_no_approval(self) -> None:
        store = MemoryStore()
        friday = start(friday_app(
            {
                "FRIDAY_NOTIFY_TOKEN": NOTIFY,
                "MEMORY_TOKEN": "memory-token",
                "EXECUTOR_URL": "",
            },
            embed=lambda: "",
            model=lambda _messages: "I have not done it.",
        ))

        def send(_url, token, payload):
            return post(friday.server_address[1], "/ask", payload, {"Friday-Notify": token})

        door = start(app(
            {"DOOR_ENABLED": "yes", "DOOR_TOKEN": DOOR, "FRIDAY_NOTIFY_TOKEN": NOTIFY},
            "http://friday:8080/ask",
            send,
        ))
        try:
            status, body = post(
                door.server_address[1],
                "/turn",
                {"text": "send the note to sam@example.com", "owner_id": "owner-1", "confirmed": True},
                {"Friday-Door": DOOR},
            )
            self.assertEqual(status, 200, body)
            self.assertEqual(body["outcome"], "waiting")
            self.assertEqual(body["action"], "send")
            self.assertNotIn("approval_id", body)
            self.assertEqual(store.approvals, {})
        finally:
            door.shutdown()
            friday.shutdown()
            door.server_close()
            friday.server_close()


def _get(port: int, path: str) -> tuple[int, dict]:
    import urllib.request

    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as response:
        return response.status, json.loads(response.read())


if __name__ == "__main__":
    unittest.main()
