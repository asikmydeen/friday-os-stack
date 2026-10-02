"""Decide an adopt-only account without calling it.

One token is kept per person id. An unknown person, or a person with no
token, is told to connect an account. Nothing is written to the owner's
tracker. Calendar and mail with an empty client say they are not
connected. Phone harvest does not create the messages collection. A
phone token already stored does not ask the owner to connect an account
while harvest is off. A headed browser records a shopper search and a
buyer open. The page is not fetched. Neither checks out. The family
role is blocked from these connections and from download clients.

A custom card keeps a health URL. Tools stay off until a manifest names
one and the Board accepts that name. A newly offered name does not
inherit an earlier acceptance. Video, photos, and downloads are not
embedded. A receipt stays in this book. It is not an episode.

confirmed=true is ignored. This module does not resolve DNS, does not
open a socket, does not write a file, and does not start a container.
Friday's ask path does not call it.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from typing import Mapping, Sequence
from urllib.parse import urlsplit

from memoryd.store import credential_shape
from netpolicy.paths import vet_adopted

SERVICES = frozenset({"fitness", "calendar", "mail", "phone"})
CONNECT = "connect your account"
NOT_CONNECTED = "not connected"
EMPTY_CLIENT = frozenset({"calendar", "mail"})
BROWSER_ACT = {"shopper": "search", "buyer": "open"}
CHECKOUT = frozenset({"checkout", "pay", "buy", "order", "send", "delete", "publish"})
MEDIA_KINDS = frozenset({
    "video",
    "photo",
    "photos",
    "download",
    "downloads",
    "movie",
    "movies",
})
_PERSON = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
_CARD = re.compile(r"[a-z][a-z0-9-]{0,63}\Z")
_TOOL = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")


@dataclass(frozen=True)
class Decision:
    outcome: str
    reason: str
    said: str = ""
    name: str = ""
    written: bool = False
    collection_created: bool = False
    embedded: bool = False
    tools_on: bool = False
    checked_out: bool = False
    fetched: bool = False
    started: bool = False
    health_url: str = ""


class Book:
    def __init__(self, owner_id: str) -> None:
        self.owner_id = owner_id
        self.tokens: dict[tuple[str, str], str] = {}
        self.browser_url = ""
        self.phone_enabled = False
        self.messages_created = False
        self.cards: dict[str, dict] = {}
        self.receipts: list[dict[str, str]] = []

    def __repr__(self) -> str:
        return "Book()"


def grant_token(
    book: Book,
    *,
    actor: str,
    service: str,
    person_id: str,
    token: str,
    confirmed: bool = False,
) -> Decision:
    del confirmed
    if actor != "board":
        return Decision("refused", "actor_cannot_approve")
    if service not in SERVICES or not _person(person_id):
        return Decision("refused", "name")
    if person_id != book.owner_id:
        return Decision("refused", "unknown_person", said=CONNECT)
    if not isinstance(token, str) or token.strip() == "" or credential_shape(token):
        return Decision("refused", "token_refused")
    book.tokens[(service, person_id)] = token
    return Decision("recorded", "name_only", name=service)


def holds(book: Book, service: str, person_id: str, token: str) -> bool:
    return book.tokens.get((service, person_id)) == token


def use_account(
    book: Book,
    service: str,
    person_id: str,
    tracker: object,
    *,
    role: str = "",
    known: bool = True,
    confirmed: bool = False,
) -> Decision:
    del tracker, confirmed
    if role == "family":
        return Decision("refused", "family_blocked")
    if service not in SERVICES:
        return Decision("refused", "unknown_service")
    if known is not True or not _person(person_id) or person_id != book.owner_id:
        return Decision("refused", "unknown_person", said=CONNECT)
    if service == "phone" and book.phone_enabled is not True:
        said = "" if (service, person_id) in book.tokens else CONNECT
        return Decision("refused", "not_enabled", said=said)
    if (service, person_id) not in book.tokens:
        if service in EMPTY_CLIENT:
            return Decision("refused", "not_connected", said=NOT_CONNECTED)
        return Decision("refused", "connect_your_account", said=CONNECT)
    return Decision("recorded", "not_sent")


def enable_phone(book: Book, *, actor: str, confirmed: bool = False) -> Decision:
    del confirmed
    if actor != "board":
        return Decision("refused", "actor_cannot_approve")
    book.phone_enabled = True
    book.messages_created = False
    return Decision("recorded", "not_created")


def grant_browser(
    book: Book,
    *,
    actor: str,
    url: str,
    resolved: Mapping[str, Sequence[str]] | None = None,
    confirmed: bool = False,
) -> Decision:
    del confirmed
    if actor != "board":
        return Decision("refused", "actor_cannot_approve")
    reason = _url_reason(url, resolved)
    if reason:
        return Decision("refused", reason)
    book.browser_url = url
    return Decision("recorded", "name_only", name="browser")


def browse(book: Book, role: str, action: str, *, confirmed: bool = False) -> Decision:
    del confirmed
    if role == "family":
        return Decision("refused", "family_blocked")
    expected = BROWSER_ACT.get(role)
    if expected is None:
        return Decision("refused", "role")
    if action in CHECKOUT:
        return Decision("refused", "not_checkout")
    if action != expected:
        return Decision("refused", "action")
    if book.browser_url == "":
        return Decision("refused", "connect_your_account", said=CONNECT)
    return Decision("recorded", "not_fetched")


def download_client(role: str, *, confirmed: bool = False) -> Decision:
    del confirmed
    if role == "family":
        return Decision("refused", "family_blocked")
    if role != "fetcher":
        return Decision("refused", "not_fetcher")
    return Decision("refused", "catalog_install_closed")


def add_card(
    book: Book,
    card_id: str,
    health_url: str,
    *,
    resolved: Mapping[str, Sequence[str]] | None = None,
    confirmed: bool = False,
) -> Decision:
    del confirmed
    if not isinstance(card_id, str) or _CARD.fullmatch(card_id) is None:
        return Decision("refused", "card")
    if card_id in book.cards:
        return Decision("refused", "already_recorded", name=card_id)
    reason = _url_reason(health_url, resolved)
    if reason:
        return Decision("refused", reason)
    book.cards[card_id] = {"health_url": health_url, "offered": [], "accepted": []}
    return Decision("recorded", "tools_off", name=card_id, health_url=health_url)


def offer_tools(book: Book, card_id: str, tools: Sequence[str]) -> Decision:
    card = book.cards.get(card_id)
    if card is None:
        return Decision("refused", "unknown_card")
    if isinstance(tools, (str, bytes)) or not isinstance(tools, (list, tuple)):
        return Decision("refused", "tool_name")
    cleaned: list[str] = []
    for tool in tools:
        if not isinstance(tool, str) or _TOOL.fullmatch(tool) is None:
            return Decision("refused", "tool_name")
        if tool not in cleaned:
            cleaned.append(tool)
    for tool in cleaned:
        if tool not in card["offered"]:
            card["offered"].append(tool)
    return Decision("recorded", "tools_off", name=card_id)


def accept_tool(
    book: Book,
    *,
    actor: str,
    card_id: str,
    tool: str,
    confirmed: bool = False,
) -> Decision:
    del confirmed
    card = book.cards.get(card_id)
    if card is None:
        return Decision("refused", "unknown_card")
    if actor != "board":
        return Decision("refused", "actor_cannot_approve", name=tool if isinstance(tool, str) else "")
    if not isinstance(tool, str) or _TOOL.fullmatch(tool) is None:
        return Decision("refused", "tool_name")
    if tool not in card["offered"]:
        return Decision("refused", "not_named", name=tool)
    if tool not in card["accepted"]:
        card["accepted"].append(tool)
    return Decision("accepted", "owner_accepted", name=tool, tools_on=True)


def embed(book: Book, kind: str, name: str) -> Decision:
    del book, kind, name
    return Decision("refused", "not_embedded")


def note_receipt(book: Book, text: str) -> Decision:
    if not isinstance(text, str) or text.strip() == "":
        return Decision("refused", "empty")
    if credential_shape(text):
        return Decision("refused", "credential")
    book.receipts.append({"text": text, "category": "receipt"})
    return Decision("recorded", "receipt", said=text)


def _person(value: object) -> bool:
    return isinstance(value, str) and _PERSON.fullmatch(value) is not None


def _url_reason(value: object, resolved: Mapping[str, Sequence[str]] | None) -> str:
    if not isinstance(value, str) or "\\" in value or " " in value or credential_shape(value):
        return "url"
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
        return "url"
    if parsed.query or parsed.fragment or not parsed.hostname:
        return "url"
    host = parsed.hostname.rstrip(".").casefold()
    addresses, reason = _addresses(resolved, host)
    if reason:
        return reason
    vetted = vet_adopted(host, addresses)
    if vetted.outcome != "allowed":
        return vetted.reason
    if not _is_ip(host) and not addresses:
        return "resolved"
    return ""


def _addresses(
    resolved: Mapping[str, Sequence[str]] | None,
    host: str,
) -> tuple[tuple[str, ...], str]:
    if resolved is None:
        return (), ""
    if isinstance(resolved, (str, bytes)) or not isinstance(resolved, Mapping):
        return (), "resolved"
    found = None
    for item, value in resolved.items():
        if isinstance(item, str) and item.rstrip(".").casefold() == host:
            found = value
            break
    if found is None:
        return (), ""
    if isinstance(found, (str, bytes)) or not isinstance(found, (list, tuple)):
        return (), "resolved"
    if any(not isinstance(item, str) or item.strip() == "" for item in found):
        return (), "resolved"
    return tuple(found), ""


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True
