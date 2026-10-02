"""List a pinned catalog and refuse every install.

catalog/PIN is comments until a commit line is filled in. An empty pin
lists nothing. Entries the caller supplies are filtered to the stable
and community trains. The enterprise train is omitted. Draft wires
under catalog/wires are not the catalog.

request_install is the product call. It returns catalog_install_closed
for every id. review_install records the later order a release would
use, and the last reason in that order is still catalog_install_closed.
confirmed=true is ignored. catalog/render.py can record a description
the caller supplies. That record does not fill this pin and does not
open install.

This module does not fetch truenas/apps and does not start a container.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

TRAINS = frozenset({"stable", "community"})
PIN_PATH = Path(__file__).resolve().parent / "PIN"
WIRES_PATH = Path(__file__).resolve().parent / "wires"

_COMMIT = re.compile(r"^commit:\s*([0-9a-fA-F]{40})\s*$")
_COMMIT_PRESENT = re.compile(r"^commit:\s*\S")
_TRAINS = re.compile(r"^trains:\s*\[(.*)\]\s*$")
_PINNED_AT = re.compile(r"^pinned_at:\s*\S")


@dataclass(frozen=True)
class Decision:
    outcome: str
    reason: str


@dataclass(frozen=True)
class Row:
    name: str
    train: str
    install: str


@dataclass(frozen=True)
class Listing:
    outcome: str
    reason: str
    rows: tuple[Row, ...] = ()

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(row.name for row in self.rows)


def _body(line: str) -> str:
    return line.split("#", 1)[0].strip()


def parse_pin(text: str) -> tuple[str, tuple[str, ...]] | Decision:
    commit = None
    trains: tuple[str, ...] | None = None
    for raw in text.splitlines():
        body = _body(raw)
        if not body:
            continue
        if _COMMIT_PRESENT.match(body):
            found = _COMMIT.match(body)
            if found is None or commit is not None:
                return Decision("empty", "pin_invalid")
            commit = found.group(1).lower()
            continue
        trains_line = _TRAINS.match(body)
        if trains_line:
            if trains is not None:
                return Decision("empty", "pin_invalid")
            parts = []
            for part in trains_line.group(1).split(","):
                name = part.strip().strip("\"'")
                if name:
                    parts.append(name)
            trains = tuple(parts)
            continue
        if _PINNED_AT.match(body):
            continue
        return Decision("empty", "pin_invalid")
    if commit is None:
        return Decision("empty", "pin_empty")
    if trains is None:
        trains = ("stable", "community")
    return commit, trains


def discover(
    pin: str | None = None,
    entries: Sequence[Mapping[str, str]] | None = None,
) -> Listing:
    text = PIN_PATH.read_text(encoding="utf-8") if pin is None else pin
    parsed = parse_pin(text)
    if isinstance(parsed, Decision):
        return Listing(parsed.outcome, parsed.reason)
    _commit, trains = parsed
    allowed = tuple(train for train in trains if train in TRAINS)
    rows: list[Row] = []
    seen: set[str] = set()
    for entry in entries or ():
        name = str(entry.get("name", "")).strip()
        train = str(entry.get("train", "")).strip()
        if not name or train not in allowed or name in seen:
            continue
        seen.add(name)
        rows.append(Row(name, train, "refused"))
    if not entries:
        return Listing("listed", "upstream_not_copied")
    return Listing("listed", "listed", tuple(rows))


def draft_ids(directory: Path | None = None) -> tuple[str, ...]:
    root = WIRES_PATH if directory is None else directory
    found: list[str] = []
    for path in sorted(root.glob("*.yml")):
        for raw in path.read_text(encoding="utf-8").splitlines():
            body = _body(raw)
            if body.startswith("id:"):
                found.append(body.split(":", 1)[1].strip())
                break
    return tuple(found)


def request_install(app_id: str, *, confirmed: bool = False) -> Decision:
    del app_id, confirmed
    return Decision("refused", "catalog_install_closed")


def review_install(
    *,
    middleware: bool = False,
    allowlisted: bool = False,
    render_passed: bool = False,
    declared: int | None = None,
    free: int | None = None,
    agent_path: bool = False,
    confirmed: bool = False,
) -> Decision:
    del confirmed
    if middleware:
        return Decision("refused", "middleware_required")
    if not allowlisted:
        return Decision("refused", "not_allowlisted")
    if not render_passed:
        return Decision("refused", "render_unproven")
    if (
        isinstance(declared, int)
        and not isinstance(declared, bool)
        and isinstance(free, int)
        and not isinstance(free, bool)
        and declared > free
    ):
        return Decision("refused", "ram_does_not_fit")
    if not agent_path:
        return Decision("refused", "agent_path_closed")
    return Decision("refused", "catalog_install_closed")
