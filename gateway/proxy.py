"""Allow only the method and path a wire health URL names.

Webhook targets are not advisor calls. A core name is dropped even when
a file mentions it. This module does not open a socket and does not
mint an approval.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from netpolicy.paths import CORE_NAMES

CLOSED_HOSTS = CORE_NAMES | frozenset({"webhooks"})
_URL = re.compile(r"http://([A-Za-z0-9.-]+):([0-9]+)(/[^\s,#]*)")


@dataclass(frozen=True)
class Allow:
    method: str
    host: str
    port: int
    path: str


def allows_from_text(text: str) -> tuple[Allow, ...]:
    found: list[Allow] = []
    lines = text.splitlines()
    for index, raw in enumerate(lines):
        body = raw.split("#", 1)[0]
        if re.search(r"health:\s*\{", body) and "url:" in body:
            _add(found, body)
            continue
        if re.search(r"^\s*health:\s*$", body):
            for follow in lines[index + 1 : index + 8]:
                nxt = follow.split("#", 1)[0]
                if "url:" in nxt:
                    _add(found, nxt)
                    break
                if nxt.strip() and not nxt.startswith((" ", "\t")):
                    break
    return tuple(found)


def allows_from_dir(directory: Path) -> tuple[Allow, ...]:
    found: list[Allow] = []
    seen: set[Allow] = set()
    for path in sorted(directory.glob("*.yml")):
        for allow in allows_from_text(path.read_text(encoding="utf-8")):
            if allow in seen:
                continue
            seen.add(allow)
            found.append(allow)
    return tuple(found)


def split_call(path: str) -> tuple[str, str] | None:
    if not path.startswith("/") or "?" in path or "#" in path or ".." in path or "\\" in path:
        return None
    rest = path[1:]
    if "/" not in rest:
        return None
    host, upstream = rest.split("/", 1)
    host = host.casefold()
    if not host or host in CLOSED_HOSTS:
        return None
    return host, "/" + upstream


def match(method: str, path: str, allows: tuple[Allow, ...]) -> Allow | None:
    if method.upper() != "GET":
        return None
    parsed = split_call(path)
    if parsed is None:
        return None
    host, upstream = parsed
    for allow in allows:
        if allow.method == "GET" and allow.host == host and allow.path == upstream:
            return allow
    return None


def _add(found: list[Allow], text: str) -> None:
    located = _URL.search(text)
    if located is None:
        return
    host = located.group(1).casefold().rstrip(".")
    if host in CLOSED_HOSTS:
        return
    port = int(located.group(2))
    if port <= 0:
        return
    path = located.group(3) or "/"
    found.append(Allow("GET", host, port, path))
