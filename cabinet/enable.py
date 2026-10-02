"""Record one inactive charter. Do not copy it into place.

The full pack under charters/full stays inactive. The Board can record
one of those names. The only target kept is the relative link
full/<id>.md. The file is not copied and the link is not created.
Family stays blocked. A starter charter is already active. An absolute
path, a path that leaves that link, and a mount pointed at the full
pack are refused and nothing new is stored. A second record keeps the
first link. A credential-shaped name is not stored, including a
percent-encoded or plus-encoded copy.

Chat cannot record one, and that refusal leaves a link already
recorded. confirmed=true is ignored. This module does not write a file,
does not create role_profile or family_shared, and does not start
taskrunner. The Board page records the same link in its own process
and does not call this module. Friday's ask path does not call it.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from urllib.parse import unquote_plus

from memoryd.store import credential_shape

STARTER = frozenset({"chief", "cto", "cfo", "coach", "home", "media"})
FULL_PACK = frozenset({
    "advisor",
    "architect",
    "backend",
    "buyer",
    "content",
    "faith",
    "family",
    "fetcher",
    "health",
    "legal",
    "mentor",
    "mobile",
    "product",
    "program",
    "researcher",
    "reviewer",
    "shopper",
    "tester",
    "travel",
    "web",
})
BLOCKED = frozenset({"family"})
_FULL_MOUNTS = frozenset({
    "full",
    "./full",
    "charters/full",
    "./charters/full",
    "/soul/agents/full",
    "charters/full/",
    "./charters/full/",
    "/soul/agents/full/",
})


@dataclass(frozen=True)
class Decision:
    outcome: str
    reason: str
    role: str = ""
    target: str = ""
    copied: bool = False
    linked: bool = False
    started: bool = False
    created: bool = False
    job_cap: int = 0


class Book:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._links: dict[str, str] = {}

    def __repr__(self) -> str:
        return "Book()"


def enable_role(
    book: Book,
    *,
    actor: object,
    role: object,
    target: object = None,
    mount: object = None,
    confirmed: bool = False,
) -> Decision:
    """Record the relative link. Copy nothing."""
    del confirmed
    if actor != "board":
        return _quiet("board_only")
    name, reason = _role(role)
    if reason:
        return _quiet(reason)
    if name in book._links:
        return _from(book, name, "already")
    if name in STARTER:
        return _quiet("already_active")
    if name in BLOCKED:
        return _quiet("family_blocked")
    if name not in FULL_PACK:
        return _quiet("unknown_role")
    mount_reason = _mount(mount)
    if mount_reason:
        return _quiet(mount_reason)
    link, reason = _target(name, target)
    if reason:
        return _quiet(reason)
    with book._lock:
        if name not in book._links:
            book._links[name] = link
    return _from(book, name, "not_copied")


def links(book: Book) -> tuple[tuple[str, str], ...]:
    with book._lock:
        return tuple(sorted(book._links.items()))


def _from(book: Book, role: str, reason: str) -> Decision:
    with book._lock:
        target = book._links.get(role, "")
    return Decision(
        "recorded",
        reason,
        role=role,
        target=target,
        copied=False,
        linked=False,
        started=False,
        created=False,
        job_cap=0,
    )


def _quiet(reason: str) -> Decision:
    return Decision(
        "refused",
        reason,
        copied=False,
        linked=False,
        started=False,
        created=False,
        job_cap=0,
    )


def _role(value: object) -> tuple[str, str]:
    if not isinstance(value, str):
        return "", "role_name"
    if _hidden(value):
        return "", "credential"
    if value == "" or value != value.strip() or "\n" in value or len(value) > 32:
        return "", "role_name"
    if not value.isascii() or not value[0].islower():
        return "", "role_name"
    if not all(part.isalnum() or part in {"_", "-"} for part in value):
        return "", "role_name"
    return value, ""


def _mount(value: object) -> str:
    if value is None or value == "":
        return ""
    if not isinstance(value, str):
        return "mount_closed"
    if _hidden(value):
        return "credential"
    text = value.strip()
    if text in _FULL_MOUNTS:
        return "drops_starter_set"
    return "mount_closed"


def _target(role: str, value: object) -> tuple[str, str]:
    link = f"full/{role}.md"
    if value is None or value == "":
        return link, ""
    if not isinstance(value, str):
        return "", "outside_mount"
    if _hidden(value):
        return "", "credential"
    if value != value.strip() or "\n" in value or "\\" in value or ".." in value:
        return "", "outside_mount"
    if value.startswith("/"):
        return "", "absolute_path"
    if value != link:
        return "", "outside_mount"
    return link, ""


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
