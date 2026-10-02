"""A stay keeps one charter. An ask does not, and a stay is not a note."""

from __future__ import annotations

import json
import threading
import unittest
from pathlib import Path

from friday.ask import ask
from friday.hat import Hats
from friday.server import app as friday_app
from memoryd.store import Notes
from runtime.http import serve

ROOT = Path(__file__).resolve().parents[1]
CHARTERS = ROOT / "charters"
KEPT = "The password is kept outside the machine"
NOTIFY = "notify-token"
MEMORY = "memory-token"


def _ask(text, notes, hats, model, **kwargs):
    seen = kwargs.setdefault("seen", {})

    def recall(**fields):
        seen["recall"] = fields
        return notes.recall(**fields)

    def save(**fields):
        seen.setdefault("saves", []).append(fields)
        return notes.save(**fields)

    def remember_model(messages):
        seen["prompt"] = messages[0]["content"]
        seen["called"] = seen.get("called", 0) + 1
        return model

    return ask(
        text=text,
        owner_id=kwargs.get("owner_id", "owner-1"),
        owner_kind=kwargs.get("owner_kind", "person"),
        charters_dir=CHARTERS,
        soul_text="You are Friday.",
        recall=recall,
        save=save,
        model=remember_model,
        embed_reason="",
        confirmed=kwargs.get("confirmed", False),
        record_task=kwargs.get("record_task"),
        hats=hats,
    )


