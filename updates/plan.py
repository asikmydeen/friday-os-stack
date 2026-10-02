"""Record an optional coding-plan base URL. Do not call it.

The engine is claude-code or gsd. The base URL is optional, and only
claude-code may have one. With the URL unset, nothing is stored and
the Anthropic key is not read from the environment. A caller-supplied
key is not stored. ANTHROPIC_API_KEY is reserved and no value is kept.

The Board is the only actor. Chat cannot record a URL, and that
refusal leaves a URL already recorded. A second record keeps the first
URL. The value stays in this process. It is not shown, not written to
a file, and not placed on the environment.

Recording it does not call the URL, does not start taskrunner, and
does not create a workspace. started, called, and read_env stay false.
This module does not open a socket, Postgres, or SQLite. Friday's ask
path does not call it.
"""

from __future__ import annotations

import hmac
import ipaddress
import threading
from dataclasses import dataclass
from urllib.parse import urlsplit

from memoryd.store import credential_shape
from netpolicy.paths import CORE_NAMES, METADATA_HOST

NAME = "CODING_PLAN_URL"
KEY_NAME = "ANTHROPIC_API_KEY"
ENGINES = frozenset({"claude-code", "gsd"})
KEPT = "The password is kept outside the machine"


@dataclass(frozen=True)
class Decision:
    outcome: str
    reason: str
    name: str = ""
    engine: str = ""
    started: bool = False
    called: bool = False
    read_env: bool = False


class Book:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._url: str | None = None
        self._engine: str = ""

    def __repr__(self) -> str:
        return "Book()"


def record_plan(
    book: Book,
    *,
    actor: str,
    engine: object,
    base_url: object = None,
    anthropic_key: object = None,
    supplied: object = None,
    confirmed: bool = False,
) -> Decision:
    del confirmed
    held = _held(book)
    if actor != "board":
        return _quiet("board_only", name=NAME if held else "", engine=_engine_of(book))
    leaked = _leaked(base_url, engine, anthropic_key, supplied)
    if held:
        if leaked == "credential":
            return _named("recorded", "name_only")
        if leaked:
            return _named("refused", leaked)
        return _named("recorded", "name_only")
    if leaked == "credential":
        return _quiet("credential")
    if leaked:
        return _quiet(leaked)
    chosen = _engine(engine)
    if chosen is None:
        return _quiet("engine")
    url, reason = _url(base_url)
    if reason == "unset":
        return _quiet("unset", outcome="recorded")
    if reason:
        return _quiet(reason)
    if chosen != "claude-code":
        return _quiet("not_for_that_engine")
    with book._lock:
        if book._url is None:
            book._url = url
            book._engine = "claude-code"
    return _named("recorded", "name_only")


def use_plan(
    book: Book,
    *,
    actor: str,
    text: object = None,
    confirmed: bool = False,
) -> Decision:
    del confirmed
    held = _held(book)
    if actor != "board":
        return _quiet("board_only", name=NAME if held else "", engine=_engine_of(book))
    if isinstance(text, str) and text not in {"", KEPT} and credential_shape(text):
        return _quiet("credential", name=NAME if held else "", engine=_engine_of(book))
    if not held:
        return _quiet("unset", outcome="off")
    return _named("refused", "not_called")


def show(book: Book, slot: object = "plan") -> Decision:
    if not _held(book):
        return _quiet("unknown_secret")
    if slot == "anthropic":
        return Decision("refused", "value_hidden", name=KEY_NAME, engine="claude-code")
    if slot != "plan":
        return _quiet("unknown_secret")
    return _named("refused", "value_hidden")


def names(book: Book) -> tuple[str, ...]:
    if not _held(book):
        return ()
    return (NAME, KEY_NAME)


def matches(book: Book, header: object) -> bool:
    if not isinstance(header, str) or header == "":
        return False
    with book._lock:
        secret = book._url
    if not isinstance(secret, str) or secret == "":
        return False
    try:
        return hmac.compare_digest(secret, header)
    except (TypeError, ValueError):
        return False


