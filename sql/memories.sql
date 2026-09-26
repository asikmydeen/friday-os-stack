-- Placeholder schema for the `memories` table that `memory_save` (memory-mcp) writes to.
-- This is a stub written for this public scaffold; it is not exported from the private
-- memory-mcp repository. Treat it as a starting point to refine once memory-mcp is
-- generalized into this stack (see README.md "Build order", step 1).

CREATE TABLE IF NOT EXISTS memories (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id   TEXT NOT NULL,
    kind        TEXT NOT NULL,
    title       TEXT,
    content     TEXT NOT NULL,
    tags        TEXT[] DEFAULT '{}',
    revision    INTEGER NOT NULL DEFAULT 1,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS memories_person_id_idx ON memories (person_id);
CREATE INDEX IF NOT EXISTS memories_kind_idx ON memories (kind);
