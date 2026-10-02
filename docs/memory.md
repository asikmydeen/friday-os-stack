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
| `friday_episodes` | bootstrap | `friday/ask.py` writes one short note per spoken turn. A stay, a remember, and a waiting turn do not. | Owner recall and the reflection job |
| `friday_findings` | bootstrap | `memoryd/card.py` records one research card. With `POSTGRES_HOST` set, `POST /card` writes it through `memory_save`. Without that host it stays on the file store. The raw page is not stored. It does not create a collection. | This owner's hub search, with an owner filter. A missing filter is refused. Friday's ask path does not call the writer. |
| `friday_persona` | bootstrap | `memoryd/persona.py` copies profile notes into one persona row on the file store. It does not create a collection. | A portrait question on that module. Friday's ask path does not call it. |
| `knowledge` | bootstrap | `memoryd/card.py` records one kept decision. With `POSTGRES_HOST` set, `POST /card` writes it through `memory_save`. Without that host it stays on the file store. A separate topic label is not stored. It does not create a collection. | This owner's hub search, with an owner filter. A missing filter is refused. Friday's ask path does not call the writer. |
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
person or role id) and `owner_kind` (`person` or `role`). Recall and
search check that id. A missing filter is refused. An advisor turn in
`friday/ask.py` uses the role's id, so it does not read the person's
notes or another person's notes. `memoryd/isolate.py` is the same check
for reflection, export, and an advisor lookup of someone else. The caller
and the subject have to be the same id and the same kind. A different
subject returns nothing, and reflection writes nothing. A role does not
read a person's notes, even when the id text matches. Reflection reads
the newest 8 of that owner's episode rows and saves one profile note for
that same owner. A credential-shaped episode is left out of that note.
When every row in that window is a credential, reflection writes nothing.
It does not call a model, it does not create a
collection, and `role_profile_*` stays uncreated. A spoken model turn
writes one episode for that owner: the owner's words and the reply,
trimmed to 1200 characters. A credential-shaped turn is left out,
including a percent-encoded or plus-encoded copy. A stay, a remember,
and a waiting turn do not write one. Ordinary remembers stay category
`note`, so reflection still has nothing to fold when those are the only
rows. Reflection folds episode rows into one profile note. A role's
episode is stored as that role and does not create a collection.
Export returns at most
8 trimmed notes for that owner. It is not a dump of the database. The
memory service exposes `POST /reflect` and `POST /export` on the same
token as recall. No new host port. These checks were not run against a
live Postgres. A person and a role never share a namespace. The first
release ships with one owner; a second person is not shipped.

## Recall pack

Every recall, including hub search over `knowledge` and
`friday_findings`, filters on `owner_id` and `owner_kind`. A missing
filter is refused. That holds on the first release, which has one owner,
so a second person does not require a new layout for these two
collections. `memoryd/hub.py` is that hub search. It queries only those
two collections. It does not query `friday_profile`, `friday_episodes`,
`friday_persona`, or `cabinet_working`. A missing owner is refused
before the embed. Another owner, including a role asking for a person,
is not searched. A credential-shaped query, owner, or topic is refused
and is not shown, including a percent-encoded or plus-encoded copy.
A stored note whose content or topic is credential-shaped is not shown.
`token=abcd` and "password is hunter22" are refused.
"The password is kept outside the machine" can be the query. At most 8
notes are returned, each trimmed to 1200 characters. `confirmed=true`
does not change that. The module does not create a collection and does
not write a point. `POST /hub` uses the same memory token as recall.
Friday's /ask calls that route for that owner and adds those notes to
the same pack of at most 8. A hub that is not ready leaves the note
pack unchanged. This check was not run against a live Qdrant.

`memoryd/persona.py` copies that owner's newest 8 profile notes into one
persona note on the file store. An ordinary remember is category `note`,
and an episode is not a profile row, so neither is copied. A
credential-shaped line is left out, including a percent-encoded or
plus-encoded copy. `token=abcd` and "password is hunter22" are not
stored. "The password is kept outside the machine" can be copied. When
every row in that window is a credential, nothing is written. The profile
rows stay. A second copy of the same text bumps that persona row. A
portrait question (`who am i`, `what am i like`) returns at most 8
persona notes, each trimmed to 1200 characters, and no other category.
A credential-shaped note id is not shown, including a percent-encoded or
plus-encoded copy. An empty id is not shown. Chat cannot extract or read
them. The Postgres client refuses category
`persona` and does not connect. `POST /save` does not write that
category. `POST /persona` is the memory route. No collection is created.
`role_profile_*` is not created. Friday's ask path does not call it.
This check was not run against a live Postgres.

