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
| `friday_findings` | bootstrap | Research cards, fetched-page summaries | This owner's hub search, with an owner filter. A missing filter is refused |
| `friday_persona` | bootstrap | Stable traits the persona pass extracts | Owner portrait questions |
| `knowledge` | bootstrap | Decisions/docs the operator asks to keep, tagged with a `topic` | This owner's hub search, with an owner filter. A missing filter is refused |
| `cabinet_working` | bootstrap | A role's scratch notes for the current turn/session | That role only — a search without an owner filter is refused |
| `role_profile_<role_id>` | first time that role remembers something worth keeping | That role's durable notes | That role only — a search without an owner filter is refused |
| `person_profile_<person_id>` | first time that person is added | That person's notes | That person's own turns |
| `person_episodes_<person_id>`, `person_persona_<person_id>` | same moment | That person's episodes/traits | That person's own turns |

`cabinet_working` and `role_profile_<role_id>` are different stores.
`cabinet_working` is created at bootstrap and holds scratch notes for the
current turn. `role_profile_<role_id>` is created the first time that role
keeps a durable note. A search of either store without an owner filter is
refused. The same split exists between `friday_*` (bootstrap, the owner's
own notes) and `person_profile_<person_id>` (lazy, a second person's notes).
For the first release, with exactly one owner and no second person yet,
`friday_*` is the only one of that pair that has any data in it. A role id
and a person id are different collection names (`role_profile_` versus
`person_profile_`) even when the id text matches.

`family_shared` is not created by bootstrap and does not exist on a fresh
install. Pooled memory shared across household members is opt-in, not a
default, because it can leak one person's notes into another person's
answers — and the first release has exactly one owner, so there is no
household to pool across yet. `family_shared` is created explicitly, the
first time a second household member is added and the owner opts into
shared logistics (see `charters/full/family.md`); until then, no code path
reads or writes it.

## Per-person isolation is the hard rule

Every Postgres row and every Qdrant payload carries `owner_id` (immutable
person or role id) and `owner_kind` (`person` or `role`). Every read and
write path — recall, search, reflection, export, and an advisor looking
something up on someone's behalf — checks that id. A failed check returns
nothing from another person's store. A person and a role never share a
namespace. The first release ships with one owner; a second person is a
later release, gated on these isolation tests passing.

## Recall pack

Every recall, including hub search over `knowledge` and
`friday_findings`, filters on `owner_id` and `owner_kind`. A missing
filter is refused. That holds on the first release, which has one owner,
so a second person does not require a new layout for these two
collections.

The memory service returns at most 8 notes, each already trimmed to a
few hundred words. Friday sends the question and that pack to the chat
provider. The provider does not receive the database. Tool results and
fetched pages can be saved as notes through `memory_save`. They are not
appended to the pack as instructions. A one-character edit is a new live
row, because the identity includes `md5(content)`. The pack cap is what
keeps that growth from being sent out in full.

## Delete/update race safety

One worker at a time holds a per-memory lock, from the moment it claims an
indexing-queue item until Qdrant has been updated. `memory_index_claim`
does that with a conditional update: the `memories` row is locked only when
`revision` still matches the queue item, in the same statement, never as a
read followed by a later write. A missing Qdrant point is never read as
proof a memory is alive — upsert would just insert it. Under the lock: a
live row whose revision still matches becomes an upsert; a row with
`deleted_at` set becomes a delete, with no upsert sent; if the revision
moved before the claim, the queue item is marked done and dropped. After
Qdrant returns, the worker re-checks the row under that same lock and
deletes the point if a tombstone won, then calls `memory_index_finish`
before the lock is released. A worker that committed the claim and then died is
reclaimable after 5 minutes (`done_at` still null). This has to hold even
when the point was already gone before a late upsert arrives, and even when
an earlier revision's write completes after a later revision's write.

## `sql/memories.sql` columns

`id`, `owner_id`, `owner_kind`, `revision`, `content`, `title`, `tags`,
`category`, `pinned`, `visibility` (`master`, `working`, `promoted`),
`index_state`, `deleted_at`, `promoted_from`, `promoted_at`, `created_at`,
`updated_at`. Callers write through `memory_save`. A second save of the
same live identity — `owner_id`, `owner_kind`, `visibility`, `category`,
and content — updates that row and increments `revision`. The unique index
that enforces it is `(owner_id, owner_kind, visibility, category, md5(content))`
where `deleted_at` is null. The hash is the indexed value because a btree
entry cannot exceed about 2704 bytes, and a note of a few paragraphs would
otherwise fail the insert. `category` defaults to `''` rather than SQL
`NULL`, because two `NULL`s are distinct in a unique index and the dedup
would silently stop. A raw `INSERT` of a duplicate raises `unique_violation`;
it does not bump `revision`. That bump lives in `memory_save`.

A promoted copy is a second live row: `memory_save` with
`visibility = 'promoted'` and `promoted_from` set to the working row.
Visibility is part of the unique key, so the copy is not collapsed into
the row it came from. `owner_kind` is part of the key for the same reason
a person and a role must not share a row when their id text matches.

`memory_index_queue` is a separate table. The memory row and its queue item
commit in the same transaction: an insert trigger, and an update trigger
that runs when `revision` changes, insert `(memory_id, revision)`, which
is unique. A worker
calls `memory_index_claim(worker)`. The claim takes the oldest row with
`done_at` null whose `claimed_at` is null or older than 5 minutes, then
conditionally updates `memories` only when `revision` still matches. The
returned `deleted_at` tells the worker whether Qdrant gets an upsert or a
delete. A revision mismatch marks that queue item done and the claim moves
on. `memory_index_finish` sets `done_at` after Qdrant returns. `index_state`
is a display label, not the work list. The queue's foreign key is
`ON DELETE RESTRICT`, so a hard delete cannot throw away a Qdrant delete
that has not finished. Soft delete is `memory_tombstone`.

`visibility` has no default. Friday's own notes pass `'master'`. Role and
person working notes pass `'working'`. A `BEFORE UPDATE` trigger rejects
any change to `owner_id` or `owner_kind`.

This file is applied from Postgres init, which runs only on an empty data
directory. An existing volume — an older `person_id`/`kind` layout, or an
earlier draft of this file that indexed raw `content` or omitted `done_at` —
is not migrated by applying the script again. Recreate `postgres_data`, or
migrate that volume explicitly, before expecting these indexes and functions.

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

The service that performs these steps is not implemented yet. The sequence
above is the contract it has to follow (see README "Build order", step 1).
