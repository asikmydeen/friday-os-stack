# Grants and the app catalog

**Status: draft.** `catalog/discover.py` lists nothing while `catalog/PIN` is empty. The Board lists app directory names from `CATALOG_ROOT` when the packed snapshot is mounted, and it does not read file text. Install stays closed. No install path starts a container. `catalog/render.py` judges a description the caller supplies. It does not render a template, does not read the draft wires, and does not write the pin. A description that passes records the 40-character pin, the template hash, and the rendered digest, and it is not installed. A version value that is not that hex shape is refused and is not stored. `catalog/propose.py` records one draft wire an advisor supplies. Tools stay off until the Board accepts that name. It does not read the draft wires, does not render a template, and does not install.

The product is the agent. Apps are guests. Friday reaches other agent
harnesses, and the sites that have no harness, without installing a
catalog app. This page is both of those attachments.

## MCP grants

An MCP server is the general way Friday attaches to a harness, including
one running on a mesh peer. A grant stores the server URL, a
`secret_ref`, the role that may call it, and the tool names that role
may see. Tools the grant does not name are not put in the prompt.
`mcpbus/ref.py` records one generated secret for that call and returns
the name `MCP_SECRET_REF` only. A caller-supplied value is not stored.
Chat cannot record one. The value stays in the process. It is not the
notify token, the messaging-door token, or the inbound MCP token.
Recording it does not call the server. `mcpbus/outbound.py` still reads
the environment and does not call that record. Friday's ask path does
not call it.

Friday also exposes an MCP server. A caller presents a per-harness
token. `mcpbus/token.py` records one generated secret and returns the
name `MCP_TOKEN` only. A caller-supplied value is not stored. Chat
cannot record one. The value stays in the process. It is not the
notify token and it is not the messaging-door token. Recording it
does not start the listener and does not create an approval. The
server still reads the environment and does not call that record.
Friday's ask path does not call it. Recall uses the owner filter and the cap of 8 notes in
`docs/memory.md`. A call that would send, pay, delete, publish, or
change the machine is stored as a waiting approval and does not run.
The caller does not get the Qdrant key, and the listener is not on the
Docker network that holds Postgres.

A new tool name, from a server or from a catalog upgrade, stays off
until the owner accepts it on the Board. `mcpbus/grants.py` is that
decision: the prompt sees the intersection of granted and offered
names, an inbound mutating call waits, and a wire stays off until the
Board accepts it. The same module records one connection grant: a
server, a secret reference name, a role, and tool names. A tool stays
out of that prompt until the Board accepts that name. A secret value
is not stored. Chat cannot record or accept one. The server is not
called. The Board page records the same grant. Friday's ask path does
not call it. That decision module does not open a listener.
`mcpbus/server.py` listens when `MCP_ENABLED` is `yes`, on the internal
`doors` network, and it does not create an approval.

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
The Board shows caller-supplied free RAM before either approval is offered, and
refuses the install when the declared memory does not fit.
`measure/ram.py` names one other guest that would free enough, or says
the machine is too small. A core flag other than false keeps that guest
off the list. A credential-shaped name is not repeated. Those numbers
are the caller's. Nothing is stopped and nothing is pulled. The Board
page shows those numbers before an install button is offered. Catalog
install stays closed. Friday's ask path does not call it.
`catalog/render.py` is that render judgment. An app that needs TrueNAS
middleware is refused and stays listed. A ZFS dataset is refused, and a
folder path standing in for that dataset is refused. Host network, host
PID, host IPC, a privileged flag, an unlisted device, and an unlisted
capability are refused, and the app stays listed. A port that does not
bind to `127.0.0.1` is refused. The image architecture must match the
host architecture the caller names. Those strings are not a measurement
of this machine. Declared memory above the caller's free RAM is refused.
`confirmed=true` does not install. The Board's accept still returns
`catalog_install_closed`. Chat cannot accept the render.

## Wire levels

