# Cabinet agents

**Status: draft.**

An agent ("Cabinet" advisor) is a charter file under `charters/<id>.md`:
YAML frontmatter (`id`, `name`, `title`, `aliases`, plus tool allow/deny
lists once tools exist) followed by a short mission in prose. The starter
set in `charters/` is generic — no family facts, no real house details, no
real infrastructure hostnames.

## Addressing in chat

- `@cto is the service up` or `ask my cfo what we spent` — a one-turn
  persona switch. The next turn is back to Friday's own voice unless the
  owner says to stay with that advisor. `friday/hat.py` keeps that stay
  in the process when the owner says "talk to my" or "stay with" a name.
  "stay with that advisor" keeps the charter from the latest one-turn
  address. "Back to Friday" clears it. An ask or an `@` mention does not
  replace it. A reply from that charter starts with the charter's name. The stay is
  not a note, a restart returns to Friday, and it does not write an
  episode.
- Every advisor reads and writes through the same memory API and the same
  app registry as Friday, but not the same namespace: `cabinet_working` and
  `role_profile_<role_id>` are scoped to that role's `owner_id`, and a
  search without an owner filter is refused (see `docs/memory.md`). A
  person and a role never share a namespace, so "same memory system" does
  not mean "one shared pool." Installing an app never creates a new
  "person" to talk to — the relevant advisor just gains that app's tools.
- A role can also carry a task on the task journal (`docs/system.md`).
  The task runs as Friday wearing that charter, under that role's owner
  id. It does not gain a tool because the goal mentioned one. Send, pay,
  delete, publish, and any machine change still wait for an approval the
  role cannot create.
- `friday/ask.py` recalls and saves an advisor turn under that role's id
  and `owner_kind=role`. The person's notes stay out, and so does any
  other person's. The index stores the row in `cabinet_working`.
  `role_profile_*` is not created. An advisor lookup of another person
  returns nothing from that person's notes (`memoryd/isolate.py`).

## Starter set (`charters/`)

| Charter | Why it's in the starter |
|---|---|
| `chief` | Day-to-day status: what's running, what's due, what needs a decision |
| `cto` | Service health and tracked work — the only starter role that talks about infrastructure at all, and even then only through the approval-gated executor |
| `cfo` | Spend tracking and costed calendar items, no real financial account access in the starter kit |
| `coach` | Light personal routines (journal, mood), never diagnostic |
| `home` | Smart-home device status/control, once Home Assistant is installed and a token is explicitly granted |
| `media` | Media-app status once a player and the `*arr` stack are installed and wired |

## Full pack (`charters/full/`)

A larger set of generic advisor roles ships inactive under `charters/full/`:
`advisor` (a blank template), `researcher`, `architect`, `backend`, `web`,
`mobile`, `tester`, `reviewer`, `buyer`, `shopper`, `fetcher`, `health`,
`family`, `legal`, `faith`, `travel`, `product`, `program`, `mentor`,
`content`. None of them contain any household-specific detail — they're
job descriptions, not people.

Only charter files directly under `charters/<id>.md` are active: Friday's
compose service bind-mounts `./charters` (not `./charters/full`) to
`/soul/agents`, and Compose has no way to union two host directories onto
one container path. Enabling a full-pack role means copying that file to
`charters/<id>.md`, or symlinking it with a relative target that stays
inside the mount:

```bash
ln -s full/<id>.md charters/<id>.md
```

That target resolves in the container to `/soul/agents/full/<id>.md`. An
absolute host path does not resolve there. Repointing the mount at
`./charters/full` would drop the starter set (`chief`, `cto`, `cfo`,
`coach`, `home`, `media`), since none of those files live under `full/`.

`cabinet/enable.py` records that decision and does not perform it. The
Board is the only actor. The only target kept is `full/<id>.md`. The
file is not copied and the link is not created. Family stays blocked. An
absolute path is refused. A mount pointed at the full pack is refused.
Chat cannot record one, and that refusal leaves a link already recorded.
A second record keeps the first link. A credential-shaped name is not
stored, including a percent-encoded or plus-encoded copy. The Board page lists those inactive names and records one relative link. It does not call that module. The file is not copied and job cap stays 0.
Friday's ask path does not call it. `role_profile_*` is not created, and
`family_shared` is not created.

## Tool grants

`cabinet/configure.py` is the decision. The candidate tools are the
charter's `tools:` list minus `deny_tools:`. A candidate is on only after
the Board accepts that name, so a code upgrade that adds a name does not
turn it on. A tool the charter does not name is shown and stays off until
the Board accepts it. A new name does not keep an older acceptance.
Accepting a name does not create an approval and does not run the tool.
Chat cannot accept one, and that refusal leaves a name the page already accepted. A request that does not name the Board as the actor does not store a secret or accept a tool. The Board page lists those six at job cap 0. Each has an ask box on that page. The chief's box calls the same Friday. A credential-shaped question is not sent. A stored secret is shown by name only. The shelf is kept beside the process environment, not on it. The page does not start taskrunner. The same page records claude-code or gsd, a budget of 5 to 180 minutes, a durable home named agent-<role>, and the collection cabinet_working. Job cap stays 0. The home is not created. Another collection is refused.

A tool result is data for the answer. The model may read it. It is not
obeyed as instructions. `friday/ask.py` puts a caller-supplied result in
the prompt as evidence. It is not the goal, it is not saved, and the
words inside it do not become the action. A credential-shaped result is
refused and is not shown, including a percent-encoded or plus-encoded copy. The Board ask box and the messaging door do
not forward one. A webhook is announced with a fixed sentence; the
raw body is not the message the model sees (`webhooks/receiver.py`,
`docs/apps.md`). Anything
worth keeping is saved through the memory service and can return later
only inside the recall pack (`docs/memory.md`).

Every starter advisor lists at job cap 0. The cap stays 0 while the code
profile is off. The Board may record a cap from 0 to 3 when that profile
is on, and may record a durable home named `agent-<role>`. Neither record
starts taskrunner, and a job name `tr-<task>` is not created. `friday/state.py` records that name as a mirror while the code profile is on, and it still does not start taskrunner. `updates/ship.py` records the ship-mcp tool surface and returns the token name only. A caller-supplied value is not stored. Submitting work does not start taskrunner and does not call Coder. Friday's ask path does not call it. `updates/plan.py` records an optional coding-plan base URL for `claude-code` and returns the name `CODING_PLAN_URL` only. With that URL unset, nothing is stored and the Anthropic key is not read. A caller-supplied key is not stored. `ANTHROPIC_API_KEY` is reserved and no value is kept. Chat cannot record it, and that refusal leaves a URL already recorded. Recording it does not call the URL and does not start taskrunner. Friday's ask path does not call it. An engine
name and a budget of 5 to 180 minutes can be recorded the same way, and
the cap stays 0. A secret slot stores a value and returns the name only.
The only collection this cut records is `cabinet_working`. `role_profile_*`
is not created.
