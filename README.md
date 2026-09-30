# friday-os-stack

**Status: experimental. [v0.0.1](docs/install.md) is a test installer you can flash, not the finished appliance. Do not run `bootstrap.sh` expecting a working Friday.**

Friday is the operating system for one always-on computer in the house. The release is a disk image. You reach it from your phone and from a chat app, and from the Board on the machine. It remembers on that computer. It calls the other AI harnesses you run, and they can call it, through MCP, with each tool granted by you. A site with no MCP is used through a browser session on the same computer. Work continues after you close the chat, and Friday comes back when it needs a decision. It cannot send, pay, delete, publish, or change the machine until you approve that exact action.

Meta Muse and Grok Bot are the hosted products in this category. Each gives the agent a computer, keeps working after the chat closes, and asks before mail, money, or a machine change goes out. Those computers sit in the vendor's cloud. This one sits in the house, and Friday is the operating system on it. The chat model is a plug: any OpenAI-compatible endpoint. Friday is the computer, the memory, and the gate.

On first boot the owner uses a monitor on that computer. The screen connects a cable or Wi-Fi, creates the server on this computer, and takes the model key. Friday then asks, on the Board, what to set up.

v0.0.1 does not do that finished boot. The stick copies Debian onto a disk you name. Its screen is a text console, plus a page at `127.0.0.1:8080`. Friday does not speak, the embed model is not in the image, and setup cannot finish. The flash steps are in [docs/install.md](docs/install.md).

A media library, Home Assistant, and the rest of the app catalog can be added later. They are guests. They are not the front of the product.

Friday, the Board, the memory service, and the executor are processes in this tree. `scripts/smoke-core.sh` builds those four images and runs one conversation on a throwaway network. That run is not the appliance. The images are not in the v0.0.1 installer, and they are not published to a registry. The phone door, the mesh, the MCP listener, and the browser session are decisions in this repository. They do not listen, and Compose has no service for them.

For the picture of the systems, what each one is for, and what this
repository implements today, see [docs/system.md](docs/system.md).

## What this is not (yet)

- Not an app you install on another operating system. The release is a disk image.
- v0.0.1 is a bootable x86_64 UEFI test installer. It contains Debian and the installer. It does not contain Friday, the Board, Docker, or the core containers.
- Not a finished first boot, and not yet tried on two physical machines.
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
  friday/                  the chat process, no host port
  board/                   the Node screen at 127.0.0.1:8080
  memoryd/                 notes service; Compose service name memory-mcp
  executor/                approval and task records; performs nothing
  runtime/                 the small JSON HTTP server those processes share
  scripts/smoke-core.sh    build the four images and run one throwaway conversation
  scripts/prove-memory.sh  memory_save on a throwaway Postgres, then one Qdrant point
  scripts/prove-isolation.sh  an app on an internal network leaves Postgres closed
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
    install.md             verify and flash the v0.0.1 test installer
    system.md              systems, capabilities, and what is implemented
    architecture.md
    memory.md              collections, payloads, backup, second speaker
    agents.md
    secrets.md
    cloudflare.md
    headscale.md
    apps.md                grants, MCP, catalog, bundles, adopt-existing
  image/                   installer rules and the x86_64 image build
  tests/test_install.py    disk rules, setup screen, and the pre-release scan
  catalog/
    PIN                    commit of github.com/truenas/apps we render
    wires/                 our understanding of an upstream app id
  deploy/
    swarm/stack.yml        same services, for people already on Swarm
    helm/                  only for an existing Kubernetes cluster
