"""Recovery reads supplied objects. A runtime creates the container step."""

from __future__ import annotations

import unittest
from pathlib import Path

from executor.server import app as executor_app
from gate.recover import recover
from gate.rules import MemoryStore, complete_step, create_approval, submit
from tests.test_gate import OWNER, T0, machine_body

LABEL = "friday.operation"


def journal(steps, operation="start"):
    store = MemoryStore()
    body = machine_body(operation=operation)
    created = create_approval(
        store, actor="board", owner_id=OWNER, kind="machine", body=body, now=T0
    )
    exchanged = submit(
        store,
        actor="board",
        action=operation,
        owner_id=OWNER,
        approval_id=created.approval_id,
        body=body,
        now=T0,
        steps=[{"name": name, "state": "pending"} for name in steps],
    )
    return store, exchanged.operation_id


def labeled(operation_id, status="running"):
    return {"labels": {LABEL: operation_id}, "status": status}


class FakeRuntime:
    """Reports containers the test stored. Does not talk to a daemon."""

    def __init__(self, status: str = "running") -> None:
        self.status = status
        self.rows: list[str] = []
        self.creates = 0
        self.asked: list[str] = []

    def containers(self, operation_id: str):
        self.asked.append(operation_id)
        return list(self.rows)

    def create_container(self, operation_id: str) -> str:
        self.creates += 1
        self.asked.append(operation_id)
        self.rows.append(self.status)
        return "running"


def seen_for(operation_id, *, networks=0, volumes=0, containers=(), connected=None, images=()):
    payload = {
        "networks": [{"labels": {LABEL: operation_id}} for _ in range(networks)],
        "volumes": [{"labels": {LABEL: operation_id}} for _ in range(volumes)],
        "containers": [labeled(operation_id, status) for status in containers],
        "images": list(images),
    }
    if connected is not None:
        payload["connected"] = connected
    return payload


