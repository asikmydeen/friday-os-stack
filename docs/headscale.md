# Headscale mesh (`mesh` profile)

**Status: draft, not implemented in this repo yet.**

Off by default (`HEADSCALE_ENABLED=0`). This is how the phone, the
laptop, and the box become one private network, so the owner can open
the Board from somewhere else and a peer can expose an MCP endpoint.
It is part of the product in [system.md](system.md). It is not a public
tunnel, and it is not on at first boot.

A peer that joins can reach the Board and the authenticated MCP
listener. It cannot reach Postgres, Qdrant, the memory service, or the
executor's control port. Joining the mesh does not join the `core`
Docker network, and it does not mount the peer's disk.

## Setup

`compose.yml` has no `mesh` services yet. That profile is build-order
step 6 (doors and devices). An MCP endpoint on a peer is step 7. When
the mesh lands, it runs Headscale plus a small HTTPS proxy for its
control URL. `HEADSCALE_URL` is reserved in `.env.example` and nothing in
this repo reads it today. The operator sets it to a name they terminate
themselves. A Cloudflare tunnel is not required for the mesh. This repo
does not run a Headscale control server it also owns the DNS for.

The intended guide (to be written once this profile lands) walks the
operator through creating one user and pre-auth keys only for machines they
mean to keep long-term.

## Cleanup boundary

Ephemeral machines (e.g. a `coder-<workspace>` node from the `code`
profile) register and get removed by that profile's own cleanup once the
workspace is gone. That cleanup must never be pointed at a permanent
machine name — a laptop, a NAS, a phone. Getting this list wrong is a
mesh-wide outage for the operator, not just a code job.
