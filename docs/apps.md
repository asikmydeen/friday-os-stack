# App catalog

**Status: draft, no install path is functional yet.**

## Where apps come from

Apps come from a pinned snapshot of [`truenas/apps`](https://github.com/truenas/apps)
(LGPL-3.0, community and stable trains only — enterprise stays off), recorded
in `catalog/PIN`. This is a Compose-based catalog **rendering**, never a fork
of the TrueNAS middleware or web UI, and the upstream tree is never copied
into this repo's git history. Seeing a name on the Discover page is not
permission to install it.

The pinned catalog is a menu. An id installs only when it has a wire, has
passed a render test, and the owner approves that exact manifest. A
template that needs host networking, host PID, host IPC, or a device or
capability the reviewed manifest does not list is refused and stays
listed. The first candidates are one media player and Home Assistant.
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
setup). An adopted app is only ever observed and called through
owner-granted tools — this stack never restarts, upgrades, or uninstalls an
adopted service, and disconnecting one just removes Friday's URL, grants,
and health check.

The base URL of an adopted app is resolved before any health call or tool
call. It is refused when it points at Postgres, Qdrant, the memory
service, the executor, the gateway's core listener, any other core
service name, a link-local address, or a host metadata address. See
`docs/architecture.md`.

## Events from apps

Webhooks are delivered to the webhook receiver, not to Friday and not to
the executor. The receiver checks the generated header and stores a typed
event. Friday announces that event with a fixed sentence (a grab, a
failure, a health change). The raw body is kept for the log and is not
placed in the model prompt. The receiver does not write an approval.

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
