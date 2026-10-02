"""Record a mesh pre-auth key. Do not call Headscale.

A phone or a laptop can have one key. The Board asks. The name comes
back. The value stays in this process. It is not shown, not written to
a file, and not placed on the environment. It is not the notify token.
A caller-supplied value is not stored. Chat cannot record one, and
that refusal leaves a key the Board already recorded.

Phone and laptop do not share a key. The key is not reused for a
coder machine, and it is not minted for one. An MCP endpoint on that
peer is a grant: an address, the key's name, a role, and tool names.
Tools stay off until the Board accepts that name. Accepting one name
does not accept another. A filesystem, a USB device, host networking,
and the Docker socket are refused and nothing is attached.

A second record keeps the first value. A 64-character lowercase hex
value is the generated key. Any other credential-shaped draw is not
stored. This module does not open a socket and does not start the
mesh. Friday's ask path does not call it.
"""

from __future__ import annotations

import hmac
import ipaddress
import re
import threading
from dataclasses import dataclass

from memoryd.store import credential_shape

PEERS = {"phone": "MESH_PREAUTH_PHONE", "laptop": "MESH_PREAUTH_LAPTOP"}
MOUNTS = frozenset({"filesystem", "disk", "usb", "host_network", "docker_socket"})
CORE = frozenset({
    "postgres",
    "qdrant",
    "memory-mcp",
    "friday",
    "executor",
    "board",
    "webhooks",
    "gateway",
    "ollama",
    "taskrunner",
})
KEPT = "The password is kept outside the machine"
_HEX = frozenset("0123456789abcdef")
_CODER = re.compile(r"coder-[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
_ROLE = re.compile(r"[a-z][a-z0-9_-]{0,31}\Z")
_TOOL = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")
_HOST = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?\Z")


@dataclass(frozen=True)
class Decision:
    outcome: str
    reason: str
    name: str = ""
    started: bool = False
    joined: bool = False
    called: bool = False


class Book:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._values: dict[str, str] = {}
        self._grants: dict[str, dict] = {}

    def __repr__(self) -> str:
        return "Book()"


def record_key(
    book: Book,
    peer: object,
    *,
    actor: str,
    rng,
    supplied: object = None,
    notify_token: object = "",
    confirmed: bool = False,
) -> Decision:
    del confirmed
    canonical, reason = _canonical(peer)
    if reason:
        return _no(reason)
    label = PEERS[canonical]
    if actor != "board":
        return _named("refused", "board_only", label if _has(book, canonical) else "")
    if _has(book, canonical):
        return _keep_key(supplied, label)
    if _leaked(supplied):
        return _no("credential")
    supplied_reason = _supplied(supplied)
    if supplied_reason:
        return _no(supplied_reason, name=label)
    notify = notify_token if isinstance(notify_token, str) else ""
    with book._lock:
        if canonical in book._values:
            return _named("recorded", "name_only", label)
        blocked = [notify] if notify else []
        for other, value in book._values.items():
            if other != canonical and value:
                blocked.append(value)
        value = _mint(rng, tuple(blocked))
        if value is None:
            return _no("not_minted", name=label)
        book._values[canonical] = value
    return _named("recorded", "name_only", label)


def show(book: Book, peer: object) -> Decision:
    canonical, reason = _canonical(peer)
    if reason == "credential":
        return _no("credential")
    if reason or not _has(book, canonical):
        return _no("unknown_secret")
    return _named("refused", "value_hidden", PEERS[canonical])


def names(book: Book) -> tuple[str, ...]:
    with book._lock:
        held = set(book._values)
    return tuple(PEERS[peer] for peer in ("phone", "laptop") if peer in held)


def matches(book: Book, peer: object, header: object) -> bool:
    if not isinstance(peer, str) or not isinstance(header, str) or header == "":
        return False
    canonical = peer.casefold()
    if canonical not in PEERS:
        return False
    with book._lock:
        secret = book._values.get(canonical)
    if not isinstance(secret, str) or secret == "":
        return False
    try:
        return hmac.compare_digest(secret, header)
    except (TypeError, ValueError):
        return False


def for_machine(book: Book, name: object) -> Decision:
    if _leaked(name):
        return _no("credential")
    canonical, reason = _canonical(name)
    if reason == "not_reused":
        return _no("not_reused")
    if reason:
        return _no(reason)
    if not _has(book, canonical):
        return _no("no_key")
    return _named("recorded", "name_only", PEERS[canonical])


def attach(
    book: Book,
    *,
    actor: str,
    peer: object,
    kind: object,
    confirmed: bool = False,
) -> Decision:
    del actor, confirmed, book
    if _leaked(peer) or _leaked(kind):
        return _no("credential")
    if isinstance(kind, str) and kind.casefold() in MOUNTS:
        return _no("mount_refused")
    return _no("not_a_mount")


def grant_endpoint(
    book: Book,
    peer: object,
    *,
    actor: str,
    address: object,
    role: object,
    tools: object,
    supplied: object = None,
    secret_ref: object = None,
    host_network: object = False,
    network_mode: object = "bridge",
    device: object = "",
    confirmed: bool = False,
) -> Decision:
    del confirmed
    canonical, reason = _canonical(peer)
    if reason:
        return _no(reason)
    label = PEERS[canonical]
    leaked = _grant_leaked(None, address, role, tools, supplied, secret_ref, device)
    if leaked and _grant(book, canonical) is not None and actor == "board":
        return _named("recorded", "name_only", label)
    if leaked:
        return _no("credential")
    if _mounted(address, host_network, network_mode, device):
        return _no("mount_refused", name=label if _has(book, canonical) else "")
    if actor != "board":
        return _named("refused", "board_only", label if _has(book, canonical) else "")
    if not _has(book, canonical):
        return _no("no_key", name=label)
    if _grant(book, canonical) is not None:
        return _keep_grant(label, address, role, tools, supplied, secret_ref)
    problem = _supplied(supplied) or _supplied(secret_ref)
    if problem:
        return _no(problem, name=label)
    text, problem = _address(address)
    if problem:
        return _no(problem, name=label)
    role_text, problem = _role(role)
    if problem:
        return _no(problem, name=label)
    tool_names, problem = _tools(tools)
    if problem:
        return _no(problem, name=label)
    with book._lock:
        if canonical in book._grants:
            return _named("recorded", "name_only", label)
        book._grants[canonical] = {
            "address": text,
            "role": role_text,
            "tools": tool_names,
            "accepted": set(),
        }
    return _named("recorded", "name_only", label)


def accept_tool(
    book: Book,
    *,
    actor: str,
    peer: object,
    name: object,
    confirmed: bool = False,
) -> Decision:
    del confirmed
    if _leaked(name):
        return _no("credential")
    canonical, reason = _canonical(peer)
    if reason:
        return _no(reason)
    label = PEERS[canonical]
    grant = _grant(book, canonical)
    if grant is None:
        if actor != "board":
            return _named("refused", "board_only", label if _has(book, canonical) else "")
        return _no("no_grant", name=label if _has(book, canonical) else "")
    if actor != "board":
        return _named("refused", "board_only", label)
    if not isinstance(name, str) or _TOOL.fullmatch(name) is None:
        return _named("refused", "tool_name", label)
    with book._lock:
        current = book._grants.get(canonical)
        if current is None or name not in current["tools"]:
            return _named("refused", "not_listed", label)
        current["accepted"].add(name)
    return _named("accepted", "owner_accepted", name)


def endpoint(book: Book, peer: object) -> tuple[str, str, str]:
    canonical, reason = _canonical(peer)
    if reason:
        return ("", "", "")
    grant = _grant(book, canonical)
    if grant is None:
        return ("", "", "")
    return (grant["address"], PEERS[canonical], grant["role"])


def tools_of(book: Book, peer: object) -> tuple[tuple[str, str], ...]:
    canonical, reason = _canonical(peer)
    if reason:
        return ()
    grant = _grant(book, canonical)
    if grant is None:
        return ()
    accepted = grant["accepted"]
    return tuple((name, "on" if name in accepted else "off") for name in grant["tools"])


def _keep_key(supplied: object, label: str) -> Decision:
    reason = _supplied(supplied)
    if reason == "credential":
        return _named("recorded", "name_only", label)
    if reason:
        return _named("refused", reason, label)
    return _named("recorded", "name_only", label)


def _keep_grant(label, address, role, tools, supplied, secret_ref) -> Decision:
    problem = _supplied(supplied) or _supplied(secret_ref)
    if problem == "credential":
        return _named("recorded", "name_only", label)
    if problem:
        return _named("refused", problem, label)
    _text, problem = _address(address)
    if problem == "credential":
        return _named("recorded", "name_only", label)
    if problem:
        return _named("refused", problem, label)
    _role_text, problem = _role(role)
    if problem:
        return _named("refused", problem, label)
    _names, problem = _tools(tools)
    if problem:
        return _named("refused", problem, label)
    return _named("recorded", "name_only", label)


def _canonical(peer: object) -> tuple[str, str]:
    if not isinstance(peer, str) or peer == "" or peer != peer.strip() or "\n" in peer or "\r" in peer:
        return "", "peer_name"
    if _leaked(peer):
        return "", "credential"
    if _CODER.fullmatch(peer) is not None or _CODER.fullmatch(peer.casefold()) is not None:
        return "", "not_reused"
    folded = peer.casefold()
    if folded not in PEERS:
        return "", "not_a_peer"
    return folded, ""


def _leaked(value: object) -> bool:
    return isinstance(value, str) and value != KEPT and value != "" and credential_shape(value)


def _grant_leaked(peer, address, role, tools, supplied, secret_ref, device) -> bool:
    if any(_leaked(value) for value in (peer, address, role, supplied, secret_ref, device)):
        return True
    if isinstance(tools, str):
        return _leaked(tools)
    if isinstance(tools, (list, tuple)):
        return any(_leaked(item) for item in tools)
    return False


def _supplied(value: object) -> str:
    if value is None or value == "":
        return ""
    if _leaked(value):
        return "credential"
    return "caller_value"


def _mounted(address, host_network, network_mode, device) -> bool:
    if host_network is not False or network_mode != "bridge" or device != "":
        return True
    return isinstance(address, str) and _mount_text(address)


def _mount_text(value: str) -> bool:
    if value == KEPT:
        return False
    folded = value.casefold()
    if folded.startswith("/") or folded.startswith("file:") or folded.startswith("usb:"):
        return True
    return "docker.sock" in folded or "/dev/" in folded


def _address(value: object) -> tuple[str, str]:
    if not isinstance(value, str) or value.strip() == "" or "\n" in value or "\r" in value:
        return "", "address"
    if value == KEPT:
        return value, ""
    if _leaked(value):
        return "", "credential"
    if _mount_text(value):
        return "", "mount_refused"
    if value != value.strip() or any(char in value for char in " \t?#") or len(value) > 256:
        return "", "address"
    if value.startswith("https://"):
        rest = value[8:]
    elif value.startswith("http://"):
        rest = value[7:]
    else:
        return "", "address"
    if rest == "" or rest.startswith("/"):
        return "", "address"
    authority = rest.split("/", 1)[0]
    if authority == "" or "@" in authority:
        return "", "address"
    host = _host(authority)
    if host is None:
        return "", "address"
    reason = _host_reason(host)
    if reason:
        return "", reason
    return value, ""


def _host(authority: str) -> str | None:
    if authority.startswith("["):
        end = authority.find("]")
        if end < 2:
            return None
        rest = authority[end + 1:]
        if rest and not re.fullmatch(r":[0-9]{1,5}", rest):
            return None
        if rest and not 1 <= int(rest[1:]) <= 65535:
            return None
        return authority[1:end]
    if authority.count(":") > 1:
        return None
    host, sep, port = authority.partition(":")
    if host == "":
        return None
    if sep:
        if not port.isdigit() or not 1 <= int(port) <= 65535:
            return None
    return host


def _host_reason(host: str) -> str:
    folded = host.casefold().rstrip(".")
    if folded in {"localhost", "localhost.localdomain"} or folded.endswith(".localhost"):
        return "loopback"
    if folded in CORE:
        return "not_core"
    try:
        ip = ipaddress.ip_address(folded)
    except ValueError:
        if _HOST.fullmatch(host) is None or host.replace(".", "").isdigit():
            return "address"
        return ""
    if ip.is_loopback or ip.is_unspecified:
        return "loopback"
    if ip.is_link_local:
        return "link_local"
    if ip.is_multicast or ip.is_reserved:
        return "address"
    return ""


def _role(value: object) -> tuple[str, str]:
    if value == KEPT:
        return KEPT, ""
    if not isinstance(value, str) or _ROLE.fullmatch(value) is None:
        return "", "role"
    if _leaked(value):
        return "", "credential"
    return value, ""


def _tools(value: object) -> tuple[tuple[str, ...], str]:
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        return (), "tool_list"
    found: list[str] = []
    for item in value:
        if not isinstance(item, str) or _TOOL.fullmatch(item) is None:
            return (), "tool_name"
        if _leaked(item):
            return (), "credential"
        if item not in found:
            found.append(item)
    return tuple(found), ""


def _has(book: Book, peer: str) -> bool:
    with book._lock:
        return peer in book._values


def _grant(book: Book, peer: str) -> dict | None:
    with book._lock:
        grant = book._grants.get(peer)
        if grant is None:
            return None
        return {
            "address": grant["address"],
            "role": grant["role"],
            "tools": grant["tools"],
            "accepted": set(grant["accepted"]),
        }


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


def _named(outcome: str, reason: str, name: str) -> Decision:
    return Decision(outcome, reason, name=name, started=False, joined=False, called=False)


def _no(reason: str, *, outcome: str = "refused", name: str = "") -> Decision:
    return Decision(outcome, reason, name=name, started=False, joined=False, called=False)
