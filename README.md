# friday-os-stack

**Status: experimental scaffolding. No release image exists yet. Do not run `bootstrap.sh` expecting a working appliance.**

Friday is a local do-it-all agent. One always-on computer in the house runs it. You reach it from your phone and from a chat app, and from the Board on the machine. It remembers on that computer. It calls the other AI harnesses you run, and they can call it, through MCP, with each tool granted by you. A site with no MCP is used through a browser session on the same computer. Work continues after you close the chat, and Friday comes back when it needs a decision. It cannot send, pay, delete, publish, or change the machine until you approve that exact action.

Meta Muse and Grok Bot are the hosted products in this category. Each gives the agent a computer, keeps working after the chat closes, and asks before mail, money, or a machine change goes out. Those computers sit in the vendor's cloud. This one sits in the house. The chat model is a plug: any OpenAI-compatible endpoint. Friday is the computer, the memory, and the gate.

A media library, Home Assistant, and the rest of the app catalog can be added later. They are guests. They are not the front of the product.

The docs in this repository are the plan. Nothing here points at a running server. The phone door, the mesh, the MCP bus, the task journal, and the browser session are part of that plan and are not built yet.

For the picture of the systems, what each one is for, and what this
repository implements today, see [docs/system.md](docs/system.md).

## What this is not (yet)

- Not a bootable USB image.
- Not a tested installer.
- Not a hosted agent account, and not a chat window in front of someone else's computer.
- Not a media-box distribution. A library can be added later, on its own disk.
- The Board is the only host page (`127.0.0.1:8080`). Friday has no host port. Nothing else is reachable until the owner turns a door on.
- No hostnames, secrets, or household facts are included.
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
    bootstrap.sh           writes .env from the example if missing, then exits
    bootstrap-memory.sh    starts Qdrant, Ollama, and Postgres; checks nomic-embed-text is 768 dims; creates collections; applies memories.sql
    bootstrap-mattermost.py optional Mattermost setup, not implemented yet
  gate/                    approval rules and the task journal
  sql/
    memories.sql           Postgres table memory_save writes to
    approvals.sql          approval records and the operation journal
  docs/
    system.md              systems, capabilities, and what is implemented
    architecture.md
    memory.md              collections, payloads, backup, second speaker
    agents.md
    secrets.md
    cloudflare.md
    headscale.md
    apps.md                grants, MCP, catalog, bundles, adopt-existing
  catalog/
    PIN                    commit of github.com/truenas/apps we render
    wires/                 our understanding of an upstream app id
  deploy/
    swarm/stack.yml        same services, for people already on Swarm
    helm/                  only for an existing Kubernetes cluster
```

## Core pieces (planned)

| Piece | Role |
|---|---|
| Friday | The only voice. Chat, Cabinet roles, and tasks. No host port. Reaches memory only through the memory service |
| Board | The only host page, at `127.0.0.1:8080`: ask, health, grants, and the screen where an approval is made. A phone on the mesh opens this same page |
| Task journal | A goal that outlives the turn. Send, pay, delete, publish, and any machine change wait for an approval chat cannot create |
| Qdrant | Semantic memory, cosine, 768 dimensions |
| Ollama (`nomic-embed-text`) | Turns a sentence into a vector. Chat itself does not run a local model |
| memory-mcp + Postgres | Durable `memories` row, id shared with the Qdrant point |
| App executor | Separate process from the chatbot. Accepts a named, approved operation only |
| Doors | A messaging adapter delivers turns and cannot approve. The mesh makes the phone, the laptop, and the box peers |
| MCP | Friday calls granted harnesses. Other harnesses call Friday. A new tool stays off until the owner accepts it |
| Browser session | For sites with no MCP. Disposable, off the core network, credentials kept in the vault |

Off until the owner turns them on, and not in this repository yet: the messaging door, the mesh, the public tunnel, the MCP listener, and the browser session. Left out of the product's front on purpose: Mattermost as a required room, Plex, Jellyfin, Radarr, Home Assistant, Coder, and any chat-sized local language model. Those are optional. A catalog id installs only after a render test and an approval. Templates that need host networking, a device, or an extra capability stay listed and refused.

## Developing against this repo

See `CONTRIBUTING.md` for prerequisites, first-time `.env` setup, what
actually runs today versus what's still a placeholder, and secret-scanning
before you push.

## License

Apache-2.0 (see `LICENSE`), unless changed before the first tagged release.

## Build order

This repo is being built up in stages before any release image is produced:

1. Memory schema, env defaults, and collection rules in this repo.
2. Mattermost as an optional door.
3. Starter Cabinet charters and an example soul, with no household facts.
4. This experimental source snapshot.
5. The gate and the task journal: approval records, recovery, mount checks, the webhook receiver, coordinated backup, and the USB image. Sending, paying, deleting, publishing, and changing the machine all wait on that gate. Catalog install stays refused. The approval rules, the journal, and the mount checks are in this repo.
6. Doors and devices. The phone opens the Board over the private mesh. One messaging adapter delivers turns and cannot approve. A public tunnel stays off, and if it is enabled later it reaches the Board only.
7. MCP, both directions, with the allowlist as the default. A catalog wire is one kind of grant.
8. A browser session on the box for sites with no MCP, behind the same gate.
9. Optional catalog guests (a media library, Home Assistant), after the agent path works.
10. Signed updates the owner can see. A Helm chart is only for someone who already runs Kubernetes. It is not how this appliance reaches a phone.

The memory bootstrap and the approval gate's first cut are in this repo. The webhook receiver, the coordinated backup, and the USB image are still ahead, and so is every step after them.
