"""The gate refuses an action the Board has not approved."""

from __future__ import annotations

import threading
import unittest
from datetime import datetime, timedelta, timezone

from gate.rules import (
    MemoryStore,
    complete_step,
    create_approval,
    record_task,
    resume_operation,
    resume_task,
    submit,
)

T0 = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
OWNER = "owner-1"


def life_body(**overrides):
    body = {
        "action_class": "send",
        "target": "sam@example.com",
        "payload_digest": "digest-1",
    }
    body.update(overrides)
    return body


def machine_body(**overrides):
    body = {
        "operation": "grant",
        "app_id": "jellyfin",
        "catalog_pin": "pin-1",
        "template_hash": "tmpl-1",
        "rendered_digest": "render-1",
        "image_digest": "image-1",
        "mounts": ["/mnt/apps/jellyfin"],
        "ports": [{"host_ip": "127.0.0.1", "host_port": 8096, "container_port": 8096}],
        "privileges": [],
        "devices": [],
        "manifest_privileges": [],
        "manifest_devices": [],
        "network_mode": "bridge",
        "pid_mode": "private",
        "ipc_mode": "private",
        "storage_disk": "/mnt/apps",
        "storage_device": "disk-apps",
        "data_device": "disk-data",
    }
    body.update(overrides)
    return body


def approve_life(store, **overrides):
    body = life_body(**overrides)
    decision = create_approval(
        store, actor="board", owner_id=OWNER, kind="life", body=body, now=T0
    )
    return decision, body


def approve_machine(store, **overrides):
    body = machine_body(**overrides)
    links = overrides.pop("links", None)
    decision = create_approval(
        store,
        actor="board",
        owner_id=OWNER,
        kind="machine",
        body=body,
        now=T0,
        links=links,
    )
    return decision, body


class OpenActions(unittest.TestCase):
    def test_draft_recall_and_granted_tool_do_not_need_an_approval(self):
        store = MemoryStore()
        for action in ("draft", "recall", "granted_tool"):
            decision = submit(
                store, actor="chat", action=action, owner_id=OWNER, confirmed=True
            )
            self.assertEqual(decision.outcome, "allowed")
            self.assertEqual(decision.reason, "open_action")
        self.assertEqual(store.approvals, {})


class ChatCannotApprove(unittest.TestCase):
    def test_sensitive_actions_wait_and_store_nothing(self):
        store = MemoryStore()
        for actor in ("chat", "door", "mcp"):
            for action in ("send", "pay", "delete", "publish", "grant", "backup"):
                decision = submit(
                    store,
                    actor=actor,
                    action=action,
                    owner_id=OWNER,
                    confirmed=True,
                )
                self.assertEqual(decision.outcome, "waiting", action)
                self.assertEqual(decision.reason, "approval_required")
        self.assertEqual(store.approvals, {})
        self.assertEqual(store.operations, {})

    def test_a_passed_approval_id_is_not_exchanged_by_chat(self):
        store = MemoryStore()
        created, body = approve_life(store)
        decision = submit(
            store,
            actor="chat",
            action="send",
            owner_id=OWNER,
            approval_id=created.approval_id,
            body=body,
            confirmed=True,
        )
        self.assertEqual(decision.outcome, "waiting")
        self.assertEqual(decision.reason, "actor_cannot_exchange")
        self.assertEqual(store.approvals[created.approval_id]["status"], "approved")
        self.assertEqual(store.operations, {})

    def test_chat_cannot_create_an_approval(self):
        store = MemoryStore()
        decision = create_approval(
            store,
            actor="chat",
            owner_id=OWNER,
            kind="life",
            body=life_body(confirmed=True),
            now=T0,
        )
        self.assertEqual(decision.reason, "actor_cannot_approve")
        self.assertEqual(store.approvals, {})


