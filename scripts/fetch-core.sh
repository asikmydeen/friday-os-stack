#!/bin/bash
# Build the amd64 core images and the nomic-embed-text weights.
# Writes /tmp/friday-image/payload. Does not start the friday-os-stack project,
# does not attach its volumes, and does not stop its containers.
set -euo pipefail

export PATH="/Applications/OrbStack.app/Contents/MacOS/xbin:/opt/homebrew/bin:${PATH:-/usr/bin:/bin}"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${FRIDAY_IMAGE_OUT:-/tmp/friday-image}"
PAYLOAD="$OUT/payload"
STATUS="$OUT/payload-status"
LOG="$OUT/payload.log"
mkdir -p "$PAYLOAD"
exec > >(tee -a "$LOG") 2>&1

echo RUNNING > "$STATUS"
finish() {
  if [ "$(cat "$STATUS" 2>/dev/null || true)" != "DONE" ]; then
    echo FAILED > "$STATUS"
  fi
}
trap finish EXIT

live_names() {
  docker ps --format '{{.Names}}' | grep '^friday-os-stack-' | sort || true
}
BEFORE="$(live_names)"
# Hash every file the image Dockerfiles copy, so a later edit is packed.
SOURCE_STAMP="$(
  find \
    "$ROOT/friday" \
    "$ROOT/board" \
    "$ROOT/memoryd" \
    "$ROOT/executor" \
    "$ROOT/backup" \
    "$ROOT/catalog" \
    "$ROOT/sql" \
    "$ROOT/gate" \
    "$ROOT/gateway" \
    "$ROOT/webhooks" \
    "$ROOT/doors" \
    "$ROOT/mcpbus" \
    "$ROOT/browser" \
    "$ROOT/runtime" \
    "$ROOT/netpolicy" \
    "$ROOT/image" \
    "$ROOT/charters" \
    "$ROOT/soul" \
    "$ROOT/deploy/helm" \
    -type f \
    ! -name '*.pyc' \
    ! -path '*/__pycache__/*' \
    -print0 \
    | sort -z \
    | xargs -0 shasum -a 256 \
    | shasum -a 256 \
    | awk '{print $1}'
)"

PY_ID="$(docker image inspect python:3.13-slim --format '{{.Id}}' 2>/dev/null || true)"
NODE_ID="$(docker image inspect node:24-alpine --format '{{.Id}}' 2>/dev/null || true)"
PG_ID="$(docker image inspect postgres:16-alpine --format '{{.Id}}' 2>/dev/null || true)"
QD_ID="$(docker image inspect qdrant/qdrant:latest --format '{{.Id}}' 2>/dev/null || true)"
OL_ID="$(docker image inspect ollama/ollama:latest --format '{{.Id}}' 2>/dev/null || true)"
HS_ID="$(docker image inspect headscale/headscale:v0.26.1 --format '{{.Id}}' 2>/dev/null || true)"
TS_ID="$(docker image inspect tailscale/tailscale:v1.82.5 --format '{{.Id}}' 2>/dev/null || true)"

restore_tags() {
  [ -n "$PY_ID" ] && docker tag "$PY_ID" python:3.13-slim || true
  [ -n "$NODE_ID" ] && docker tag "$NODE_ID" node:24-alpine || true
  [ -n "$PG_ID" ] && docker tag "$PG_ID" postgres:16-alpine || true
  [ -n "$QD_ID" ] && docker tag "$QD_ID" qdrant/qdrant:latest || true
  [ -n "$OL_ID" ] && docker tag "$OL_ID" ollama/ollama:latest || true
  [ -n "$HS_ID" ] && docker tag "$HS_ID" headscale/headscale:v0.26.1 || true
  [ -n "$TS_ID" ] && docker tag "$TS_ID" tailscale/tailscale:v1.82.5 || true
  docker rm -f friday-image-ollama >/dev/null 2>&1 || true
  docker network rm friday-image-embed >/dev/null 2>&1 || true
}
trap 'restore_tags; finish' EXIT

