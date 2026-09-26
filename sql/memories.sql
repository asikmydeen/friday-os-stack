-- Schema for the `memories` table that memory-mcp's `memory_save` writes to,
-- and that Qdrant points reference by the same id. See docs/memory.md for
-- the full write/delete race-safety rules this schema exists to support.
--
-- CHECK constraints are declared once, on the table, at the bottom of each
-- block below. Column comments describe intent only and must not restate
-- the constraint text, so the two never drift apart.
--
-- This runs only against an empty Postgres data directory (Postgres skips
-- init scripts once `PGDATA` already has a cluster). An existing volume
-- from an older column layout is not migrated by this file and must be
-- migrated explicitly before this schema is applied on top of it.
--
-- This is a stub written for this public scaffold; it is not exported
-- verbatim from the private memory-mcp repository. Treat it as a starting
-- point to refine once memory-mcp is generalized into this stack
-- (see README.md "Build order", step 1).

CREATE TABLE IF NOT EXISTS memories (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id      TEXT NOT NULL,                   -- person id or role id; the app must never issue an UPDATE that changes it
    owner_kind    TEXT NOT NULL,                   -- 'person' or 'role'
    revision      INTEGER NOT NULL DEFAULT 1,       -- monotonic; the indexer's conditional claim checks this
    content       TEXT NOT NULL,
    title         TEXT,
    tags          TEXT[] DEFAULT '{}',
    category      TEXT NOT NULL DEFAULT '',          -- '' (not NULL) so the same-content unique key below dedups reliably
    pinned        BOOLEAN NOT NULL DEFAULT false,
    visibility    TEXT NOT NULL DEFAULT 'working',   -- Friday's own writes must set 'master' explicitly; role/person writes default to 'working'
    index_state   TEXT NOT NULL DEFAULT 'pending',
    deleted_at    TIMESTAMPTZ,
    promoted_from UUID REFERENCES memories(id),
    promoted_at   TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT memories_owner_kind_check CHECK (owner_kind IN ('person', 'role')),
    CONSTRAINT memories_visibility_check CHECK (visibility IN ('master', 'working', 'promoted')),
    CONSTRAINT memories_index_state_check CHECK (index_state IN ('pending', 'indexed', 'failed'))
);

-- Same-content dedup: writing identical content for the same owner (and
-- category) updates that row and bumps `revision`, per docs/memory.md,
-- instead of inserting a second row. `category` defaults to '' rather than
-- NULL specifically so this key participates in ON CONFLICT — Postgres
-- treats two NULLs as distinct, which would otherwise let duplicates
-- through for every row that never sets a category. This key also
-- collapses a promoted copy (`promoted_from` set) into the working row it
-- was promoted from, since content+owner+category is unchanged by
-- promotion.
CREATE UNIQUE INDEX IF NOT EXISTS memories_owner_content_idx
    ON memories (owner_id, category, content)
    WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS memories_owner_idx ON memories (owner_id, owner_kind);
CREATE INDEX IF NOT EXISTS memories_category_idx ON memories (category);

-- Indexing queue: the row and its queue item must commit together (see
-- docs/memory.md "Delete/update race safety"). A worker claims the oldest
-- unclaimed item with a conditional UPDATE against `memories.revision`, so
-- the queue -- not `memories.index_state` alone -- is the work list. A
-- tombstoned row (`deleted_at` set) still owes a Qdrant delete, so it must
-- stay queued until that delete lands; filtering the queue by
-- `deleted_at IS NULL` on `memories` would hide exactly that case.
CREATE TABLE IF NOT EXISTS memory_index_queue (
    id           BIGSERIAL PRIMARY KEY,
    memory_id    UUID NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    revision     INTEGER NOT NULL,        -- the revision this queue item is for; a claim checks this still matches memories.revision
    claimed_at   TIMESTAMPTZ,
    claimed_by   TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS memory_index_queue_unclaimed_idx
    ON memory_index_queue (created_at)
    WHERE claimed_at IS NULL;
