# friday-os-stack

**Status: experimental scaffolding. No release image exists yet. Do not run `bootstrap.sh` expecting a working appliance.**

This is the public monorepo for the open-source Friday appliance: a small always-on box that runs a chat assistant (Friday), a set of advisors (the Cabinet), a Board dashboard, and durable memory, with an optional catalog of self-hosted apps (media servers, home automation, etc.) layered on top.

The full plan this repo is being built against lives in a private companion repo and is summarized below. Nothing here is a fork of, or contains history from, any private repository. This tree starts from a single scrubbed commit.

## What this is not (yet)

- Not a bootable USB image.
- Not a tested installer.
- Not connected to any production instance, hostnames, secrets, or family data.
- Not ready for anyone to self-host from.

## Layout

```
friday-os-stack/
  compose.yml              profiles: core, chat, code, edge, mesh
  .env.example             names only, empty secrets
  config/
    hostnames.example.yml  which container each hostname hits
  charters/                starter Cabinet advisor charters, generic owner
    full/                  larger inactive advisor pack (copy in what you need)
  soul/SOUL.example.md     short character file the operator edits
  scripts/
    bootstrap.sh           writes .env, then runs the memory bootstrap
    bootstrap-memory.sh    waits for Qdrant and Ollama, creates collections, checks 768 dims
    bootstrap-mattermost.py generalized Mattermost setup
  sql/
    memories.sql           Postgres table memory_save writes to
  docs/
    architecture.md
    memory.md              collections, payloads, backup, second speaker
    agents.md
    secrets.md
    cloudflare.md
    headscale.md
    apps.md                catalog, bundles, adopt-existing, uninstall
  catalog/
    PIN                    commit of github.com/truenas/apps we render
    wires/                 our understanding of an upstream app id
  deploy/
    swarm/stack.yml        same services, for people already on Swarm
    helm/                  after Compose is proven
```

## Core pieces (planned)

| Piece | Role |
|---|---|
| Friday | Chat, Cabinet turns, console |
| Board | Discover screen: installed, available, health, grants |
| Qdrant | Semantic memory, cosine, 768 dimensions |
| Ollama (`nomic-embed-text`) | Turns a sentence into a vector; chat itself does not run a local model |
| memory-mcp + Postgres | Durable `memories` row, id shared with the Qdrant point |
| App executor | Separate process from the chatbot; accepts a named, approved operation only |

Left out of core on purpose: Mattermost, Telegram, Plex, Jellyfin, Radarr, Home Assistant, Coder, Cloudflare, Headscale, and any chat-sized local language model. Those are optional, allowlisted apps installed after the core boots.

## Developing against this repo

See `CONTRIBUTING.md` for prerequisites, first-time `.env` setup, what
actually runs today versus what's still a placeholder, and secret-scanning
before you push.

## License

Apache-2.0 (see `LICENSE`), unless changed before the first tagged release.

## Build order

This repo is being built up in stages before any release image is produced:

1. Private portability branch work (memory isolation, env defaults) lands upstream first.
2. Mattermost made generic as an optional door.
3. Starter Cabinet charters and example soul (no live family/owner data).
4. This experimental source snapshot — where we are now.
5. Executor, recovery, and appliance checks (approval records, mount roots, webhook receiver, coordinated backup, USB image build + scan).
6. First allowlisted app wires (media stack).
7. Optional code/edge/mesh profiles (Taskrunner, tunnels, mesh networking).
8. Helm chart for core, after Compose is proven.

No step past 4 has landed yet.