class HatTests(unittest.TestCase):
    def test_ask_is_one_turn_and_stay_keeps_the_charter(self) -> None:
        notes = Notes()
        notes.save(owner_id="owner-1", owner_kind="person", content="the person's note", category="note")
        notes.save(
            owner_id="chief",
            owner_kind="role",
            content="the role label is north",
            category="note",
            visibility="working",
        )
        notes.save(
            owner_id="cto",
            owner_kind="role",
            content="the cto label",
            category="note",
            visibility="working",
        )
        hats = Hats()
        seen: dict = {}
        answer = _ask("ask my chief what is running", notes, hats, "Running.", seen=seen)
        self.assertEqual(answer.role, "chief")
        self.assertEqual(answer.reply, "Chief: Running.")
        self.assertEqual(hats.staying, {})
        self.assertNotIn("the person's note", seen["prompt"])

        answer = _ask("what is next", notes, hats, "Next.", seen=seen)
        self.assertEqual(answer.role, "friday")
        self.assertEqual(answer.reply, "Next.")
        self.assertEqual(seen["recall"]["owner_id"], "owner-1")

        saved = len(seen.get("saves") or [])
        answer = _ask("talk to my chief", notes, hats, "no", seen=seen)
        self.assertEqual((answer.outcome, answer.reason, answer.reply), ("spoken", "staying", "Chief: Staying."))
        self.assertEqual(hats.staying, {("owner-1", "person"): "chief"})
        self.assertEqual(len(seen.get("saves") or []), saved)
        self.assertEqual(seen["called"], 2)

        answer = _ask("what is next", notes, hats, "Still chief.", seen=seen)
        self.assertEqual(answer.role, "chief")
        self.assertEqual(answer.reply, "Chief: Still chief.")
        self.assertEqual(seen["recall"], {"owner_id": "chief", "owner_kind": "role"})
        self.assertIn("the role label is north", seen["prompt"])
        self.assertNotIn("the person's note", seen["prompt"])

        answer = _ask("ask my cto what is running", notes, hats, "The stack.", seen=seen)
        self.assertEqual(answer.role, "cto")
        self.assertEqual(answer.reply, "CTO: The stack.")
        self.assertEqual(hats.staying[("owner-1", "person")], "chief")
        self.assertIn("the cto label", seen["prompt"])
        self.assertNotIn("the role label is north", seen["prompt"])

        answer = _ask("what is next", notes, hats, "Back on chief.", seen=seen)
        self.assertEqual(answer.role, "chief")
        self.assertEqual(hats.staying[("owner-1", "person")], "chief")

    def test_back_to_friday_clears_the_stay_and_another_owner_is_separate(self) -> None:
        notes = Notes()
        hats = Hats()
        seen: dict = {}
        _ask("stay with coach", notes, hats, "no", seen=seen)
        self.assertEqual(hats.staying[("owner-1", "person")], "coach")
        other = _ask("what is next", notes, hats, "Coach.", seen=seen, owner_id="owner-2")
        self.assertEqual(other.role, "friday")
        self.assertEqual(hats.staying.get(("owner-2", "person")), None)

        answer = _ask("back to friday", notes, hats, "Friday.", seen=seen, confirmed=True)
        self.assertEqual(answer.role, "friday")
        self.assertEqual(answer.reply, "Friday.")
        self.assertEqual(hats.staying, {})
        self.assertNotIn(("owner-1", "person"), hats.staying)

        answer = _ask("what is next", notes, hats, "Friday again.", seen=seen)
        self.assertEqual(answer.role, "friday")
        self.assertEqual(answer.reply, "Friday again.")

    def test_an_unknown_name_and_a_credential_owner_do_not_stick(self) -> None:
        notes = Notes()
        hats = Hats()
        seen: dict = {}
        _ask("stay with my chief", notes, hats, "no", seen=seen)
        answer = _ask("stay with my family", notes, hats, "Still.", seen=seen)
        self.assertEqual(answer.role, "chief")
        self.assertEqual(hats.staying, {("owner-1", "person"): "chief"})
        self.assertIn("family", seen["prompt"])

        hats.staying[("owner-1", "person")] = "missing"
        answer = _ask("what is next", notes, hats, "Friday.", seen=seen)
        self.assertEqual(answer.role, "friday")
        self.assertEqual(hats.staying, {})

        refused = _ask("stay with my chief", notes, hats, "no", seen=seen, owner_id="token=abcd")
        self.assertEqual(refused.reason, "credential")
        self.assertEqual(refused.reply, "")
        self.assertEqual(hats.staying, {})
        self.assertNotIn("token=abcd", refused.reply)

    def test_a_stay_remembers_a_note_and_does_not_fold_or_approve(self) -> None:
        notes = Notes()
        hats = Hats()
        seen: dict = {}
        tasks: list[dict] = []
        _ask("stay with my chief", notes, hats, "no", seen=seen)
        answer = _ask(
            "remember " + KEPT,
            notes,
            hats,
            "no",
            seen=seen,
            confirmed=True,
            record_task=lambda **fields: tasks.append(fields),
        )
        self.assertEqual(answer.reply, "Chief: I'll remember that.")
        role = notes.recall(owner_id="chief", owner_kind="role")
        self.assertEqual(role.notes[0]["content"], KEPT)
        self.assertEqual(role.notes[0]["category"], "note")
        self.assertEqual(seen["saves"][-1]["category"], "note")
        person = notes.recall(owner_id="owner-1", owner_kind="person")
        self.assertEqual(person.notes, ())

        refused = _ask("remember token=abcd", notes, hats, "no", seen=seen)
        self.assertEqual(refused.reason, "credential")
        self.assertEqual(len(notes.recall(owner_id="chief", owner_kind="role").notes), 1)

        waiting = _ask(
            "stop the spare service",
            notes,
            hats,
            "no",
            seen=seen,
            confirmed=True,
            record_task=lambda **fields: tasks.append(fields),
        )
        self.assertEqual(waiting.outcome, "waiting")
        self.assertEqual(waiting.reply, "Chief: That waits on the Board. I have not done it.")
        self.assertEqual(tasks, [{
            "owner_id": "chief",
            "role_id": "chief",
            "goal": "stop the spare service",
            "action": "stop",
        }])
        self.assertEqual(
            [row.category for row in notes.rows.values()],
            ["note"],
        )

    def test_stay_with_that_advisor_keeps_the_latest_one_turn_charter(self) -> None:
        notes = Notes()
        notes.save(owner_id="owner-1", owner_kind="person", content="the person's note", category="note")
        notes.save(
            owner_id="cfo",
            owner_kind="role",
            content="the cfo label",
            category="note",
            visibility="working",
        )
        notes.save(
            owner_id="chief",
            owner_kind="role",
            content="the role label is north",
            category="note",
            visibility="working",
        )
        hats = Hats()
        seen: dict = {}
        tasks: list[dict] = []
        answer = _ask("ask my finance what we spent", notes, hats, "Spent.", seen=seen)
        self.assertEqual(answer.role, "cfo")
        self.assertEqual(answer.reply, "CFO: Spent.")
        self.assertEqual(hats.staying, {})
        answer = _ask("what is next", notes, hats, "Friday.", seen=seen)
        self.assertEqual(answer.role, "friday")

        called = seen["called"]
        saved = len(seen.get("saves") or [])
        answer = _ask("stay with that advisor", notes, hats, "no", seen=seen)
        self.assertEqual(answer.reply, "CFO: Staying.")
        self.assertEqual(seen["called"], called)
        self.assertEqual(hats.staying, {("owner-1", "person"): "cfo"})
        self.assertEqual(len(seen.get("saves") or []), saved)
        answer = _ask("what is next", notes, hats, "Still.", seen=seen)
        self.assertEqual(answer.reply, "CFO: Still.")
        self.assertIn("the cfo label", seen["prompt"])
        self.assertNotIn("the person's note", seen["prompt"])
        waiting = _ask(
            "stop the spare service",
            notes,
            hats,
            "no",
            seen=seen,
            confirmed=True,
            record_task=lambda **fields: tasks.append(fields),
        )
        self.assertEqual(waiting.reply, "CFO: That waits on the Board. I have not done it.")
        self.assertEqual(tasks, [{
            "owner_id": "cfo",
            "role_id": "cfo",
            "goal": "stop the spare service",
            "action": "stop",
        }])

        _ask("talk to my chief", notes, hats, "no", seen=seen)
        self.assertEqual(hats.staying[("owner-1", "person")], "chief")
        answer = _ask("@cto what is up", notes, hats, "Up.", seen=seen)
        self.assertEqual(answer.role, "cto")
        self.assertEqual(answer.reply, "CTO: Up.")
        self.assertEqual(hats.staying[("owner-1", "person")], "chief")
        answer = _ask("stay with them", notes, hats, "no", seen=seen)
        self.assertEqual(answer.reply, "CTO: Staying.")
        self.assertEqual(hats.staying[("owner-1", "person")], "cto")

        _ask("back to friday", notes, hats, "Friday.", seen=seen)
        answer = _ask("stay with that", notes, hats, "Friday again.", seen=seen)
        self.assertEqual(answer.role, "friday")
        self.assertEqual(answer.reply, "Friday again.")
        self.assertEqual(hats.staying, {})

        _ask("ask my cfo what we spent", notes, hats, "Spent.", seen=seen)
        other = _ask("stay with that advisor", notes, hats, "Mine.", seen=seen, owner_id="owner-2")
        self.assertEqual(other.role, "friday")
        self.assertNotIn(("owner-2", "person"), hats.staying)
        self.assertEqual(hats.staying, {})
        refused = _ask("stay with that advisor", notes, hats, "no", seen=seen, owner_id="token=abcd")
        self.assertEqual(refused.reason, "credential")
        self.assertNotIn("abcd", refused.reply)
        self.assertNotIn("abcd", str(hats.staying))
        self.assertNotIn("abcd", str(hats.asked))

    def test_the_process_keeps_the_stay_and_a_new_process_does_not(self) -> None:
        notes = Notes()
        notes.save(
            owner_id="chief",
            owner_kind="role",
            content="the role label is north",
            category="note",
            visibility="working",
        )
        prompts: list[str] = []

        def model(messages):
            prompts.append(messages[0]["content"])
            return "Here."

        env = {
            "FRIDAY_NOTIFY_TOKEN": NOTIFY,
            "MEMORY_TOKEN": MEMORY,
            "CHARTERS_DIR": str(CHARTERS),
            "SOUL_PATH": str(ROOT / "soul" / "SOUL.example.md"),
        }
        first = serve(friday_app(env, notes=notes, embed=lambda: "", model=model), "127.0.0.1", 0)
        thread = threading.Thread(target=first.serve_forever, daemon=True)
        thread.start()
        try:
            port = first.server_address[1]
            stayed, body = _post(port, {"text": "stay with my chief", "owner_id": "owner-1"})
            self.assertEqual(stayed, 200, body)
            self.assertEqual(body["reply"], "Chief: Staying.")
            status, body = _post(port, {"text": "what is next", "owner_id": "owner-1", "confirmed": True})
            self.assertEqual(status, 200, body)
            self.assertEqual(body["role"], "chief")
            self.assertEqual(body["reply"], "Chief: Here.")
            self.assertIn("the role label is north", prompts[-1])
        finally:
            first.shutdown()
            first.server_close()

        prompts.clear()
        second = serve(friday_app(env, notes=notes, embed=lambda: "", model=model), "127.0.0.1", 0)
        thread = threading.Thread(target=second.serve_forever, daemon=True)
        thread.start()
        try:
            status, body = _post(second.server_address[1], {"text": "what is next", "owner_id": "owner-1"})
            self.assertEqual(body["role"], "friday")
            self.assertEqual(body["reply"], "Here.")
            self.assertNotIn("the role label is north", prompts[-1])
        finally:
            second.shutdown()
            second.server_close()


def _post(port: int, payload: dict) -> tuple[int, dict]:
    import urllib.error
    import urllib.request

    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/ask",
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
