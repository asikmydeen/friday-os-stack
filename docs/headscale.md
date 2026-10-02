# Headscale mesh

**Status: setup choice.** The mesh stays quiet until the owner picks one
of three paths on the setup page. Leaving it unset keeps the Board on
this computer and is a complete install.

A peer that joins can open the Board, and the authenticated MCP
listener when that profile is on. It cannot reach Postgres, Qdrant, the
memory service, or the executor. Joining the mesh does not join Docker
network `core`, and it does not mount a disk, a USB device, or the
Docker socket.

## The three choices

The setup page asks before the server is created. Creating the server
again applies a choice made later.

- **This computer only.** Nothing from the mesh starts.
- **Join an existing mesh.** This computer runs the Tailscale client.
  Setup asks for the control URL and a pre-auth key. Headscale stays
  where it already runs. The key is stored mode 0600 and is not shown
  on the setup screen.
- **Create the mesh on this computer.** This computer runs Headscale
  and a client that joins it. Setup asks for the control URL other
  devices will use. That URL has to be reachable from those devices,
  on a port other than the Board, Postgres, Qdrant, Ollama, or the
  gateway. After Headscale is up it mints one-time keys. The phone key
  and the laptop key are shown until setup is finished, then hidden.
  This computer's own key is not shown.

The Board stays on `127.0.0.1:8080`. The client publishes that local
port onto the tailnet as HTTP on port 80
(`tailscale serve --bg --http=80 8080`). The mesh carries that HTTP.
Postgres, Qdrant, and the executor are not given a tailnet address.

## Where it runs

The image compose file has two profiles. `mesh` is the client, on the
host network so it can reach the Board. `mesh-server` is Headscale, on
network `mesh`, which is not `core`. Neither profile starts until
setup records that choice. `pull_policy` is `never`. The images are
packed in the core image tar.

The dev `compose.yml` does not start Headscale or the client.
`HEADSCALE_URL` in `.env.example` is a placeholder. Setup stores the
URL the owner types. It does not read that example.

`doors/reach.py` still decides which ephemeral name a later cleanup may
remove. It does not call Headscale. `doors/peers.py` records a key name
for a phone or a laptop and does not store a caller-supplied value and
does not open a socket. The setup path is separate from that record.

## Cleanup boundary

Ephemeral machines (a `coder-<workspace>` node from the `code` profile)
register and get removed by that profile's own cleanup once the
workspace is gone. That cleanup must never be pointed at a permanent
machine name: a laptop, a NAS, a phone.

`remove_node` in `doors/reach.py` is that rule. It does not open a
socket and it does not delete a node. While the mesh is off, an
ephemeral name is skipped. A name other than `coder-<workspace>` is
refused, including `phone`, `laptop`, and `nas` in any case. A caller
can pass more names that must be kept, and those are refused even when
they look like a coder node. When the mesh is on, a coder name can be
removed only after that workspace is gone. If the work failed, the name
is kept until three hours have passed. `confirmed=true` does not change
the result.
