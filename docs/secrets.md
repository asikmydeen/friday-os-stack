# Secrets

**Status: draft.**

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

That path shows the minted Board password and accepts the display name,
the timezone, and the chat endpoint. It cannot install an app, change a
grant, or read memory. Every other path on port 8080 returns 401 without
the Board password. Dashboard authentication is not turned off to make
setup work.

The chat endpoint is an OpenAI-compatible base URL, an API key, a fast
model, and an optional think model. Chat stays off until that endpoint
returns a real, non-empty reply. The local embed check is separate and
must return a 768-dimension vector from the pinned model.

The owner confirms they have saved the Board password before setup is
marked complete. The launcher then deletes the provisioning token and
`/provision` returns 404. Until that confirmation, every boot returns to
the same screen and shows the same password. A power loss after the
secrets exist does not mint a second set.

## Lost Board password

After setup is complete, a lost Board password is replaced from a recovery
prompt on the text console. The owner opens it from the local keyboard.
It is not reachable over the network. It shows the new password once and
leaves memory and the other secrets in place.

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
