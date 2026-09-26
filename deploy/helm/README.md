# Helm chart (planned)

Not started. Per the plan, this comes only after the Compose stack is
proven, and only covers the core services (never Headscale or `cloudflared`).
A recreate deploy strategy and `ReadWriteOncePod` (where supported) are
required so the SQLite-backed `friday` service never runs two pods at once,
even mid-rollout.