class RecoveryTests(unittest.TestCase):
    def test_chat_cannot_recover_or_mint_an_approval(self) -> None:
        store, operation_id = journal(("network", "volume", "container"))
        before = len(store.approvals)
        decision = recover(
            store,
            operation_id,
            seen_for(operation_id, networks=1, volumes=1),
            actor="chat",
            confirmed=True,
        )
        self.assertEqual(decision.reason, "actor_cannot_apply")
        self.assertEqual(len(store.approvals), before)
        self.assertEqual(store.operations[operation_id]["state"], "ready")

    def test_a_labeled_network_and_volume_are_not_a_running_container(self) -> None:
        store, operation_id = journal(("network", "volume", "container"))
        seen = seen_for(operation_id, networks=1, volumes=1)
        first = recover(store, operation_id, seen, actor="executor", confirmed=True)
        again = recover(store, operation_id, seen, actor="executor")
        operation = store.operations[operation_id]
        self.assertEqual((first.outcome, first.reason), ("running", "resume"))
        self.assertEqual(first.step, "container")
        self.assertEqual(first.action, "container")
        self.assertIs(first.create, True)
        self.assertEqual(again.action, "container")
        self.assertIs(again.create, True)
        self.assertEqual(operation["state"], "running")
        self.assertNotEqual(operation["state"], "applied")
        self.assertEqual(
            operation["steps"],
            [
                {"name": "network", "state": "done"},
                {"name": "volume", "state": "done"},
                {"name": "container", "state": "pending"},
            ],
        )
        self.assertEqual(len(store.approvals), 1)
        self.assertEqual(len(store.operations), 1)

        network_only = recover(
            store,
            operation_id,
            seen_for(operation_id, networks=1),
            actor="executor",
        )
        self.assertEqual(network_only.action, "volume")
        self.assertNotEqual(store.operations[operation_id]["state"], "applied")

    def test_applied_waits_until_the_container_is_up_and_is_not_created_twice(self) -> None:
        store, operation_id = journal(("network", "volume", "container"))
        seen = seen_for(operation_id, networks=1, volumes=1, containers=("exited",))
        not_up = recover(store, operation_id, seen, actor="executor")
        self.assertEqual(not_up.reason, "container_not_up")
        self.assertEqual(not_up.action, "start")
        self.assertIs(not_up.create, False)
        self.assertNotEqual(store.operations[operation_id]["state"], "applied")

        other = seen_for(operation_id, networks=1, volumes=1)
        other["containers"] = [labeled("someone-else", "running")]
        ignored = recover(store, operation_id, other, actor="executor")
        self.assertEqual(ignored.action, "container")
        self.assertIs(ignored.create, True)

        up = recover(
            store,
            operation_id,
            seen_for(operation_id, networks=1, volumes=1, containers=("Running",)),
            actor="executor",
        )
        self.assertEqual((up.outcome, up.reason), ("applied", "applied"))
        self.assertIsNone(up.action)
        self.assertIs(up.create, False)
        self.assertEqual(store.operations[operation_id]["state"], "applied")
        second = recover(
            store,
            operation_id,
            seen_for(operation_id, networks=1, volumes=1, containers=("running",)),
            actor="executor",
        )
        self.assertEqual(second.reason, "already_applied")
        self.assertIs(second.create, False)
        self.assertIsNone(second.action)
        self.assertEqual(len(store.approvals), 1)

    def test_two_labeled_containers_block_without_a_third(self) -> None:
        store, operation_id = journal(("network", "volume", "container"))
        decision = recover(
            store,
            operation_id,
            seen_for(operation_id, networks=1, volumes=1, containers=("running", "running")),
            actor="executor",
        )
        self.assertEqual((decision.outcome, decision.reason), ("blocked", "second_container"))
        self.assertIs(decision.create, False)
        self.assertIsNone(decision.action)
        self.assertEqual(store.operations[operation_id]["state"], "blocked")

    def test_a_finished_stop_is_not_issued_again_and_a_label_is_not_success(self) -> None:
        store, operation_id = journal(("stop",), operation="stop")
        claimed = complete_step(store, operation_id, "stop", actor="executor")
        self.assertEqual(claimed.reason, "step_recorded")
        self.assertEqual(store.operations[operation_id]["state"], "running")
        running = recover(
            store,
            operation_id,
            seen_for(operation_id, containers=("running",)),
            actor="executor",
        )
        self.assertEqual(running.reason, "labeled_not_success")
        self.assertEqual(running.action, "stop")
        self.assertIs(running.create, False)
        self.assertEqual(store.operations[operation_id]["steps"], [{"name": "stop", "state": "pending"}])
        self.assertNotEqual(store.operations[operation_id]["state"], "applied")

        missing = recover(store, operation_id, seen_for(operation_id), actor="executor")
        self.assertEqual(missing.reason, "container_missing")
        self.assertIsNone(missing.action)
        self.assertIs(missing.create, False)
        self.assertNotEqual(store.operations[operation_id]["state"], "applied")

        stopped = recover(
            store,
            operation_id,
            seen_for(operation_id, containers=("exited",)),
            actor="executor",
        )
        self.assertEqual((stopped.outcome, stopped.reason), ("applied", "applied"))
        self.assertIsNone(stopped.action)
        self.assertNotEqual(stopped.action, "stop")
        self.assertEqual(len(store.approvals), 1)

    def test_disconnect_leaves_the_container_running_and_pull_does_not_create_one(self) -> None:
        store, operation_id = journal(("disconnect",), operation="disconnect")
        left = recover(
            store,
            operation_id,
            seen_for(operation_id, containers=("running",), connected=False),
            actor="executor",
        )
        self.assertEqual(left.reason, "applied")
        self.assertIsNone(left.action)
        still = MemoryStore()
        body = machine_body(operation="disconnect")
        created = create_approval(
            still, actor="board", owner_id=OWNER, kind="machine", body=body, now=T0
        )
        exchanged = submit(
            still,
            actor="board",
            action="disconnect",
            owner_id=OWNER,
            approval_id=created.approval_id,
            body=body,
            now=T0,
            steps=[{"name": "disconnect", "state": "pending"}],
        )
        waiting = recover(
            still,
            exchanged.operation_id,
            seen_for(exchanged.operation_id, containers=("running",), connected=True),
            actor="executor",
        )
        self.assertEqual(waiting.action, "disconnect")
        self.assertIs(waiting.create, False)
        self.assertNotEqual(still.operations[exchanged.operation_id]["state"], "applied")
        stopped = recover(
            still,
            exchanged.operation_id,
            seen_for(exchanged.operation_id, containers=("exited",), connected=False),
            actor="executor",
        )
        self.assertEqual(stopped.reason, "not_left_running")
        self.assertIsNone(stopped.action)

        pulled_store, pulled_id = journal(("pull",), operation="pull")
        digest = machine_body()["image_digest"]
        waiting_pull = recover(pulled_store, pulled_id, seen_for(pulled_id), actor="executor")
        self.assertEqual(waiting_pull.action, "pull")
        self.assertIs(waiting_pull.create, False)
        done = recover(
            pulled_store,
            pulled_id,
            seen_for(pulled_id, images=(digest,)),
            actor="executor",
        )
        self.assertEqual(done.reason, "applied")
        self.assertIs(done.create, False)

    def test_install_and_a_bad_observation_do_not_change_the_journal(self) -> None:
        store = MemoryStore()
        store.operations["install-1"] = {
            "id": "install-1",
            "approval_id": "approval-1",
            "owner_id": OWNER,
            "kind": "machine",
            "operation": "install",
            "steps": [{"name": "container", "state": "pending"}],
            "state": "ready",
        }
        closed = recover(store, "install-1", seen_for("install-1"), actor="executor")
        self.assertEqual(closed.reason, "catalog_install_closed")
        self.assertEqual(store.operations["install-1"]["state"], "ready")
        self.assertEqual(store.approvals, {})

        live, operation_id = journal(("container",))
        refused = recover(live, operation_id, ["nope"], actor="executor")
        self.assertEqual(refused.reason, "observation_missing")
        self.assertEqual(live.operations[operation_id]["state"], "ready")
        held = recover(
            live,
            operation_id,
            seen_for(operation_id, containers=("restarting",)),
            actor="executor",
        )
        self.assertEqual(held.reason, "observation_incomplete")
        self.assertEqual(live.operations[operation_id]["state"], "ready")

    def test_the_executor_route_does_not_start_a_container(self) -> None:
        store, operation_id = journal(("network", "volume", "container"))
        handler = executor_app(
            store,
            {"BOARD_APPROVAL_TOKEN": "approval-token", "FRIDAY_NOTIFY_TOKEN": "notify-token"},
        )
        status, body = handler(
            "POST",
            "/recover",
            {"Friday-Notify": "notify-token"},
            {"operation_id": operation_id, "seen": seen_for(operation_id, networks=1, volumes=1)},
        )
        self.assertEqual(status, 401)
        self.assertEqual(store.operations[operation_id]["state"], "ready")
        status, body = handler(
            "POST",
            "/recover",
            {"Friday-Approval": "approval-token"},
            {
                "operation_id": operation_id,
                "seen": seen_for(operation_id, networks=1, volumes=1),
                "confirmed": True,
            },
        )
        self.assertEqual(status, 200, body)
        self.assertEqual(body["action"], "container")
        self.assertIs(body["create"], True)
        self.assertIs(body["started"], False)
        self.assertNotEqual(body["outcome"], "applied")
        self.assertEqual(len(store.approvals), 1)

    def test_applied_waits_until_the_runtime_says_up_and_is_not_created_twice(self) -> None:
        runtime = FakeRuntime("created")
        store, operation_id = journal(("network", "volume", "container"))
        seen = seen_for(operation_id, networks=1, volumes=1, containers=("running",))
        waiting = recover(
            store,
            operation_id,
            seen,
            actor="executor",
            runtime=runtime,
            confirmed=True,
        )
        self.assertEqual(waiting.reason, "container_not_up")
        self.assertIs(waiting.started, False)
        self.assertIs(waiting.create, False)
        self.assertNotEqual(store.operations[operation_id]["state"], "applied")
        self.assertEqual(runtime.creates, 1)
        self.assertEqual(runtime.rows, ["created"])
        again = recover(store, operation_id, seen, actor="executor", runtime=runtime)
        self.assertEqual(again.reason, "container_not_up")
        self.assertEqual(runtime.creates, 1)
        self.assertNotEqual(store.operations[operation_id]["state"], "applied")
        runtime.rows[:] = ["running"]
        applied = recover(store, operation_id, seen, actor="executor", runtime=runtime)
        self.assertEqual((applied.outcome, applied.reason), ("applied", "applied"))
        self.assertIs(applied.started, False)
        self.assertEqual(runtime.creates, 1)
        self.assertEqual(store.operations[operation_id]["state"], "applied")
        runtime.rows.clear()
        second = recover(store, operation_id, seen, actor="executor", runtime=runtime)
        self.assertEqual(second.reason, "already_applied")
        self.assertIs(second.started, False)
        self.assertEqual(runtime.creates, 1)

    def test_a_runtime_that_reports_up_applies_on_the_create_and_not_again(self) -> None:
        runtime = FakeRuntime("running")
        store, operation_id = journal(("network", "volume", "container"))
        seen = seen_for(operation_id, networks=1, volumes=1)
        first = recover(store, operation_id, seen, actor="executor", runtime=runtime)
        self.assertEqual((first.outcome, first.reason), ("applied", "applied"))
        self.assertIs(first.started, True)
        self.assertEqual(runtime.creates, 1)
        self.assertEqual(runtime.rows, ["running"])
        second = recover(store, operation_id, seen, actor="executor", runtime=runtime)
        self.assertEqual(second.reason, "already_applied")
        self.assertIs(second.started, False)
        self.assertEqual(runtime.creates, 1)
        self.assertEqual(len(store.approvals), 1)

    def test_an_existing_runtime_container_is_not_created_again(self) -> None:
        runtime = FakeRuntime("exited")
        runtime.rows.append("Running")
        store, operation_id = journal(("network", "volume", "container"))
        seen = seen_for(operation_id, networks=1, volumes=1)
        applied = recover(store, operation_id, seen, actor="executor", runtime=runtime)
        self.assertEqual(applied.reason, "applied")
        self.assertIs(applied.started, False)
        self.assertEqual(runtime.creates, 0)
        self.assertEqual(runtime.rows, ["Running"])

    def test_the_runtime_is_not_asked_before_the_container_step_or_for_a_stop(self) -> None:
        runtime = FakeRuntime()
        store, operation_id = journal(("network", "volume", "container"))
        early = recover(
            store,
            operation_id,
            seen_for(operation_id),
            actor="executor",
            runtime=runtime,
        )
        self.assertEqual(early.action, "network")
        self.assertEqual(runtime.creates, 0)
        self.assertEqual(runtime.asked, [])
        self.assertNotEqual(store.operations[operation_id]["state"], "applied")
        chat = recover(
            store,
            operation_id,
            seen_for(operation_id, networks=1, volumes=1),
            actor="chat",
            runtime=runtime,
            confirmed=True,
        )
        self.assertEqual(chat.reason, "actor_cannot_apply")
        self.assertEqual(runtime.creates, 0)
        self.assertEqual(runtime.asked, [])
        stopped, stop_id = journal(("stop",), operation="stop")
        stop = recover(
            stopped,
            stop_id,
            seen_for(stop_id, containers=("running",)),
            actor="executor",
            runtime=runtime,
        )
        self.assertEqual(stop.action, "stop")
        self.assertEqual(runtime.creates, 0)
        self.assertEqual(runtime.asked, [])
        self.assertNotEqual(stopped.operations[stop_id]["state"], "applied")

    def test_two_runtime_containers_block_and_a_broken_runtime_does_not_apply(self) -> None:
        runtime = FakeRuntime()
        runtime.rows.extend(("running", "running"))
        store, operation_id = journal(("network", "volume", "container"))
        seen = seen_for(operation_id, networks=1, volumes=1)
        blocked = recover(store, operation_id, seen, actor="executor", runtime=runtime)
        self.assertEqual(blocked.reason, "second_container")
        self.assertEqual(runtime.creates, 0)
        self.assertEqual(store.operations[operation_id]["state"], "blocked")

        class Down:
            def containers(self, operation_id: str):
                raise OSError("docker daemon")

            def create_container(self, operation_id: str) -> str:
                raise AssertionError("created")

        fresh, fresh_id = journal(("container",))
        refused = recover(
            fresh,
            fresh_id,
            seen_for(fresh_id),
            actor="executor",
            runtime=Down(),
        )
        self.assertEqual(refused.reason, "runtime_refused")
        self.assertNotIn("docker", refused.reason)
        self.assertEqual(fresh.operations[fresh_id]["state"], "ready")
        bare = recover(fresh, fresh_id, seen_for(fresh_id), actor="executor", runtime=object())
        self.assertEqual(bare.reason, "runtime_refused")
        self.assertEqual(fresh.operations[fresh_id]["state"], "ready")

    def test_the_route_uses_the_fake_runtime_and_a_posted_name_does_not(self) -> None:
        runtime = FakeRuntime("created")
        store, operation_id = journal(("network", "volume", "container"))
        handler = executor_app(
            store,
            {"BOARD_APPROVAL_TOKEN": "approval-token", "FRIDAY_NOTIFY_TOKEN": "notify-token"},
            runtime=runtime,
        )
        payload = {
            "operation_id": operation_id,
            "seen": seen_for(operation_id, networks=1, volumes=1),
            "runtime": "docker",
            "confirmed": True,
        }
        status, body = handler("POST", "/recover", {"Friday-Approval": "approval-token"}, payload)
        self.assertEqual(status, 200, body)
        self.assertEqual(body["reason"], "container_not_up")
        self.assertIs(body["started"], False)
        self.assertNotEqual(body["outcome"], "applied")
        self.assertEqual(runtime.creates, 1)
        self.assertNotEqual(store.operations[operation_id]["state"], "applied")
        status, body = handler("POST", "/recover", {"Friday-Approval": "approval-token"}, payload)
        self.assertEqual(runtime.creates, 1)
        self.assertNotEqual(store.operations[operation_id]["state"], "applied")
        runtime.rows[:] = ["running"]
        status, body = handler("POST", "/recover", {"Friday-Approval": "approval-token"}, payload)
        self.assertEqual(status, 200, body)
        self.assertEqual(body["outcome"], "applied")
        self.assertIs(body["started"], False)
        self.assertEqual(runtime.creates, 1)

        other, other_id = journal(("network", "volume", "container"))
        posted = executor_app(
            other,
            {"BOARD_APPROVAL_TOKEN": "approval-token", "FRIDAY_NOTIFY_TOKEN": "notify-token"},
        )
        status, body = posted(
            "POST",
            "/recover",
            {"Friday-Approval": "approval-token"},
            {
                "operation_id": other_id,
                "seen": seen_for(other_id, networks=1, volumes=1),
                "runtime": "docker",
            },
        )
        self.assertEqual(status, 200, body)
        self.assertEqual(body["action"], "container")
        self.assertIs(body["create"], True)
        self.assertIs(body["started"], False)
        self.assertNotEqual(other.operations[other_id]["state"], "applied")
        up_runtime = FakeRuntime("running")
        up_store, up_id = journal(("network", "volume", "container"))
        up_handler = executor_app(
            up_store,
            {"BOARD_APPROVAL_TOKEN": "approval-token", "FRIDAY_NOTIFY_TOKEN": "notify-token"},
            runtime=up_runtime,
        )
        status, body = up_handler(
            "POST",
            "/recover",
            {"Friday-Approval": "approval-token"},
            {"operation_id": up_id, "seen": seen_for(up_id, networks=1, volumes=1)},
        )
        self.assertEqual(status, 200, body)
        self.assertEqual(body["outcome"], "applied")
        self.assertIs(body["started"], True)
        self.assertEqual(up_runtime.creates, 1)
        status, body = up_handler(
            "POST",
            "/recover",
            {"Friday-Approval": "approval-token"},
            {"operation_id": up_id, "seen": seen_for(up_id, networks=1, volumes=1)},
        )
        self.assertEqual(body["reason"], "already_applied")
        self.assertIs(body["started"], False)
        self.assertEqual(up_runtime.creates, 1)
        source_path = Path(recover.__code__.co_filename)
        source = source_path.read_text(encoding="utf-8")
        server = Path(executor_app.__code__.co_filename).read_text(encoding="utf-8")
        for text in (source, server):
            self.assertNotIn("import docker", text)
            self.assertNotIn("docker.sock", text)
            self.assertNotIn("subprocess", text)
            self.assertNotIn("import socket", text)
            self.assertNotIn("urlopen", text)
        root = source_path.parents[1]
        ask = (root / "friday" / "ask.py").read_text(encoding="utf-8")
        self.assertNotIn("create_container", ask)
        self.assertNotIn("gate.recover", ask)


if __name__ == "__main__":
    unittest.main()