`memoryd/card.py` records one research card or one kept decision for
that owner. Without `POSTGRES_HOST` the row stays on the file store.
The card is category `finding`. The
decision is category `knowledge`. A raw page is not stored, including a
percent-encoded or plus-encoded copy and a copy rebuilt by that removal. A credential-shaped summary is
not stored. `token=abcd` and "password is hunter22" are not stored.
"The password is kept outside the machine" can be stored. Chat cannot
record one. With `POSTGRES_HOST` set, `POST /card` writes that row
through `memory_save`. A second card of the same text revises that one
row. `POST /save` still refuses those categories and does not connect.
`POST /card` is the memory
route. No collection is created. A separate topic label is not stored.
Friday's ask path does not call it. A tool result is still not saved.
This check was not run against a live Postgres.

The memory service returns at most 8 notes, each already trimmed to a
few hundred words. Friday sends the question and that pack to the chat
provider. The provider does not receive the database. An MCP caller of
Friday is not a bypass: the same owner filter and the same cap apply,
and the caller does not receive the Qdrant key. A tool result stays
evidence in the prompt and is not saved. A fetched page is not appended
to the pack as instructions. A one-character edit is a new live
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
moved before the claim, the queue item is marked done and dropped.
`memoryd/index.py` reads the row again after the embed and before the
upsert. A tombstone is a delete, and that path does not upsert. A newer
revision is not written over the point. After Qdrant returns, the worker
re-checks the row. A tombstone deletes the point. If this claim's payload
revision is still the point and the row has moved on, that payload is
removed. A point whose revision is already newer is left in place. The
worker then calls `memory_index_finish`. A worker that committed the claim
and then died is reclaimable after 5 minutes (`done_at` still null). The
same rule holds when the point was already gone before a late upsert
would have arrived, and when an earlier revision finishes after a later
one. These checks are in the worker. They were not run against a live
Qdrant in this change.

## `sql/memories.sql` columns

`id`, `owner_id`, `owner_kind`, `revision`, `content`, `title`, `tags`,
`category`, `pinned`, `visibility` (`master`, `working`, `promoted`),
`index_state`, `deleted_at`, `promoted_from`, `promoted_at`, `created_at`,
`updated_at`. Callers write through `memory_save`. A save whose text
looks like a credential is refused, and nothing is written. The words
password and token, with no value, are not a credential. An assignment
such as `token=abcd` is a credential. So is "password is hunter22",
because that value contains a digit. "The password is kept outside the
machine" has no value and is stored. `qdrant_store` is refused. The index
worker still upserts a point that `memory_save` already accepted.
`sql/memories.sql` raises `credential` before the insert. The unit tests
cover the Python gate and do not open Postgres. A second save of the
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
`memoryd/promote.py` makes that copy. The Board is the only actor.
Chat is refused, and `friday/ask.py` does not call it. The working row
stays, including its revision. A second call bumps the copy and does
not add a third row. A promoted row that points at a different id is
not revised. A credential-shaped working row is not copied. "The
password is kept outside the machine" can be copied. With
`POSTGRES_HOST` set, `POST /promote` writes that copy through
`memory_save` and keeps the working row's id in `promoted_from`. A
promoted save with no pointer is refused and does not connect. `POST
/save` still does not promote. No collection is created. This check
was not run against a live Postgres.

`memoryd/soul.py` records one proposal for `SOUL.md` or `CHAPTER.md`.
The Board applies that proposal only when the presented token matches
the one the caller supplies. The token is not stored. A blank token
does not apply. A credential-shaped token does not apply. A week flag
does not apply it. A proposal whose name is not one of those two files
does not replace the current text. The previous text stays on the
record. The example file is not read or written. Chat cannot record or apply, and Friday's ask
path does not call it. `POST /soul` is not a memory route. No
collection is created.

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

Postgres init applies this file only on an empty data directory.
`scripts/bootstrap-memory.sh` applies it again on every run. Re-applying it
does not migrate an older volume — an older `person_id`/`kind` layout, or an
earlier draft that indexed raw `content` or omitted `done_at`. Recreate
`postgres_data`, or migrate that volume explicitly, before expecting these
indexes and functions.

## Backup

