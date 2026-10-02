"""Decide an advisor's tools, job cap, and secret names.

The candidate tools are the charter's `tools` list minus `deny_tools`.
A candidate is on only after the Board accepts that name, so a code
upgrade that adds a name does not turn it on. A tool the charter does
not name is shown and stays off until the Board accepts it. A new name
does not keep an older acceptance. Accepting a name does not create an
approval and does not run the tool.

Job cap starts at 0. It stays 0 while the caller says the code profile
is off, and that record clears every role. The Board may record a cap
from 0 to 3 when that profile is on.
The record does not start taskrunner. A durable home would be named
`agent-<role>` and is not created. A job would be named `tr-<task>`
and is not created either.

A secret slot stores a value and returns the name only. The only
collection this cut records is `cabinet_working`.

confirmed=true is ignored. This module does not read the environment,
does not start a container, and does not write a file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

ENGINES = frozenset({"claude-code", "gsd"})
_ROLE = re.compile(r"[a-z][a-z0-9_-]{0,31}\Z")
_TOOL = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")
_TASK = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
_SECRET = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}\Z")
_COLLECTION = "cabinet_working"


@dataclass(frozen=True)
class Decision:
    outcome: str
    reason: str
    name: str = ""
    cap: int | None = None
    started: bool = False


@dataclass(frozen=True)
class Tool:
    name: str
    state: str


@dataclass(frozen=True)
class Advisor:
    id: str
    name: str
    job_cap: int
    tools: tuple[Tool, ...]


def _role(value: object) -> bool:
    return isinstance(value, str) and _ROLE.fullmatch(value) is not None


def _tool(value: object) -> bool:
    return isinstance(value, str) and _TOOL.fullmatch(value) is not None


def _items(value: str) -> tuple[str, ...] | None:
    text = value.strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    if text == "":
        return ()
    found: list[str] = []
    for part in text.split(","):
        name = part.strip().strip("\"'")
        if not _tool(name):
            return None
        if name not in found:
            found.append(name)
    return tuple(found)


def _front(text: str) -> dict[str, str]:
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}
    meta: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip()
    return meta


def charter_tools(text: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return (tools, deny). An unreadable list fails closed to nothing on."""
    meta = _front(text)
    tools = _items(meta["tools"]) if "tools" in meta else ()
    deny = _items(meta["deny_tools"]) if "deny_tools" in meta else ()
    if tools is None or deny is None:
        return (), ()
    return tools, deny


def effective(tools: Iterable[str], deny: Iterable[str]) -> tuple[str, ...]:
    denied = {item for item in deny if _tool(item)}
    found: list[str] = []
    for name in tools:
        if _tool(name) and name not in denied and name not in found:
            found.append(name)
    return tuple(found)


