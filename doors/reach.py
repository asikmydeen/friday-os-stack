"""Decide what a door may reach.

A messaging adapter delivers a turn. It cannot approve, call the
executor, or read Postgres. A mesh peer opens the Board and the
authenticated MCP listener. Joining the mesh is not joining core. The
tunnel stays off. If a caller marks it enabled, the only target is the
Board, and only after an access check the owner verified. memory-mcp,
Qdrant, Postgres, taskrunner, Radarr, Sonarr, Prowlarr, and qBittorrent
are never publishable.

confirmed=true is ignored. This module does not listen and does not
open a socket.

remove_node decides a later cleanup. It does not delete a peer. While
Headscale is absent, an ephemeral name is skipped. A name other than
coder-<workspace> is refused, including a phone, a laptop, and a NAS.
Failed coder work is kept for three hours. A caller can name more
machines that must be kept.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

NON_PUBLISHABLE = frozenset({
    "memory-mcp",
    "qdrant",
    "postgres",
    "taskrunner",
    "radarr",
    "sonarr",
    "prowlarr",
    "qbittorrent",
})
MESH_OPEN = {
    "board": "board",
    "mcp": "mcp_listener",
}
PERMANENT = frozenset({"phone", "laptop", "nas"})
THREE_HOURS = 3 * 60 * 60
_CODER = re.compile(r"coder-[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")


@dataclass(frozen=True)
class Decision:
    outcome: str
    reason: str


def deliver(actor: str, *, confirmed: bool = False) -> Decision:
    del confirmed
    if actor.casefold() == "adapter":
        return Decision("delivered", "turn")
    return Decision("refused", "not_an_adapter")


def adapter_touch(target: str, *, confirmed: bool = False) -> Decision:
    del target, confirmed
    return Decision("refused", "adapter_cannot_approve")


def join_mesh() -> Decision:
    return Decision("joined", "not_core")


def mesh_open(service: str) -> Decision:
    reason = MESH_OPEN.get(service.casefold())
    if reason is None:
        return Decision("refused", "mesh_not_core")
    return Decision("allowed", reason)


def tunnel(
    *,
    enabled: bool = False,
    target: str = "board",
    access_checked: bool = False,
    confirmed: bool = False,
) -> Decision:
    del confirmed
    if enabled is not True:
        return Decision("off", "tunnel_off")
    name = target.casefold()
    if name in NON_PUBLISHABLE:
        return Decision("refused", "not_publishable")
    if name != "board":
        return Decision("refused", "board_only")
    if access_checked is not True:
        return Decision("refused", "access_unchecked")
    return Decision("allowed", "board")


def remove_node(
    name: str,
    *,
    mesh_on: bool = False,
    workspace_gone: bool = False,
    failed_at: int | None = None,
    now: int = 0,
    permanent: tuple[str, ...] = (),
    confirmed: bool = False,
) -> Decision:
    del confirmed
    blocked = PERMANENT | {item.casefold() for item in permanent}
    if name.casefold() in blocked or _CODER.fullmatch(name) is None:
        return Decision("refused", "permanent_peer")
    if mesh_on is not True:
        return Decision("skipped", "headscale_absent")
    if workspace_gone is not True:
        return Decision("kept", "workspace_still_here")
    if failed_at is not None:
        if (
            isinstance(failed_at, bool)
            or not isinstance(failed_at, int)
            or isinstance(now, bool)
            or not isinstance(now, int)
            or now - failed_at < THREE_HOURS
        ):
            return Decision("kept", "failed_work_kept")
    return Decision("remove", "coder_workspace_gone")
