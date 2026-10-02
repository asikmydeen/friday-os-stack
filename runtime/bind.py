"""Choose the address a process listens on.

BIND_HOST=core means the address this container uses to reach CORE_PEER.
On the image compose that peer is Postgres, which is on core only, so the
socket is the core address. The same container's address on apps has no
listener. Any other BIND_HOST is used as written, including 0.0.0.0.
"""

from __future__ import annotations

import socket
import time
from collections.abc import Callable, Mapping

Resolve = Callable[[str], str]
Pause = Callable[[float], None]


def bind_host(
    env: Mapping[str, str],
    *,
    resolve: Resolve | None = None,
    attempts: int = 20,
    pause: Pause | None = None,
) -> str:
    host = env.get("BIND_HOST") or "0.0.0.0"
    if host != "core":
        return host
    peer = env.get("CORE_PEER") or "postgres"
    return facing_address(peer, resolve=resolve, attempts=attempts, pause=pause)


def facing_address(
    peer: str,
    *,
    resolve: Resolve | None = None,
    attempts: int = 20,
    pause: Pause | None = None,
) -> str:
    lookup = resolve or udp_facing
    wait = pause or time.sleep
    if attempts < 1:
        raise OSError("core_address")
    for attempt in range(attempts):
        address = ""
        try:
            found = lookup(peer)
        except OSError:
            found = ""
        if isinstance(found, str):
            address = found
        if address and not address.startswith("127."):
            return address
        if attempt + 1 < attempts:
            wait(0.25)
    raise OSError("core_address")


def udp_facing(peer: str) -> str:
    """Local IPv4 used to reach peer. A UDP connect assigns that address and sends nothing."""
    try:
        infos = socket.getaddrinfo(peer, 9, socket.AF_INET, socket.SOCK_DGRAM)
    except socket.gaierror as exc:
        raise OSError("core_address") from exc
    if not infos:
        raise OSError("core_address")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(infos[0][4])
        address = sock.getsockname()[0]
    finally:
        sock.close()
    if not isinstance(address, str) or not address:
        raise OSError("core_address")
    return address
