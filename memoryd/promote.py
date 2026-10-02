"""Copy one working note into its own promoted row.

The working row stays. A second copy of that same row bumps the
promoted row. A promoted row that points somewhere else is left as it
is. Chat cannot do this, and the ask path does not call it. A
credential-shaped note is not copied. On the file store the copy is
another row. On Postgres it is memory_save with that working id. A
promoted save with no pointer does not connect. No collection is
created.

confirmed=true is ignored.
"""

from __future__ import annotations

from memoryd.store import Decision, credential_shape


def promote(notes, *, actor: str, note_id: str, confirmed: bool = False) -> Decision:
    del confirmed
    if actor != "board":
        return Decision("refused", "board_only")
    if not isinstance(note_id, str) or note_id == "":
        return Decision("refused", "unknown_note")
    rows = getattr(notes, "rows", None)
    if not isinstance(rows, dict):
        copy = getattr(notes, "promote_working", None)
        if not callable(copy):
            return Decision("refused", "not_the_file_store")
        return copy(note_id)
    row = rows.get(note_id)
    if row is None or row.deleted:
        return Decision("refused", "unknown_note")
    if row.visibility != "working":
        return Decision("refused", "not_working")
    if credential_shape(row.content):
        return Decision("refused", "credential")
    return notes.save(
        owner_id=row.owner_id,
        owner_kind=row.owner_kind,
        content=row.content,
        visibility="promoted",
        category=row.category,
        promoted_from=row.id,
    )
