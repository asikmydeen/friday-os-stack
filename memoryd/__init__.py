"""Memory service.

Recall, reflection, and export require an owner. Another person's notes
stay out. The pack holds at most 8 notes. `memoryd.hub` searches only
`knowledge` and `friday_findings` for that owner and does not write a
point. Friday's /ask calls that search through POST /hub and keeps the
same cap. A hub that is not ready leaves the note pack unchanged. `memoryd.persona` copies one owner's profile notes into a persona
note on the file store. Chat cannot extract or read it, and Friday's ask
path does not call it. `memoryd.card` records one research card or one
kept decision. The raw page is not stored, including a copy rebuilt by removing it. Chat cannot
record one, and Friday's ask path does not call it. With
`POSTGRES_HOST` set, `POST /card` writes that row through `memory_save`.
A second card of the same text revises that one row. `POST /save` still
refuses those categories and does not connect. A working note is copied to a
promoted row only by `memoryd.promote`, and only for the Board. With
`POSTGRES_HOST` set, `POST /promote` writes that copy through
`memory_save` and keeps the working row's id. A promoted save with no
pointer is refused and does not connect. Chat cannot, and Friday's ask
path does not call it. A soul
proposal is recorded by `memoryd.soul` and applied only with a matching
token. The file store does not open Postgres or Qdrant. The process
does, when those hosts are set.
"""

from memoryd.store import RECALL_CAP, Decision, Notes

__all__ = ["RECALL_CAP", "Decision", "Notes"]
