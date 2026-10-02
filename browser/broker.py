"""Record one generated secret for one browser site.

The Board asks. The name SITE_CREDENTIAL comes back. The value stays in
this process. It is not shown, not written to a file, and not placed
on the process environment. It is not the notify token, the messaging-door
token, or the inbound MCP token. A caller-supplied value is not stored.
Chat cannot record one, and that refusal leaves a secret the Board
already recorded.

One site is recorded. A second record keeps the first value and the
first site. A 64-character lowercase hex value is the generated secret.
Any other credential-shaped draw is not stored. The model is not given
the value. A core name, a loopback address, and a link-local address
are refused. An abbreviated loopback spelling is refused too. Recording it does not fetch a page, does not start a
browser, and does not create an approval. This module does not resolve
DNS and does not open a socket. browser/server.py still reads the
environment and does not call this record. Friday's ask path does not
call it.
"""

from __future__ import annotations

import hmac
import ipaddress
import re
import threading
from dataclasses import dataclass

from memoryd.store import credential_shape
from netpolicy.paths import CORE_NAMES

NAME = "SITE_CREDENTIAL"
KEPT = "The password is kept outside the machine"
_HEX = frozenset("0123456789abcdef")
_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
_METADATA = "metadata.google.internal"


@dataclass(frozen=True)
class Decision:
    outcome: str
    reason: str
    name: str = ""
    site: str = ""
    started: bool = False
    fetched: bool = False
    sent: bool = False
    approved: bool = False


class Book:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._value: str | None = None
        self._site: str | None = None

    def __repr__(self) -> str:
        return "Book()"


def record_site(
    book: Book,
    *,
    actor: str,
    site: object,
    rng,
    supplied: object = None,
    notify_token: object = "",
    door_token: object = "",
    mcp_token: object = "",
    confirmed: bool = False,
) -> Decision:
    del confirmed
    held = _stored_site(book)
    if actor != "board":
        return _no("board_only", name=NAME if held else "", site=held)
    if held:
        return _keep(supplied, held)
    reason = _supplied(supplied)
    if reason == "credential":
        return _no("credential")
    if reason:
        return _no(reason, name=NAME)
    chosen, problem = _site(site)
    if problem == "credential":
        return _no("credential")
    if problem:
        return _no(problem, name=NAME)
    blocked = tuple(
        item
        for item in (notify_token, door_token, mcp_token)
        if isinstance(item, str) and item != ""
    )
    with book._lock:
        if book._value is not None and book._site is not None:
            return _named("recorded", "name_only", book._site)
        value = _mint(rng, blocked)
        if value is None:
            return _no("not_minted", name=NAME)
        book._value = value
        book._site = chosen
    return _named("recorded", "name_only", chosen)


def hold(book: Book, who: str) -> Decision:
    site = _stored_site(book)
    if who == "model":
        return _named("withheld", "model_sees_page", site) if site else _no("model_sees_page")
    if who == "broker":
        if not site:
            return _no("unknown_secret")
        return _named("held", "for_the_site", site)
    return _no("unknown_party", name=NAME if site else "", site=site)


def show(book: Book) -> Decision:
    site = _stored_site(book)
    if not site:
        return _no("unknown_secret")
    return _named("refused", "value_hidden", site)


def names(book: Book) -> tuple[str, ...]:
    if not _stored_site(book):
        return ()
    return (NAME,)


def matches(book: Book, header: object) -> bool:
    if not isinstance(header, str) or header == "":
        return False
    with book._lock:
        secret = book._value
    if not isinstance(secret, str) or secret == "":
        return False
    try:
        return hmac.compare_digest(secret, header)
    except (TypeError, ValueError):
        return False


def _stored_site(book: Book) -> str:
    with book._lock:
        if book._value is None or not book._site:
            return ""
        return book._site


def _keep(supplied: object, site: str) -> Decision:
    reason = _supplied(supplied)
    if reason == "credential":
        return _named("recorded", "name_only", site)
    if reason:
        return _named("refused", reason, site)
    return _named("recorded", "name_only", site)


def _supplied(value: object) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, str) and value != KEPT and credential_shape(value):
        return "credential"
    return "caller_value"


def _site(value: object) -> tuple[str, str]:
    if isinstance(value, (list, tuple)):
        return "", "one_at_a_time"
    if not isinstance(value, str):
        return "", "site"
    if credential_shape(value):
        return "", "credential"
    if "\n" in value or "\r" in value:
        return "", "site"
    text = value.strip().casefold().rstrip(".")
    if not text or len(text) > 253 or ".." in text:
        return "", "site"
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        address = _abbreviated_ipv4(text)
    if address is not None:
        if address.is_link_local:
            return "", "link_local"
        if address.is_loopback or address.is_unspecified:
            return "", "loopback"
        return "", "site"
    if text == _METADATA or text.endswith("." + _METADATA):
        return "", "metadata"
    if text == "localhost" or text.endswith(".localhost"):
        return "", "loopback"
    if any(mark in text for mark in "/\\:@#? "):
        return "", "site"
    labels = text.split(".")
    if any(_LABEL.fullmatch(label) is None for label in labels):
        return "", "site"
    if text in CORE_NAMES:
        return "", "core_closed"
    return text, ""


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


def _named(outcome: str, reason: str, site: str) -> Decision:
    return Decision(outcome, reason, name=NAME, site=site)


def _no(reason: str, *, name: str = "", site: str = "") -> Decision:
    return Decision("refused", reason, name=name, site=site)
