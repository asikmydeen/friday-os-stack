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
- Every advisor shares the same memory, the same receipts, and the same
  app registry as Friday. Installing an app never creates a new "person" to
  talk to — the relevant advisor just gains that app's tools.

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
`content`. An operator copies the ones they want into `charters/` (or
points the compose mount at both directories) to enable them. None of them
contain any household-specific detail — they're job descriptions, not
people.

## Tool grants

A charter's effective tools are its `tools:` list minus `deny_tools:`. A
code upgrade that would add a new tool to a charter never turns it on
silently — the new tool name shows up on the Board and stays off until the
owner explicitly accepts it for that advisor. This is the same "propose,
then confirm" habit soul-file changes use.

Compute defaults (once profile `code` exists) start every role at job cap 0.
Raising a cap, or turning on a durable workspace, is an explicit operator
action per role, not a default.
