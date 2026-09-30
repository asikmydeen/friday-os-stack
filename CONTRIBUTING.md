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
| `compose.yml` | Builds `friday`, `board`, `memory-mcp`, and `executor` from this tree. The tags are local. They are not in a registry. Empty tokens make those four processes exit, and their restart policy is `no`. v0.0.1 does not contain them |
| `scripts/bootstrap.sh` | Writes `.env` from the example, then exits with a message — does not run bootstrap-memory yet |
| `scripts/bootstrap-memory.sh` | Starts Qdrant, Ollama, and Postgres, checks that `nomic-embed-text` is 768 dimensions, creates the six collections, and applies `sql/memories.sql`. Does not start Friday, the Board, or memory-mcp |
| `gate/`, `sql/approvals.sql`, `executor/` | Approval rules and the task journal. Chat cannot create or exchange an approval. Catalog install is refused. The executor records the row and does not send mail or start a container. `python3 -m unittest discover -s tests -t .` covers the rules |
| `webhooks/`, `sql/webhooks.sql` | An app post is classified and stored. The header `Friday-Webhook` must match that app. The announcement is one fixed sentence. The same unittest command covers `tests/test_webhooks.py`. Compose has no webhooks service |
| `backup/`, `sql/backup.sql` | Writers pause before the stores are copied. A live SQLite file and a stored passphrase are refused. A failed upgrade restores the backup before the old slot boots. The same unittest command covers `tests/test_backup.py`. Compose has no backup service |
| `image/`, `tests/test_install.py` | Disk rules, the text-console installer, and the local setup page. The same unittest command covers them. The USB image is a GitHub release, not a file in git. v0.0.1 does not contain Friday, the Board, Docker, or the core containers |
| `catalog/discover.py`, `tests/test_discover.py` | Lists a pin. The pin in this repo is empty, so the list is empty. Every install returns `catalog_install_closed`. Draft wires are not installed |
| `measure/ram.py`, `tests/test_ram.py` | Decides from numbers the caller supplies. A complete record is `not_a_hardware_measurement`. `fits` refuses declared memory above free RAM |
| `netpolicy/paths.py`, `tests/test_netpolicy.py` | Decides which name may open which port. Does not create a Docker network |
| `doors/reach.py`, `tests/test_doors.py` | The adapter delivers a turn and cannot approve. The mesh opens the Board. The tunnel stays off. Nothing listens |
| `mcpbus/grants.py`, `tests/test_grants.py` | Visible tools are the granted names the server also offers. A mutating inbound call waits and creates no approval |
| `browser/session.py`, `tests/test_browser.py` | The broker holds the secret. Read and draft proceed. Send, pay, delete, and publish wait |
| `guests/lifecycle.py`, `tests/test_guests.py` | Install stays closed. Adopt records `adopted` and starts nothing here. A managed uninstall keeps the files |
| `updates/signed.py`, `tests/test_updates.py` | An empty signature is unsigned. A signature string is `signature_not_checked` and is not applied. The code profile does not start taskrunner |
| `deploy/helm/` | A note. No chart. It waits until the Compose core is proven |
| `scripts/bootstrap-mattermost.py` | Placeholder; exits 1 immediately |
| `charters/`, `soul/SOUL.example.md` | Real content, usable today as the source of truth for what a charter/soul file should look like |
| `catalog/wires/*.yml` | Draft wire specs. `draft_ids()` reads the `id:` lines. No renderer or executor consumes them |
| `friday/`, `board/`, `memoryd/`, `runtime/` | The chat process, the Node screen, and the notes service. With `POSTGRES_HOST` set, saves call `memory_save` and the index worker writes Qdrant. Without it, notes stay in a JSON file. `scripts/prove-memory.sh` covers the Postgres path. `node --test board/server.test.js` covers the screen |

## How to work on this repo right now

1. **The four core processes** (`friday/`, `board/`, `memoryd/`, `executor/`) —
   `python3 -m unittest discover -s tests -t .` and `node --test board/server.test.js`.
   `./scripts/smoke-core.sh` builds the images and runs one conversation on a
   throwaway network. `./scripts/prove-memory.sh` calls `memory_save` on a
   throwaway Postgres and indexes one point. Neither script calls Compose.
2. **Docs and specs** (`docs/*.md`, `catalog/wires/*.yml`) — read and edit
   directly.
3. **Charters** (`charters/`, `charters/full/`) — plain Markdown with YAML
   frontmatter.
4. **Compose and the memory stores** — `docker compose config` checks syntax.
   Pass `--env-file .env.example` when you do not want your local `.env` in
   that output. `shellcheck scripts/*.sh` checks the scripts.

   ```bash
   # .env must contain a non-empty POSTGRES_PASSWORD or postgres exits.
   # Leave this alone if those three services are already running for you.
   docker compose --profile core up qdrant ollama postgres
   ```

   `./scripts/bootstrap-memory.sh` starts those three services, checks the
   embed model, creates the collections, and applies `sql/memories.sql`.
   It does not start Friday, the Board, or memory-mcp. A chat-profile start
   needs the tokens in `.env.example`. Empty tokens make the four processes
   exit.

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
