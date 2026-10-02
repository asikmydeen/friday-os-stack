"""One approval through approval_store. The connection is a stub."""

from __future__ import annotations

import unittest
import uuid
from pathlib import Path

from executor.server import app as executor_app
from executor.server import open_approvals
from friday.ask import ask
from gate.rules import MemoryStore
from gate.sqlstore import SCHEMA, PostgresApprovals, exchange_approval, record_approval, statements

ROOT = Path(__file__).resolve().parents[1]
APPROVAL = "11111111-1111-4111-8111-111111111111"
OPERATION = "22222222-2222-4222-8222-222222222222"
OTHER = "33333333-3333-4333-8333-333333333333"
SECRET = "password is hunter22"
KEPT = "The password is kept outside the machine"
ENV = {
    "BOARD_APPROVAL_TOKEN": "approval-secret",
    "FRIDAY_NOTIFY_TOKEN": "notify-secret",
}


class Box:
    """One connection. It does not open a database."""

    def __init__(self, rows=(), fail: BaseException | None = None) -> None:
        self.rows = list(rows)
        self.fail = fail
        self.calls: list[tuple] = []
        self.ran: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        if params is None:
            self.ran.append(sql)
        else:
            self.calls.append((sql, params))
            if any(isinstance(item, str) and "changed-digest" in item for item in params):
                raise RuntimeError("already_exchanged")
        if self.fail is not None:
            raise self.fail
        return self

    def fetchone(self):
        if not self.rows:
            return None
        return self.rows.pop(0)


def _life(**over):
    body = {
        "action_class": "send",
        "target": "sam@example.com",
        "payload_digest": "digest-1",
    }
    body.update(over)
    return body


def _machine(**over):
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
    body.update(over)
    return body


def _record(**over):
    fields = {
        "actor": "board",
        "action": "send",
        "owner_id": "owner-1",
        "body": _life(),
    }
    fields.update(over)
    return fields


def _exchange(**over):
    fields = {
        "actor": "board",
        "action": "send",
        "owner_id": "owner-1",
        "approval_id": APPROVAL,
        "body": _life(),
    }
    fields.update(over)
    return fields


