-- Schema for the `memories` table that memory-mcp's `memory_save` writes to,
-- and that Qdrant points reference by the same id. See docs/memory.md for
-- the full write/delete race-safety rules this schema exists to support.
--
-- This is a stub written for this public scaffold; it is not exported
-- verbatim from the private memory-mcp repository. Treat it as a starting
-- point to refine once memory-mcp is generalized into this stack
-- (see README.md "Build order", step 1).

CREATE TABLE IF NOT EXISTS memories (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id      TEXT NOT NULL,                 -- immutable person id or role id
    owner_kind    TEXT NOT NULL,                 -- 'person' or 'role'
    revision      INTEGER NOT NULL DEFAULT 1,     -- monotonic; the indexer's claim checks this
    content       TEXT NOT NULL,
    title         TEXT,
    tags          TEXT[] DEFAULT '{}',
    category      TEXT,
    pinned        BOOLEAN NOT NULL DEFAULT false,
    visibility    TEXT NOT NULL DEFAULT 'working', -- 'master', 'working', 'promoted'
    index_state   TEXT NOT NULL DEFAULT 'pending',  -- pending / indexed / failed
    deleted_at    TIMESTAMPTZ,
    promoted_from UUID REFERENCES memories(id),
    promoted_at   TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT memories_owner_kind_check CHECK (owner_kind IN ('person', 'role')),
    CONSTRAINT memories_visibility_check CHECK (visibility IN ('master', 'working', 'promoted'))
);

CREATE INDEX IF NOT EXISTS memories_owner_idx ON memories (owner_id, owner_kind);
CREATE INDEX IF NOT EXISTS memories_category_idx ON memories (category);
CREATE INDEX IF NOT EXISTS memories_index_state_idx ON memories (index_state) WHERE deleted_at IS NULL;