if [ -f "$PAYLOAD/READY" ] && [ -s "$PAYLOAD/core-images.tar" ] && [ -d "$PAYLOAD/ollama-models/models" ] \
  && grep -q 'friday-os-stack/webhooks:0.1.0-amd64 linux/amd64' "$PAYLOAD/pins.txt" \
  && grep -q 'friday-os-stack/gateway:0.1.0-amd64 linux/amd64' "$PAYLOAD/pins.txt" \
  && grep -q 'friday-os-stack/door:0.1.0-amd64 linux/amd64' "$PAYLOAD/pins.txt" \
  && grep -q 'friday-os-stack/mcp:0.1.0-amd64 linux/amd64' "$PAYLOAD/pins.txt" \
  && grep -q 'friday-os-stack/browser:0.1.0-amd64 linux/amd64' "$PAYLOAD/pins.txt" \
  && grep -q 'friday-os-stack/headscale:0.26.1-amd64 linux/amd64' "$PAYLOAD/pins.txt" \
  && grep -q 'friday-os-stack/tailscale:1.82.5-amd64 linux/amd64' "$PAYLOAD/pins.txt" \
  && [ "$(cat "$PAYLOAD/source-stamp" 2>/dev/null || true)" = "$SOURCE_STAMP" ]; then
  echo "payload already ready"
  echo DONE > "$STATUS"
  exit 0
fi
rm -f "$PAYLOAD/READY"

cd "$ROOT"

echo "building amd64 images"
# provenance and sbom off: the guest docker load wants one image, not an attestation index.
docker build --platform linux/amd64 --provenance=false --sbom=false -t friday-os-stack/friday:0.1.0-amd64 -f friday/Dockerfile .
docker build --platform linux/amd64 --provenance=false --sbom=false -t friday-os-stack/board:0.1.0-amd64 -f board/Dockerfile .
docker build --platform linux/amd64 --provenance=false --sbom=false -t friday-os-stack/memory-mcp:0.1.0-amd64 -f memoryd/Dockerfile .
docker build --platform linux/amd64 --provenance=false --sbom=false -t friday-os-stack/executor:0.1.0-amd64 -f executor/Dockerfile .
docker build --platform linux/amd64 --provenance=false --sbom=false -t friday-os-stack/webhooks:0.1.0-amd64 -f webhooks/Dockerfile .
docker build --platform linux/amd64 --provenance=false --sbom=false -t friday-os-stack/gateway:0.1.0-amd64 -f gateway/Dockerfile .
docker build --platform linux/amd64 --provenance=false --sbom=false -t friday-os-stack/door:0.1.0-amd64 -f doors/Dockerfile .
docker build --platform linux/amd64 --provenance=false --sbom=false -t friday-os-stack/mcp:0.1.0-amd64 -f mcpbus/Dockerfile .
docker build --platform linux/amd64 --provenance=false --sbom=false -t friday-os-stack/browser:0.1.0-amd64 -f browser/Dockerfile .

# A plain pull --platform on this Docker daemon keeps the host-architecture tag.
# Building FROM the upstream image with an explicit platform produces an amd64 image.
pin_upstream() {
  local upstream="$1"
  local dest="$2"
  local restore_id="$3"
  echo "pinning $dest from $upstream"
  docker build --platform linux/amd64 --provenance=false --sbom=false -t "$dest" - <<EOF
FROM ${upstream}
EOF
  if [ -n "$restore_id" ]; then
    docker tag "$restore_id" "$upstream"
  fi
}

echo "pinning amd64 third-party images"
pin_upstream postgres:16-alpine friday-os-stack/postgres:16-amd64 "$PG_ID"
pin_upstream qdrant/qdrant:latest friday-os-stack/qdrant:pinned-amd64 "$QD_ID"
pin_upstream ollama/ollama:latest friday-os-stack/ollama:pinned-amd64 "$OL_ID"
pin_upstream headscale/headscale:v0.26.1 friday-os-stack/headscale:0.26.1-amd64 "$HS_ID"
pin_upstream tailscale/tailscale:v1.82.5 friday-os-stack/tailscale:1.82.5-amd64 "$TS_ID"

