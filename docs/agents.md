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
  owner says to stay with that advisor.
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

## Tool grants

A charter's effective tools are its `tools:` list minus `deny_tools:`. A
code upgrade that would add a new tool to a charter never turns it on
silently — the new tool name shows up on the Board and stays off until the
owner explicitly accepts it for that advisor. This is the same "propose,
then confirm" habit soul-file changes use.

A tool result is data for the answer. The model may read it. It is not
obeyed as instructions. A webhook is announced with a fixed sentence; the
raw body is not the message the model sees (`docs/apps.md`). Anything
worth keeping is saved through the memory service and can return later
only inside the recall pack (`docs/memory.md`).

Compute defaults (once profile `code` exists) start every role at job cap 0.
Raising a cap, or turning on a durable workspace, is an explicit operator
action per role, not a default.