class Exchange(unittest.TestCase):
    def test_matching_life_step_exchanges_once(self):
        store = MemoryStore()
        created, body = approve_life(store)
        first = submit(
            store,
            actor="board",
            action="send",
            owner_id=OWNER,
            approval_id=created.approval_id,
            body=body,
            now=T0 + timedelta(minutes=1),
        )
        second = submit(
            store,
            actor="board",
            action="send",
            owner_id=OWNER,
            approval_id=created.approval_id,
            body=body,
            now=T0 + timedelta(minutes=2),
        )
        self.assertEqual(first.outcome, "exchanged")
        self.assertEqual(second.reason, "already_exchanged")
        self.assertEqual(first.operation_id, second.operation_id)
        self.assertEqual(len(store.operations), 1)
        self.assertEqual(store.approvals[created.approval_id]["status"], "exchanged")

    def test_a_different_digest_voids_the_record(self):
        store = MemoryStore()
        created, body = approve_life(store)
        body["payload_digest"] = "digest-2"
        decision = submit(
            store,
            actor="board",
            action="send",
            owner_id=OWNER,
            approval_id=created.approval_id,
            body=body,
            now=T0,
        )
        self.assertEqual(decision.reason, "void")
        self.assertEqual(store.approvals[created.approval_id]["status"], "void")
        self.assertEqual(store.operations, {})

    def test_a_different_action_voids_the_record(self):
        store = MemoryStore()
        created, body = approve_life(store)
        decision = submit(
            store,
            actor="board",
            action="pay",
            owner_id=OWNER,
            approval_id=created.approval_id,
            body=body,
            now=T0,
        )
        self.assertEqual(decision.reason, "void")
        self.assertEqual(store.operations, {})

    def test_expiry_is_ten_minutes(self):
        store = MemoryStore()
        created, body = approve_life(store)
        still = submit(
            store,
            actor="board",
            action="send",
            owner_id=OWNER,
            approval_id=created.approval_id,
            body=body,
            now=T0 + timedelta(minutes=10) - timedelta(seconds=1),
        )
        self.assertEqual(still.outcome, "exchanged")

        store = MemoryStore()
        created, body = approve_life(store)
        expired = submit(
            store,
            actor="board",
            action="send",
            owner_id=OWNER,
            approval_id=created.approval_id,
            body=body,
            now=T0 + timedelta(minutes=10),
        )
        self.assertEqual(expired.reason, "expired")
        self.assertEqual(store.approvals[created.approval_id]["status"], "expired")
        self.assertEqual(store.operations, {})

    def test_concurrent_exchange_writes_one_journal(self):
        store = MemoryStore()
        created, body = approve_life(store)
        results = []

        def once():
            results.append(
                submit(
                    store,
                    actor="board",
                    action="send",
                    owner_id=OWNER,
                    approval_id=created.approval_id,
                    body=body,
                    now=T0,
                )
            )

        threads = [threading.Thread(target=once) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        ids = {item.operation_id for item in results}
        self.assertEqual(len(store.operations), 1)
        self.assertEqual(len(ids), 1)


class CatalogInstall(unittest.TestCase):
    def test_every_app_id_is_refused_and_nothing_is_stored(self):
        store = MemoryStore()
        for app_id in ("jellyfin", "plex", "home-assistant", "radarr"):
            created = create_approval(
                store,
                actor="board",
                owner_id=OWNER,
                kind="machine",
                body=machine_body(operation="install", app_id=app_id),
                now=T0,
            )
            submitted = submit(
                store,
                actor="board",
                action="install",
                owner_id=OWNER,
                body=machine_body(operation="install", app_id=app_id),
                confirmed=True,
                now=T0,
            )
            self.assertEqual(created.reason, "catalog_install_closed")
            self.assertEqual(submitted.reason, "catalog_install_closed")
        self.assertEqual(store.approvals, {})
        self.assertEqual(store.operations, {})

    def test_a_planted_install_row_is_not_consumed(self):
        store = MemoryStore()
        approval_id = "planted"
        store.approvals[approval_id] = {
            "id": approval_id,
            "kind": "machine",
            "owner_id": OWNER,
            "status": "approved",
            "body": {"operation": "install", "app_id": "jellyfin"},
            "expires_at": T0 + timedelta(minutes=10),
            "operation_id": None,
            "created_by": "board",
        }
        decision = submit(
            store,
            actor="board",
            action="install",
            owner_id=OWNER,
            approval_id=approval_id,
            now=T0,
        )
        self.assertEqual(decision.reason, "catalog_install_closed")
        self.assertEqual(store.approvals[approval_id]["status"], "approved")
        self.assertEqual(store.operations, {})


class MachineRules(unittest.TestCase):
    def test_a_matching_grant_exchanges(self):
        store = MemoryStore()
        created, body = approve_machine(store)
        decision = submit(
            store,
            actor="board",
            action="grant",
            owner_id=OWNER,
            approval_id=created.approval_id,
            body=body,
            now=T0,
        )
        self.assertEqual(decision.outcome, "exchanged")
        self.assertEqual(created.reason, "recorded")

    def test_forbidden_mounts_are_refused(self):
        cases = [
            {"mounts": ["/etc/passwd"]},
            {"mounts": ["/home/owner/videos"]},
            {"mounts": ["/run/secrets/token"]},
            {"mounts": ["/soul/SOUL.md"]},
            {"mounts": ["/var/lib/friday/sqlite/friday.db"]},
            {"mounts": ["/var/lib/docker"]},
            {"mounts": ["/var/run/docker.sock"]},
            {"mounts": ["/"]},
            {"mounts": ["/mnt/apps/../../etc"]},
            {"mounts": ["/other/jellyfin"]},
        ]
        for overrides in cases:
            store = MemoryStore()
            decision, _body = approve_machine(store, **overrides)
            self.assertEqual(decision.outcome, "refused", overrides)
            self.assertEqual(store.approvals, {})

    def test_a_symlink_to_etc_is_refused(self):
        store = MemoryStore()
        decision, _body = approve_machine(
            store,
            mounts=["/mnt/apps/hidden"],
            links={"/mnt/apps/hidden": "/etc"},
        )
        self.assertIn(decision.reason, {"mount_forbidden", "mount_outside_disk", "mount_root"})
        self.assertEqual(store.approvals, {})

    def test_symlink_parent_is_resolved_before_dotdot(self):
        store = MemoryStore()
        decision, _body = approve_machine(
            store,
            mounts=["/mnt/apps/hidden/../ok"],
            links={"/mnt/apps/hidden": "/etc"},
        )
        self.assertEqual(decision.outcome, "refused")
        self.assertEqual(store.approvals, {})

    def test_host_modes_devices_and_ports(self):
        refused = [
            {"network_mode": "host"},
            {"pid_mode": "host"},
            {"ipc_mode": "host"},
            {"privileges": ["SYS_ADMIN"]},
            {"devices": ["/dev/dri"]},
            {"storage_device": "disk-data"},
            {
                "ports": [
                    {"host_ip": "0.0.0.0", "host_port": 8096, "container_port": 8096}
                ]
            },
        ]
        for overrides in refused:
            store = MemoryStore()
            decision, _body = approve_machine(store, **overrides)
            self.assertEqual(decision.outcome, "refused", overrides)
            self.assertEqual(store.approvals, {})

    def test_a_changed_digest_voids_a_grant(self):
        store = MemoryStore()
        created, body = approve_machine(store)
        body["image_digest"] = "image-2"
        decision = submit(
            store,
            actor="board",
            action="grant",
            owner_id=OWNER,
            approval_id=created.approval_id,
            body=body,
            now=T0,
        )
        self.assertEqual(decision.reason, "void")

    def test_publish_port_may_name_a_route(self):
        store = MemoryStore()
        body = machine_body(
            operation="publish_port",
            mounts=[],
            ports=[{"host_ip": "0.0.0.0", "host_port": 443, "container_port": 8443}],
        )
        created = create_approval(
            store, actor="board", owner_id=OWNER, kind="machine", body=body, now=T0
        )
        decision = submit(
            store,
            actor="board",
            action="publish_port",
            owner_id=OWNER,
            approval_id=created.approval_id,
            body=body,
            now=T0,
        )
        self.assertEqual(decision.outcome, "exchanged", decision.reason)


class Recovery(unittest.TestCase):
    def test_resume_does_not_mint_an_approval_or_a_second_journal(self):
        store = MemoryStore()
        created, body = approve_machine(store, operation="stop", mounts=[])
        exchanged = submit(
            store,
            actor="board",
            action="stop",
            owner_id=OWNER,
            approval_id=created.approval_id,
            body=body,
            now=T0,
            steps=[
                {"name": "network", "state": "done"},
                {"name": "stop", "state": "pending"},
            ],
        )
        before = len(store.approvals)
        resumed = resume_operation(store, exchanged.operation_id)
        self.assertEqual(resumed.operation_id, exchanged.operation_id)
        self.assertEqual(len(store.approvals), before)
        self.assertEqual(len(store.operations), 1)
        self.assertEqual(store.operations[exchanged.operation_id]["steps"][0]["state"], "done")

    def test_a_finished_step_is_not_recorded_twice(self):
        store = MemoryStore()
        created, body = approve_machine(store, operation="stop", mounts=[])
        exchanged = submit(
            store,
            actor="board",
            action="stop",
            owner_id=OWNER,
            approval_id=created.approval_id,
            body=body,
            now=T0,
            steps=[{"name": "stop", "state": "pending"}],
        )
        chat = complete_step(store, exchanged.operation_id, "stop", actor="chat")
        self.assertEqual(chat.reason, "actor_cannot_apply")
        first = complete_step(store, exchanged.operation_id, "stop", actor="executor")
        second = complete_step(store, exchanged.operation_id, "stop", actor="executor")
        operation = store.operations[exchanged.operation_id]
        self.assertEqual(first.reason, "step_recorded")
        self.assertEqual(second.reason, "step_recorded")
        self.assertEqual(operation["steps"], [{"name": "stop", "state": "done"}])
        self.assertEqual(operation["state"], "applied")
        self.assertEqual(len(store.approvals), 1)


class TaskJournal(unittest.TestCase):
    def test_a_sensitive_step_waits_without_an_approval(self):
        store = MemoryStore()
        decision = record_task(
            store,
            owner_id=OWNER,
            role_id="chief",
            goal="Book Tuesday and tell me when it needs a card",
            steps=[{"name": "draft"}, {"name": "pay"}],
        )
        self.assertEqual(decision.reason, "waiting")
        self.assertEqual(store.approvals, {})
        resumed = resume_task(store, decision.task_id)
        self.assertEqual(resumed.reason, "resumed")
        self.assertEqual(store.tasks[decision.task_id]["state"], "waiting")
        self.assertEqual(store.tasks[decision.task_id]["steps"][0], {"name": "draft", "state": "pending"})
        self.assertEqual(len(store.approvals), 0)

    def test_drafts_alone_are_ready(self):
        store = MemoryStore()
        decision = record_task(
            store,
            owner_id=OWNER,
            role_id=None,
            goal="Summarize the thread",
            steps=[{"name": "draft"}, {"name": "recall"}],
        )
        self.assertEqual(decision.reason, "ready")
        self.assertEqual(store.approvals, {})


if __name__ == "__main__":
    unittest.main()
