# App catalog

**Status: draft, no install path is functional yet.**

## Where apps come from

Apps come from a pinned snapshot of [`truenas/apps`](https://github.com/truenas/apps)
(LGPL-3.0, community and stable trains only — enterprise stays off), recorded
in `catalog/PIN`. This is a Compose-based catalog **rendering**, never a fork
of the TrueNAS middleware or web UI, and the upstream tree is never copied
into this repo's git history. Seeing a name on the Discover page is not
permission to install it.

## Wire levels

| Wire level | What Friday can do | Where it comes from |
|---|---|---|
| **Known** | Health, logs, start, stop, plus the app's real API through a named advisor | `catalog/wires/<id>.yml`, hand-written for this repo |
| **Listed** | Discover can show the name. Install stays refused until the id is allowlisted and has passed a render test. | The rest of the pinned catalog |
| **Proposed** | A draft wire an advisor writes after inspecting the app; tools stay off until the owner accepts it | Same "propose, then confirm" habit as a charter change |

A catalog upgrade never turns a new tool on by itself.

## Wire file shape

Each `catalog/wires/<id>.yml` describes how Friday attaches to that app —
storage mounts (under an owner-named root only), the loopback-only port,
the health/webhook URL the executor watches, which advisor gets the tools,
and which secret names it needs. It is not a second copy of the upstream
Compose template; the render still comes from the pinned `truenas/apps`
snapshot.

## Approval, not automation

Installing an app never happens without an explicit, confirmed approval
record created by the owner on the Board or in the console (see
`docs/architecture.md` for exactly what that record must contain and why a
model argument can't substitute for it). A managed uninstall stops the
container and removes the grants/tunnel entry it added, but never deletes
the underlying data files without a separate, explicit confirm.

## Managed vs. adopted

Every installed app row is `managed` (this stack started it) or `adopted`
(it was already running somewhere else, e.g. on an existing TrueNAS/Plex
setup). An adopted app is only ever observed and called through
owner-granted tools — this stack never restarts, upgrades, or uninstalls an
adopted service, and disconnecting one just removes Friday's URL, grants,
and health check.

## Shared library volume (media bundle)

A "Movies and TV" bundle wires several apps together against one shared
`library` volume, so no app gets its own private copy of the media files:

| Path | Who writes | Who reads |
|---|---|---|
| `library/downloads` | qBittorrent | Radarr, Sonarr |
| `library/movies` | Radarr | Jellyfin / Plex |
| `library/tv` | Sonarr | Jellyfin / Plex |

Only the Fetcher and Media advisors are granted the download-client and
player tools respectively — no other advisor gets them.
