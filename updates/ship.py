"""Record the ship-mcp tool surface. Do not start taskrunner.

ship-mcp is how Friday would submit work when the code profile is on.
This cut records that surface and returns the token name only. The
value stays in this process. It is not shown, not written to a file,
and not placed on the environment. It is not the notify token and it
is not the Coder token.

The Board is the only actor. Chat cannot record the surface, and that
refusal leaves a surface already recorded. A caller-supplied value is
not stored. A second record keeps the first value. An empty Coder URL
keeps the profile off and stores nothing. The template name stays
taskrunner-universal unless the Board names another plain name.
Submitting work does not call Coder and does not create a workspace.

This module does not open a socket, does not open Postgres, and does
not create a database. Friday's ask path does not call it.
"""

from __future__ import annotations

import hmac
import threading
from dataclasses import dataclass

from memoryd.store import credential_shape

TOKEN_NAME = "SHIP_MCP_TOKEN"
GITHUB_NAME = "GITHUB_TOKEN"
DEFAULT_TEMPLATE = "taskrunner-universal"
KEPT = "The password is kept outside the machine"
_HEX = frozenset("0123456789abcdef")


@dataclass(frozen=True)
class Decision:
    outcome: str
    reason: str
    name: str = ""
    started: bool = False
    created: bool = False
    called: bool = False


class Book:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._token: str | None = None
        self._url = ""
        self._template = ""
        self._task: str | None = None

    def __repr__(self) -> str:
        return "Book()"


def record_surface(
    book: Book,
    *,
    actor: str,
    enabled: object = False,
    coder_url: object = "",
    coder_token: object = None,
    github_token: object = None,
    template: object = None,
    rng=None,
    supplied: object = None,
    notify_token: object = "",
    confirmed: bool = False,
) -> Decision:
    del confirmed
    held = _held(book)
    if actor != "board":
        return _no("board_only", name=TOKEN_NAME if held else "")
    if held:
        return _keep(book, coder_url, coder_token, github_token, template, supplied)
    leaked = _leaked(coder_url, coder_token, github_token, template, supplied)
    if leaked:
        return _no(leaked)
    if enabled is not True:
        return _no("profile_off", outcome="off")
    url, reason = _url(coder_url)
    if reason:
        return _no(reason, outcome="off" if reason == "no_coder_url" else "refused")
    reason = _coder_token(coder_token)
    if reason:
        return _no(reason)
    reason = _supplied(github_token)
    if reason:
        return _no(reason)
    reason = _supplied(supplied)
    if reason:
        return _no(reason)
    chosen, reason = _template(template)
    if reason:
        return _no(reason)
    notify = notify_token if isinstance(notify_token, str) else ""
    present = coder_token if isinstance(coder_token, str) else ""
    value = _mint(rng, (notify, present))
    if value is None:
        return _no("not_minted", name=TOKEN_NAME)
    with book._lock:
        if book._token is not None:
            return _named("recorded", "name_only")
        book._token = value
        book._url = url or ""
        book._template = chosen or DEFAULT_TEMPLATE
    return _named("recorded", "name_only")


def show(book: Book, slot: object = "ship") -> Decision:
    if not _held(book):
        return _no("unknown_secret")
    if slot == "github":
        return _named("refused", "value_hidden", GITHUB_NAME)
    if slot != "ship":
        return _no("unknown_secret")
    return _named("refused", "value_hidden")


def names(book: Book) -> tuple[str, ...]:
    if not _held(book):
        return ()
    return (TOKEN_NAME, GITHUB_NAME)


def matches(book: Book, header: object) -> bool:
    if not isinstance(header, str) or header == "":
        return False
    with book._lock:
        secret = book._token
    if not isinstance(secret, str) or secret == "":
        return False
    try:
        return hmac.compare_digest(secret, header)
    except (TypeError, ValueError):
        return False


def template_of(book: Book) -> str:
    with book._lock:
        return book._template


def links(book: Book) -> tuple[str, ...]:
    with book._lock:
        url = book._url
    if url == "":
        return ()
    return ("coder",)


