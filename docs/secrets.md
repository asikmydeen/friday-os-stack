# Secrets

**Status: draft.** The rules below are the target. The v0.0.1 test
image follows the secret rules and cannot finish setup. See
[install.md](install.md).

## v0.0.1 test image

The image ships with an empty machine id, no SSH host keys, no default
password, and no application secrets. On the installed system it mints
the Board password, the notify token, the memory token, and the Qdrant
key once, on the data partition. A power loss does not mint a second
set. The screen shows the Board password until setup completes.

This image cannot complete setup. The embed model is not in it, so the
provisioning token stays and `/provision` does not return 404. The page
says Friday does not speak. The page is not the Node Board. There is no
SSH. Password recovery is the local keyboard, and only after setup is
complete, so that prompt is not available in this image.

## What never ships baked into an image

No secret ships baked into a released image, and no example value here is
real. First boot generates the machine id and every application secret
before the owner is asked anything, and it stores them only on the data
volume/partition. Two machines started from the same image must end up with
different machine ids and different secrets — that's a release-gate check,
not a suggestion.

## What bootstrap mints on first boot

| Secret | Used by |
|---|---|
| `FRIDAY_NOTIFY_TOKEN` | Admin endpoints, compared with `hmac.compare_digest`, never `==` |
| Board password | Dashboard login. Shown on the setup screen until the owner confirms they have saved it, then never echoed again |
| memory-mcp token | Friday ↔ memory-mcp auth |
| `QDRANT_API_KEY` | Sent as the `api-key` header; an empty key is a failed bootstrap |

If the model key the owner supplies is missing, chat does not start. If any
of the four secrets above is empty, Friday exits at startup rather than
silently running with an open dashboard.

## Setup screen

First boot is a full-screen browser on a monitor attached to the machine.
There is no SSH. The launcher, not the page, creates a provisioning token
in a file that only that local user can read. The browser sends it only
to `http://127.0.0.1:8080/provision`.

That path opens on the local screen before a network link exists. It
shows the minted Board password. Every other path on port 8080 returns
401 without the Board password. Dashboard authentication is not turned
off to make setup work. The page cannot install a catalog app, change a
grant, or read owner memory.

The screen is part of the OS. Open WebUI and LibreChat are not part of
setup. It walks through these steps:

1. Connect a cable, or choose a Wi-Fi network and enter its password.
   The page shows the link. A later boot reuses a saved link.
2. Create the server. The owner confirms, and the page starts the core
   that shipped in the image. This computer is the server. Those pieces
   are not downloaded. The Board stays at `127.0.0.1:8080`.
3. Display name, timezone, and the chat endpoint: an OpenAI-compatible
   base URL, an API key, a fast model, and an optional think model.
   That endpoint is the model. Setup names no vendor. Chat stays off
   until that endpoint returns a real, non-empty reply. The local embed
   check is separate and must return a 768-dimension vector from the
   pinned model.
4. The owner confirms they have saved the Board password. The launcher
   then deletes the provisioning token and `/provision` returns 404.

Until that confirmation, every boot returns to the same screen and
shows the same password. A power loss after the secrets exist does not
mint a second set.

A Wi-Fi password taken on this screen is stored on the data partition.
It is not one of the four secrets minted above, and the Board does not
show it again.

The image already carries Friday's character and the Cabinet roles.
The owner's notes start empty. After the password is confirmed and the
key has returned a real reply, the same page opens the conversation and
Friday speaks first, asking what to set up. A goal that should outlive the turn goes into the task
journal. Sending, paying, deleting, publishing, installing, and
changing the machine wait on that page until the owner approves the
exact step.

## Lost Board password

After setup is complete, a lost Board password is replaced from a recovery
prompt on the text console. The owner opens it from the local keyboard.
It is not reachable over the network. It shows the new password once and
leaves memory and the other secrets in place.

## Door, MCP, and browser secrets

These are minted or pasted when that piece is turned on. They are not
questions on the first-boot screen. Each is stored in the secrets
volume and referenced by name.

| Secret | Used by |
|---|---|
| Messaging-door token | The adapter that delivers turns to Friday. The adapter cannot approve |
| Mesh pre-auth key | One long-lived peer (phone, laptop). Not reused for an ephemeral code machine |
| Inbound MCP token | One outside harness calling Friday. Recall stays owner-filtered |
| Outbound MCP `secret_ref` | Friday calling a granted server. The model receives tool results, not this value |
| Site credential | The browser session's broker, for that site only. The model does not receive the password or the card |

## App webhook secret

Registering an app's webhook generates a secret for that app alone. It
is not one of the four secrets minted at first boot, and it is not
`FRIDAY_NOTIFY_TOKEN`. The receiver compares the request header
`Friday-Webhook` with `hmac.compare_digest`. The Board shows the name.
It does not show the value.

## Connections and app secrets

- Integrations (external APIs, app credentials) store a reference to a
  secret (`secret_ref`), never the secret value itself, alongside the
  object that uses it.
- An app-specific secret (a Radarr API key, a Home Assistant long-lived
  token, a Plex claim token) is created or pasted at install time and
  stored in the secrets volume, referenced by name from the app registry.
- The Board shows the secret's **name**. It never echoes the value back
  once it has been entered — not on the same screen, not later, not in
  logs.

## What must never be committed to this repo

- `.env` (only `.env.example`, names only, no real values)
- `bridge.json` or any Mattermost/tunnel/mesh credential file
- Any real API key, tunnel token, or Headscale pre-auth key
- `friday.sqlite3`, a Qdrant snapshot, or a Postgres dump
- A filled-in soul file, or any real household fact

A secret scan (`gitleaks` or `trufflehog`) is expected to run clean on this
tree before any push that touches `scripts/`, `compose.yml`, or `.env.example`.
