"""Record one log for a known app. Do not read a container.

The sentence is "Logs were read." The cleaned log is evidence under
that sentence. It is not a goal and it is not an action. A credential-
shaped log is not stored, including a percent-encoded or plus-encoded
copy. A vault secret is removed, including a percent-encoded or plus-encoded
copy, a further encoding of that copy, a copy split by whitespace, and
a copy rebuilt by that removal. A log that is only the secret is not
stored. "The password is kept outside the machine" can be the log.

The Board or Friday may record one. Chat cannot, and that refusal
leaves a row already recorded. A second record keeps the first log.
A listed or proposed app is refused. A core service is refused.
confirmed=true is ignored.

This module does not read a container, does not open a socket, does not
start one, and does not create an approval. Friday's ask path does not
call it. Start is not recorded here.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from urllib.parse import quote, quote_plus, unquote_plus

from memoryd.store import credential_shape
from netpolicy.paths import CORE_NAMES

SAID = "Logs were read."
ACTORS = frozenset({"board", "friday"})
TEXT_LIMIT = 1200
_ID = re.compile(r"[a-z][a-z0-9-]{0,63}\Z")


@dataclass(frozen=True)
class Decision:
    outcome: str
    reason: str
    app_id: str = ""
    said: str = ""
    body: str = ""
    kept: bool = False
    started: bool = False
    fetched: bool = False
    performed: bool = False


class Book:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.rows: dict[str, dict] = {}

    def __repr__(self) -> str:
        return "Book()"


def note_logs(
    book: Book,
    *,
    app_id: object,
    body: object,
    actor: object,
    wire_level: object = "known",
    secret: object = "",
    confirmed: bool = False,
) -> Decision:
    del confirmed
    name, reason = _app(app_id)
    if reason:
        return _quiet(reason)
    if wire_level != "known":
        return _quiet("not_known")
    if not isinstance(secret, str):
        return _quiet("secret")
    cleaned, reason = _log(body, secret)
    if reason:
        return _quiet(reason)
    if _chat(actor):
        return _kept(book, name, "chat_cannot")
    if actor not in ACTORS:
        return _kept(book, name, "actor_cannot")
    with book._lock:
        row = book.rows.get(name)
        if row is not None:
            return _from(name, row, "already")
        stored = {"said": SAID, "body": cleaned}
        book.rows[name] = stored
        return _from(name, stored, "evidence")


def shown(book: Book, app_id: object) -> Decision:
    name, reason = _app(app_id)
    if reason:
        return _quiet(reason)
    with book._lock:
        row = book.rows.get(name)
        if row is None:
            return _quiet("no_log")
        return _from(name, row, "evidence")


def _from(app_id: str, row: dict, reason: str) -> Decision:
    return Decision(
        "recorded",
        reason,
        app_id=app_id,
        said=row["said"],
        body=row["body"],
        kept=True,
    )


def _kept(book: Book, app_id: str, reason: str) -> Decision:
    with book._lock:
        row = book.rows.get(app_id)
        if row is None:
            return _quiet(reason)
        return _from(app_id, row, reason)


def _quiet(reason: str) -> Decision:
    return Decision("refused", reason)


def _chat(actor: object) -> bool:
    return isinstance(actor, str) and actor.strip().casefold() == "chat"


def _app(value: object) -> tuple[str, str]:
    if not isinstance(value, str) or value == "" or value != value.strip() or "\n" in value or "\r" in value:
        return "", "app_id"
    if _hidden(value):
        return "", "credential"
    if value.casefold() in CORE_NAMES:
        return "", "core_locked"
    if _ID.fullmatch(value) is None:
        return "", "app_id"
    return value, ""


def _log(body: object, secret: str) -> tuple[str, str]:
    if not isinstance(body, str) or body.strip() == "":
        return "", "log_text"
    if _hidden(body):
        return "", "credential"
    flat = " ".join(body.split())
    stripped = " ".join(_without_secret(flat, secret).split())
    if secret.strip() != "" and _still_holds(stripped, secret):
        return "", "secret"
    if stripped == "":
        return "", "log_text"
    if _hidden(stripped):
        return "", "credential"
    return stripped[:TEXT_LIMIT], ""


def _hidden(text: str) -> bool:
    seen = text
    for _ in range(3):
        if credential_shape(" ".join(seen.split())):
            return True
        decoded = unquote_plus(seen)
        if decoded == seen:
            return False
        seen = decoded
    return credential_shape(" ".join(seen.split()))


def _without_secret(body: str, secret: str) -> str:
    if secret.strip() == "":
        return body
    needles = _secret_forms(secret)
    text = body
    for _ in range(len(body) + 1):
        nxt = text
        for needle in needles:
            nxt = nxt.replace(needle, "")
        if nxt == text:
            break
        text = nxt
    return text


def _still_holds(text: str, secret: str) -> bool:
    return any(needle in text for needle in _secret_forms(secret))


def _secret_forms(secret: str) -> tuple[str, ...]:
    found: list[str] = []

    def add(item: str) -> None:
        if item and item not in found:
            found.append(item)

    seen = secret
    for _ in range(4):
        flat = " ".join(seen.split())
        if flat:
            add(flat)
            encoded = flat
            plus = flat
            for _level in range(3):
                encoded = quote(encoded, safe="")
                plus = quote_plus(plus)
                add(encoded)
                add(plus)
                add(encoded.lower())
                add(plus.lower())
        decoded = unquote_plus(seen)
        if decoded == seen:
            break
        seen = decoded
    found.sort(key=len, reverse=True)
    return tuple(found)