class PostgresApprovalTests(unittest.TestCase):
    def test_schema_keeps_each_function_in_one_statement(self) -> None:
        parts = statements(SCHEMA.read_text(encoding="utf-8"))
        store = next(part for part in parts if "FUNCTION approval_store" in part)
        owner = next(part for part in parts if "FUNCTION approval_exchange_owner" in part)
        exchange = next(part for part in parts if "FUNCTION approval_exchange(" in part)
        self.assertEqual(store.count("$$"), 2)
        self.assertEqual(owner.count("$$"), 2)
        self.assertIn("actor_cannot_approve", store)
        self.assertIn("catalog_install_closed", store)
        self.assertIn("owner_mismatch", owner)
        self.assertIn("RETURN approval_exchange", owner)
        self.assertIn("RETURNS uuid", exchange)
        proof = (ROOT / "tests" / "approvals.sql").read_text(encoding="utf-8")
        self.assertIn("op1 := approval_exchange(", proof)
        self.assertIn("approval_exchange_owner", proof)

    def test_two_exchanges_call_the_functions_and_keep_one_id(self) -> None:
        box = Box(rows=[(APPROVAL,), (OPERATION,), (uuid.UUID(OPERATION),)])
        client = PostgresApprovals(lambda: box)
        store = MemoryStore()
        book: dict[str, str] = {}
        recorded = record_approval(store, _record(body=_life(confirmed=True)), client)
        first = exchange_approval(store, _exchange(), client, book)
        second = exchange_approval(store, _exchange(), client, book)
        self.assertEqual(recorded.reason, "recorded")
        self.assertEqual(recorded.approval_id, APPROVAL)
        self.assertEqual(first.reason, "exchanged")
        self.assertEqual(first.operation_id, OPERATION)
        self.assertEqual(second.reason, "already_exchanged")
        self.assertEqual(second.operation_id, OPERATION)
        self.assertEqual(len(store.operations), 1)
        self.assertEqual(store.operations[OPERATION]["state"], "ready")
        self.assertEqual(store.approvals[APPROVAL]["status"], "exchanged")
        self.assertEqual(len(box.calls), 3)
        self.assertIn("approval_store", box.calls[0][0])
        self.assertIn("approval_exchange_owner", box.calls[1][0])
        self.assertNotIn("confirmed", box.calls[0][1][3])
        self.assertNotIn(SECRET, repr(recorded))
        self.assertEqual(book[APPROVAL], OPERATION)

    def test_a_changed_body_voids_and_a_replay_does_not_rewrite(self) -> None:
        voided = Box(rows=[(None,), ("void",)])
        store = MemoryStore()
        decision = exchange_approval(
            store,
            _exchange(body=_life(payload_digest="other")),
            PostgresApprovals(lambda: voided),
            {},
        )
        self.assertEqual(decision.reason, "void")
        self.assertIsNone(decision.operation_id)
        self.assertEqual(store.operations, {})
        self.assertIn("status FROM approvals", voided.calls[1][0])
        changed = Box(rows=[(OPERATION,)])
        book = {APPROVAL: OPERATION}
        replay = exchange_approval(
            store,
            _exchange(body=_life(payload_digest="changed-digest")),
            PostgresApprovals(lambda: changed),
            book,
        )
        self.assertEqual(replay.reason, "already_exchanged")
        self.assertIsNone(replay.operation_id)
        self.assertEqual(book[APPROVAL], OPERATION)

    def test_refusals_do_not_open_the_connection(self) -> None:
        box = Box(rows=[(APPROVAL,), (OPERATION,)])
        client = PostgresApprovals(lambda: box)
        store = MemoryStore()
        refused = [
            record_approval(store, _record(actor="chat"), client),
            record_approval(store, _record(action="install", operation="install"), client),
            record_approval(store, _record(body=_life(target=SECRET)), client),
            record_approval(store, _record(body=_life(target="password%20is%20hunter22")), client),
            record_approval(store, _record(owner_id=""), client),
            record_approval(
                store,
                _record(action="grant", body=_machine(mounts=["/etc"])),
                client,
            ),
            record_approval(
                store,
                _record(action="grant", body=_machine(mounts=["/home/owner"])),
                client,
            ),
            record_approval(
                store,
                _record(action="grant", body=_machine(mounts=["/run/secrets/board"])),
                client,
            ),
            record_approval(
                store,
                _record(
                    action="grant",
                    body=_machine(mounts=["/mnt/apps/link"]),
                    links={"/mnt/apps/link": "/etc"},
                ),
                client,
            ),
            exchange_approval(store, _exchange(actor="chat"), client, {}),
            exchange_approval(store, _exchange(action="install"), client, {}),
            exchange_approval(store, _exchange(body=_life(target=SECRET)), client, {}),
            exchange_approval(store, _exchange(body=_machine(mounts=["/etc"]), action="grant"), client, {}),
        ]
        self.assertEqual(box.calls, [])
        self.assertEqual(store.approvals, {})
        self.assertEqual(refused[0].reason, "actor_cannot_approve")
        self.assertEqual(refused[1].reason, "catalog_install_closed")
        self.assertEqual(refused[2].reason, "credential")
        self.assertEqual(refused[3].reason, "credential")
        self.assertEqual(refused[4].reason, "missing_owner")
        self.assertEqual(refused[5].reason, "mount_forbidden")
        self.assertEqual(refused[6].reason, "mount_forbidden")
        self.assertEqual(refused[7].reason, "mount_forbidden")
        self.assertEqual(refused[8].reason, "mount_forbidden")
        self.assertEqual(refused[9].reason, "actor_cannot_exchange")
        self.assertEqual(refused[10].reason, "catalog_install_closed")
        self.assertEqual(refused[11].reason, "credential")
        self.assertEqual(refused[12].reason, "mount_forbidden")
        kept = record_approval(store, _record(body=_life(target=KEPT)), client)
        self.assertEqual(kept.approval_id, APPROVAL)
        self.assertNotIn(SECRET, box.calls[0][1][3])
        self.assertIn(KEPT, box.calls[0][1][3])
        retried = exchange_approval(store, _exchange(), client, {})
        self.assertEqual(retried.operation_id, OPERATION)
        self.assertEqual(len(box.calls), 2)

    def test_a_driver_error_is_postgres_and_hides_the_body(self) -> None:
        store = MemoryStore()
        client = PostgresApprovals(lambda: Box(fail=RuntimeError(SECRET)))
        decision = record_approval(store, _record(), client)
        self.assertEqual(decision.reason, "postgres")
        self.assertIsNone(decision.approval_id)
        self.assertEqual(store.approvals, {})
        self.assertNotIn("hunter22", repr(decision))
        mismatch = exchange_approval(
            store,
            _exchange(),
            PostgresApprovals(lambda: Box(fail=RuntimeError("owner_mismatch"))),
            {},
        )
        self.assertEqual(mismatch.reason, "owner_mismatch")

    def test_a_checksum_is_stored_and_a_hex_target_is_not(self) -> None:
        digest = "ab" * 32
        pin = "cd" * 20
        box = Box(rows=[(APPROVAL,), (OTHER,), (OPERATION,)])
        client = PostgresApprovals(lambda: box)
        store = MemoryStore()
        blocked = record_approval(store, _record(body=_life(target=pin)), client)
        self.assertEqual(blocked.reason, "credential")
        self.assertEqual(box.calls, [])
        kept = record_approval(store, _record(body=_life(payload_digest=digest)), client)
        self.assertEqual(kept.reason, "recorded")
        self.assertIn(digest, box.calls[0][1][3])
        machine = record_approval(
            store,
            _record(action="grant", body=_machine(catalog_pin=pin, image_digest=digest)),
            client,
        )
        self.assertEqual(machine.reason, "recorded")
        exchanged = exchange_approval(
            store,
            _exchange(body=_life(payload_digest=digest)),
            client,
            {},
        )
        self.assertEqual(exchanged.operation_id, OPERATION)

    def test_ensure_applies_the_script_and_hides_a_driver_error(self) -> None:
        box = Box()
        self.assertTrue(PostgresApprovals(lambda: box).ensure())
        self.assertTrue(any("approval_store" in part for part in box.ran))
        self.assertTrue(any("approval_exchange_owner" in part for part in box.ran))
        failed = PostgresApprovals(lambda: Box(fail=RuntimeError(SECRET)))
        self.assertFalse(failed.ensure())

    def test_open_approvals_stays_unset_until_postgres_is_configured(self) -> None:
        self.assertIsNone(open_approvals({}))
        with self.assertRaises(SystemExit) as missing:
            open_approvals({"POSTGRES_HOST": "postgres", "POSTGRES_USER": "postgres"})
        self.assertEqual(str(missing.exception), "executor: postgres")
        self.assertNotIn("password", str(missing.exception))
        with self.assertRaises(SystemExit) as leaked:
            open_approvals({"POSTGRES_HOST": "postgres", "POSTGRES_PASSWORD": SECRET})
        self.assertEqual(str(leaked.exception), "executor: postgres")
        self.assertNotIn("hunter22", str(leaked.exception))

    def test_without_a_connection_the_process_file_remains(self) -> None:
        store = MemoryStore()
        decision = record_approval(store, _record(), None)
        self.assertEqual(decision.reason, "recorded")
        self.assertEqual(len(store.approvals), 1)
        self.assertNotIn(SECRET, str(store.approvals))

    def test_http_exchanges_once_and_sends_nothing(self) -> None:
        box = Box(rows=[(APPROVAL,), (OPERATION,), (OPERATION,), (None,), ("expired",)])
        handle = executor_app(
            MemoryStore(),
            ENV,
            approvals=PostgresApprovals(lambda: box),
        )
        headers = {"Friday-Approval": "approval-secret"}
        status, body = handle("POST", "/approvals", headers, _record(body=_life(confirmed=True)))
        self.assertEqual(status, 200)
        self.assertEqual(body["approval_id"], APPROVAL)
        self.assertFalse(body["started"])
        self.assertFalse(body["sent"])
        self.assertNotIn("confirmed", box.calls[0][1][3])
        again, exchanged = handle("POST", "/exchange", headers, _exchange())
        self.assertEqual(again, 200)
        self.assertEqual(exchanged["operation_id"], OPERATION)
        self.assertFalse(exchanged["sent"])
        second, kept = handle("POST", "/exchange", headers, _exchange())
        self.assertEqual(second, 200)
        self.assertEqual(kept["reason"], "already_exchanged")
        self.assertEqual(kept["operation_id"], OPERATION)
        chat, denied = handle(
            "POST",
            "/approvals",
            {"Friday-Notify": "notify-secret"},
            _record(),
        )
        self.assertEqual((chat, denied["reason"]), (401, "unauthenticated"))
        actor, waiting = handle("POST", "/exchange", headers, _exchange(actor="chat"))
        self.assertEqual((actor, waiting["reason"]), (202, "actor_cannot_exchange"))
        self.assertFalse(waiting["sent"])
        closed, install = handle("POST", "/approvals", headers, _record(action="install"))
        self.assertEqual((closed, install["reason"]), (403, "catalog_install_closed"))
        self.assertEqual(len(box.calls), 3)
        late, expired = handle(
            "POST",
            "/exchange",
            headers,
            _exchange(approval_id=OTHER),
        )
        self.assertEqual((late, expired["reason"]), (403, "expired"))
        self.assertFalse(expired["sent"])
        self.assertNotIn(SECRET, str(expired))

    def test_http_hides_a_driver_error(self) -> None:
        handle = executor_app(
            MemoryStore(),
            ENV,
            approvals=PostgresApprovals(lambda: Box(fail=RuntimeError(SECRET))),
        )
        status, body = handle(
            "POST",
            "/approvals",
            {"Friday-Approval": "approval-secret"},
            _record(),
        )
        self.assertEqual(status, 503)
        self.assertEqual(body["reason"], "postgres")
        self.assertIsNone(body["approval_id"])
        self.assertFalse(body["started"])
        self.assertFalse(body["sent"])
        self.assertNotIn("hunter22", str(body))

    def test_ask_does_not_import_the_approval_store(self) -> None:
        source = (ROOT / "friday" / "ask.py").read_text(encoding="utf-8")
        self.assertNotIn("approval_store", source)
        self.assertNotIn("approval_exchange_owner", source)
        self.assertNotIn("gate.sqlstore", source)
        self.assertNotIn("record_approval", source)
        answer = ask(
            text="send the note to sam@example.com",
            owner_id="owner-1",
            charters_dir=ROOT / "charters",
            soul_text="You are Friday.",
            recall=lambda **_kwargs: None,
            save=lambda **_kwargs: None,
            model=lambda _messages: "sent",
            embed_reason="",
        )
        self.assertEqual(answer.outcome, "waiting")
        self.assertEqual(answer.reason, "board_must_approve")
        self.assertEqual(answer.action, "send")


if __name__ == "__main__":
    unittest.main()
