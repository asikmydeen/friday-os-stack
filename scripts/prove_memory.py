"""Prove memory_save, owner isolation, and one Qdrant point.

Runs inside a throwaway network. The embed vector is 768 numbers from
this process. It does not call Ollama.
"""

from __future__ import annotations

import os
import urllib.error
import urllib.request

from memoryd.index import drain, search
from memoryd.qdrant import Qdrant
from memoryd.sqlstore import PostgresNotes

VECTOR = [0.1] * 768


def main() -> None:
    env = dict(os.environ)
    notes = PostgresNotes.from_env(env)
    if not notes.ping():
        raise SystemExit("postgres")
    saved = notes.save(
        owner_id="owner-1",
        owner_kind="person",
        content="the project codename is lighthouse",
        visibility="master",
        category="note",
    )
    if saved.reason != "created" or not saved.note_id:
        raise SystemExit(f"save {saved.reason}")
    again = notes.save(
        owner_id="owner-1",
        owner_kind="person",
        content="the project codename is lighthouse",
        visibility="master",
        category="note",
    )
    if again.note_id != saved.note_id or again.revision != 2:
        raise SystemExit("revision")
    own = notes.recall(owner_id="owner-1", owner_kind="person")
    if [note["content"] for note in own.notes] != ["the project codename is lighthouse"]:
        raise SystemExit("recall")
    other = notes.recall(owner_id="owner-2", owner_kind="person")
    if other.notes:
        raise SystemExit("leaked")
    role = notes.save(
        owner_id="owner-1",
        owner_kind="role",
        content="the project codename is lighthouse",
        visibility="working",
        category="note",
    )
    if role.note_id == saved.note_id:
        raise SystemExit("role shared the person row")
    person = notes.recall(owner_id="owner-1", owner_kind="person")
    if len(person.notes) != 1:
        raise SystemExit("role leaked into the person recall")

    qdrant = Qdrant(env["QDRANT_URL"], env["QDRANT_API_KEY"])
    refused = _status(env["QDRANT_URL"] + "/collections", None)
    if refused != 401:
        raise SystemExit(f"qdrant accepted a request without the key ({refused})")
    reason = drain(notes, qdrant, lambda _text: list(VECTOR))
    if reason != "idle":
        raise SystemExit(f"index {reason}")
    found = search(
        qdrant,
        lambda _text: list(VECTOR),
        owner_id="owner-1",
        owner_kind="person",
        text="lighthouse",
    )
    if [note["content"] for note in found.notes] != ["the project codename is lighthouse"]:
        raise SystemExit("search")
    hidden = search(
        qdrant,
        lambda _text: list(VECTOR),
        owner_id="owner-1",
        owner_kind="role",
        text="lighthouse",
    )
    if [note["id"] for note in hidden.notes] != [role.note_id]:
        raise SystemExit("role search")
    missing = search(qdrant, lambda _text: list(VECTOR), owner_id="", owner_kind="person", text="lighthouse")
    if missing.reason != "missing_owner":
        raise SystemExit("filter")

    gone = notes.tombstone(saved.note_id)
    if gone.reason != "tombstone":
        raise SystemExit("tombstone")
    reason = drain(notes, qdrant, lambda _text: list(VECTOR))
    if reason != "idle":
        raise SystemExit(f"delete index {reason}")
    after = notes.recall(owner_id="owner-1", owner_kind="person")
    if after.notes:
        raise SystemExit("tombstone still recalled")
    missed = search(
        qdrant,
        lambda _text: list(VECTOR),
        owner_id="owner-1",
        owner_kind="person",
        text="lighthouse",
    )
    if missed.notes:
        raise SystemExit("point remained")
    if _unfinished(notes) != 0:
        raise SystemExit("queue")
    print("prove-memory: one postgres row was indexed and then deleted")


def _status(url: str, key: str | None) -> int:
    headers = {}
    if key:
        headers["api-key"] = key
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        exc.close()
        return exc.code


def _unfinished(notes: PostgresNotes) -> int:
    with notes._connect() as conn:
        row = conn.execute(
            "SELECT count(*) FROM memory_index_queue WHERE done_at IS NULL"
        ).fetchone()
    return int(row[0])


if __name__ == "__main__":
    main()
