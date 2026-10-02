"""Record one proposed wire. Nothing is installed.

An advisor records a draft for one app: that advisor, one method, one
path, and the tool names. Every tool stays off until the Board accepts
that name. Accepting one name does not accept another. The same advisor can revise that draft. Another advisor cannot replace
it. A new name stays off. A name the Board already accepted stays on
only when the revised draft still lists it. An acceptance on one app
does not turn the same name on for another app.

Chat cannot record a draft or accept a name, and that refusal leaves an
accepted name in place. The family role is not an advisor for this
draft. Host network, a network mode other than bridge, host PID, host
IPC, a privileged flag, a device, and a capability are refused, and
nothing is stored.

This module does not read catalog/wires, does not render Jinja, does
not write catalog/PIN, and does not open a URL. confirmed=true is
ignored. apply_proposal returns catalog_install_closed. Friday's ask
path does not call this module.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from memoryd.store import credential_shape
from netpolicy.paths import CORE_NAMES

ADVISORS = frozenset({
    "advisor",
    "architect",
    "backend",
    "buyer",
    "chief",
    "cfo",
    "coach",
    "content",
    "cto",
    "fetcher",
    "health",
    "home",
    "legal",
    "media",
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
METHODS = frozenset({"GET", "POST"})
_APP = re.compile(r"[a-z][a-z0-9-]{0,62}\Z")
_TOOL = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")
_PATH = re.compile(r"/[A-Za-z0-9._~/-]{0,200}\Z")


@dataclass(frozen=True)
class Decision:
    outcome: str
    reason: str
    app: str = ""
    advisor: str = ""
    tools: tuple[str, ...] = ()
    on: tuple[str, ...] = ()
    tools_on: bool = False
    method: str = ""
    path: str = ""
    level: str = ""
    listed: bool = False
    install: str = "refused"
    applied: bool = False
    started: bool = False
    jinja: bool = False
    pin_written: bool = False
    wires_read: bool = False
    approval: bool = False
    probed: bool = False


@dataclass(frozen=True)
class _Draft:
    advisor: str
    method: str
    path: str
    tools: tuple[str, ...]


class Book:
    def __init__(self) -> None:
        self.drafts: dict[str, _Draft] = {}
        self.accepted: dict[str, tuple[str, ...]] = {}

    def __repr__(self) -> str:
        return "Book()"


def propose_wire(
    book: Book,
    *,
    actor: str,
    app: str,
    advisor: str,
    method: str,
    path: str,
    tools: object,
    confirmed: bool = False,
    host_network: object = False,
    network_mode: object = "bridge",
    host_pid: object = False,
    pid_mode: object = "",
    host_ipc: object = False,
    ipc_mode: object = "",
    privileged: object = False,
    devices: object = (),
    capabilities: object = (),
) -> Decision:
    del confirmed
    reason = _unsafe(
        host_network,
        network_mode,
        host_pid,
        pid_mode,
        host_ipc,
        ipc_mode,
        privileged,
        devices,
        capabilities,
    )
    if reason:
        return _closed(reason)
    cleaned, reason = _fields(app, advisor, method, path, tools)
    if reason:
        return _closed(reason)
    app_id, advisor_id, verb, route, names = cleaned
    actor_id = actor.strip().casefold() if isinstance(actor, str) else ""
    if actor_id == "family" or advisor_id == "family":
        return _closed("family_blocked")
    if actor_id in {"chat", "board", "friday"} or actor_id != advisor_id:
        return _closed("actor_cannot_propose")
    if advisor_id not in ADVISORS:
        return _closed("advisor")
    existing = book.drafts.get(app_id)
    if existing is not None and existing.advisor != advisor_id:
        return _closed("not_that_advisor")
    previous = book.accepted.get(app_id, ())
    kept = tuple(name for name in previous if name in names)
    revised = app_id in book.drafts
    book.drafts[app_id] = _Draft(advisor_id, verb, route, names)
    book.accepted[app_id] = kept
    return _open(book, app_id, "revised" if revised else "proposed", tools_on=False)


def accept_tool(
    book: Book,
    actor: str,
    app: str,
    name: str,
    *,
    confirmed: bool = False,
) -> Decision:
    del confirmed
    app_id = _app(app)
    draft = book.drafts.get(app_id) if app_id else None
    if draft is None:
        return _closed("no_draft")
    kept = book.accepted.get(app_id, ())
    actor_id = actor.strip().casefold() if isinstance(actor, str) else ""
    if actor_id != "board":
        return _open(book, app_id, "actor_cannot_approve", outcome="refused", tools_on=False)
    if not isinstance(name, str) or name not in draft.tools:
        return _open(book, app_id, "not_offered", outcome="refused", tools_on=False)
    if name not in kept:
        kept = kept + (name,)
        book.accepted[app_id] = kept
    return _open(book, app_id, "owner_accepted", outcome="accepted", tools_on=True)


def tools_for(book: Book, app: str, role: str) -> Decision:
    role_id = role.strip().casefold() if isinstance(role, str) else ""
    if role_id == "family":
        return _closed("family_blocked")
    app_id = _app(app)
    draft = book.drafts.get(app_id) if app_id else None
    if draft is None:
        return _closed("no_draft")
    if role_id != draft.advisor:
        return _closed("not_that_advisor")
    return _open(book, app_id, "proposed")


def apply_proposal(book: Book, app: str = "", *, confirmed: bool = False) -> Decision:
    del confirmed
    app_id = _app(app)
    if app_id and app_id in book.drafts:
        decision = _open(book, app_id, "catalog_install_closed", outcome="refused")
        return Decision(
            "refused",
            "catalog_install_closed",
            app=decision.app,
            advisor=decision.advisor,
            tools=decision.tools,
            on=decision.on,
            tools_on=False,
            method=decision.method,
            path=decision.path,
            level="proposed",
            listed=True,
            install="refused",
            applied=False,
            started=False,
            probed=False,
        )
    return _closed("catalog_install_closed")


def _open(
    book: Book,
    app_id: str,
    reason: str,
    *,
    outcome: str = "recorded",
    tools_on: bool | None = None,
) -> Decision:
    draft = book.drafts[app_id]
    on = tuple(name for name in draft.tools if name in book.accepted.get(app_id, ()))
    shown = bool(on) if tools_on is None else tools_on
    return Decision(
        outcome,
        reason,
        app=app_id,
        advisor=draft.advisor,
        tools=draft.tools,
        on=on,
        tools_on=shown,
        method=draft.method,
        path=draft.path,
        level="proposed",
        listed=True,
        install="refused",
        applied=False,
        started=False,
        probed=False,
    )


def _closed(reason: str) -> Decision:
    return Decision("refused", reason)


def _unsafe(
    host_network: object,
    network_mode: object,
    host_pid: object,
    pid_mode: object,
    host_ipc: object,
    ipc_mode: object,
    privileged: object,
    devices: object,
    capabilities: object,
) -> str:
    if host_network is not False or network_mode == "host":
        return "host_network"
    if network_mode != "bridge":
        return "network_mode"
    if host_pid is not False or pid_mode == "host":
        return "host_pid"
    if pid_mode not in ("", "private"):
        return "pid_mode"
    if host_ipc is not False or ipc_mode == "host":
        return "host_ipc"
    if ipc_mode not in ("", "private"):
        return "ipc_mode"
    if privileged is not False:
        return "privileged"
    if _listed(devices):
        return "device_not_in_manifest"
    if _listed(capabilities):
        return "capability_not_in_manifest"
    return ""


def _fields(
    app: object,
    advisor: object,
    method: object,
    path: object,
    tools: object,
) -> tuple[tuple[str, str, str, str, tuple[str, ...]] | None, str]:
    if isinstance(app, str) and _secret(app):
        return None, "credential"
    if isinstance(advisor, str) and _secret(advisor):
        return None, "credential"
    if not isinstance(advisor, str):
        return None, "advisor"
    advisor_id = advisor.strip().casefold()
    app_id = _app(app)
    if app_id is None:
        return None, "app_id"
    if app_id in CORE_NAMES:
        return None, "core_closed"
    if not isinstance(method, str) or not isinstance(path, str):
        return None, "path"
    verb = method.strip().upper()
    route = path.strip()
    if _secret(app_id) or _secret(advisor_id) or _secret(verb) or _secret(route):
        return None, "credential"
    if _jinja(verb) or _jinja(route):
        return None, "jinja"
    if verb not in METHODS:
        return None, "method"
    if not _PATH.fullmatch(route) or ".." in route or "//" in route:
        return None, "path"
    names, reason = _tools(tools)
    if reason:
        return None, reason
    if advisor_id == "family":
        return None, "family_blocked"
    return (app_id, advisor_id, verb, route, names), ""


def _tools(value: object) -> tuple[tuple[str, ...] | None, str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, (tuple, list)):
        return None, "tool_name"
    found: list[str] = []
    for name in value:
        if not isinstance(name, str) or _secret(name):
            return None, "credential" if isinstance(name, str) and _secret(name) else "tool_name"
        if _jinja(name):
            return None, "jinja"
        if _TOOL.fullmatch(name) is None:
            return None, "tool_name"
        if name in found:
            continue
        found.append(name)
    if not found:
        return None, "tool_name"
    return tuple(found), ""


def _app(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    name = value.strip().casefold()
    if _secret(name) or _APP.fullmatch(name) is None:
        return None
    return name


def _secret(value: str) -> bool:
    return credential_shape(value)


def _jinja(value: str) -> bool:
    return "{{" in value or "{%" in value


def _listed(value: object) -> bool:
    if isinstance(value, str):
        return value != ""
    if isinstance(value, (tuple, list)):
        return len(value) > 0
    return value is not None
