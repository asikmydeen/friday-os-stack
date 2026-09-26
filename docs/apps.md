# App catalog

**Status: draft, no install path is functional yet.**

Apps come from a pinned snapshot of `truenas/apps` (see `catalog/PIN`), never
installed as TrueNAS itself — this is a Compose-based catalog rendering, not
a fork of the TrueNAS middleware or web UI.

Each entry in `catalog/wires/` describes how Friday attaches to that app:
which advisor gets which tool, which storage paths it mounts, and which
health/webhook URLs the executor watches. Installing an app never happens
without an explicit, confirmed approval from the owner, and a managed
uninstall never deletes the underlying data files without a separate confirm.

An "adopted" app (one already running outside this stack) is only ever
observed and called through owner-granted tools — this stack never restarts,
upgrades, or uninstalls an adopted service.
