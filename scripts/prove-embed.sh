#!/usr/bin/env bash
# Pull nomic-embed-text into a throwaway Ollama and ask memoryd's client
# for one vector. Does not call Compose, does not attach to the
# friday-os-stack project, and does not use that project's Ollama volume.
set -euo pipefail

cd "$(dirname "$0")/.."

prefix=friday-embed
net=friday-embed-prove
image=friday-os-stack/memory-mcp:0.1.0

cleanup() {
  docker rm -f "$prefix-ollama" >/dev/null 2>&1 || true
  docker network rm "$net" >/dev/null 2>&1 || true
}
trap cleanup EXIT

live_before="$(docker ps --filter name=friday-os-stack- --format '{{.Names}}' | sort)"

if ! docker image inspect "$image" >/dev/null 2>&1; then
  echo "prove-embed: ${image} is not local" >&2
  exit 1
fi
if ! docker image inspect ollama/ollama:latest >/dev/null 2>&1; then
  echo "prove-embed: ollama/ollama:latest is not local" >&2
  exit 1
fi

cleanup
trap cleanup EXIT

docker network create "$net" >/dev/null
docker run -d --name "$prefix-ollama" --network "$net" ollama/ollama:latest >/dev/null

ready=0
for _ in $(seq 1 40); do
  if docker exec "$prefix-ollama" ollama list >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done
if [ "$ready" != 1 ]; then
  echo "prove-embed: ollama did not answer" >&2
  docker logs "$prefix-ollama" 2>&1 | tail -20 >&2
  exit 1
fi

docker exec "$prefix-ollama" ollama pull nomic-embed-text

embedded=0
for _ in $(seq 1 6); do
  if docker run --rm --network "$net" \
    -e OLLAMA_URL=http://friday-embed-ollama:11434 \
    -v "$PWD/scripts/prove_embed.py:/prove.py:ro" \
    --entrypoint python \
    "$image" /prove.py; then
    embedded=1
    break
  fi
  sleep 2
done
if [ "$embedded" != 1 ]; then
  echo "prove-embed: nomic-embed-text did not return 768 numbers" >&2
  exit 1
fi

live_after="$(docker ps --filter name=friday-os-stack- --format '{{.Names}}' | sort)"
if [ "$live_before" != "$live_after" ]; then
  echo "prove-embed: the existing friday-os-stack containers changed" >&2
  exit 1
fi

echo "prove-embed: nomic-embed-text returned 768 numbers"
