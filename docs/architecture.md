# Architecture

**Status: draft. This describes the target design, not a built system.**

Friday runs as a single always-on process that talks to a small set of
services: durable memory (Qdrant + Postgres via memory-mcp), an embedding
model (Ollama, `nomic-embed-text`), and a dashboard (Board). Optional apps
(media servers, home automation, etc.) are added later through an allowlisted
catalog, each wired to a named advisor persona (a "Cabinet" agent) rather than
given free access to the whole system.

See the repo README for the full compose profile layout (`core`, `chat`,
`code`, `edge`, `mesh`) and the build order this project follows before any
release image is produced.

## Key boundary

The chat process never runs infrastructure commands directly. Anything that
mutates state outside of chat (installing an app, changing a grant, running a
backup) goes through a separate executor process that only accepts a named,
pre-approved operation — never a raw shell string or an arbitrary Compose file.