| Wire level | What Friday can do | Where it comes from |
|---|---|---|
| **Known** | Health, logs, start, stop, and pull, plus the app's real API through a named advisor. `guests/known.py` records one log as "Logs were read." The cleaned log is evidence under that sentence. A credential-shaped log is not stored. It does not read a container. `guests/start.py` records that the Board asked to start one known managed app. The sentence is "A start was asked." The container is not started. An adopted app is not started. Chat cannot record one, and that refusal leaves the row. A credential-shaped name or note is not stored. "The password is kept outside the machine" can be a note. Pull is not this record. `guests/stop.py` records that the Board asked to stop one known managed app. The sentence is "A stop was asked." The container is not stopped. An adopted app is not stopped. Chat cannot record one, and that refusal leaves the row. A credential-shaped name or note is not stored. "The password is kept outside the machine" can be a note. Deleting the files is not this record. The registry stop still returns not_stopped and does not change the row. `guests/pull.py` records that the Board asked to pull one known managed app. The sentence is "A pull was asked." The image is not pulled. An adopted app is not pulled. Chat cannot record one, and that refusal leaves the row. A credential-shaped name or note is not stored. "The password is kept outside the machine" can be a note. Starting and stopping are not this record. `guests/call.py` records that the Board asked the named advisor to call one known app, including an adopted app. The sentence is "An API call was asked." The call is not made and the gateway is not opened. A tool stays off until the Board accepts that name. Accepting one name does not accept another. Chat cannot record or accept one. A credential-shaped name or note is not stored. "The password is kept outside the machine" can be a note. Starting, stopping, and pulling are not this record. `guests/upgrade.py` records that the Board asked to upgrade one known managed app. The sentence is "An upgrade was asked." The image is not upgraded. A new tool stays off until the Board accepts that name. Accepting one name does not accept another. Chat cannot record or accept one. Applying it returns catalog_install_closed | `catalog/wires/<id>.yml`, hand-written for this repo |
| **Listed** | Discover can show the name. Install stays refused until the id is allowlisted and has passed a render test. `catalog/allowlist.py` allowlists jellyfin on one Board fire and leaves every other catalog id closed. Install of an id that is not allowlisted stays closed, and install of jellyfin stays closed too. It does not store a sentence. Chat cannot fire it. Friday's ask path does not call it. | The rest of the pinned catalog |
| **Proposed** | A draft wire an advisor writes after inspecting the app. `catalog/propose.py` records the caller-supplied draft. Tools stay off until the Board accepts that name. A new name does not inherit an earlier acceptance. Another advisor cannot replace that draft. Chat cannot record the draft or accept a name. Nothing is installed | Same "propose, then confirm" habit as a charter change |

A catalog upgrade never turns a new tool on by itself. `guests/upgrade.py` records that the Board asked to upgrade one known managed app. The sentence is "An upgrade was asked." The image is not upgraded and the container is not restarted. A new tool stays off until the Board accepts that name. Accepting one name does not accept another. An adopted app is not upgraded. Chat cannot record or accept one, and that refusal leaves the row. Applying it returns `catalog_install_closed`. Friday's ask path does not call it.

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
substitute for it). A managed uninstall records that the grants and one tunnel name are removed. It does not stop the container. The library stays. A separate confirm does not delete the files.

## Managed vs. adopted

Every installed app row is `managed` (this stack started it) or `adopted`
(it was already running somewhere else, e.g. on an existing TrueNAS/Plex
setup). `guests/lifecycle.py` records that choice. Install of a guest,
including the movies and TV bundle, stays closed while the agent path
is not running. Adopt records `adopted` and starts nothing here.
Disconnecting an adopted app removes Friday's URL, grants, and health
check, and leaves the external app running. A managed uninstall keeps
the video files. `record_removal` records that the Board removed that app's grants and one tunnel name. The library stays. The container is not stopped. A separate confirm does not delete the files. Chat cannot record either, and that refusal leaves the row. A second record keeps the first names. A credential-shaped name is not stored, including a percent-encoded or plus-encoded copy. It does not call Cloudflare. Friday's ask path does not call it. Home
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
using `hmac.compare_digest`. `webhooks/secret.py` records one generated
secret for Jellyfin, Radarr, or Sonarr and returns the name only. A
caller-supplied value is not stored. Chat cannot record one. Radarr
and Sonarr do not share a secret. A 64-character hex value is the
generated secret. Any other credential-shaped draw is not stored. The
value stays in the process, is not written to a file, and is not placed
on the process environment. The module does not post the webhook.
Jellyfin posts `POST /media`. Radarr and
Sonarr post `POST /arr`. A secret matches only the source allowed on
that route. Two apps on the same route that share one secret are
refused, and nothing is stored. Any method other than POST is refused.
A body larger than 256 KiB is refused, and nothing is stored.