Backup is a coordinated pause, not four files copied independently whenever
each finishes. Delivery workers, the index reconciler, and executor
mutations stop first; an in-flight journal step is left clearly finished or
clearly unfinished. SQLite is copied through the SQLite backup API (never a
raw copy of a live file). `backup/sqlite.py` is that copy: one open
connection, including one named file-backed connection, into a destination
the executor already opened, and only while writers are paused.
A path is not opened. A byte copy of a live file stays refused. An unnamed temporary disk database stays refused. Chat cannot
run it, and Friday's ask path does not call it. The Postgres dump and the Qdrant snapshot are
taken inside that same pause, then writers resume. Optional-app data
(Jellyfin's config, the movie files) is explicitly excluded from this
manifest — restoring the core never rolls optional apps backward.

`backup/coordinated.py` and `sql/backup.sql` are that pause and the
manifest. The passphrase is not stored in the manifest. Chat cannot
start the pause. An upgrade writes the inactive system slot only. If
that slot's `/ready` fails, the boot attempts run out, or power is
lost, the pre-upgrade backup is restored before the old slot boots.
`updates/packages.py` refuses an open-ended apt upgrade and does not apply it.
A reflash is a new install, not an upgrade, and it does not erase a disk.
Delivery workers stay paused until a restored pending send has asked
the provider. A provider that already accepted it is not sent again. A
provider that cannot say leaves the item for the owner. A blank-host
restore loads that manifest onto a new box and returns the same
caller-supplied memory. Restarting the box that sealed it is not that
restore. A pending or uncertain delivery stays unsent until the provider
is asked. The idempotency key is kept on the row and is not sent. No
collection is created. `backup/sqlite.py` does not open a file. With POSTGRES_HOST set, the executor calls `backup_store` for one pause. A second store of that pause returns the same id. Without that host the manifest stays in memory. A live SQLite method, a passphrase, a movie name, and catalog install are refused before the connection opens. Chat cannot record one. Friday's ask path does not import that call. The Board form is separate from the life-step button. The image compose gives the executor the Postgres settings and mounts `sql/backup.sql` for a new data directory. The unit test uses a stub connection. This cut does not copy a disk, does not start a
container, and Compose has no backup service. It was not run against a
live Postgres.

## `scripts/bootstrap-memory.sh`

`scripts/bootstrap-memory.sh` performs this sequence. `memoryd/` is the
notes service Compose calls memory-mcp. When `POSTGRES_HOST` is set,
a save calls `memory_save` and a tombstone calls `memory_tombstone`.
Recall reads the `memories` table. A worker claims `memory_index_queue`,
embeds a live row with `nomic-embed-text`, and upserts that point under
the same id. A tombstone deletes the point. A person note is stored in
`friday_profile`, an episode in `friday_episodes`, a finding in
`friday_findings`, a persona note in `friday_persona`, and a knowledge
note in `knowledge`. The Postgres client refuses category `persona`, so that row stays on
the file store and that save does not connect. A finding and a
knowledge note are written by `POST /card` through `memory_save` when
`POSTGRES_HOST` is set. `POST /save` still refuses those categories and
does not connect. A role is stored in `cabinet_working`, so it does
not share the person's collection. `family_shared`, `person_*`, and
`role_profile_*` are not created. Search requires `owner_id` and
`owner_kind`, and the pack stays at 8. Without `POSTGRES_HOST`, those
same owner rules stay in a JSON file and this SQL is not called.
`scripts/prove-memory.sh` runs the Postgres path on throwaway
containers. That proof uses a 768-number stub in place of Ollama.
`scripts/prove-embed.sh` pulls `nomic-embed-text` into a throwaway
Ollama, leaves the Compose project's Ollama volume alone, and
`memoryd`'s client receives a vector of length 768. v0.0.1 does not
contain this service or that model. A later local image packs both.
Its QEMU boot started the core, which checks that local embed. That
compressed file is over the GitHub release limit and is not the
published download.

1. Wait until Qdrant (`/readyz`) and Ollama (`/api/tags`) answer.
2. Confirm `nomic-embed-text` returns a vector of length 768 before any
   collection is created. The tags list has to name that model, or that
   name plus one tag. A name that only starts with the pin does not
   count. A 200 from `/api/embed` has to name the model. A missing id
   on that reply is refused, and the older endpoint is not tried. The
   older embeddings endpoint is used only when `/api/embed` does not
   answer. It may omit the id. A reply that names a different model is
   refused, including one that also returns 768. The memory client does
   the same when a reply names a model, and still accepts an unnamed
   768-vector from the older endpoint. These checks were not run
   against a live Ollama.
3. Create the collections above if they are missing. An existing collection
   is left in place, so a second run does not wipe notes. A collection whose
   size is not 768, or whose distance is not cosine, is left in place and
   the script stops.
4. Create keyword payload indexes on `owner_id`, `owner_kind`, `topic`,
   and `source`. There is no `member_key` index and no `agent_id` index.
   `image/qdrant_bootstrap.py` requests those four for the same six
   collections. An existing collection is left in place, including its
   points, and an index the collection does not already list is still
   requested. `memoryd/qdrant.py` does the same when the index worker
   ensures a collection. A size other than 768, or a distance other than
   cosine, is refused and nothing is written. `family_shared` is not
   created. That request was not run against a live Qdrant.
5. Apply `sql/memories.sql`.
6. Write one smoke-test point, search it back above a score threshold,
   delete it, and only then exit 0. `image/qdrant_bootstrap.py` does that
   round trip after the six collections exist. The only id it deletes is
   the fixed smoke id. Other points stay. When every collection count is
   zero after that delete, the setup screen says `Notes: empty`. Any
   other count says `Notes: kept`. A missing hit, a low score, or a count
   that fell does not say empty, and the core does not start. It does not
   write Postgres. This check was not run against a live Qdrant.
