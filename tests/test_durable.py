"""The state book survives in the SQLite file named by the caller."""

from __future__ import annotations

import inspect
import tempfile
import threading
import unittest
from pathlib import Path

import friday.ask as ask_mod
import friday.state as state
from friday.durable import open_book, persist, state_from_env
from friday.server import app as friday_app
from friday.state import (
    close_obligation,
    delete_turn,
    deliveries,
    jobs,
    mirror_job,
    obligations,
    record_delivery,
    record_obligation,
    record_reminder,
    record_turn,
    reminders,
    turns,
)
from memoryd.store import Notes
from runtime.http import serve

ROOT = Path(__file__).resolve().parents[1]
NOTIFY = "notify-token"
MEMORY = "memory-token"
KEPT = "The password is kept outside the machine"
TOKEN = "token=abcd"
HUNTER = "password is hunter22"


def _post(port: int, path: str, payload: dict) -> tuple[int, dict]:
    import json
    import urllib.error
    import urllib.request

    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Friday-Notify": NOTIFY},
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


class DurableTests(unittest.TestCase):
    def test_a_reopen_sees_the_book_and_a_secret_is_not_in_the_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "friday.sqlite"
            book = open_book(path)
            self.assertEqual(
                persist(
                    book,
                    record_turn,
                    actor="friday",
                    owner_id="owner",
                    speaker="owner",
                    role="friday",
                    text="hello",
                ).reason,
                "turn",
            )
            self.assertEqual(
                persist(
                    book,
                    record_obligation,
                    actor="board",
                    owner_id="owner",
                    name="taxes",
                    text=KEPT,
                ).reason,
                "obligation",
            )
            self.assertEqual(
                persist(
                    book,
                    record_reminder,
                    actor="board",
                    owner_id="owner",
                    text="ping",
                    when="Tuesday",
                ).reason,
                "not_sent",
            )
            self.assertEqual(
                persist(
                    book,
                    record_delivery,
                    actor="friday",
                    owner_id="owner",
                    item_id="m1",
                    key=KEPT,
                ).reason,
                "not_sent",
            )
            self.assertEqual(
                persist(
                    book,
                    mirror_job,
                    actor="friday",
                    owner_id="owner",
                    role="cto",
                    task_id="build",
                    code_on=True,
                ).reason,
                "not_started",
            )
            self.assertEqual(
                persist(
                    book,
                    close_obligation,
                    actor="board",
                    owner_id="owner",
                    name="taxes",
                ).reason,
                "done",
            )
            refused = persist(
                book,
                record_turn,
                actor="friday",
                owner_id="owner",
                speaker="owner",
                role="friday",
                text=HUNTER,
            )
            self.assertEqual(refused.reason, "credential")
            self.assertEqual(
                persist(
                    book,
                    delete_turn,
                    actor="chat",
                    owner_id="owner",
                    confirmed=True,
                ).reason,
                "stays",
            )
            raw = path.read_bytes()
            self.assertNotIn(HUNTER.encode(), raw)
            self.assertNotIn(TOKEN.encode(), raw)
            self.assertNotIn(b"supplied-token", raw)

            again = open_book(path)
            self.assertEqual(turns(again, "owner"), (
                {"owner_id": "owner", "speaker": "owner", "role": "friday", "text": "hello"},
            ))
            self.assertEqual(obligations(again, "owner"), (
                {"owner_id": "owner", "name": "taxes", "text": KEPT, "state": "done"},
            ))
            self.assertEqual(reminders(again, "owner"), (
                {"owner_id": "owner", "text": "ping", "when": "Tuesday", "fired": False},
            ))
            self.assertEqual(deliveries(again, "owner")[0]["status"], "pending")
            self.assertEqual(jobs(again, "owner")[0]["state"], "not_started")
            self.assertEqual(jobs(again, "owner")[0]["workspace"], "tr-build")
            self.assertNotIn(HUNTER, repr(again))

    def test_a_tampered_secret_row_is_not_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "friday.sqlite"
            book = open_book(path)
            persist(
                book,
                record_turn,
                actor="friday",
                owner_id="owner",
                speaker="owner",
                role="friday",
                text="hello",
            )
            book._state_conn.execute(
                "INSERT INTO turns (owner_id, speaker, role, body) VALUES (?, ?, ?, ?)",
                ("owner", "owner", "friday", HUNTER),
            )
            loaded = open_book(path)
            self.assertEqual(len(turns(loaded, "owner")), 1)
            self.assertNotIn(HUNTER, turns(loaded, "owner")[0]["text"])
            self.assertNotIn(HUNTER, repr(loaded))

    def test_a_relative_path_a_symlink_and_an_unset_env_do_not_open(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(OSError) as relative:
                open_book("friday.sqlite")
            self.assertEqual(str(relative.exception), "state_path")
            link = root / "link.sqlite"
            link.symlink_to(root / "missing.sqlite")
            with self.assertRaises(OSError) as linked:
                open_book(link)
            self.assertEqual(str(linked.exception), "state_path")
            with self.assertRaises(OSError) as folder:
                open_book(root)
            self.assertEqual(str(folder.exception), "state_path")
            self.assertIsNone(state_from_env({}))
            opened = state_from_env({"FRIDAY_STATE": str(root / "from-env.sqlite")})
            self.assertIsNotNone(opened)
            self.assertEqual(turns(opened, "owner"), ())

    def test_the_ask_module_does_not_open_the_book(self) -> None:
        source = inspect.getsource(state)
        self.assertNotIn("sqlite3", source)
        ask_source = inspect.getsource(ask_mod)
        self.assertNotIn("friday.state", ask_source)
        self.assertNotIn("friday.durable", ask_source)
        self.assertNotIn("record_turn", ask_source)

    def test_a_spoken_turn_is_still_there_after_the_process_reopens_the_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "friday.sqlite"
            book = open_book(path)
            notes = Notes()
            handler = friday_app(
                {
                    "FRIDAY_NOTIFY_TOKEN": NOTIFY,
                    "MEMORY_TOKEN": MEMORY,
                    "CHARTERS_DIR": str(ROOT / "charters"),
                    "SOUL_PATH": str(ROOT / "soul" / "SOUL.example.md"),
                },
                notes=notes,
                embed=lambda: "",
                model=lambda _messages: "What should we set up?",
                state=book,
            )
            server = serve(handler, "127.0.0.1", 0)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                status, body = _post(
                    server.server_address[1],
                    "/ask",
                    {"text": "hello", "owner_id": "owner-1"},
                )
                self.assertEqual(status, 200, body)
                self.assertEqual(body["reply"], "What should we set up?")
                waiting, held = _post(
                    server.server_address[1],
                    "/ask",
                    {"text": "pay the invoice", "owner_id": "owner-1"},
                )
                self.assertEqual(waiting, 200, held)
                self.assertEqual(held["outcome"], "waiting")
                secret, blocked = _post(
                    server.server_address[1],
                    "/ask",
                    {"text": HUNTER, "owner_id": "owner-1"},
                )
                self.assertEqual(secret, 200, blocked)
            finally:
                server.shutdown()
                server.server_close()
            reopened = open_book(path)
            spoken = turns(reopened, "owner-1")
            self.assertEqual(
                [row["text"] for row in spoken],
                [
                    "hello",
                    "What should we set up?",
                    "pay the invoice",
                    held["reply"],
                    "What should we set up?",
                ],
            )
            self.assertNotIn(HUNTER, [row["text"] for row in spoken])
            self.assertNotIn(HUNTER, path.read_text(errors="ignore"))
            self.assertNotIn(HUNTER, repr(reopened))