def engine_of(book: Book) -> str:
    return _engine_of(book)


def _held(book: Book) -> bool:
    with book._lock:
        return book._url is not None


def _engine_of(book: Book) -> str:
    with book._lock:
        return book._engine


def _leaked(base_url: object, engine: object, anthropic_key: object, supplied: object) -> str:
    for value in (base_url, engine):
        if isinstance(value, str) and value not in {"", KEPT} and credential_shape(value):
            return "credential"
    if _caller(anthropic_key, allow_kept=True):
        return _caller(anthropic_key, allow_kept=True)
    return _caller(supplied, allow_kept=False)


def _caller(value: object, *, allow_kept: bool) -> str:
    if value is None or value == "":
        return ""
    if allow_kept and isinstance(value, str) and value == KEPT:
        return ""
    if isinstance(value, str) and credential_shape(value):
        return "credential"
    return "caller_value"


def _engine(value: object) -> str | None:
    if isinstance(value, str) and value in ENGINES:
        return value
    return None


def _url(value: object) -> tuple[str | None, str]:
    if value is None:
        return None, "unset"
    if not isinstance(value, str):
        return None, "url"
    if value == KEPT:
        return value, ""
    if value.strip() == "":
        return None, "unset"
    if (
        value != value.strip()
        or "\n" in value
        or "\r" in value
        or " " in value
        or len(value) > 256
    ):
        return None, "url"
    if credential_shape(value):
        return None, "credential"
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or parts.username or parts.password or "@" in value:
        return None, "url"
    if parts.query or parts.fragment or not parts.hostname:
        return None, "url"
    reason = _host(parts.hostname)
    if reason:
        return None, reason
    return value, ""


def _host(host: str) -> str:
    text = host.strip().casefold().rstrip(".")
    if text in CORE_NAMES:
        return "core_closed"
    if text == METADATA_HOST or text.endswith("." + METADATA_HOST):
        return "metadata"
    if text == "localhost" or text.endswith(".localhost"):
        return "loopback"
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        address = _abbreviated_ipv4(text)
    if address is None:
        return ""
    if address.is_link_local:
        return "link_local"
    if address.is_loopback or address.is_unspecified:
        return "loopback"
    return ""


def _abbreviated_ipv4(text: str) -> ipaddress.IPv4Address | None:
    parts = text.split(".")
    if not 1 <= len(parts) <= 4:
        return None
    numbers: list[int] = []
    for part in parts:
        number = _number(part)
        if number is None:
            return None
        numbers.append(number)
    if len(numbers) == 4:
        if any(number > 255 for number in numbers):
            return None
        value = (numbers[0] << 24) | (numbers[1] << 16) | (numbers[2] << 8) | numbers[3]
    elif len(numbers) == 3:
        if numbers[0] > 255 or numbers[1] > 255 or numbers[2] > 65535:
            return None
        value = (numbers[0] << 24) | (numbers[1] << 16) | numbers[2]
    elif len(numbers) == 2:
        if numbers[0] > 255 or numbers[1] > 16777215:
            return None
        value = (numbers[0] << 24) | numbers[1]
    elif numbers[0] > 0xFFFFFFFF:
        return None
    else:
        value = numbers[0]
    return ipaddress.IPv4Address(value)


def _number(part: str) -> int | None:
    if part.startswith("0x"):
        digits = part[2:]
        if digits == "" or any(char not in "0123456789abcdef" for char in digits):
            return None
        return int(digits, 16)
    if part.startswith("0") and len(part) > 1:
        if any(char not in "01234567" for char in part):
            return None
        return int(part, 8)
    if part == "" or not part.isdigit():
        return None
    return int(part, 10)


def _named(outcome: str, reason: str) -> Decision:
    return Decision(
        outcome,
        reason,
        name=NAME,
        engine="claude-code",
        started=False,
        called=False,
        read_env=False,
    )


def _quiet(reason: str, *, outcome: str = "refused", name: str = "", engine: str = "") -> Decision:
    return Decision(outcome, reason, name=name, engine=engine, started=False, called=False, read_env=False)
