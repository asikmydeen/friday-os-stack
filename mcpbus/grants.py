"""Decide which tools a prompt may see, and which calls wait.

The visible set is the intersection of the names the owner granted and
the names the server offered. Anything else stays out of the prompt.
An inbound mutating call waits for the Board. This function does not
create an approval. A catalog wire is one kind of grant and stays off
until the owner accepts it on the Board.

A connection grant names one server, one secret reference, one role,
and the tool names that role may see. Those names stay out of the
prompt until the Board accepts each one. A secret value is not stored.
Chat cannot record or accept one, and that refusal leaves a grant
already recorded. A second record for the same server keeps the first.
The server is not called.

confirmed=true is ignored. This module does not open a listener.
Friday's ask path does not call it.
"""

from __future__ import annotations

import ipaddress
import re
import threading
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import unquote_plus, urlsplit

from memoryd.store import credential_shape
from netpolicy.paths import CORE_NAMES, METADATA_HOST

MUTATING = frozenset({
    "send",
    "pay",
    "delete",
    "publish",
    "install",
    "uninstall",
    "grant",
    "backup",
    "publish_port",
    "publish_hostname",
    "start",
    "stop",
    "pull",
    "disconnect",
    "upgrade",
})


@dataclass(frozen=True)
class Decision:
    outcome: str
    reason: str


def _names(values: Iterable[str]) -> set[str]:
    return {str(value) for value in values}


def visible(granted: Iterable[str], offered: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(_names(granted) & _names(offered)))


def inbound(
    tool: str,
    granted: Iterable[str],
    offered: Iterable[str],
    *,
    confirmed: bool = False,
) -> Decision:
    del confirmed
    if tool not in visible(granted, offered):
        return Decision("refused", "not_in_prompt")
    if tool in MUTATING:
        return Decision("waiting", "board_must_approve")
    return Decision("allowed", "granted_tool")


def accept_tool(actor: str, tool: str, *, confirmed: bool = False) -> Decision:
    del tool, confirmed
    if actor != "board":
        return Decision("refused", "actor_cannot_approve")
    return Decision("accepted", "owner_accepted")


def wire_as_grant(*, accepted: bool, actor: str = "board") -> Decision:
    if accepted is True and actor == "board":
        return Decision("granted", "accepted")
    return Decision("off", "awaiting_acceptance")


ROLES = frozenset({"friday", "chief", "cto", "cfo", "coach", "home", "media"})
KEPT = "The password is kept outside the machine"
_CLOSED = CORE_NAMES | frozenset({"webhooks", "taskrunner"})
_ROLE = re.compile(r"[a-z][a-z0-9_-]{0,31}\Z")
_TOOL = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")
_REF = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}\Z")


@dataclass(frozen=True)
class Connection:
    outcome: str
    reason: str
    server: str = ""
    role: str = ""
    secret_ref: str = ""
    prompt: tuple[str, ...] = ()
    started: bool = False
    called: bool = False


class GrantBook:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: dict[str, dict] = {}

    def __repr__(self) -> str:
        return "GrantBook()"


def record_grant(
    book: GrantBook,
    *,
    actor: str,
    server: object,
    role: object,
    tools: object,
    secret_ref: object,
    secret: object = None,
    value: object = None,
    token: object = None,
    password: object = None,
    confirmed: bool = False,
) -> Connection:
    """Store one grant. The prompt stays empty until each tool is accepted."""
    del confirmed
    leaked = _supplied(secret) or _supplied(value) or _supplied(token) or _supplied(password)
    if leaked == "credential" or _leaked(server) or _leaked(role) or _leaked(secret_ref) or _leaked_tools(tools):
        return _quiet("credential")
    if actor != "board":
        return _quiet("actor_cannot_approve")
    if leaked:
        return _quiet(leaked)
    url, reason = _server(server)
    if reason:
        return _quiet(reason)
    chosen, reason = _role(role)
    if reason:
        return _quiet(reason)
    named, reason = _tools(tools)
    if reason:
        return _quiet(reason)
    ref, reason = _ref(secret_ref)
    if reason:
        return _quiet(reason)
    with book._lock:
        held = book._rows.get(url)
        if held is not None:
            return _from(held, "kept")
        book._rows[url] = {
            "server": url,
            "role": chosen,
            "secret_ref": ref,
            "tools": named,
            "accepted": [],
        }
        return _from(book._rows[url], "prompt")