A matching post stores one typed event. With `POSTGRES_HOST` set, the receiver calls `webhook_store` and a retry of the same body is the same row. Without that host, the event stays in memory for the life of the process. `sql/webhooks.sql` is that table. The type
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
not write an approval. `GET /announcements` returns those sentences
and not the body. It requires `Friday-Notify`. Without that token the
read is refused. Friday reads `http://webhooks:8080` only. The ask
path does not. The Board lists the sentences. Chat cannot post one.

The image compose starts the receiver on the internal `apps` network and
on `core`, so the process can write `webhook_store`. It publishes no
host port and it does not proxy to Postgres. A guest on `apps` is not
given that route. The dev `compose.yml` has neither network attachment.
Port 8080 on the host is the Board.

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

`guests/bundle.py` records that plan and does not apply it. Jellyfin is
the default player. Choosing Plex asks for the claim token's name and
does not store a value. The other player, Home Assistant, Bazarr, and
Tautulli stay out of the base plan. Recording the other player later
keeps Radarr and Sonarr as the writers, names that player's secret
names, loopback bind, and wired health URL, and leaves Media on the
primary. Bazarr can be recorded later. Its movie and TV paths are
read-write, and the chosen player reads them. Tautulli is recorded
only when Plex is primary. None of those records is applied. A best-first quality list is refused. A
library path on the data partition is refused. Settings pages stay on
`127.0.0.1`, and qBittorrent's page is `127.0.0.1:8081`. Refusing a
public name does not stop swarm traffic. A health probe is the wired
URL and is not opened. An add call is not announced as a download.
Catalog install stays closed. Friday's ask path does not call this
module.

qBittorrent's settings page binds to `127.0.0.1:8081`, because the Board
uses host port 8080. Its swarm traffic still
leaves the machine. That traffic is the app working, and it is a separate
fact from publishing a hostname. Refusing a public name for qBittorrent
does not stop the swarm. The same is true of indexers the owner later
adds in Prowlarr: those calls leave the machine, and the settings pages
stay on localhost.

## Home Assistant

Home Assistant is a separate catalog entry, not part of that bundle.
`guests/home.py` records the plan and does not apply it. The plan names
the Home charter and the tools `home_status` and `home_control` for
that role only. No other advisor is named. The URL and the long-lived
token are secret names, and a caller-supplied value is not stored.
Config sits on the app storage disk. The page binds to
`127.0.0.1:8123`. The health probe is `http://home-assistant:8123/api/`
and is not opened. Host network, host PID, host IPC, and a device or
capability the manifest does not list are refused. Declared memory
above the caller's free RAM is refused, and those numbers are not a
measurement of the machine. A tool is on only after the Board accepts
that name. A name the manifest does not list stays off. Chat cannot
accept a name, and that refusal leaves a name the Board already
accepted. Catalog install stays closed. Friday's ask path does not
call this module.

## App registry

