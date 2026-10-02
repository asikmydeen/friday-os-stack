"""Record one research card or one kept decision for one owner.

The card is category finding. The decision is category knowledge. The
raw page is not the note, including a percent-encoded or plus-encoded
copy and a copy rebuilt by that removal. A credential-shaped summary is
not stored. A separate topic label
is not stored. Chat cannot record one. The file store writes a row.
When the store offers save_card, that call writes memory_save. This
module does not open a connection, does not write a point, and does not
call a model. No collection is created. Friday's ask
path does not call it. A tool result is still not saved.

confirmed=true is ignored.
"""

from __future__ import annotations

from urllib.parse import quote, quote_plus, unquote_plus

from memoryd.isolate import same_owner
from memoryd.store import Decision, credential_shape

TRIM = 1200
KINDS = frozenset({"finding", "knowledge"})
_STRIP = 12


def chat_blocked(actor: object) -> bool:
    return isinstance(actor, str) and actor.strip().casefold() == "chat"


def record_card(
    notes,
    *,
    caller_id: str,
    caller_kind: str,
    kind: object,
    text: object,
    page: object = None,
    subject_id: str | None = None,
    subject_kind: str | None = None,
    actor: object = "",
    confirmed: bool = False,
) -> Decision:
    """Write one finding or one knowledge row. Write nothing for anyone else."""
    del confirmed
    if chat_blocked(actor):
        return Decision("refused", "chat_cannot")
    gate = same_owner(caller_id, caller_kind, subject_id, subject_kind)
    if gate == "missing_owner":
        return Decision("refused", "missing_owner")
    if gate == "other_owner":
        return Decision("ok", "other_owner")
    caller = _caller(caller_id, caller_kind)
    if caller is None:
        return Decision("refused", "missing_owner")
    if _hidden(caller[0]):
        return Decision("refused", "credential")
    if _file_store(notes):
        writer = "file"
    elif callable(getattr(notes, "save_card", None)):
        writer = "card"
    else:
        return Decision("refused", "not_the_file_store")
    if not isinstance(kind, str) or kind not in KINDS:
        return Decision("refused", "kind")
    if not isinstance(text, str):
        return Decision("refused", "text")
    if page is not None and not isinstance(page, str):
        return Decision("refused", "page")
    summary = _flat(text)
    if _hidden(summary):
        return Decision("refused", "credential")
    if isinstance(page, str) and _flat(page) != "":
        summary = _without_page(summary, page)
        if summary is None:
            return Decision("refused", "raw_page")
    elif summary == "":
        return Decision("refused", "empty_content")
    if summary == "" or _hidden(summary):
        return Decision("refused", "credential" if summary else "empty_content")
    kept = summary[:TRIM]
    if kept == "" or _hidden(kept):
        return Decision("refused", "credential")
    visibility = "working" if caller[1] == "role" else "master"
    if writer == "file":
        saved = notes.save(
            owner_id=caller[0],
            owner_kind=caller[1],
            content=kept,
            visibility=visibility,
            category=kind,
        )
    else:
        saved = notes.save_card(
            owner_id=caller[0],
            owner_kind=caller[1],
            content=kept,
            category=kind,
        )
    if saved.outcome != "saved":
        return Decision(saved.outcome, saved.reason)
    return saved


def _caller(caller_id, caller_kind) -> tuple[str, str] | None:
    gate = same_owner(caller_id, caller_kind)
    if gate is not None:
        return None
    return caller_id.strip(), caller_kind


def _file_store(notes) -> bool:
    return isinstance(getattr(notes, "rows", None), dict)


def _flat(text: str) -> str:
    return " ".join(text.replace("\n", " ").split())


def _forms(value: str) -> tuple[str, ...]:
    found: list[str] = []

    def add(item: str) -> None:
        if item and item not in found:
            found.append(item)

    seen = value
    for _ in range(4):
        flat = _flat(seen)
        if flat:
            add(flat)
            encoded = flat
            plus = flat
            for _level in range(3):
                encoded = quote(encoded, safe="")
                plus = quote_plus(plus)
                add(encoded)
                add(plus)
        decoded = unquote_plus(seen)
        if decoded == seen:
            break
        seen = decoded
    found.sort(key=len, reverse=True)
    return tuple(found)


def _scrub(flat: str, form: str) -> str:
    if form == "":
        return flat
    if len(form) >= _STRIP or " " in form:
        if form not in flat:
            return flat
        return flat.replace(form, "")
    if form not in flat.split(" "):
        return flat
    return " ".join(part for part in flat.split(" ") if part != form)


def _page_remains(flat: str, forms: tuple[str, ...]) -> bool:
    if flat in forms:
        return True
    tokens = flat.split(" ")
    for form in forms:
        if len(form) >= _STRIP or " " in form:
            if form in flat:
                return True
        elif form in tokens:
            return True
    return False


def _without_page(summary: str, page: str) -> str | None:
    forms = _forms(page)
    flat = _flat(summary)
    if flat == "" or flat in forms:
        return None
    for _ in range(8):
        nxt = flat
        for form in forms:
            nxt = _scrub(nxt, form)
        nxt = _flat(nxt)
        if nxt == flat:
            break
        flat = nxt
    if flat == "" or _page_remains(flat, forms):
        return None
    return flat


def _hidden(text: str) -> bool:
    if not isinstance(text, str) or text == "":
        return False
    seen = text
    for _ in range(3):
        if credential_shape(" ".join(seen.split())):
            return True
        decoded = unquote_plus(seen)
        if decoded == seen:
            return False
        seen = decoded
    return credential_shape(" ".join(seen.split()))
