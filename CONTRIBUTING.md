# Contributing / local development

**Status: draft. Most of the pipeline below (steps 5+ of the build order in
`README.md`) is not implemented yet — this is what running against this
repo today actually looks like, plus what changes once each step lands.**

## Prerequisites

- Docker + Docker Compose v2 (`docker compose version`).
- A model API key for whichever provider you'll point `MODEL_API_KEY` /
  `MODEL_BASE_URL` at (see `.env.example`). This stack does not ship a
  chat-sized local model.
- Python 3.11+ if you're working on `scripts/bootstrap-mattermost.py` or any
  future Python tooling in this repo. Nothing here is pinned to 3.11 the
  way the private Friday process is, but matching it avoids surprises.
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
  `MODEL_THINK`, `MODEL_FAST`).
- Leave `POSTGRES_PASSWORD` and `BOARD_PASSWORD` blank for now if you're
  just reading code — nothing here mints or checks them yet (see "What
  works today" below). Do not put a real production password in this repo's
  `.env`; it lives only on your machine and is already gitignored.
- Leave `MATTERMOST_ENABLED`, `CLOUDFLARE_ENABLED`, `HEADSCALE_ENABLED` at
  `0` unless you are specifically working on one of those optional doors.

## What works today vs. what's a placeholder

| Piece | State |
|---|---|
| `compose.yml` | Valid Compose file; `friday`, `board`, `memory-mcp` images are named but not published anywhere — `docker compose up` will fail to pull them |
| `scripts/bootstrap.sh` | Writes `.env` from the example, then exits with a message — does not run bootstrap-memory yet |
| `scripts/bootstrap-memory.sh` | Placeholder; exits 1 immediately |
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
   docker compose --profile core up qdrant ollama postgres
   ```

   This is the closest thing to a working slice of this stack today —
   useful for developing `bootstrap-memory.sh` or the memory schema against
   real services.

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

## Where the authoritative plan lives

This repo intentionally carries only a compressed, generic version of the
plan. If you need the full detailed design (executor internals, USB image
build, per-service env var lists, migration/rollback semantics) — that's in
the private `friday-architecture` repo's `plans/OPEN_SOURCE_ONBOARDING.md`
and isn't duplicated here. Open an issue if a doc in this repo is missing
context you need to contribute; docs get expanded deliberately, section by
section, as each build-order step actually lands (see README "Build order").
