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
| Board password | Dashboard login, shown once on the setup screen |
| memory-mcp token | Friday ↔ memory-mcp auth |
| `QDRANT_API_KEY` | Sent as the `api-key` header; an empty key is a failed bootstrap |

If the model key the owner supplies is missing, chat does not start. If any
of the four secrets above is empty, Friday exits at startup rather than
silently running with an open dashboard.

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
