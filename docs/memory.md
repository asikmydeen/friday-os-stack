# Memory

**Status: draft.**

Durable memory is split across two stores that share one id per fact:

- **Postgres** (`memories` table, see `sql/memories.sql`) holds the durable
  row: content, tags, revision.
- **Qdrant** holds the embedding (768 dimensions, `nomic-embed-text` via
  Ollama) for semantic recall, tagged with the same id.

Memory is scoped per person. A second person in the household cannot recall,
search, or otherwise read another person's memories through any advisor.

Deleting a memory removes both the Postgres row and the Qdrant point; a
delete that races an in-flight embed must not leave an orphaned point behind.

This document will be filled in with the concrete API once memory-mcp is
generalized for this stack (see README "Build order", step 1).
