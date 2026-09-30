"""Load the starter charters shipped beside Friday."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Charter:
    id: str
    name: str
    body: str
    aliases: tuple[str, ...]


def _frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text
    meta: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip()
    return meta, text[end + 5 :]


def load_charters(directory: Path) -> dict[str, Charter]:
    found: dict[str, Charter] = {}
    if not directory.is_dir():
        return found
    for path in sorted(directory.glob("*.md")):
        meta, body = _frontmatter(path.read_text(encoding="utf-8"))
        charter_id = meta.get("id") or path.stem
        aliases = [charter_id, path.stem]
        aliases.extend(part.strip() for part in meta.get("aliases", "").split(",") if part.strip())
        charter = Charter(charter_id, meta.get("name") or charter_id, body.strip(), tuple(aliases))
        for alias in aliases:
            found[alias.casefold()] = charter
    return found
