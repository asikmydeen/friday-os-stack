# Cloudflare tunnel (optional, `edge` profile)

**Status: draft, not implemented in this repo yet.**

Off by default (`CLOUDFLARE_ENABLED=0`). The first release ships with no
tunnel at all. The Board is the only host page, at `127.0.0.1:8080`.
Friday has no host port. A tunnel is a path to the Board, not a login,
so turning one on later is treated as a security-sensitive change, not a
convenience toggle.

## Rule before any hostname is added

Before a route is published, it must have a verified access check: either
Cloudflare Access in front of it, or the app's own login, only when a wire
explicitly says that login is sufficient on its own. If neither is true for
a given app, that app's hostname is refused, tunnel or no tunnel.

## What is never publishable

memory-mcp, Qdrant, Postgres, taskrunner, Radarr, Sonarr, Prowlarr, and
qBittorrent are never publishable routes, regardless of what the operator
asks for. Their ports stay bound to `127.0.0.1` and stay off the `apps`
network's path to any public hostname. Refusing a public name does not
stop qBittorrent's swarm traffic, or the indexer calls the owner adds in
Prowlarr. Those leave the machine while the settings pages stay on
localhost. See `docs/apps.md`.

## Config

`config/hostnames.example.yml` shows the file shape with three sample
entries (`friday`, `board`, `jellyfin`). Those names are examples, not
routes this stack publishes. The `friday` and `board` samples both target
the Board service. Friday's container is not a route. The owner copies
the file and adds one real name at a time. The Board is the only core
service that may receive a public hostname, and only after the access
check above has been verified.
A tunnel is created only after that check passes, and is torn down cleanly
if the check ever starts failing — nothing stays exposed just because the
tunnel container happens to still be running.

This stack never calls the Cloudflare API to buy or attach a domain; the
operator brings their own zone and tunnel token.