```

## Core pieces

| Piece | Role |
|---|---|
| Friday | The only voice. Chat, Cabinet roles, and tasks. No host port. Reaches memory only through the memory service |
| Board | The screen of the OS, at `127.0.0.1:8080`. Ask, health, grants, and the place where an approval is made. A phone on the mesh opens this same screen. Friday has no second screen and no host port |
| Task journal | A goal that outlives the turn. Send, pay, delete, publish, and any machine change wait for an approval chat cannot create |
| Qdrant | Semantic memory, cosine, 768 dimensions |
| Ollama (`nomic-embed-text`) | Turns a sentence into a vector. Chat itself does not run a local model |
| memory-mcp + Postgres | Durable `memories` row, id shared with the Qdrant point |
| App executor | Separate process from the chatbot. Accepts a named, approved operation only |
| Doors | A messaging adapter delivers turns and cannot approve. The mesh makes the phone, the laptop, and the box peers |
| MCP | Friday calls granted harnesses. Other harnesses call Friday. A new tool stays off until the owner accepts it |
| Browser session | For sites with no MCP. Disposable, off the core network, credentials kept in the vault |

The four processes above are in this tree and Compose can build them. With `POSTGRES_HOST` set, the memory service calls `memory_save` and indexes the point in Qdrant. Without that host, notes stay in a JSON file. `scripts/prove-memory.sh` proves the Postgres path on throwaway containers, using a 768-number stub in place of Ollama. `scripts/prove-isolation.sh` puts Postgres on a throwaway bridge and an app container on a throwaway internal network. The app cannot resolve that name and cannot open port 5432. A container on the Postgres network can, and a container attached to both networks can. Compose still has only the `core` network. The executor records an approval and does not send mail, pay, or start a container. Catalog install stays closed.

Off until the owner turns them on: the messaging door, the mesh, the public tunnel, the MCP listener, and the browser session. The decisions for those are in `doors/`, `mcpbus/`, and `browser/`. Nothing in those modules listens, and Compose has no service for them. Left out of the product's front on purpose: Mattermost as a required room, Plex, Jellyfin, Radarr, Home Assistant, Coder, and any chat-sized local language model. Those are optional. A catalog id installs only after a render test and an approval. Templates that need host networking, a device, or an extra capability stay listed and refused.

## Developing against this repo

See `CONTRIBUTING.md` for prerequisites, first-time `.env` setup, what
actually runs today versus what's still a placeholder, and secret-scanning
before you push.

## License

Apache-2.0 (see `LICENSE`).

## Build order

This repo is being built up in stages before any release image is produced:

1. Memory schema, env defaults, and collection rules in this repo.
2. Mattermost as an optional door.
3. Starter Cabinet charters and an example soul, with no household facts.
4. This experimental source snapshot.
5. The gate and the task journal: approval records, recovery, mount checks, the webhook receiver, coordinated backup, and the USB image. Sending, paying, deleting, publishing, and changing the machine all wait on that gate. Catalog install stays refused. The approval rules, the journal, the mount checks, the webhook rules, and the coordinated backup are in this repo. Friday, the Board, the memory service, and the executor are processes in this tree. `scripts/smoke-core.sh` builds them and runs one conversation on a throwaway network. `scripts/prove-memory.sh` calls `memory_save` on a throwaway Postgres and indexes one point in a throwaway Qdrant. That proof uses a 768-number stub in place of Ollama. The executor does not perform the approved action. `catalog/discover.py` lists nothing while `catalog/PIN` is empty and refuses every install. `measure/ram.py` decides from numbers the caller supplies. `netpolicy/paths.py` decides that an app may open the webhook receiver and that a core name stays closed. `scripts/prove-isolation.sh` checks the packet: an app on a throwaway internal network leaves Postgres closed by name and by address, a container on the Postgres network opens it, and a container on both networks opens it. Compose still has only `core`. v0.0.1 is a test installer. It does not contain Friday, the Board, Docker, or the core containers, so this step is not finished.
6. Doors and devices. `doors/reach.py` records the decision: the phone opens the Board over the private mesh, one messaging adapter delivers turns and cannot approve, and a public tunnel stays off. If a tunnel is enabled later it reaches the Board only, after an access check. Nothing in that module listens.
7. MCP, both directions, with the allowlist as the default. `mcpbus/grants.py` keeps unlisted tools out of the prompt. An inbound mutating call waits for the Board and creates no approval. A catalog wire is one kind of grant and stays off until the owner accepts it.
8. A browser session on the box for sites with no MCP, behind the same gate. `browser/session.py` keeps credentials with the broker. Read and draft proceed. Send, pay, delete, and publish wait. Compose has no browser network.
9. Optional catalog guests (a media library, Home Assistant), after the agent path works. `guests/lifecycle.py` keeps install closed. Adopt records an app that is already running. Disconnect leaves that app running. A managed uninstall keeps the video files. Home Assistant is a separate entry.
10. Signed updates the owner can see. `updates/signed.py` refuses an empty signature and refuses a signature it cannot check, so nothing is applied. The code profile stays off without a Coder URL, and a supplied token still does not start taskrunner. A Helm chart is only for someone who already runs Kubernetes. `deploy/helm/` has no chart. It is not how this appliance reaches a phone.

The memory bootstrap, the approval gate, the webhook receiver, the coordinated backup, the four core processes, and the v0.0.1 test installer are in this repo. The disk image is the GitHub release, not a file in git. The phone door, the mesh, the MCP listener, and the browser session do not listen. Catalog install stays closed. Helm is unstarted. Step 5 is not finished.
