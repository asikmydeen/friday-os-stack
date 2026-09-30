"""Postgres authority. Writes go through memory_save and memory_tombstone.

The Qdrant key is not used here. A connection error stays a short reason
and does not include the password or the note.
"""

from __future__ import annotations

from memoryd.index import Claim, Memory
from memoryd.store import OWNER_KINDS, RECALL_CAP, VISIBILITIES, Decision


def configured(env: dict[str, str]) -> bool:
    return bool(env.get("POSTGRES_HOST"))


def config_reason(env: dict[str, str]) -> str:
    if not configured(env):
        return ""
    if not env.get("POSTGRES_PASSWORD") or not env.get("POSTGRES_USER"):
        return "postgres"
    return ""


class PostgresNotes:
    def __init__(self, connect) -> None:
        self._connect = connect

    @classmethod
    def from_env(cls, env: dict[str, str]) -> PostgresNotes:
        reason = config_reason(env)
        if reason:
            raise SystemExit(f"memoryd: {reason}")
        try:
            import psycopg
        except ImportError as exc:
            raise SystemExit("memoryd: postgres_driver") from exc
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

    def ping(self) -> bool:
        try:
            with self._connect() as conn:
                conn.execute("SELECT 1")
            return True
        except Exception:
            return False

    def transaction(self):
        return _Transaction(self._connect)

    def save(
        self,
        *,
        owner_id: str,
        owner_kind: str,
        content: str,
        visibility: str = "master",
        category: str = "",
    ) -> Decision:
        if not owner_id or owner_kind not in OWNER_KINDS:
            return Decision("refused", "missing_owner")
        if visibility not in VISIBILITIES:
            return Decision("refused", "visibility")
        if not isinstance(content, str) or content.strip() == "":
            return Decision("refused", "empty_content")
        try:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT id::text, revision
                    FROM memory_save(%s, %s, %s, %s, %s) AS saved
                    """,
                    (owner_id, owner_kind, content, visibility, category or ""),
                ).fetchone()
        except Exception as exc:
            return Decision("refused", _reason(exc))
        if row is None or row[0] is None:
            return Decision("refused", "postgres")
        revision = int(row[1])
        reason = "revised" if revision > 1 else "created"
        return Decision("saved", reason, note_id=row[0], revision=revision)

    def recall(self, *, owner_id: str | None, owner_kind: str | None, limit: int = RECALL_CAP) -> Decision:
        if not owner_id or owner_kind not in OWNER_KINDS:
            return Decision("refused", "missing_owner")
        cap = RECALL_CAP if not isinstance(limit, int) or isinstance(limit, bool) else min(limit, RECALL_CAP)
        if cap < 1:
            cap = 1
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT id::text, owner_id, owner_kind, revision, content, visibility, category
                    FROM memories
                    WHERE deleted_at IS NULL
                      AND owner_id = %s
                      AND owner_kind = %s
                    ORDER BY revision DESC, updated_at DESC
                    LIMIT %s
                    """,
                    (owner_id, owner_kind, cap),
                ).fetchall()
        except Exception:
            return Decision("refused", "postgres")
        notes = tuple(
            {
                "id": row[0],
                "owner_id": row[1],
                "owner_kind": row[2],
                "revision": row[3],
                "content": row[4],
                "visibility": row[5],
                "category": row[6],
            }
            for row in rows
        )
        return Decision("ok", "recalled", notes=notes)

    def tombstone(self, note_id: str) -> Decision:
        if not note_id:
            return Decision("refused", "unknown_note")
        try:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT id::text, revision
                    FROM memory_tombstone(%s::uuid) AS gone
                    """,
                    (note_id,),
                ).fetchone()
        except Exception as exc:
            if getattr(exc, "sqlstate", None) == "22P02":
                return Decision("refused", "unknown_note")
            return Decision("refused", "postgres")
        if row is None or row[0] is None:
            return Decision("refused", "unknown_note")
        return Decision("saved", "tombstone", note_id=row[0], revision=int(row[1]))


class _Transaction:
    def __init__(self, connect) -> None:
        self._connect = connect
        self._conn = None

    def __enter__(self):
        self._conn = self._connect()
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                self._conn.commit()
            else:
                self._conn.rollback()
        finally:
            self._conn.close()
        return False

    def claim(self, worker: str) -> Claim | None:
        row = self._conn.execute(
            """
            SELECT queue_id, memory_id::text, revision, deleted_at IS NOT NULL
            FROM memory_index_claim(%s)
            """,
            (worker,),
        ).fetchone()
        if row is None:
            return None
        return Claim(queue_id=int(row[0]), memory_id=row[1], revision=int(row[2]), deleted=bool(row[3]))

    def fetch(self, memory_id: str) -> Memory | None:
        row = self._conn.execute(
            """
            SELECT id::text, owner_id, owner_kind, revision, content,
                   visibility, category, deleted_at IS NOT NULL
            FROM memories
            WHERE id = %s::uuid
            """,
            (memory_id,),
        ).fetchone()
        if row is None:
            return None
        return Memory(
            id=row[0],
            owner_id=row[1],
            owner_kind=row[2],
            revision=int(row[3]),
            content=row[4],
            visibility=row[5],
            category=row[6],
            deleted=bool(row[7]),
        )

    def finish(self, queue_id: int) -> None:
        self._conn.execute("SELECT memory_index_finish(%s)", (queue_id,))

    def mark_indexed(self, memory_id: str, revision: int) -> None:
        self._conn.execute(
            """
            UPDATE memories
            SET index_state = 'indexed'
            WHERE id = %s::uuid AND revision = %s AND deleted_at IS NULL
            """,
            (memory_id, revision),
        )


def _reason(exc: Exception) -> str:
    name = ""
    diag = getattr(exc, "diag", None)
    if diag is not None:
        name = getattr(diag, "constraint_name", "") or ""
    if "owner_kind" in name:
        return "missing_owner"
    if "visibility" in name:
        return "visibility"
    return "postgres"
