"""Write one backup manifest through backup_store.

The caller supplies the connection. A live SQLite method, a passphrase,
and a movie file are refused before that connection opens. A failure is
the reason postgres and does not include the registry or the driver text.
Without a connection the manifest stays in the process. A second store of
the same pause returns the same id. Nothing is copied and no container
is started. Chat cannot record one.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from urllib.parse import unquote_plus

from memoryd.store import credential_shape

SCHEMA = Path(__file__).resolve().parents[1] / "sql" / "backup.sql"
METHODS = frozenset({"backup_api", "clean_shutdown"})
MARKS = frozenset({"managed", "adopted"})
EXCLUDED = frozenset({"movies", "jellyfin_config", "optional_apps", "library"})
_ACTOR = "board"
_PAUSE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")
_APP = re.compile(r"[a-z][a-z0-9-]{0,63}\Z")
_KEPT = "The password is kept outside the machine"
_LEAKS = ("passphrase", "password", "secret", "token", "value")


class ManifestError(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class Decision:
    outcome: str
    reason: str
    manifest_id: str = ""
    copied: bool = False
    started: bool = False
    connected: bool = False

    def __repr__(self) -> str:
        return f"Decision({self.outcome!r}, {self.reason!r})"


class PostgresManifests:
    def __init__(self, connect) -> None:
        self._connect = connect

    @classmethod
    def from_env(cls, env: dict[str, str]) -> PostgresManifests:
        if not env.get("POSTGRES_PASSWORD") or not env.get("POSTGRES_USER"):
            raise ManifestError("postgres")
        try:
            import psycopg
        except ImportError as exc:
            raise ManifestError("postgres") from exc
        host = env["POSTGRES_HOST"]
        port = int(env.get("POSTGRES_PORT") or "5432")
        dbname = env.get("POSTGRES_DB") or "memories"
        user = env["POSTGRES_USER"]
        password = env["POSTGRES_PASSWORD"]

        def connect():
            return psycopg.connect(
                host=host,
                port=port,
                dbname=dbname,
                user=user,
                password=password,
                connect_timeout=5,
            )

        return cls(connect)

    def ensure(self) -> bool:
        try:
            script = SCHEMA.read_text(encoding="utf-8")
        except OSError:
            return False
        try:
            parts = statements(script)
        except ValueError:
            return False
        if not parts:
            return False
        try:
            with self._connect() as conn:
                for part in parts:
                    conn.execute(part)
        except Exception:
            return False
        return True

    def store(self, pause_id: str, method: str, registry: list[dict]) -> str:
        payload = json.dumps(registry, sort_keys=True, separators=(",", ":"))
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT backup_store(%s::uuid, %s, %s::jsonb, %s::text[])::text",
                    (pause_id, method, payload, []),
                ).fetchone()
        except Exception as exc:
            raise ManifestError("postgres") from exc
        found = _manifest_id(None if row is None else row[0])
        if not found:
            raise ManifestError("postgres")
        return found


def record_manifest(book: dict, fields: Mapping, manifests=None) -> Decision:
    """Record one manifest. Refusals do not open the connection."""
    if not isinstance(fields, Mapping):
        return Decision("refused", "registry_mark")
    if fields.get("actor") != _ACTOR:
        return Decision("refused", "actor_cannot_backup")
    if fields.get("operation") == "install" or fields.get("action") == "install":
        return Decision("refused", "catalog_install_closed")
    if _leaking(fields):
        return Decision("refused", "passphrase_in_manifest")
    extra = fields.get("included_extra", fields.get("include_names"))
    if extra not in (None, [], ()):
        return Decision("refused", "optional_app_excluded")
    method = fields.get("sqlite_method")
    if method in {"live_file", "path", "copy"}:
        return Decision("refused", "live_sqlite")
    if method not in METHODS:
        return Decision("refused", "sqlite_method")
    pause_id = fields.get("pause_id")
    if not isinstance(pause_id, str) or _hidden(pause_id) or _pause(pause_id) == "":
        return Decision("refused", "credential" if isinstance(pause_id, str) and _hidden(pause_id) else "pause_id")
    registry, reason = _registry(fields.get("registry"))
    if reason:
        return Decision("refused", reason)
    if manifests is None:
        return _memory(book, pause_id)
    try:
        manifest_id = manifests.store(pause_id, method, registry)
    except ManifestError:
        return Decision("refused", "postgres")
    return _kept(book, pause_id, manifest_id, connected=True)


def statements(script: str) -> list[str]:
    """Split a script. A dollar-quoted function body stays one statement."""
    out: list[str] = []
    buf: list[str] = []
    index = 0
    length = len(script)
    while index < length:
        if script.startswith("--", index):
            end = script.find("\n", index)
            index = length if end == -1 else end + 1
            continue
        if script.startswith("$$", index):
            end = script.find("$$", index + 2)
            if end == -1:
                raise ValueError("schema")
            buf.append(script[index:end + 2])
            index = end + 2
            continue
        if script[index] == ";":
            text = "".join(buf).strip()
            if text:
                out.append(text)
            buf = []
            index += 1
            continue
        buf.append(script[index])
        index += 1
    tail = "".join(buf).strip()
    if tail:
        out.append(tail)
    return out


def _memory(book: dict, pause_id: str) -> Decision:
    held = book.get(pause_id)
    if isinstance(held, str) and _pause(held):
        return Decision("manifested", "already_stored", manifest_id=held)
    manifest_id = str(uuid.uuid4())
    book[pause_id] = manifest_id
    return Decision("manifested", "stored", manifest_id=manifest_id)


def _kept(book: dict, pause_id: str, manifest_id: str, *, connected: bool) -> Decision:
    previous = book.get(pause_id)
    book[pause_id] = manifest_id
    reason = "already_stored" if previous == manifest_id else "stored"
    return Decision("manifested", reason, manifest_id=manifest_id, connected=connected)


def _registry(value: object) -> tuple[list[dict] | None, str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
        return None, "registry_mark"
    if len(value) == 0 or len(value) > 8:
        return None, "registry_mark"
    rows: list[dict] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, Mapping) or set(item) != {"id", "mark"}:
            return None, "registry_mark"
        app_id = item.get("id")
        mark = item.get("mark")
        if not isinstance(app_id, str) or not isinstance(mark, str):
            return None, "registry_mark"
        if _hidden(app_id) or _hidden(mark):
            return None, "credential"
        if app_id in EXCLUDED:
            return None, "optional_app_excluded"
        if _APP.fullmatch(app_id) is None or mark not in MARKS:
            return None, "registry_mark"
        if app_id in seen:
            return None, "registry_mark"
        seen.add(app_id)
        rows.append({"id": app_id, "mark": mark})
    return rows, ""


def _leaking(fields: Mapping) -> bool:
    for name in _LEAKS:
        if name not in fields:
            continue
        value = fields.get(name)
        if value in (None, "", _KEPT):
            continue
        return True
    return False


def _manifest_id(value: object) -> str:
    if isinstance(value, uuid.UUID):
        value = str(value)
    if isinstance(value, str) and _pause(value):
        return value
    return ""


def _pause(value: object) -> str:
    if not isinstance(value, str) or _PAUSE.fullmatch(value) is None:
        return ""
    try:
        parsed = uuid.UUID(value)
    except ValueError:
        return ""
    if str(parsed) != value:
        return ""
    return value


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