def submit(
    book: Book,
    *,
    actor: str,
    task: object,
    confirmed: bool = False,
) -> Decision:
    del confirmed
    if not _held(book):
        return _no("not_recorded")
    if actor != "board":
        return _named("refused", "not_started")
    if not isinstance(task, str) or task.strip() == "" or "\n" in task or "\r" in task:
        return _named("refused", "task")
    if credential_shape(task):
        with book._lock:
            if book._task is not None:
                return _named("refused", "not_started")
        return _no("credential")
    with book._lock:
        if book._task is None:
            book._task = task
    return _named("refused", "not_started")


def tasks(book: Book) -> tuple[str, ...]:
    with book._lock:
        if book._task is None:
            return ()
        return (book._task,)


def _held(book: Book) -> bool:
    with book._lock:
        return book._token is not None


def _keep(book, coder_url, coder_token, github_token, template, supplied) -> Decision:
    leaked = _leaked(coder_url, coder_token, github_token, template, supplied)
    if leaked == "credential":
        return _named("recorded", "name_only")
    if leaked:
        return _named("refused", leaked)
    if _url(coder_url)[1] or _coder_token(coder_token) or _supplied(github_token) or _supplied(supplied):
        reason = _url(coder_url)[1] or _coder_token(coder_token) or _supplied(github_token) or _supplied(supplied)
        if reason == "credential":
            return _named("recorded", "name_only")
        outcome = "off" if reason == "no_coder_url" else "refused"
        return Decision(outcome, reason, name=TOKEN_NAME, started=False, created=False, called=False)
    chosen, reason = _template(template)
    if reason == "credential":
        return _named("recorded", "name_only")
    if reason:
        return _named("refused", reason)
    del chosen
    return _named("recorded", "name_only")


def _leaked(coder_url, coder_token, github_token, template, supplied) -> str:
    for value in (coder_url, coder_token, template):
        if isinstance(value, str) and value not in {"", KEPT} and credential_shape(value):
            return "credential"
    for value in (github_token, supplied):
        if isinstance(value, str) and value != "" and credential_shape(value):
            return "credential"
    return ""


def _url(value: object) -> tuple[str | None, str]:
    if not isinstance(value, str) or value.strip() == "":
        return None, "no_coder_url"
    if value == KEPT:
        return value, ""
    if (
        value != value.strip()
        or "\n" in value
        or "\r" in value
        or " " in value
        or "@" in value
        or "?" in value
        or len(value) > 256
        or not (value.startswith("https://") or value.startswith("http://"))
    ):
        return None, "coder_url"
    if credential_shape(value):
        return None, "credential"
    return value, ""


def _coder_token(value: object) -> str:
    if not isinstance(value, str) or value.strip() == "" or "\n" in value or "\r" in value:
        return "token_required"
    if credential_shape(value):
        return "credential"
    return ""


def _supplied(value: object) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, str) and credential_shape(value):
        return "credential"
    return "caller_value"


def _template(value: object) -> tuple[str | None, str]:
    if value is None or value == "":
        return DEFAULT_TEMPLATE, ""
    if not isinstance(value, str) or "\n" in value or "\r" in value or len(value) > 128 or value.strip() == "":
        return None, "template"
    if value == KEPT:
        return value, ""
    if not value or value != value.strip() or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789-" for char in value):
        return None, "template"
    if not value[0].isalpha():
        return None, "template"
    if credential_shape(value):
        return None, "credential"
    return value, ""


def _named(outcome: str, reason: str, name: str = TOKEN_NAME) -> Decision:
    return Decision(outcome, reason, name=name, started=False, created=False, called=False)


def _no(reason: str, *, outcome: str = "refused", name: str = "") -> Decision:
    return Decision(outcome, reason, name=name, started=False, created=False, called=False)


def _draw(rng) -> str | None:
    try:
        value = rng.token_hex(32)
    except Exception:
        return None
    if not isinstance(value, str) or value == "" or "\n" in value or "\r" in value:
        return None
    if len(value) == 64 and all(char in _HEX for char in value):
        return value
    if credential_shape(value):
        return None
    return value


def _mint(rng, blocked: tuple[str, ...]) -> str | None:
    if rng is None:
        return None
    first = _draw(rng)
    if first is None:
        return None
    if first not in blocked:
        return first
    second = _draw(rng)
    if second is None or second in blocked:
        return None
    return second
