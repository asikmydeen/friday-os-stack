"""A soul proposal is recorded. The example file is not written."""

from __future__ import annotations

import unittest
from pathlib import Path

from friday.ask import ask
from memoryd.index import COLLECTIONS
from memoryd.server import app
from memoryd.soul import Book, apply_proposal, record_proposal
from memoryd.store import Notes

KEPT = "The password is kept outside the machine"
TOKEN = "apply-token"
OTHER = "other-token"
ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "soul" / "SOUL.example.md"


def _record(book: Book, **kwargs):
    fields = {
        "actor": "board",
        "name": "SOUL.md",
        "text": "Ask before a change.",
    }
    fields.update(kwargs)
    return record_proposal(book, **fields)


class SoulProposalTests(unittest.TestCase):
    def test_the_board_records_one_proposal_and_chat_does_not(self) -> None:
        book = Book()
        example = EXAMPLE.read_text(encoding="utf-8")
        before = tuple(COLLECTIONS)
        refused = _record(book, actor="chat", confirmed=True)
        self.assertEqual(refused.reason, "board_only")
        self.assertEqual(_record(book, actor="friday").reason, "board_only")
        self.assertEqual(_record(book, actor="adapter").reason, "board_only")
        self.assertEqual(book.proposals, {})
        self.assertEqual(book.current, {})

        recorded = _record(book, confirmed=True)
        self.assertEqual((recorded.outcome, recorded.reason), ("recorded", "proposal"))
        self.assertEqual(recorded.name, "SOUL.md")
        self.assertEqual(recorded.path, f"soul/proposals/{recorded.proposal_id}.md")
        self.assertIs(recorded.applied, False)
        self.assertIs(recorded.files_written, False)
        self.assertIs(recorded.example_read, False)
        self.assertIs(recorded.token_stored, False)
        self.assertIs(recorded.scheduled, False)
        self.assertEqual(book.current, {})
        self.assertEqual(book.history, [])
        self.assertEqual(book.proposals[recorded.proposal_id].text, "Ask before a change.")

        again = _record(book, text="A second draft.")
        self.assertEqual(again.reason, "proposal_open")
        self.assertEqual(set(book.proposals), {recorded.proposal_id})
        chapter = _record(book, name="CHAPTER.md", text="This chapter is still short.")
        self.assertEqual(chapter.reason, "proposal")
        self.assertEqual(set(book.proposals), {recorded.proposal_id, chapter.proposal_id})
        self.assertEqual(EXAMPLE.read_text(encoding="utf-8"), example)
        self.assertFalse((ROOT / "soul" / "proposals").exists())
        self.assertEqual(tuple(COLLECTIONS), before)

    def test_only_the_two_character_files_are_named(self) -> None:
        book = Book()
        for name in ("agents/chief.md", "chief.md", "SOUL.example.md", "soul/SOUL.md", "../SOUL.md", "soul.md"):
            decision = _record(book, name=name)
            self.assertEqual(decision.reason, "not_a_soul_file", name)
        self.assertEqual(_record(book, text="  ").reason, "empty")
        self.assertEqual(_record(book, text=True).reason, "empty")  # type: ignore[arg-type]
        self.assertEqual(book.proposals, {})

    def test_a_credential_is_not_recorded_and_the_kept_sentence_is(self) -> None:
        book = Book()
        for text in ("token=abcd", "password is hunter22", "password%20is%20hunter22", "password+is+hunter22"):
            decision = _record(book, text=text, confirmed=True)
            self.assertEqual(decision.reason, "credential")
            self.assertNotIn("hunter22", str(decision))
            self.assertNotIn("abcd", str(decision))
        self.assertEqual(book.proposals, {})
        kept = _record(book, text=KEPT)
        self.assertEqual(kept.reason, "proposal")
        self.assertEqual(book.proposals[kept.proposal_id].text, KEPT)

    def test_apply_needs_a_matching_token_and_keeps_the_previous_text(self) -> None:
        book = Book()
        book.current["SOUL.md"] = "The example text the operator started from."
        recorded = _record(book, text=KEPT)
        proposal_id = recorded.proposal_id
        chat = apply_proposal(
            book,
            actor="chat",
            proposal_id=proposal_id,
            token=TOKEN,
            expected=TOKEN,
            confirmed=True,
            weekly=True,
        )
        self.assertEqual(chat.reason, "board_only")
        self.assertEqual(book.current["SOUL.md"], "The example text the operator started from.")
        self.assertEqual(book.history, [])
        self.assertIs(book.proposals[proposal_id].applied, False)

        missing = apply_proposal(
            book,
            actor="board",
            proposal_id=proposal_id,
            token="",
            expected="",
            weekly=True,
        )
        self.assertEqual(missing.reason, "token_required")
        self.assertIs(missing.scheduled, False)
        self.assertIs(missing.applied, False)
        mismatch = apply_proposal(
            book,
            actor="board",
            proposal_id=proposal_id,
            token="token=abcd",
            expected=OTHER,
        )
        self.assertEqual(mismatch.reason, "token_mismatch")
        self.assertNotIn("abcd", str(mismatch))
        self.assertNotIn("abcd", str(book))
        self.assertEqual(book.history, [])
        self.assertIs(book.proposals[proposal_id].applied, False)
        blank = apply_proposal(
            book,
            actor="board",
            proposal_id=proposal_id,
            token=" ",
            expected=" ",
        )
        self.assertEqual(blank.reason, "token_required")
        shaped = apply_proposal(
            book,
            actor="board",
            proposal_id=proposal_id,
            token="token=abcd",
            expected="token=abcd",
        )
        self.assertEqual(shaped.reason, "credential")
        self.assertNotIn("abcd", str(shaped))
        self.assertNotIn("abcd", str(book))
        short = apply_proposal(
            book,
            actor="board",
            proposal_id=proposal_id,
            token="short",
            expected="much-longer-token",
        )
        self.assertEqual(short.reason, "token_mismatch")
        self.assertEqual(book.history, [])
        self.assertIs(book.proposals[proposal_id].applied, False)
        book.current["CHAPTER.md"] = "Chapter stays."

        applied = apply_proposal(
            book,
            actor="board",
            proposal_id=proposal_id,
            token=TOKEN,
            expected=TOKEN,
            confirmed=True,
            weekly=True,
        )
        self.assertEqual((applied.outcome, applied.reason), ("applied", "applied"))
        self.assertIs(applied.applied, True)
        self.assertIs(applied.files_written, False)
        self.assertIs(applied.example_read, False)
        self.assertIs(applied.token_stored, False)
        self.assertIs(applied.scheduled, False)
        self.assertNotIn(TOKEN, str(applied))
        self.assertNotIn(TOKEN, str(book))
        self.assertEqual(book.current["SOUL.md"], KEPT)
        self.assertEqual(book.current["CHAPTER.md"], "Chapter stays.")
        self.assertEqual(book.history[0].previous, "The example text the operator started from.")
        self.assertEqual(book.history[0].proposal_id, proposal_id)
        self.assertEqual(len(book.history), 1)

        second = apply_proposal(
            book,
            actor="board",
            proposal_id=proposal_id,
            token=TOKEN,
            expected=TOKEN,
        )
        self.assertEqual(second.reason, "already_applied")
        self.assertIs(second.applied, False)
        self.assertEqual(len(book.history), 1)
        self.assertEqual(book.current["SOUL.md"], KEPT)

        later = _record(book, text="Ask before a change.")
        self.assertEqual(later.reason, "proposal")
        again = apply_proposal(
            book,
            actor="board",
            proposal_id=later.proposal_id,
            token=TOKEN,
            expected=TOKEN,
        )
        self.assertEqual(again.reason, "applied")
        self.assertEqual(book.history[1].previous, KEPT)
        self.assertEqual(book.current["SOUL.md"], "Ask before a change.")
        self.assertEqual(len(book.history), 2)
        self.assertFalse(hasattr(book, "token"))

    def test_a_generated_hex_token_applies(self) -> None:
        book = Book()
        minted = "ab" * 32
        recorded = _record(book, text="A later public line.")
        generated = apply_proposal(
            book,
            actor="board",
            proposal_id=recorded.proposal_id,
            token=minted,
            expected=minted,
        )
        self.assertEqual(generated.reason, "applied")
        self.assertEqual(book.current["SOUL.md"], "A later public line.")
        self.assertNotIn(minted, str(generated))
        self.assertNotIn(minted, str(book))

    def test_a_bad_token_shape_and_a_credential_body_do_not_apply(self) -> None:
        book = Book()
        recorded = _record(book)
        proposal_id = recorded.proposal_id
        for token, expected in ((True, TOKEN), (TOKEN, None), ("", TOKEN)):
            decision = apply_proposal(
                book,
                actor="board",
                proposal_id=proposal_id,
                token=token,  # type: ignore[arg-type]
                expected=expected,  # type: ignore[arg-type]
            )
            self.assertEqual(decision.reason, "token_required")
        self.assertEqual(
            apply_proposal(
                book,
                actor="board",
                proposal_id="missing",
                token=TOKEN,
                expected=TOKEN,
            ).reason,
            "unknown_proposal",
        )
        self.assertEqual(book.current, {})
        book.proposals[proposal_id].name = "SOUL.example.md"
        renamed = apply_proposal(
            book,
            actor="board",
            proposal_id=proposal_id,
            token=TOKEN,
            expected=TOKEN,
            confirmed=True,
        )
        self.assertEqual(renamed.reason, "not_a_soul_file")
        self.assertEqual(book.current, {})
        self.assertEqual(book.history, [])
        self.assertIs(book.proposals[proposal_id].applied, False)
        book.proposals[proposal_id].name = "SOUL.md"
        book.proposals[proposal_id].text = "  "
        blank = apply_proposal(
            book,
            actor="board",
            proposal_id=proposal_id,
            token=TOKEN,
            expected=TOKEN,
        )
        self.assertEqual(blank.reason, "empty")
        self.assertEqual(book.current, {})
        self.assertIs(book.proposals[proposal_id].applied, False)
        book.proposals[proposal_id].text = "password is hunter22"
        refused = apply_proposal(
            book,
            actor="board",
            proposal_id=proposal_id,
            token=TOKEN,
            expected=TOKEN,
            confirmed=True,
        )
        self.assertEqual(refused.reason, "credential")
        self.assertNotIn("hunter22", str(refused))
        self.assertEqual(book.current, {})
        self.assertEqual(book.history, [])
        self.assertIs(book.proposals[proposal_id].applied, False)

    def test_ask_does_not_call_this_module_and_there_is_no_soul_route(self) -> None:
        text = Path("friday/ask.py").read_text(encoding="utf-8")
        self.assertNotIn("record_proposal", text)
        self.assertNotIn("apply_proposal", text)
        self.assertNotIn("memoryd.soul", text)
        example = EXAMPLE.read_text(encoding="utf-8")
        notes = Notes()

        def recall(**kwargs):
            return notes.recall(**kwargs)

        def save(**kwargs):
            return notes.save(**kwargs)

        answer = ask(
            text="remember the project codename is lighthouse",
            owner_id="owner-1",
            owner_kind="person",
            charters_dir=ROOT / "charters",
            soul_text="You are Friday.",
            recall=recall,
            save=save,
            model=lambda _messages: "Noted.",
            embed_reason="",
            confirmed=True,
        )
        self.assertEqual(answer.reason, "remembered")
        self.assertEqual(EXAMPLE.read_text(encoding="utf-8"), example)

        handle = app(notes, {"MEMORY_TOKEN": "memory-token", "QDRANT_API_KEY": "qdrant-token"})
        status, body = handle(
            "POST",
            "/soul",
            {"Friday-Memory": "memory-token"},
            {"actor": "board", "name": "SOUL.md", "text": KEPT, "token": TOKEN, "confirmed": True},
        )
        self.assertEqual((status, body["reason"]), (404, "unknown_path"))
        self.assertNotIn(TOKEN, str(body))


if __name__ == "__main__":
    unittest.main()
