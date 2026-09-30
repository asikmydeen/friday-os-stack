# Grants and the app catalog

**Status: draft.** `catalog/discover.py` lists nothing while `catalog/PIN` is empty, and install stays closed. No install path starts a container.

The product is the agent. Apps are guests. Friday reaches other agent
harnesses, and the sites that have no harness, without installing a
catalog app. This page is both of those attachments.

## MCP grants

An MCP server is the general way Friday attaches to a harness, including
one running on a mesh peer. A grant stores the server URL, a
`secret_ref`, the role that may call it, and the tool names that role
may see. Tools the grant does not name are not put in the prompt.

Friday also exposes an MCP server. A caller presents a per-harness
token. Recall uses the owner filter and the cap of 8 notes in
`docs/memory.md`. A call that would send, pay, delete, publish, or
change the machine is stored as a waiting approval and does not run.
The caller does not get the Qdrant key, and the listener is not on the
Docker network that holds Postgres.

A new tool name, from a server or from a catalog upgrade, stays off
until the owner accepts it on the Board. `mcpbus/grants.py` is that
decision: the prompt sees the intersection of granted and offered
names, an inbound mutating call waits, and a wire stays off until the
Board accepts it. The module does not open a listener.

## Where apps come from

Apps come from a pinned snapshot of [`truenas/apps`](https://github.com/truenas/apps)
(LGPL-3.0, community and stable trains only — enterprise stays off), recorded
in `catalog/PIN`. This is a Compose-based catalog **rendering**, never a fork
of the TrueNAS middleware or web UI, and the upstream tree is never copied
into this repo's git history. The image copy leaves out a file whose text
matches the image secret scan, and the scan still reads the snapshot that
remains. Seeing a name on the Discover page is not permission to install it.

The pinned catalog is a menu of guests, not the front of the product.
An id installs only when it has a wire, has
passed a render test, and the owner approves that exact manifest. A
wire is an outbound grant whose tools are the method and path it names. A
template that needs host networking, host PID, host IPC, or a device or
capability the reviewed manifest does not list is refused and stays
listed. After the agent path exists, the first guests are one
media player and Home Assistant.
The Board shows measured free RAM before either approval is offered, and
refuses the install when the declared memory does not fit.

## Wire levels

| Wire level | What Friday can do | Where it comes from |
|---|---|---|
| **Known** | Health, logs, start, stop, plus the app's real API through a named advisor | `catalog/wires/<id>.yml`, hand-written for this repo |
| **Listed** | Discover can show the name. Install stays refused until the id is allowlisted and has passed a render test. | The rest of the pinned catalog |
| **Proposed** | A draft wire an advisor writes after inspecting the app; tools stay off until the owner accepts it | Same "propose, then confirm" habit as a charter change |

A catalog upgrade never turns a new tool on by itself.

## Wire file shape

Each `catalog/wires/<id>.yml` describes how Friday attaches to that app —
storage mounts (on the app storage disk only), the loopback-only port,
the health/webhook URL the executor watches, which advisor gets the tools,
and which secret names it needs. It is not a second copy of the upstream
Compose template; the render still comes from the pinned `truenas/apps`
snapshot.

## Approval, not automation

Installing an app never happens without an explicit, confirmed approval
record created by the owner on the Board (see `docs/architecture.md`
for exactly what that record must contain and why a model argument can't
substitute for it). A managed uninstall stops the container and removes the grants and tunnel entry it added, but never deletes
the underlying data files without a separate, explicit confirm.

## Managed vs. adopted

Every installed app row is `managed` (this stack started it) or `adopted`
(it was already running somewhere else, e.g. on an existing TrueNAS/Plex
setup). `guests/lifecycle.py` records that choice. Install of a guest,
including the movies and TV bundle, stays closed while the agent path
is not running. Adopt records `adopted` and starts nothing here.
Disconnecting an adopted app removes Friday's URL, grants, and health
check, and leaves the external app running. A managed uninstall keeps
the video files. Deleting those files is a separate confirm. Home
Assistant is a separate entry, not part of the bundle.

The base URL of an adopted app is resolved before any health call or tool
call. It is refused when it points at Postgres, Qdrant, the memory
service, the executor, the gateway's core listener, any other core
service name, a link-local address, or a host metadata address.
`vet_adopted` in `netpolicy/paths.py` is that check. A private LAN address
can be an adopted app. See `docs/architecture.md`.

## Events from apps

An app posts to the webhook receiver. Friday does not receive that post,
and the executor does not either. `webhooks/receiver.py` compares the
header `Friday-Webhook` with the secret generated for that one app,
using `hmac.compare_digest`. Jellyfin posts `POST /media`. Radarr and
Sonarr post `POST /arr`. A secret matches only the source allowed on
that route. Two apps on the same route that share one secret are
refused, and nothing is stored. Any method other than POST is refused.
A body larger than 256 KiB is refused, and nothing is stored.

A matching post stores one typed event in memory for the life of the process. `sql/webhooks.sql` is the table definition. The type
comes from a fixed list of event names. A Servarr `Grab` is a grab. A
health change is health. `DownloadFailed`, `GrabFailed`, and
`ManualInteractionRequired` are failures. A Servarr import (`Download`)
and any other body, including text that looks like instructions, are
`other`. Friday may then say one of four sentences:

- grab: "A download was grabbed."
- failure: "A download failed."
- health: "An app health state changed."
- other: "An app sent an event."

`speak()` returns the sentence for the stored type. It does not read
the body. The raw body stays in the log. A retry of the same body from
the same app returns the same row and is not announced again. The row
has no approval id. The receiver does not call the executor and does
not write an approval.

The image compose starts the receiver on an internal `apps` network and
publishes no host port. The dev `compose.yml` has neither. The process
does not open Postgres. Port 8080 on the host is the Board.

## Shared library volume (media bundle)

A "Movies and TV" bundle wires several apps together against one shared
`library` volume, so no app gets its own private copy of the media files.
That volume is created on the app storage disk the owner names when they
approve the bundle. The disk is a different device from the data
partition, which holds Postgres, Qdrant, SQLite, the soul, secrets, and
the pre-upgrade backup. Downloads and video files are refused on the data
partition. The layout is in `docs/architecture.md`.

| Path | Who writes | Who reads |
|---|---|---|
| `library/downloads` | qBittorrent | Radarr, Sonarr |
| `library/movies` | Radarr | Jellyfin or Plex |
| `library/tv` | Sonarr | Jellyfin or Plex |
| subtitle files under `library/movies` and `library/tv` | Bazarr, optional and not in the base bundle | Jellyfin or Plex |

The bundle asks one question, Jellyfin or Plex, and installs only the
player that was chosen. The other player is not installed, and Plex's
claim token is asked only when Plex was chosen. qBittorrent, Prowlarr,
Radarr, and Sonarr are always part of the bundle. Bazarr is a separate
wire: it writes subtitle files into the movie and TV directories, so those
mounts are read-write.

Only the Fetcher and Media advisors are granted the download-client and
player tools respectively — no other advisor gets them.

qBittorrent's settings page binds to `127.0.0.1:8081`, because the Board
uses host port 8080. Its swarm traffic still
leaves the machine. That traffic is the app working, and it is a separate
fact from publishing a hostname. Refusing a public name for qBittorrent
does not stop the swarm. The same is true of indexers the owner later
adds in Prowlarr: those calls leave the machine, and the settings pages
stay on localhost.
