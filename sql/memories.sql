-- Schema for the `memories` table that memory-mcp's `memory_save` writes to,
-- and that Qdrant points reference by the same id. See docs/memory.md for
-- the full write/delete race-safety rules this schema exists to support.
--
-- CHECK constraints are declared once, on the table, at the bottom of each
-- block below. Column comments describe intent only and must not restate
-- the constraint text, so the two never drift apart.
--
-- This runs only against an empty Postgres data directory (Postgres skips
-- init scripts once `PGDATA` already has a cluster). A volume created from
-- an earlier draft of this file — `person_id`/`kind`, a btree on raw
-- `content`, or a queue without `done_at` — is not altered by re-applying
-- this script. Recreate that volume, or migrate it explicitly, before
-- relying on the functions below.
--
-- This schema is the contract memory_save writes in this repository.
-- The service that calls it is not implemented yet
-- (see README.md "Build order", step 1).

CREATE TABLE IF NOT EXISTS memories (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id      TEXT NOT NULL,                     -- person id or role id; a trigger rejects updates
    owner_kind    TEXT NOT NULL,                     -- which namespace the id belongs to
    revision      INTEGER NOT NULL DEFAULT 1,        -- monotonic; a claim matches this exact value
    content       TEXT NOT NULL,
    title         TEXT,
    tags          TEXT[] DEFAULT '{}',
    category      TEXT NOT NULL DEFAULT '',          -- '' so the dedup key never sees SQL NULL
    pinned        BOOLEAN NOT NULL DEFAULT false,
    visibility    TEXT NOT NULL,                     -- no default: Friday passes master, roles pass working
    index_state   TEXT NOT NULL DEFAULT 'pending',   -- display label; the queue table is the work list
    deleted_at    TIMESTAMPTZ,
    promoted_from UUID REFERENCES memories(id),
    promoted_at   TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT memories_owner_kind_check CHECK (owner_kind IN ('person', 'role')),
    CONSTRAINT memories_visibility_check CHECK (visibility IN ('master', 'working', 'promoted')),
    CONSTRAINT memories_index_state_check CHECK (index_state IN ('pending', 'indexed', 'failed')),
    CONSTRAINT memories_revision_check CHECK (revision >= 1)
);

-- Dedup key for a live row. md5(content) stays under the btree entry limit
-- (~2704 bytes); indexing content itself rejects a note of a few paragraphs.
-- owner_kind keeps a person and a role with the same id text apart.
-- visibility keeps a promoted copy as its own live row, pointed at by
-- promoted_from, instead of collapsing it into the working row.
-- Soft-deleted rows drop out of the key so the same text can be saved again.
DROP INDEX IF EXISTS memories_owner_content_idx;
CREATE UNIQUE INDEX memories_owner_content_idx
    ON memories (owner_id, owner_kind, visibility, category, md5(content))
    WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS memories_owner_idx ON memories (owner_id, owner_kind);
CREATE INDEX IF NOT EXISTS memories_category_idx ON memories (category);

-- One queue item per (memory, revision). The memory row and this item commit
-- together via the enqueue trigger. ON DELETE RESTRICT keeps a hard delete
-- from dropping the item before the worker has removed the Qdrant point;
-- callers soft-delete through memory_tombstone instead.
CREATE TABLE IF NOT EXISTS memory_index_queue (
    id           BIGSERIAL PRIMARY KEY,
    memory_id    UUID NOT NULL REFERENCES memories(id) ON DELETE RESTRICT,
    revision     INTEGER NOT NULL,
    claimed_at   TIMESTAMPTZ,
    claimed_by   TEXT,
    done_at      TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT memory_index_queue_revision_key UNIQUE (memory_id, revision)
);

-- Work list is "not finished". A claim older than the lease is eligible
-- again, so a worker that committed a claim and then died does not stick
-- the row forever. Tombstones stay in this list until memory_index_finish.
CREATE INDEX IF NOT EXISTS memory_index_queue_work_idx
    ON memory_index_queue (created_at)
    WHERE done_at IS NULL;

CREATE OR REPLACE FUNCTION memories_guard_update()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
BEGIN
    IF NEW.owner_id IS DISTINCT FROM OLD.owner_id
       OR NEW.owner_kind IS DISTINCT FROM OLD.owner_kind THEN
        RAISE EXCEPTION 'owner_id and owner_kind are immutable on memories';
    END IF;

    -- memory_save sets revision itself. A raw UPDATE that changes the
    -- stored fact, and forgets to bump revision, still has to enqueue.
    IF NEW.revision = OLD.revision AND (
        NEW.content IS DISTINCT FROM OLD.content
        OR NEW.category IS DISTINCT FROM OLD.category
        OR NEW.visibility IS DISTINCT FROM OLD.visibility
        OR NEW.title IS DISTINCT FROM OLD.title
        OR NEW.tags IS DISTINCT FROM OLD.tags
        OR NEW.pinned IS DISTINCT FROM OLD.pinned
        OR NEW.deleted_at IS DISTINCT FROM OLD.deleted_at
        OR NEW.promoted_from IS DISTINCT FROM OLD.promoted_from
    ) THEN
        NEW.revision := OLD.revision + 1;
        NEW.index_state := 'pending';
        NEW.updated_at := now();
    END IF;

    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION memories_enqueue()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
BEGIN
    INSERT INTO memory_index_queue (memory_id, revision)
    VALUES (NEW.id, NEW.revision)
    ON CONFLICT (memory_id, revision) DO NOTHING;
    RETURN NEW;
