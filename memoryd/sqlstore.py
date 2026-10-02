"""Postgres authority. Writes go through memory_save and memory_tombstone.

A promoted copy is that same function with the working row's id. A
promoted save with no pointer does not connect. A research card is
save_card, category finding or knowledge. A direct save of those
categories does not connect. The Qdrant key is not
used here. A connection error stays a short reason and does not include
the password or the note.
"""

from __future__ import annotations

import re

from memoryd.index import Claim, Memory
from memoryd.store import OWNER_KINDS, RECALL_CAP, VISIBILITIES, Decision, credential_shape

_UUID = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\Z"
)


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
        promoted_from: str | None = None,
    ) -> Decision:
        if not owner_id or owner_kind not in OWNER_KINDS:
            return Decision("refused", "missing_owner")
        if visibility not in VISIBILITIES:
            return Decision("refused", "visibility")
        if not isinstance(content, str) or content.strip() == "":
            return Decision("refused", "empty_content")
        if credential_shape(content):
            return Decision("refused", "credential")
        # The persona pass writes that category on the file store only.
        if isinstance(category, str) and category.strip().casefold() == "persona":
            return Decision("refused", "persona_pass")
        # POST /save cannot write a card. POST /card calls save_card.
        if isinstance(category, str) and category.strip().casefold() in {"finding", "findings", "knowledge"}:
            return Decision("refused", "card_pass")
        category = category or ""
        if visibility != "promoted":
            if promoted_from is not None:
                return Decision("refused", "promoted_from")
            return self._insert(owner_id, owner_kind, content, visibility, category)
        if not isinstance(promoted_from, str) or _UUID.fullmatch(promoted_from) is None:
            return Decision("refused", "promoted_from")
        return self._promote(owner_id, owner_kind, content, category, promoted_from)

    def promote_working(self, note_id: str) -> Decision:
        """Copy one working row. The pointer is that row's id."""
        if not isinstance(note_id, str) or _UUID.fullmatch(note_id) is None:
            return Decision("refused", "unknown_note")
        try:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT owner_id, owner_kind, content, visibility, category,
                           deleted_at IS NOT NULL
                    FROM memories
                    WHERE id = %s::uuid
                    """,
                    (note_id,),
                ).fetchone()
        except Exception as exc:
            if getattr(exc, "sqlstate", None) == "22P02":
                return Decision("refused", "unknown_note")
            return Decision("refused", "postgres")
        if row is None or row[5] is True:
            return Decision("refused", "unknown_note")
        if row[3] != "working":
            return Decision("refused", "not_working")
        if credential_shape(row[2]):
            return Decision("refused", "credential")
        return self.save(
            owner_id=row[0],
            owner_kind=row[1],
            content=row[2],
            visibility="promoted",
            category=row[4] or "",
            promoted_from=note_id,
        )

    def save_card(
        self,
        *,
        owner_id: str,
        owner_kind: str,
        content: str,
        category: str,
    ) -> Decision:
        """Write one finding or one knowledge row. A direct save does not."""
        if not owner_id or owner_kind not in OWNER_KINDS:
            return Decision("refused", "missing_owner")
        if category not in {"finding", "knowledge"}:
            return Decision("refused", "kind")
        if not isinstance(content, str) or content.strip() == "":
            return Decision("refused", "empty_content")
        if credential_shape(content):
            return Decision("refused", "credential")
        visibility = "working" if owner_kind == "role" else "master"
        return self._insert(owner_id, owner_kind, content, visibility, category)

    def _insert(
        self,
        owner_id: str,
        owner_kind: str,
        content: str,
        visibility: str,
        category: str,
    ) -> Decision:
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

    def _promote(
        self,
        owner_id: str,
        owner_kind: str,
        content: str,
        category: str,
        promoted_from: str,
    ) -> Decision:
        try:
            with self._connect() as conn:
                source = conn.execute(
                    """
                    SELECT owner_id, owner_kind, content, visibility, category,
                           deleted_at IS NOT NULL
                    FROM memories
                    WHERE id = %s::uuid
                    """,
                    (promoted_from,),
                ).fetchone()
                if source is None or source[5] is True:
                    return Decision("refused", "unknown_note")
                if source[3] != "working":
                    return Decision("refused", "not_working")
                if source[0] != owner_id or source[1] != owner_kind:
                    return Decision("refused", "other_owner")
                if source[2] != content or (source[4] or "") != category:
                    return Decision("refused", "not_a_copy")
                existing = conn.execute(
                    """
                    SELECT id::text, revision, promoted_from::text
                    FROM memories
                    WHERE deleted_at IS NULL
                      AND owner_id = %s
                      AND owner_kind = %s
                      AND visibility = 'promoted'
                      AND category = %s
                      AND md5(content) = md5(%s)
                    """,
                    (owner_id, owner_kind, category, content),
                ).fetchone()
                if existing is not None and str(existing[2] or "").casefold() != promoted_from.casefold():
                    return Decision("refused", "not_a_copy")
                row = conn.execute(
                    """
                    SELECT id::text, revision
                    FROM memory_save(%s, %s, %s, 'promoted', %s, NULL, '{}'::text[], false, %s::uuid)
                         AS saved
                    """,
                    (owner_id, owner_kind, content, category, promoted_from),
                ).fetchone()
        except Exception as exc:
            if getattr(exc, "sqlstate", None) == "22P02":
                return Decision("refused", "unknown_note")
            return Decision("refused", _reason(exc))
        if row is None or row[0] is None:
            return Decision("refused", "postgres")
        revision = int(row[1])
        reason = "revised" if revision > 1 else "created"
        return Decision("saved", reason, note_id=row[0], revision=revision)

    def recall(
        self,
        *,
        owner_id: str | None,
        owner_kind: str | None,
        limit: int = RECALL_CAP,
        category: str | None = None,
    ) -> Decision:
        if not owner_id or owner_kind not in OWNER_KINDS:
            return Decision("refused", "missing_owner")
        if category is not None and not isinstance(category, str):
            return Decision("refused", "category")
        cap = RECALL_CAP if not isinstance(limit, int) or isinstance(limit, bool) else min(limit, RECALL_CAP)
        if cap < 1:
            cap = 1
        params: list = [owner_id, owner_kind]
        category_sql = ""
        if category is not None:
            category_sql = "AND category = %s"
            params.append(category)
        params.append(cap)
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    f"""
                    SELECT id::text, owner_id, owner_kind, revision, content, visibility, category
                    FROM memories
                    WHERE deleted_at IS NULL
                      AND owner_id = %s
                      AND owner_kind = %s
                      {category_sql}
                    ORDER BY revision DESC, updated_at DESC
                    LIMIT %s
                    """,
                    tuple(params),
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
    if "credential" in str(exc).casefold():
        return "credential"
    name = ""
    diag = getattr(exc, "diag", None)
    if diag is not None:
        name = getattr(diag, "constraint_name", "") or ""
    if "owner_kind" in name:
        return "missing_owner"
    if "visibility" in name:
        return "visibility"
    return "postgres"