for image in \
  friday-os-stack/friday:0.1.0-amd64 \
  friday-os-stack/board:0.1.0-amd64 \
  friday-os-stack/memory-mcp:0.1.0-amd64 \
  friday-os-stack/executor:0.1.0-amd64 \
  friday-os-stack/postgres:16-amd64 \
  friday-os-stack/qdrant:pinned-amd64 \
  friday-os-stack/ollama:pinned-amd64 \
  friday-os-stack/webhooks:0.1.0-amd64 \
  friday-os-stack/gateway:0.1.0-amd64 \
  friday-os-stack/door:0.1.0-amd64 \
  friday-os-stack/mcp:0.1.0-amd64 \
  friday-os-stack/browser:0.1.0-amd64 \
  friday-os-stack/headscale:0.26.1-amd64 \
  friday-os-stack/tailscale:1.82.5-amd64
do
  arch="$(docker image inspect "$image" --format '{{.Os}}/{{.Architecture}}')"
  if [ "$arch" != "linux/amd64" ]; then
    echo "$image is $arch" >&2
    exit 1
  fi
  echo "$image $arch $(docker image inspect "$image" --format '{{.Id}}')"
done > "$PAYLOAD/pins.txt"

echo "pulling nomic-embed-text"
if find "$PAYLOAD/ollama-models" -type d -name nomic-embed-text | grep -q .; then
  echo "nomic-embed-text weights already in payload"
else
docker rm -f friday-image-ollama >/dev/null 2>&1 || true
docker network inspect friday-image-embed >/dev/null 2>&1 || docker network create friday-image-embed >/dev/null
# The weight files are the model bytes. Pull them with the native engine.
# The image saved below is the amd64 tag.
docker run -d --name friday-image-ollama \
  --network friday-image-embed \
  ollama/ollama:latest
ready=0
for _ in $(seq 1 60); do
  if docker exec friday-image-ollama ollama list >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 2
done
if [ "$ready" -ne 1 ]; then
  echo "ollama did not start" >&2
  docker logs friday-image-ollama >&2 || true
  exit 1
fi
docker exec friday-image-ollama ollama pull nomic-embed-text
docker exec friday-image-ollama ollama show nomic-embed-text > "$PAYLOAD/nomic-show.txt"
rm -rf "$PAYLOAD/ollama-models" "$PAYLOAD/ollama-models-tmp"
docker cp friday-image-ollama:/root/.ollama/models "$PAYLOAD/ollama-models-tmp"
mkdir -p "$PAYLOAD/ollama-models"
mv "$PAYLOAD/ollama-models-tmp" "$PAYLOAD/ollama-models/models"
find "$PAYLOAD/ollama-models" -name 'id_*' -delete
if ! find "$PAYLOAD/ollama-models" -type d -name 'nomic-embed-text' | grep -q .; then
  echo "nomic-embed-text weights were not copied" >&2
  exit 1
fi
docker rm -f friday-image-ollama >/dev/null
docker network rm friday-image-embed >/dev/null
fi

echo "saving images"
docker save -o "$PAYLOAD/core-images.tar" \
  friday-os-stack/friday:0.1.0-amd64 \
  friday-os-stack/board:0.1.0-amd64 \
  friday-os-stack/memory-mcp:0.1.0-amd64 \
  friday-os-stack/executor:0.1.0-amd64 \
  friday-os-stack/postgres:16-amd64 \
  friday-os-stack/qdrant:pinned-amd64 \
  friday-os-stack/ollama:pinned-amd64 \
  friday-os-stack/webhooks:0.1.0-amd64 \
  friday-os-stack/gateway:0.1.0-amd64 \
  friday-os-stack/door:0.1.0-amd64 \
  friday-os-stack/mcp:0.1.0-amd64 \
  friday-os-stack/browser:0.1.0-amd64 \
  friday-os-stack/headscale:0.26.1-amd64 \
  friday-os-stack/tailscale:1.82.5-amd64

AFTER="$(live_names)"
if [ "$BEFORE" != "$AFTER" ]; then
  echo "live containers changed" >&2
  echo "before: $BEFORE" >&2
  echo "after: $AFTER" >&2
  exit 1
fi

{
  echo "tar $(stat -f '%z' "$PAYLOAD/core-images.tar" 2>/dev/null || stat -c '%s' "$PAYLOAD/core-images.tar")"
  du -sh "$PAYLOAD/ollama-models" "$PAYLOAD/core-images.tar"
} | tee "$PAYLOAD/sizes.txt"

printf '%s\n' "$SOURCE_STAMP" > "$PAYLOAD/source-stamp"
: > "$PAYLOAD/READY"
echo DONE > "$STATUS"
echo "payload ready"
