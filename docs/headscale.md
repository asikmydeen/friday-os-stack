# Headscale mesh (optional, `mesh` profile)

**Status: draft, not implemented in this repo yet.**

Off by default (`HEADSCALE_ENABLED=0`). Intended for operators who want to
reach this box from other devices over a private mesh network instead of a
public tunnel.

## Setup

Profile `mesh` runs Headscale plus a small HTTPS proxy for its control URL.
The operator sets `HEADSCALE_URL` to a name that profile `edge` already
serves, or to a name they terminate themselves — this repo does not run a
Headscale control server it also owns the DNS for.

The intended guide (to be written once this profile lands) walks the
operator through creating one user and pre-auth keys only for machines they
mean to keep long-term.

## Cleanup boundary

Ephemeral machines (e.g. a `coder-<workspace>` node from the `code`
profile) register and get removed by that profile's own cleanup once the
workspace is gone. That cleanup must never be pointed at a permanent
machine name — a laptop, a NAS, a phone. Getting this list wrong is a
mesh-wide outage for the operator, not just a code job.
