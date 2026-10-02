"""Friday's state book stays in the process. It does not open SQLite."""

from __future__ import annotations

import inspect
import os
import unittest

import friday.ask as ask_mod
import friday.state as state
from friday.state import (
    Book,
    close_obligation,
    delete_turn,
    deliveries,
    fire_reminder,
    jobs,
    mirror_job,
    obligations,
    record_delivery,
    record_obligation,
    record_reminder,
    record_turn,
    reminders,
    send_delivery,
    turns,
)

KEPT = "The password is kept outside the machine"
TOKEN = "token=abcd"
HUNTER = "password is hunter22"


class StateTests(unittest.TestCase):
    def test_a_turn_is_kept_for_that_owner_and_chat_cannot_delete_it(self) -> None:
        book = Book()
        refused = record_turn(
            book,
            actor="chat",
            owner_id="owner",
            speaker="owner",
            role="friday",
            text="hello",
            confirmed=True,
        )
        self.assertEqual(refused.reason, "actor_cannot_record")
        self.assertEqual(turns(book, "owner"), ())

        first = record_turn(
            book,
            actor="friday",
            owner_id="owner",
            speaker="owner",
            role="friday",
            text="hello",
            confirmed=True,
        )
        second = record_turn(
            book,
            actor="friday",
            owner_id="owner",
            speaker="friday",
            role="chief",
            text=KEPT,
        )
        self.assertEqual(first.reason, "turn")
        self.assertEqual(second.count, 2)
        self.assertEqual(
            turns(book, "owner"),
            (
                {"owner_id": "owner", "speaker": "owner", "role": "friday", "text": "hello"},
                {"owner_id": "owner", "speaker": "friday", "role": "chief", "text": KEPT},
            ),
        )
        self.assertNotIn("category", turns(book, "owner")[0])
        self.assertEqual(turns(book, "other"), ())
        self.assertEqual(turns(book, TOKEN), ())
        self.assertEqual(delete_turn(book, actor="chat", owner_id="owner", confirmed=True).reason, "stays")
        self.assertEqual(delete_turn(book, actor="friday", owner_id="owner").reason, "stays")
        self.assertEqual(len(turns(book, "owner")), 2)

        secret = record_turn(
            book, actor="friday", owner_id=TOKEN, speaker="owner", role="friday", text="hello"
        )
        self.assertEqual(secret.reason, "credential")
        self.assertNotIn(TOKEN, repr(secret))
        self.assertNotIn(TOKEN, repr(book))
        shaped = record_turn(
            book, actor="friday", owner_id="owner", speaker="owner", role="friday", text=HUNTER
        )
        self.assertEqual(shaped.reason, "credential")
        self.assertNotIn(HUNTER, repr(shaped))
        self.assertNotIn(HUNTER, repr(book))
        self.assertEqual(len(turns(book, "owner")), 2)
        self.assertEqual(record_turn(
            book, actor="friday", owner_id="owner", speaker="owner", role="Friday", text="hello"
        ).reason, "role")
        padded = record_turn(
            book, actor="friday", owner_id="owner\n", speaker="owner", role="friday", text="hi"
        )
        self.assertEqual(padded.reason, "owner")
        self.assertEqual(turns(book, "owner\n"), ())
        self.assertEqual(len(turns(book, "owner")), 2)
        self.assertEqual(repr(book), "Book()")

    def test_one_obligation_thread_and_chat_cannot_close_it(self) -> None:
        book = Book()
        opened = record_obligation(
            book, actor="board", owner_id="owner", name="taxes", text=KEPT, confirmed=True
        )
        self.assertEqual(opened.reason, "obligation")
        self.assertEqual(opened.state, "open")
        again = record_obligation(
            book, actor="board", owner_id="owner", name="taxes", text="a different line"
        )
        self.assertEqual(again.reason, "already")
        self.assertEqual(obligations(book, "owner"), (
            {"owner_id": "owner", "name": "taxes", "text": KEPT, "state": "open"},
        ))
        other = record_obligation(
            book, actor="board", owner_id="other", name="taxes", text="theirs"
        )
        self.assertEqual(other.reason, "obligation")
        self.assertEqual(len(obligations(book, "owner")), 1)
        self.assertEqual(obligations(book, "other")[0]["text"], "theirs")

        chat = close_obligation(
            book, actor="chat", owner_id="owner", name="taxes", confirmed=True
        )
        self.assertEqual(chat.reason, "board_only")
        self.assertEqual(chat.state, "open")
        self.assertEqual(obligations(book, "owner")[0]["state"], "open")
        closed = close_obligation(book, actor="board", owner_id="owner", name="taxes")
        self.assertEqual(closed.reason, "done")
        self.assertEqual(len(obligations(book, "owner")), 1)
        self.assertEqual(
            close_obligation(book, actor="board", owner_id="owner", name="taxes").reason,
            "already_done",
        )
        self.assertEqual(
            record_obligation(
                book, actor="board", owner_id="owner", name="taxes", text=HUNTER
            ).reason,
            "already",
        )
        self.assertNotIn(HUNTER, repr(book))
        missing = record_obligation(
            book, actor="board", owner_id="owner", name="bills", text=TOKEN
        )
        self.assertEqual(missing.reason, "credential")
        self.assertEqual(missing.name, "bills")
        self.assertNotIn(TOKEN, repr(missing))
        self.assertEqual(obligations(book, "owner"), (
            {"owner_id": "owner", "name": "taxes", "text": KEPT, "state": "done"},
        ))
        self.assertEqual(
            record_obligation(
                book, actor="chat", owner_id="owner", name="bills", text="no"
            ).reason,
            "board_only",
        )
        self.assertEqual(len(obligations(book, "owner")), 1)

    def test_a_reminder_is_recorded_and_not_sent(self) -> None:
        book = Book()
        recorded = record_reminder(
            book,
            actor="board",
            owner_id="owner",
            text=KEPT,
            when="Tuesday",
            confirmed=True,
        )
        self.assertEqual(recorded.reason, "not_sent")
        self.assertFalse(recorded.sent)
        self.assertEqual(reminders(book, "owner"), (
            {"owner_id": "owner", "text": KEPT, "when": "Tuesday", "fired": False},
        ))
        self.assertEqual(reminders(book, "other"), ())
        fired = fire_reminder(book, actor="board", owner_id="owner", confirmed=True)
        self.assertEqual(fired.reason, "not_sent")
        self.assertFalse(fired.sent)
        self.assertFalse(reminders(book, "owner")[0]["fired"])
        self.assertEqual(
            record_reminder(
                book, actor="chat", owner_id="owner", text="ping", when="later"
            ).reason,
            "board_only",
        )
        self.assertEqual(len(reminders(book, "owner")), 1)
        secret = record_reminder(
            book, actor="board", owner_id="owner", text=HUNTER, when="Tuesday"
        )
        self.assertEqual(secret.reason, "credential")
        self.assertNotIn(HUNTER, repr(secret))
        self.assertNotIn(HUNTER, repr(book))
        self.assertFalse(
            record_reminder(
                book, actor="board", owner_id="owner", text="ping", when=True
            ).sent
        )

    def test_a_delivery_keeps_its_key_and_is_not_sent(self) -> None:
        book = Book()
        recorded = record_delivery(
            book,
            actor="friday",
            owner_id="owner",
            item_id="m1",
            key=KEPT,
            confirmed=True,
        )
        self.assertEqual(recorded.reason, "not_sent")
        self.assertEqual(recorded.state, "pending")
        self.assertFalse(recorded.sent)
        self.assertNotIn(KEPT, repr(recorded))
        again = record_delivery(
            book, actor="friday", owner_id="owner", item_id="m1", key="other-key"
        )
        self.assertEqual(again.reason, "already")
        self.assertEqual(deliveries(book, "owner")[0]["key"], KEPT)
        self.assertEqual(deliveries(book, "other"), ())
        held = record_delivery(
            book,
            actor="friday",
            owner_id="owner",
            item_id="m2",
            key="later",
            status="uncertain",
        )
        self.assertEqual(held.state, "uncertain")
        self.assertEqual(
            record_delivery(
                book, actor="friday", owner_id="owner", item_id="m3", key="x", status="delivered"
            ).reason,
            "unknown_status",
        )
        self.assertEqual(
            [row["item_id"] for row in deliveries(book, "owner")],
            ["m1", "m2"],
        )
        sent = send_delivery(
            book, actor="chat", owner_id="owner", item_id="m1", confirmed=True
        )
        self.assertEqual(sent.reason, "not_sent")
        self.assertEqual(sent.state, "pending")
        self.assertFalse(sent.sent)
        self.assertEqual(deliveries(book, "owner")[0]["status"], "pending")
        self.assertEqual(
            send_delivery(book, actor="friday", owner_id="owner", item_id="m2").state,
            "uncertain",
        )
        self.assertEqual(
            record_delivery(
                book, actor="chat", owner_id="owner", item_id="m9", key="x"
            ).reason,
            "actor_cannot_record",
        )
        secret = record_delivery(
            book, actor="friday", owner_id="owner", item_id="m4", key=TOKEN
        )
        self.assertEqual(secret.reason, "credential")
        self.assertNotIn(TOKEN, repr(secret))
        self.assertNotIn(TOKEN, repr(book))
        self.assertEqual(len(deliveries(book, "owner")), 2)

    def test_a_coder_job_is_mirrored_and_not_started(self) -> None:
        book = Book()
        off = mirror_job(
            book,
            actor="friday",
            owner_id="owner",
            role="cto",
            task_id="build",
            code_on=False,
            token="supplied-token",
            confirmed=True,
        )
        self.assertEqual(off.reason, "code_profile_off")
        self.assertEqual(off.name, "tr-build")
        self.assertFalse(off.started)
        self.assertFalse(off.created)
        self.assertEqual(jobs(book, "owner"), ())
        self.assertEqual(
            mirror_job(
                book,
                actor="friday",
                owner_id="owner",
                role="cto",
                task_id="build",
                code_on="true",
            ).reason,
            "code_profile_off",
        )

        mirrored = mirror_job(
            book,
            actor="friday",
            owner_id="owner",
            role="cto",
            task_id="build",
            code_on=True,
            token=KEPT,
            confirmed=True,
        )
        self.assertEqual(mirrored.reason, "not_started")
        self.assertEqual(mirrored.name, "tr-build")
        self.assertFalse(mirrored.started)
        self.assertFalse(mirrored.created)
        self.assertNotIn(KEPT, repr(mirrored))
        self.assertEqual(jobs(book, "owner"), (
            {
                "owner_id": "owner",
                "role": "cto",
                "task_id": "build",
                "workspace": "tr-build",
                "state": "not_started",
            },
        ))
        self.assertNotIn("token", jobs(book, "owner")[0])
        again = mirror_job(
            book,
            actor="friday",
            owner_id="owner",
            role="chief",
            task_id="build",
            code_on=True,
            token=TOKEN,
        )
        self.assertEqual(again.reason, "already")
        self.assertEqual(again.name, "tr-build")
        self.assertNotIn(TOKEN, repr(again))
        self.assertEqual(jobs(book, "owner")[0]["role"], "cto")
        self.assertEqual(len(jobs(book, "owner")), 1)
        self.assertEqual(jobs(book, "other"), ())

        chat = mirror_job(
            book,
            actor="chat",
            owner_id="owner",
            role="cto",
            task_id="build",
            code_on=True,
            confirmed=True,
        )
        self.assertEqual(chat.reason, "actor_cannot_record")
        self.assertEqual(chat.name, "tr-build")
        self.assertFalse(chat.created)
        self.assertEqual(len(jobs(book, "owner")), 1)

        secret = mirror_job(
            book,
            actor="friday",
            owner_id="owner",
            role="cto",
            task_id="other",
            code_on=True,
            token=TOKEN,
        )
        self.assertEqual(secret.reason, "credential")
        self.assertEqual(secret.name, "")
        self.assertNotIn(TOKEN, repr(secret))
        self.assertNotIn(TOKEN, repr(book))
        self.assertEqual(len(jobs(book, "owner")), 1)
        self.assertEqual(
            mirror_job(
                book,
                actor="friday",
                owner_id="owner",
                role="friday",
                task_id="other",
                code_on=True,
            ).reason,
            "role",
        )

    def test_the_book_does_not_open_sqlite_or_the_ask_path(self) -> None:
        source = inspect.getsource(state)
        self.assertNotIn("sqlite3", source)
        self.assertNotIn("socket", source)
        self.assertNotIn("os.environ", source)
        ask_source = inspect.getsource(ask_mod)
        self.assertNotIn("friday.state", ask_source)
        self.assertNotIn("record_turn", ask_source)
        before = os.environ.get("CODER_TOKEN")
        os.environ["CODER_TOKEN"] = "supplied-token"
        try:
            book = Book()
            mirror_job(
                book,
                actor="friday",
                owner_id="owner",
                role="cto",
                task_id="build",
                code_on=True,
                token=os.environ["CODER_TOKEN"],
            )
            self.assertEqual(os.environ["CODER_TOKEN"], "supplied-token")
            self.assertNotIn("supplied-token", repr(book))
            self.assertNotIn("token", jobs(book, "owner")[0])
        finally:
            if before is None:
                os.environ.pop("CODER_TOKEN", None)
            else:
                os.environ["CODER_TOKEN"] = before


if __name__ == "__main__":
    unittest.main()