END;
$$;

-- Upsert path. A second save of the same live identity updates that row
-- and bumps revision. A different visibility (a promoted copy) is a new row.
CREATE OR REPLACE FUNCTION memory_save(
    p_owner_id TEXT,
    p_owner_kind TEXT,
    p_content TEXT,
    p_visibility TEXT,
    p_category TEXT DEFAULT '',
    p_title TEXT DEFAULT NULL,
    p_tags TEXT[] DEFAULT '{}',
    p_pinned BOOLEAN DEFAULT false,
    p_promoted_from UUID DEFAULT NULL
) RETURNS memories
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
DECLARE
    row memories;
BEGIN
    INSERT INTO memories (
        owner_id, owner_kind, content, visibility, category,
        title, tags, pinned, promoted_from, promoted_at, index_state
    ) VALUES (
        p_owner_id,
        p_owner_kind,
        p_content,
        p_visibility,
        COALESCE(p_category, ''),
        p_title,
        COALESCE(p_tags, '{}'),
        COALESCE(p_pinned, false),
        p_promoted_from,
        CASE WHEN p_promoted_from IS NULL THEN NULL ELSE now() END,
        'pending'
    )
    ON CONFLICT (owner_id, owner_kind, visibility, category, (md5(content)))
    WHERE deleted_at IS NULL
    DO UPDATE SET
        revision = memories.revision + 1,
        title = EXCLUDED.title,
        tags = EXCLUDED.tags,
        pinned = EXCLUDED.pinned,
        index_state = 'pending',
        updated_at = now()
    RETURNING * INTO row;

    RETURN row;
END;
$$;

-- Soft delete. The guard trigger bumps revision and the enqueue trigger
-- records it, so the worker still sees a Qdrant delete to perform.
CREATE OR REPLACE FUNCTION memory_tombstone(p_id UUID)
RETURNS memories
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
DECLARE
    row memories;
BEGIN
    UPDATE memories
    SET deleted_at = now()
    WHERE id = p_id AND deleted_at IS NULL
    RETURNING * INTO row;
    RETURN row;
END;
$$;

-- Oldest unfinished item whose claim is free or older than p_lease
-- (default 5 minutes). The memory row is updated only when its revision
-- still matches; that conditional update is the row lock. A mismatch marks
-- the queue item done and the function tries the next one. deleted_at comes
-- back so the caller deletes the Qdrant point instead of upserting it.
CREATE OR REPLACE FUNCTION memory_index_claim(
    p_worker TEXT,
    p_lease INTERVAL DEFAULT INTERVAL '5 minutes'
) RETURNS TABLE (
    queue_id BIGINT,
    memory_id UUID,
    revision INTEGER,
    deleted_at TIMESTAMPTZ
)
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
DECLARE
    candidate memory_index_queue%ROWTYPE;
    mem memories%ROWTYPE;
BEGIN
    IF p_worker IS NULL OR length(btrim(p_worker)) = 0 THEN
        RAISE EXCEPTION 'memory_index_claim requires a worker id';
    END IF;

    LOOP
        SELECT q.* INTO candidate
        FROM memory_index_queue q
        WHERE q.done_at IS NULL
          AND (q.claimed_at IS NULL OR q.claimed_at < now() - p_lease)
        ORDER BY q.created_at
        FOR UPDATE SKIP LOCKED
        LIMIT 1;

        IF NOT FOUND THEN
            RETURN;
        END IF;

        UPDATE memories m
        SET index_state = m.index_state
        WHERE m.id = candidate.memory_id
          AND m.revision = candidate.revision
        RETURNING * INTO mem;

        IF NOT FOUND THEN
            UPDATE memory_index_queue
            SET done_at = now(), claimed_by = p_worker
            WHERE id = candidate.id;
            CONTINUE;
        END IF;

        UPDATE memory_index_queue
        SET claimed_at = now(), claimed_by = p_worker
        WHERE id = candidate.id;

        queue_id := candidate.id;
        memory_id := mem.id;
        revision := mem.revision;
        deleted_at := mem.deleted_at;
        RETURN NEXT;
        RETURN;
    END LOOP;
END;
$$;

CREATE OR REPLACE FUNCTION memory_index_finish(p_queue_id BIGINT)
RETURNS void
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
BEGIN
    UPDATE memory_index_queue
    SET done_at = now()
    WHERE id = p_queue_id AND done_at IS NULL;
END;
$$;

DROP TRIGGER IF EXISTS memories_guard_update ON memories;
CREATE TRIGGER memories_guard_update
    BEFORE UPDATE ON memories
    FOR EACH ROW
    EXECUTE FUNCTION memories_guard_update();

DROP TRIGGER IF EXISTS memories_enqueue_insert ON memories;
CREATE TRIGGER memories_enqueue_insert
    AFTER INSERT ON memories
    FOR EACH ROW
    EXECUTE FUNCTION memories_enqueue();

-- Not "UPDATE OF revision": a BEFORE trigger may bump revision when the
-- statement only set deleted_at. OF filters on the statement's target list
-- and would skip that enqueue.
DROP TRIGGER IF EXISTS memories_enqueue_update ON memories;
CREATE TRIGGER memories_enqueue_update
    AFTER UPDATE ON memories
    FOR EACH ROW
    WHEN (OLD.revision IS DISTINCT FROM NEW.revision)
    EXECUTE FUNCTION memories_enqueue();
