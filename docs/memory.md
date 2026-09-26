# Memory

**Status: draft.**

## Two stores, one id per fact

- **Postgres** (`memories` table, see `sql/memories.sql`) is the authority
  for a memory. The row and its indexing-queue item commit in one
  transaction, under an id created for that memory. Each memory has a
  monotonic `revision`.
- **Qdrant** holds the embedding (768 dimensions, `nomic-embed-text` via
  Ollama, cosine distance) for semantic recall, tagged with that same id.

## Collections (all cosine, 768 dimensions, `on_disk: true`)

| Collection | Created at | Who writes | Who may read |
|---|---|---|---|
| `friday_profile` | bootstrap | Remembers, and reflection folding episodes into stable facts | The owner's own turns |
| `friday_episodes` | bootstrap | A short note per turn | Owner recall and the reflection job |
| `friday_findings` | bootstrap | Research cards, fetched-page summaries | Owner hub search |
| `friday_persona` | bootstrap | Stable traits the persona pass extracts | Owner portrait questions |
| `knowledge` | bootstrap | Decisions/docs the operator asks to keep, tagged with a `topic` | Hub search for every owner turn |
| `cabinet_working` | bootstrap | A role's working notes | That role only — a search without an owner filter is refused |
| `role_profile_<role_id>` | first time that role remembers | That role's working notes | That role's own gather/recall |
| `person_profile_<person_id>` | first time that person is added | That person's notes | That person's own turns |
| `person_episodes_<person_id>`, `person_persona_<person_id>` | same moment | That person's episodes/traits | That person's own turns |

A new install ships with an empty `family_shared` — pooled memory shared
across household members is opt-in, not a default, because it can leak one
person's notes into another person's answers.

## Per-person isolation is the hard rule

Every Postgres row and every Qdrant payload carries `owner_id` (immutable
person or role id) and `owner_kind` (`person` or `role`). Every read and
write path — recall, search, reflection, export, and an advisor looking
something up on someone's behalf — checks that id. A failed check returns
nothing from another person's store. A person and a role never share a
namespace. The first release ships with one owner; a second person is a
later release, gated on these isolation tests passing.

## Delete/update race safety

One worker at a time holds a per-memory lock, from the moment it claims an
indexing-queue item until Qdrant has been updated. The claim is a
conditional update (`revision` and `deleted_at` checked in the same
statement), never a read followed by a later write. A missing Qdrant point
is never read as proof a memory is alive — upsert would just insert it.
Under the lock: a live row whose revision still matches becomes an upsert;
a row with `deleted_at` set becomes a delete, with no upsert sent; if the
revision moved before the claim, the item is dropped. After Qdrant returns,
the same lock re-checks Postgres and deletes the point if a tombstone won,
before releasing the lock. This has to hold even when the point was already
gone before a late upsert arrives, and even when an earlier revision's
write completes after a later revision's write.

## `sql/memories.sql` columns

`id`, `owner_id`, `owner_kind`, `revision`, `content`, `title`, `tags`,
`category`, `pinned`, `visibility` (`master`, `working`, `promoted`),
`index_state`, `deleted_at`, `promoted_from`, `promoted_at`, `created_at`,
`updated_at`. Writing the same content for the same owner updates the row
and increments `revision` rather than creating a duplicate.

## Backup

Backup is a coordinated pause, not four files copied independently whenever
each finishes. Delivery workers, the index reconciler, and executor
mutations stop first; an in-flight journal step is left clearly finished or
clearly unfinished. SQLite is copied through the SQLite backup API (never a
raw copy of a live file). The Postgres dump and the Qdrant snapshot are
taken inside that same pause, then writers resume. Optional-app data
(Jellyfin's config, the movie files) is explicitly excluded from this
manifest — restoring the core never rolls optional apps backward.

## `scripts/bootstrap-memory.sh` (intended sequence, not yet implemented)

1. Wait for Qdrant and Ollama to be healthy.
2. Confirm the probe embedding has length 768; refuse to continue on a
   mismatch, so a different embed model never silently mixes into the same
   collection.
3. Create the collections above if missing — an existing collection is left
   alone so a second boot never wipes notes.
4. Create keyword payload indexes on `owner_id`, `owner_kind`, `topic`,
   `source`.
5. Apply `sql/memories.sql`.
6. Write one smoke-test point, search it back above a score threshold,
   delete it, and only then exit 0.

This document will be filled in with the concrete API once memory-mcp is
generalized for this stack (see README "Build order", step 1).
