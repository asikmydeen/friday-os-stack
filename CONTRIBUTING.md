# Contributing / local development

**Status: draft.** The v0.0.1 test installer is in `image/`. The finished
appliance, and steps 6 onward in the README build order, are not
implemented yet. This page is what running against this repo today
actually looks like.
The product those steps are building is the local agent in
`docs/system.md`: a computer in the house, doors, devices, MCP, and a
browser session, with the catalog as a guest.

## Prerequisites

- Docker + Docker Compose v2 (`docker compose version`).
- A model API key for whichever provider you'll point `MODEL_API_KEY` /
  `MODEL_BASE_URL` at (see `.env.example`). This stack does not ship a
  chat-sized local model.
- Python 3.11+ for `image/`, `gate/`, `webhooks/`, `backup/`, and
  `scripts/bootstrap-mattermost.py`.
- `git` and (optionally) the GitHub CLI (`gh`) if you're opening PRs.

## First-time setup

```bash
git clone https://github.com/asikmydeen/friday-os-stack
cd friday-os-stack
cp .env.example .env        # then edit .env — see below
```

Fill in `.env`:
- `OWNER_NAME`, `OWNER_TIMEZONE` — your own values, not a placeholder.
- Exactly one model provider block (`MODEL_API_KEY`, `MODEL_BASE_URL`,
  `MODEL_THINK`, `MODEL_FAST`). Product setup keeps chat off until that
  endpoint returns a real reply (`docs/secrets.md`). Nothing in this repo
  probes it yet.
- `BOARD_PASSWORD` may stay blank while you are only reading code — nothing
  here checks it yet. `POSTGRES_USER` may stay blank (the Postgres image
  then uses `postgres`). `POSTGRES_PASSWORD` must be a non-empty local
  value before the infra command below; the image exits on startup when it
  is empty. Do not put a real production password in `.env`. It lives only
  on your machine and is already gitignored.
- Leave `MATTERMOST_ENABLED`, `CLOUDFLARE_ENABLED`, `HEADSCALE_ENABLED` at
  `0` unless you are specifically working on one of those optional doors.

## What works today vs. what's a placeholder

| Piece | State |
|---|---|
| `compose.yml` | Valid Compose file; `friday`, `board`, `memory-mcp` images are named but not published anywhere — `docker compose up` will fail to pull them |
| `scripts/bootstrap.sh` | Writes `.env` from the example, then exits with a message — does not run bootstrap-memory yet |
| `scripts/bootstrap-memory.sh` | Starts Qdrant, Ollama, and Postgres, checks that `nomic-embed-text` is 768 dimensions, creates the six collections, and applies `sql/memories.sql`. Does not start Friday, the Board, or memory-mcp |
| `gate/`, `sql/approvals.sql` | Approval rules and the task journal. Chat cannot create or exchange an approval. Catalog install is refused. `python3 -m unittest discover -s tests -t .` covers the rules. The executor container is not in Compose |
| `webhooks/`, `sql/webhooks.sql` | An app post is classified and stored. The header `Friday-Webhook` must match that app. The announcement is one fixed sentence. The same unittest command covers `tests/test_webhooks.py`. Compose has no webhooks service |
| `backup/`, `sql/backup.sql` | Writers pause before the stores are copied. A live SQLite file and a stored passphrase are refused. A failed upgrade restores the backup before the old slot boots. The same unittest command covers `tests/test_backup.py`. Compose has no backup service |
| `image/`, `tests/test_install.py` | Disk rules, the text-console installer, and the local setup page. The same unittest command covers them. The USB image is a GitHub release, not a file in git. v0.0.1 does not contain Friday, the Board, Docker, or the core containers |
| `scripts/bootstrap-mattermost.py` | Placeholder; exits 1 immediately |
| `charters/`, `soul/SOUL.example.md` | Real content, usable today as the source of truth for what a charter/soul file should look like |
| `catalog/wires/*.yml` | Draft wire specs — not yet consumed by any renderer or executor |
| `docs/*.md` | Design docs describing the target; read these before writing code against this repo, since several pieces (executor, memory-mcp) don't exist here yet |

## How to work on this repo right now

Since the runnable core (`friday`, `board`, `memory-mcp` images) doesn't
exist in this repo yet, most contributions fall into one of these buckets:

1. **Docs and specs** (`docs/*.md`, `catalog/wires/*.yml`) — read/edit
   directly, no infra needed.
2. **Charters** (`charters/`, `charters/full/`) — plain Markdown with YAML
   frontmatter; no infra needed to review or add one.
3. **Compose/scripts scaffolding** (`compose.yml`, `scripts/*`,
   `sql/memories.sql`) — validate with `docker compose config` (syntax
   only; it will not start the placeholder images) and `shellcheck
   scripts/*.sh` if you have it installed.
4. **Bringing up the infra-only services** (Qdrant, Ollama, Postgres) to
   develop against them directly, without the `friday`/`board` images:

   ```bash
   # .env must contain a non-empty POSTGRES_PASSWORD or postgres exits.
   docker compose --profile core up qdrant ollama postgres
   ```

   `./scripts/bootstrap-memory.sh` is that same slice: it starts these three
   services, checks the embed model, creates the collections, and applies
   `sql/memories.sql`. Friday, the Board, and memory-mcp stay stopped.

## Secret hygiene before every push

Run a secret scanner before pushing anything that touches `scripts/`,
`compose.yml`, `.env.example`, or `catalog/`:

```bash
gitleaks detect --no-git -s .
# or
trufflehog filesystem .
```

Never commit `.env`, a real hostname, a real API key, or any file from the
"must never be committed" list in `docs/secrets.md`.

## Where the plan lives

`README.md` ("Build order") and `docs/` are the plan for this project.
Open an issue if a doc is missing context you need to contribute. Docs
grow as each build-order step lands.
