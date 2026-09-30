# Helm chart (planned)

Not started. The chart waits until the Compose core is proven. This chart is for someone who already runs Kubernetes. It
is not how a household reaches Friday from a phone, and the appliance
does not wait on it. See the build order in the repo README.

If it is written, it comes only after the Compose stack is proven, and
it covers the core services only (never Headscale, the browser session,
or `cloudflared`). A recreate deploy strategy and `ReadWriteOncePod`
(where supported) are required so the SQLite-backed `friday` service
never runs two pods at once, even mid-rollout.
