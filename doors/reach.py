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
"""

from __future__ import annotations

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
