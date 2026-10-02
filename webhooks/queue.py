"""Write one webhook row through webhook_store.

The caller supplies the connection. A failure is the reason postgres
and does not include the body, the password, or the driver text.
Without POSTGRES_HOST the process keeps the event in memory instead.
A list reads source and event type only. It does not read the body.
This module does not call the executor and does not write an approval.
"""

from __future__ import annotations

import json
from pathlib import Path

SCHEMA = Path(__file__).resolve().parents[1] / "sql" / "webhooks.sql"


class QueueError(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class PostgresQueue:
    def __init__(self, connect) -> None:
        self._connect = connect

    @classmethod
    def from_env(cls, env: dict[str, str]) -> PostgresQueue:
        if not env.get("POSTGRES_PASSWORD") or not env.get("POSTGRES_USER"):
            raise QueueError("postgres")
        try:
            import psycopg
        except ImportError as exc:
            raise QueueError("postgres") from exc
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

    def insert_event(
        self,
        source: str,
        route: str,
        event_type: str,
        announcement: str,
        body_raw: str,
        digest: str,
    ) -> tuple[str, bool]:
        try:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT id::text, inserted
                    FROM webhook_store(%s, %s, %s, %s, %s::jsonb, %s, %s)
                    """,
                    (source, route, event_type, announcement, _json_or_none(body_raw), body_raw, digest),
                ).fetchone()
        except Exception:
            raise QueueError("postgres") from None
        if row is None or not isinstance(row[0], str) or row[0] == "":
            raise QueueError("postgres")
        return row[0], row[1] is True

    def list_announcements(self) -> list[dict]:
        try:
            with self._connect() as conn:
                found = conn.execute(
                    """
                    SELECT source, event_type
                    FROM webhook_events
                    ORDER BY received_at DESC
                    LIMIT 8
                    """
                ).fetchall()
        except Exception:
            raise QueueError("postgres") from None
        rows: list[dict] = []
        for item in found:
            if not isinstance(item, (tuple, list)) or len(item) < 2:
                continue
            rows.append({"source": item[0], "event_type": item[1]})
        return rows


def statements(script: str) -> list[str]:
    """Split a script. A dollar-quoted function body stays one statement."""
    out: list[str] = []
    buf: list[str] = []
    i = 0
    length = len(script)
    while i < length:
        if script.startswith("--", i):
            end = script.find("\n", i)
            i = length if end == -1 else end + 1
            continue
        if script.startswith("$$", i):
            end = script.find("$$", i + 2)
            if end == -1:
                raise ValueError("schema")
            buf.append(script[i:end + 2])
            i = end + 2
            continue
        if script[i] == ";":
            text = "".join(buf).strip()
            if text:
                out.append(text)
            buf = []
            i += 1
            continue
        buf.append(script[i])
        i += 1
    tail = "".join(buf).strip()
    if tail:
        out.append(tail)
    return out


def _json_or_none(raw: str) -> str | None:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, (dict, list)):
        return None
    return raw
