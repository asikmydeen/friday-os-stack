#!/bin/bash
# Build the x86_64 test installer. The image is written under /tmp, not into git.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${FRIDAY_IMAGE_OUT:-/tmp/friday-image}"
mkdir -p "$OUT"
STATUS="$OUT/build-status"
LOG="$OUT/build.log"
PIDFILE="$OUT/build.pid"

if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "build already running" >&2
  exit 1
fi
echo $$ > "$PIDFILE"

finish() {
  if [ "$(cat "$STATUS" 2>/dev/null || true)" != "DONE" ]; then
    echo FAILED > "$STATUS"
  fi
  rm -f "$PIDFILE"
}
trap finish EXIT

echo RUNNING > "$STATUS"
export PATH="/Applications/OrbStack.app/Contents/MacOS/xbin:/opt/homebrew/bin:${PATH:-/usr/bin:/bin}"

docker run --platform linux/amd64 --privileged --rm \
  -v "$ROOT:/src:ro" \
  -v "$OUT:/out" \
  debian:stable \
  bash /src/image/build-inside.sh > "$LOG" 2>&1

echo DONE > "$STATUS"
