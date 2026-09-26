# Cloudflare tunnel (optional, `edge` profile)

**Status: draft, not implemented in this repo yet.**

Off by default (`CLOUDFLARE_ENABLED=0`). When turned on, a tunnel is created
only after a verified access check per route, and is torn down cleanly if
that check ever fails. No route is exposed by default just because the
tunnel container is running.