class Config:
    def __init__(self) -> None:
        self._caps: dict[str, int] = {}
        self._code_on = False
        self._durable: dict[str, bool] = {}
        self._baseline: dict[str, set[str]] = {}
        self._extra: dict[str, set[str]] = {}
        self._secrets: dict[tuple[str, str], str] = {}
        self._engines: dict[str, tuple[str, int]] = {}
        self._collections: dict[str, tuple[str, ...]] = {}

    def __repr__(self) -> str:
        return "Config()"

    def cap(self, role: str) -> int:
        if not _role(role) or self._code_on is not True:
            return 0
        return self._caps.get(role, 0)

    def advisors(self, directory: Path) -> tuple[Advisor, ...]:
        if not directory.is_dir():
            return ()
        found: list[Advisor] = []
        for path in sorted(directory.glob("*.md")):
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            meta = _front(text)
            role = meta.get("id") or path.stem
            if not _role(role):
                continue
            tools, deny = charter_tools(text)
            label = meta.get("name") or role
            found.append(Advisor(role, label, self.cap(role), self.shelf(role, tools, deny, ())))
        found.sort(key=lambda item: item.id)
        return tuple(found)

    def shelf(
        self,
        role: str,
        tools: Iterable[str],
        deny: Iterable[str],
        offered: Iterable[str],
    ) -> tuple[Tool, ...]:
        if not _role(role):
            return ()
        named = [name for name in tools if _tool(name)]
        extras = [name for name in offered if _tool(name)]
        denied = {item for item in deny if _tool(item)}
        accepted = self._baseline.get(role, set()) | self._extra.get(role, set())
        rows: list[Tool] = []
        seen: set[str] = set()
        for name in named + sorted(set(extras) - set(named)):
            if name in seen:
                continue
            seen.add(name)
            on = name not in denied and name in accepted
            rows.append(Tool(name, "on" if on else "off"))
        return tuple(rows)

    def accept(
        self,
        actor: str,
        role: str,
        tool: str,
        *,
        tools: Iterable[str],
        deny: Iterable[str],
        offered: Iterable[str] = (),
        confirmed: bool = False,
    ) -> Decision:
        del confirmed
        if actor != "board":
            return Decision("refused", "actor_cannot_approve", name=tool if _tool(tool) else "")
        if not _role(role) or not _tool(tool):
            return Decision("refused", "tool_name")
        denied = {item for item in deny if _tool(item)}
        if tool in denied:
            return Decision("refused", "denied", name=tool)
        if tool in {name for name in tools if _tool(name)}:
            self._baseline.setdefault(role, set()).add(tool)
            return Decision("accepted", "owner_accepted", name=tool)
        if tool in {name for name in offered if _tool(name)}:
            self._extra.setdefault(role, set()).add(tool)
            return Decision("accepted", "owner_accepted", name=tool)
        return Decision("refused", "not_offered", name=tool)

    def set_cap(
        self,
        actor: str,
        role: str,
        cap: int,
        *,
        code_on: bool = False,
        confirmed: bool = False,
    ) -> Decision:
        del confirmed
        if not _role(role):
            return Decision("refused", "role_name", cap=0, started=False)
        if actor != "board":
            return Decision("refused", "actor_cannot_approve", cap=self.cap(role), started=False)
        if isinstance(cap, bool) or not isinstance(cap, int) or cap < 0 or cap > 3:
            return Decision("refused", "cap_range", cap=self.cap(role), started=False)
        if code_on is not True:
            self._code_on = False
            self._caps.clear()
            if cap != 0:
                return Decision("refused", "code_profile_off", cap=0, started=False)
            return Decision("recorded", "cap_zero", cap=0, started=False)
        self._code_on = True
        self._caps[role] = cap
        return Decision("recorded", "not_started", cap=cap, started=False)

    def set_durable(self, actor: str, role: str, on: bool, *, confirmed: bool = False) -> Decision:
        del confirmed
        if actor != "board":
            return Decision("refused", "actor_cannot_approve", started=False)
        if not _role(role) or not isinstance(on, bool):
            return Decision("refused", "role_name", started=False)
        self._durable[role] = on
        home = f"agent-{role}" if on else ""
        return Decision("recorded", "not_started", name=home, started=False)

    def dispatch(self, role: str, task_id: str, *, confirmed: bool = False) -> Decision:
        del confirmed
        if not _role(role) or not isinstance(task_id, str) or _TASK.fullmatch(task_id) is None:
            return Decision("refused", "name", started=False)
        return Decision("refused", "not_started", name=f"tr-{task_id}", started=False)

    def set_engine(
        self,
        actor: str,
        role: str,
        engine: str,
        budget: int,
        *,
        confirmed: bool = False,
    ) -> Decision:
        del confirmed
        if actor != "board":
            return Decision("refused", "actor_cannot_approve", started=False)
        if not _role(role) or engine not in ENGINES:
            return Decision("refused", "engine", started=False)
        if isinstance(budget, bool) or not isinstance(budget, int) or budget < 5 or budget > 180:
            return Decision("refused", "budget", started=False)
        self._engines[role] = (engine, budget)
        return Decision("recorded", "not_started", name=engine, cap=self.cap(role), started=False)

    def set_collections(
        self,
        actor: str,
        role: str,
        names: Iterable[str],
        *,
        confirmed: bool = False,
    ) -> Decision:
        del confirmed
        if actor != "board":
            return Decision("refused", "actor_cannot_approve")
        if not _role(role) or isinstance(names, str):
            return Decision("refused", "collection_closed")
        cleaned: list[str] = []
        for name in names:
            if name != _COLLECTION:
                return Decision("refused", "collection_closed")
            if name not in cleaned:
                cleaned.append(name)
        self._collections[role] = tuple(cleaned)
        return Decision("recorded", _COLLECTION if cleaned else "none")

    def collections(self, role: str) -> tuple[str, ...]:
        if not _role(role):
            return ()
        return self._collections.get(role, ())

    def put_secret(
        self,
        actor: str,
        role: str,
        name: str,
        value: str,
        *,
        confirmed: bool = False,
    ) -> Decision:
        del confirmed
        if actor != "board":
            return Decision("refused", "actor_cannot_approve")
        if not _role(role) or not isinstance(name, str) or _SECRET.fullmatch(name) is None:
            return Decision("refused", "secret_name")
        if not isinstance(value, str) or value.strip() == "":
            return Decision("refused", "secret_value", name=name)
        self._secrets[(role, name)] = value
        return Decision("recorded", "name_only", name=name)

    def secret_names(self, role: str) -> tuple[str, ...]:
        if not _role(role):
            return ()
        return tuple(sorted(name for owner, name in self._secrets if owner == role))

    def show_secret(self, role: str, name: str) -> Decision:
        if (role, name) not in self._secrets:
            return Decision("refused", "unknown_secret")
        return Decision("refused", "value_hidden", name=name)

    def matches(self, role: str, name: str, value: str) -> bool:
        return self._secrets.get((role, name)) == value