def accept_grant_tool(
    book: GrantBook,
    *,
    actor: str,
    server: object,
    tool: object,
    confirmed: bool = False,
) -> Connection:
    """Accept one named tool into that role's prompt. Do not call it."""
    del confirmed
    if _leaked(server) or _leaked(tool):
        return _quiet("credential")
    if actor != "board":
        return _quiet("actor_cannot_approve")
    url, reason = _server(server)
    if reason:
        return _quiet(reason)
    name, reason = _one_tool(tool)
    if reason:
        return _quiet(reason)
    with book._lock:
        held = book._rows.get(url)
        if held is None:
            return _quiet("unknown_server")
        if name not in held["tools"]:
            return _from(held, "not_offered", outcome="refused")
        if name not in held["accepted"]:
            held["accepted"].append(name)
        return _from(held, "owner_accepted", outcome="accepted")


def prompt_for(book: GrantBook, server: object, role: object) -> tuple[str, ...]:
    """Accepted names for this server and role. Anything else stays out."""
    if not isinstance(server, str) or not isinstance(role, str):
        return ()
    with book._lock:
        held = book._rows.get(server)
        if held is None or held["role"] != role:
            return ()
        return tuple(sorted(held["accepted"]))


def _from(row: dict, reason: str, *, outcome: str = "recorded") -> Connection:
    return Connection(
        outcome,
        reason,
        server=row["server"],
        role=row["role"],
        secret_ref=row["secret_ref"],
        prompt=tuple(sorted(row["accepted"])),
        started=False,
        called=False,
    )


def _quiet(reason: str) -> Connection:
    return Connection("refused", reason, started=False, called=False)


def _leaked(value: object) -> bool:
    return isinstance(value, str) and value not in {"", KEPT} and _hidden(value)


def _leaked_tools(value: object) -> bool:
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        return False
    return any(_leaked(item) for item in value)


def _supplied(value: object) -> str:
    if value is None or value == "" or value == KEPT:
        return ""
    if isinstance(value, str) and _hidden(value):
        return "credential"
    return "caller_value"


def _hidden(text: str) -> bool:
    seen = text
    for _ in range(3):
        if credential_shape(seen):
            return True
        decoded = unquote_plus(seen)
        if decoded == seen:
            return False
        seen = decoded
    return credential_shape(seen)


def _role(value: object) -> tuple[str, str]:
    if isinstance(value, str) and value == "family":
        return "", "family_blocked"
    if isinstance(value, str) and value in ROLES and _ROLE.fullmatch(value):
        return value, ""
    return "", "role_name"


def _ref(value: object) -> tuple[str, str]:
    if isinstance(value, str) and _REF.fullmatch(value):
        return value, ""
    return "", "secret_ref"


def _tools(value: object) -> tuple[tuple[str, ...], str]:
    if isinstance(value, str) or not isinstance(value, (list, tuple)) or not value or len(value) > 8:
        return (), "tool_name"
    names: list[str] = []
    for item in value:
        name, reason = _one_tool(item)
        if reason:
            return (), reason
        if name not in names:
            names.append(name)
    return tuple(names), ""


def _one_tool(value: object) -> tuple[str, str]:
    if isinstance(value, str) and _TOOL.fullmatch(value):
        return value, ""
    return "", "tool_name"


def _server(value: object) -> tuple[str, str]:
    if not isinstance(value, str):
        return "", "url"
    if (
        value != value.strip()
        or value == ""
        or "\n" in value
        or "\r" in value
        or " " in value
        or "%" in value
        or len(value) > 256
    ):
        return "", "url"
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or parts.username or parts.password or "@" in value:
        return "", "url"
    if parts.query or parts.fragment or not parts.hostname:
        return "", "url"
    reason = _host(parts.hostname)
    if reason:
        return "", reason
    return value, ""


def _host(host: str) -> str:
    text = host.strip().casefold().rstrip(".")
    if text in _CLOSED:
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