`guests/registry.py` is an in-process registry. A row holds an id, a
train, a version, a status, an image, loopback ports, folders, a health
URL, a declared memory limit, and a wire level. `observe` records an
adopted app and does not start it. `install` writes nothing.
`check_service` and "what's running" read those rows and do not open
the health URL. "What's using RAM" is the declared limit, not a
measurement of the machine. Stopping an adopted app, including Plex,
leaves it running. Chat cannot stop a managed row. The Board's stop
waits and does not change the row. A folder on the data partition, or
one that canonicalizes to `/etc`, home, the secrets volume, or the
Docker socket, is refused. A managed row names a storage disk and two
different devices. A health name is kept only with the addresses the
caller resolved. The module does not resolve DNS, does not open
SQLite, and does not start or stop a container. Friday's ask path does
not call it. An empty restore leaves the rows already recorded.
`guests/known.py` records one log for a known app. The sentence is
"Logs were read." The cleaned log is evidence under that sentence and
is not a goal. A credential-shaped log is not stored, including a
percent-encoded or plus-encoded copy. A vault secret is removed,
including a percent-encoded or plus-encoded copy, a further encoding of
that copy, a copy split by whitespace, and a copy rebuilt by that removal. Chat cannot record one, and
that refusal leaves the row. It does not read a container. Friday's ask path does not call it. `guests/start.py` records that the Board asked to start one known managed app. The sentence is "A start was asked." The container is not started. An adopted app is not started. Chat cannot record one, and that refusal leaves the row. A second record keeps the first name. A credential-shaped name or note is not stored, including a percent-encoded or plus-encoded copy. "The password is kept outside the machine" can be a note. Pull is not this record. Friday's ask path does not call it. `guests/stop.py` records that the Board asked to stop one known managed app. The sentence is "A stop was asked." The container is not stopped. An adopted app is not stopped. Chat cannot record one, and that refusal leaves the row. A second record keeps the first name. A credential-shaped name or note is not stored, including a percent-encoded or plus-encoded copy. "The password is kept outside the machine" can be a note. Deleting the files is not this record. The registry stop still returns not_stopped and does not change the row. `guests/pull.py` records that the Board asked to pull one known managed app. The sentence is "A pull was asked." The image is not pulled. An adopted app is not pulled. Chat cannot record one, and that refusal leaves the row. A second record keeps the first name. A credential-shaped name or note is not stored, including a percent-encoded or plus-encoded copy. "The password is kept outside the machine" can be a note. Starting and stopping are not this record. Friday's ask path does not call it. `guests/call.py` records that the Board asked the named advisor to call one known app, including an adopted app. The sentence is "An API call was asked." The call is not made and the gateway is not opened. The named advisor is media for Jellyfin and Plex, fetcher for Radarr, Sonarr, Prowlarr, qBittorrent, and Bazarr, and home for Home Assistant. A tool stays off until the Board accepts that name. Accepting one name does not accept another, and it does not accept that name for another app. Chat cannot record or accept one, and that refusal leaves the row and an accepted name. A second record keeps the first tool and the first note. A credential-shaped name, advisor, tool, or note is not stored, including a percent-encoded or plus-encoded copy. "The password is kept outside the machine" can be a note. Starting, stopping, and pulling are not this record. Refusing the call does not stop qBittorrent's swarm. Friday's ask path does not call it. `guests/upgrade.py` records that the Board asked to upgrade one known managed app. The sentence is "An upgrade was asked." The image is not upgraded and the container is not restarted. A new tool stays off until the Board accepts that name. Accepting one name does not accept another. An adopted app is not upgraded. Chat cannot record or accept one, and that refusal leaves the row and an accepted name. A second record keeps the first note and the first tool list. A credential-shaped name, tool, or note is not stored, including a percent-encoded or plus-encoded copy. "The password is kept outside the machine" can be a note. Pulling, starting, stopping, and calling are not this record. Refusing the upgrade does not stop qBittorrent's swarm. Applying it returns catalog_install_closed. Friday's ask path does not call it.

## Adopt-only accounts

`guests/accounts.py` keeps one token per person id for a fitness
tracker, calendar, mail, and phone harvest. An unknown person, or a
person with no fitness token, is told "connect your account." Nothing
is written to the owner's tracker. Calendar and mail with no client
say "not connected." Phone harvest does not create the `messages`
collection. A headed browser records a shopper search and a buyer open. The page
is not fetched, and neither checks out. A phone token that is already
stored does not ask the owner to connect an account while harvest is
off. The family role is blocked from these connections and from
download clients. Download-client tools stay off. Catalog install stays
closed.

A custom card keeps a health URL the caller already resolved. A
link-local address is refused. This module does not resolve DNS. Tools
stay off until a manifest names one and the Board accepts that name.
Video, photos, and downloads are not embedded. A receipt such as
"added this movie" stays in the book as a receipt, not an episode.
Friday's ask path does not call this module.
