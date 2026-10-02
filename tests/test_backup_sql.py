"""One backup manifest through backup_store. The connection is a stub."""

from __future__ import annotations

import unittest
import uuid
from pathlib import Path

from backup.sqlstore import SCHEMA, PostgresManifests, record_manifest, statements
from executor.server import app as executor_app
from executor.server import open_manifests
from friday.ask import ask
from gate.rules import MemoryStore

ROOT = Path(__file__).resolve().parents[1]
PAUSE = "abcdef01-2345-4678-89ab-cdef01234567"
MANIFEST = "22222222-2222-4222-8222-222222222222"
SECRET = "password is hunter22"
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
        if self.fail is not None:
            raise self.fail
        if params is None:
            self.ran.append(sql)
        else:
            self.calls.append((sql, params))
        return self

    def fetchone(self):
        if not self.rows:
            return None
        return self.rows.pop(0)


def _fields(**over):
    body = {
        "actor": "board",
        "pause_id": PAUSE,
        "sqlite_method": "backup_api",
        "registry": [{"id": "notes", "mark": "managed"}],
    }
    body.update(over)
    return body


class PostgresManifestTests(unittest.TestCase):
    def test_schema_keeps_the_function_in_one_statement(self) -> None:
        parts = statements(SCHEMA.read_text(encoding="utf-8"))
        self.assertTrue(any(part.startswith("CREATE TABLE") for part in parts))
        function = next(part for part in parts if "FUNCTION backup_store" in part)
        self.assertIn("RETURN existing", function)
        self.assertEqual(function.count("$$"), 2)
        self.assertEqual(len(parts), 2)

    def test_two_stores_call_backup_store_and_keep_one_id(self) -> None:
        box = Box(rows=[(MANIFEST,), (uuid.UUID(MANIFEST),)])
        manifests = PostgresManifests(lambda: box)
        book: dict = {}
        first = record_manifest(book, _fields(), manifests)
        second = record_manifest(book, _fields(sqlite_method="clean_shutdown"), manifests)
        self.assertEqual(first.reason, "stored")
        self.assertEqual(first.manifest_id, MANIFEST)
        self.assertTrue(first.connected)
        self.assertFalse(first.copied)
        self.assertFalse(first.started)
        self.assertEqual(second.reason, "already_stored")
        self.assertEqual(second.manifest_id, MANIFEST)
        self.assertEqual(len(box.calls), 2)
        sql, params = box.calls[0]
        self.assertIn("backup_store", sql)
        self.assertIn("::text", sql)
        self.assertEqual(params[0], PAUSE)
        self.assertEqual(params[1], "backup_api")
        self.assertEqual(params[3], [])
        self.assertNotIn(SECRET, repr(first))
        self.assertEqual(book[PAUSE], MANIFEST)

    def test_memory_keeps_the_id_without_a_connection(self) -> None:
        book: dict = {}
        first = record_manifest(book, _fields(), None)
        second = record_manifest(book, _fields(), None)
        self.assertEqual(first.reason, "stored")
        self.assertEqual(second.reason, "already_stored")
        self.assertEqual(second.manifest_id, first.manifest_id)
        self.assertFalse(second.connected)
        self.assertRegex(first.manifest_id, r"[0-9a-f-]{36}")

    def test_refusals_do_not_open_the_connection(self) -> None:
        opened = {"n": 0}

        def connect():
            opened["n"] += 1
            raise AssertionError("connected")

        manifests = PostgresManifests(connect)
        cases = [
            _fields(actor="chat"),
            _fields(actor="friday"),
            _fields(action="install"),
            _fields(operation="install"),
            _fields(sqlite_method="live_file"),
            _fields(sqlite_method="path"),
            _fields(sqlite_method="copy"),
            _fields(passphrase=SECRET),
            _fields(token="token=abcd"),
            _fields(value=SECRET),
            _fields(pause_id=SECRET),
            _fields(pause_id="password%20is%20hunter22"),
            _fields(registry=[{"id": "movies", "mark": "managed"}]),
            _fields(registry=[{"id": "jellyfin_config", "mark": "adopted"}]),
            _fields(included_extra=["library"]),
            _fields(include_names=["optional_apps"]),
            _fields(registry=[{"id": "notes", "mark": "managed", "token": SECRET}]),
        ]
        reasons = {record_manifest({}, case, manifests).reason for case in cases}
        self.assertIn("actor_cannot_backup", reasons)
        self.assertIn("catalog_install_closed", reasons)
        self.assertIn("live_sqlite", reasons)
        self.assertIn("passphrase_in_manifest", reasons)
        self.assertIn("credential", reasons)
        self.assertIn("optional_app_excluded", reasons)
        self.assertIn("registry_mark", reasons)
        self.assertEqual(opened["n"], 0)
        kept = record_manifest({}, _fields(passphrase="The password is kept outside the machine"), None)
        self.assertEqual(kept.reason, "stored")
        self.assertNotIn(SECRET, repr(kept))

    def test_a_driver_error_is_postgres_and_hides_the_registry(self) -> None:
        box = Box(fail=RuntimeError(SECRET))
        decision = record_manifest({}, _fields(), PostgresManifests(lambda: box))
        self.assertEqual(decision.reason, "postgres")
        self.assertEqual(decision.outcome, "refused")
        self.assertEqual(decision.manifest_id, "")
        self.assertNotIn("hunter22", repr(decision))
        self.assertNotIn("notes", repr(decision))
        broken = PostgresManifests(lambda: Box(rows=[("id-1",)]))
        missing = record_manifest({}, _fields(), broken)
        self.assertEqual(missing.reason, "postgres")
        self.assertNotIn("id-1", repr(missing))
        self.assertEqual(missing.manifest_id, "")

    def test_ensure_applies_the_script_and_hides_a_driver_error(self) -> None:
        box = Box()
        self.assertTrue(PostgresManifests(lambda: box).ensure())
        self.assertTrue(any("CREATE TABLE" in part for part in box.ran))
        self.assertTrue(any("backup_store" in part for part in box.ran))
        failed = PostgresManifests(lambda: Box(fail=RuntimeError(SECRET)))
        self.assertFalse(failed.ensure())

    def test_open_manifests_stays_unset_until_postgres_is_configured(self) -> None:
        self.assertIsNone(open_manifests({}))
        with self.assertRaises(SystemExit) as missing:
            open_manifests({"POSTGRES_HOST": "postgres", "POSTGRES_USER": "postgres"})
        self.assertEqual(str(missing.exception), "executor: postgres")
        self.assertNotIn("password", str(missing.exception))
        with self.assertRaises(SystemExit) as leaked:
            open_manifests({"POSTGRES_HOST": "postgres", "POSTGRES_PASSWORD": SECRET})
        self.assertEqual(str(leaked.exception), "executor: postgres")
        self.assertNotIn("hunter22", str(leaked.exception))

    def test_http_requires_the_approval_token_and_copies_nothing(self) -> None:
        handle = executor_app(MemoryStore(), ENV)
        headers = {"Friday-Approval": "approval-secret"}
        status, body = handle("POST", "/backup", headers, _fields())
        self.assertEqual(status, 200)
        self.assertEqual(body["reason"], "stored")
        self.assertFalse(body["copied"])
        self.assertFalse(body["started"])
        self.assertEqual(len(body["manifest_id"]), 36)
        again_status, again = handle("POST", "/backup", headers, _fields())
        self.assertEqual(again_status, 200)
        self.assertEqual(again["reason"], "already_stored")
        self.assertEqual(again["manifest_id"], body["manifest_id"])
        chat, denied = handle(
            "POST",
            "/backup",
            {"Friday-Notify": "notify-secret"},
            _fields(),
        )
        self.assertEqual((chat, denied["reason"]), (401, "unauthenticated"))
        self.assertNotIn("manifest_id", denied)
        actor, refused = handle("POST", "/backup", headers, _fields(actor="chat"))
        self.assertEqual((actor, refused["reason"]), (403, "actor_cannot_backup"))
        live, sqlite = handle("POST", "/backup", headers, _fields(sqlite_method="live_file"))
        self.assertEqual((live, sqlite["reason"]), (403, "live_sqlite"))
        leaked_status, leaked = handle("POST", "/backup", headers, _fields(passphrase=SECRET))
        self.assertEqual((leaked_status, leaked["reason"]), (403, "passphrase_in_manifest"))
        self.assertNotIn("hunter22", str(leaked))
        closed, install = handle("POST", "/backup", headers, _fields(action="install"))
        self.assertEqual((closed, install["reason"]), (403, "catalog_install_closed"))
        method, wrong = handle("GET", "/backup", headers, {})
        self.assertEqual((method, wrong["reason"]), (405, "method_refused"))
        self.assertFalse(wrong["copied"])
        box = Box(rows=[(MANIFEST,)])
        postgres = executor_app(MemoryStore(), ENV, manifests=PostgresManifests(lambda: box))
        stored, row = postgres("POST", "/backup", headers, _fields())
        self.assertEqual(stored, 200)
        self.assertEqual(row["manifest_id"], MANIFEST)
        self.assertEqual(box.calls[0][1][0], PAUSE)
        down = executor_app(
            MemoryStore(),
            ENV,
            manifests=PostgresManifests(lambda: Box(fail=RuntimeError(SECRET))),
        )
        failed, hidden = down("POST", "/backup", headers, _fields())
        self.assertEqual(failed, 503)
        self.assertEqual(hidden["reason"], "postgres")
        self.assertNotIn("hunter22", str(hidden))
        self.assertFalse(hidden["started"])

    def test_ask_waits_and_does_not_import_the_manifest(self) -> None:
        source = (ROOT / "friday" / "ask.py").read_text(encoding="utf-8")
        self.assertNotIn("sqlstore", source)
        self.assertNotIn("backup_store", source)
        self.assertNotIn("record_manifest", source)
        tasks: list[dict] = []
        called = {"model": 0}

        def model(_messages):
            called["model"] += 1
            return "done"

        answer = ask(
            text="backup the notes",
            owner_id="owner-1",
            charters_dir=ROOT / "charters",
            soul_text="You are Friday.",
            recall=lambda **_kwargs: None,
            save=lambda **_kwargs: None,
            model=model,
            embed_reason="",
            record_task=lambda **kwargs: tasks.append(kwargs),
        )
        self.assertEqual(answer.outcome, "waiting")
        self.assertEqual(answer.reason, "board_must_approve")
        self.assertEqual(answer.action, "backup")
        self.assertEqual(called["model"], 0)
        self.assertEqual(tasks, [{
            "owner_id": "owner-1",
            "role_id": "friday",
            "goal": "backup the notes",
            "action": "backup",
        }])


if __name__ == "__main__":
    unittest.main()
