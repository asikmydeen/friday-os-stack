#!/usr/bin/env bash
# Apply sql/memories.sql on a throwaway Postgres, index one note in a
# throwaway Qdrant, and remove both. Does not call Compose and does not
# attach to the friday-os-stack project.
set -euo pipefail

cd "$(dirname "$0")/.."

prefix=friday-prove
net=friday-memory-prove

cleanup() {
  docker rm -f "$prefix-postgres" "$prefix-qdrant" >/dev/null 2>&1 || true
  docker network rm "$net" >/dev/null 2>&1 || true
}
trap cleanup EXIT

live_before="$(docker ps --filter name=friday-os-stack- --format '{{.Names}}' | sort)"

set -a
eval "$(python3 - <<'PY'
import secrets
print(f"POSTGRES_PASSWORD={secrets.token_hex(16)}")
print(f"QDRANT_API_KEY={secrets.token_hex(16)}")
PY
)"
set +a

docker build -f memoryd/Dockerfile -t friday-os-stack/memory-mcp:0.1.0 .

cleanup
trap cleanup EXIT
docker network create "$net" >/dev/null

docker run -d --name "$prefix-postgres" --network "$net" \
  -e POSTGRES_PASSWORD \
  -e POSTGRES_USER=memory \
  -e POSTGRES_DB=memories \
  -v "$PWD/sql/memories.sql:/docker-entrypoint-initdb.d/01-memories.sql:ro" \
  postgres:16-alpine >/dev/null

docker run -d --name "$prefix-qdrant" --network "$net" \
  -e "QDRANT__SERVICE__API_KEY=${QDRANT_API_KEY}" \
  qdrant/qdrant:latest >/dev/null

ready=0
for _ in $(seq 1 40); do
  if docker exec "$prefix-postgres" psql -U memory -d memories -c 'SELECT count(*) FROM memories' >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done
if [ "$ready" != 1 ]; then
  echo "prove-memory: postgres did not apply memories.sql" >&2
  docker logs "$prefix-postgres" 2>&1 | tail -20 >&2
  exit 1
fi

qdrant_ready=0
for _ in $(seq 1 40); do
  if docker run --rm --network "$net" --entrypoint python friday-os-stack/memory-mcp:0.1.0 \
    -c 'import urllib.request; urllib.request.urlopen("http://friday-prove-qdrant:6333/readyz", timeout=2).read()' \
    >/dev/null 2>&1; then
    qdrant_ready=1
    break
  fi
  sleep 1
done
if [ "$qdrant_ready" != 1 ]; then
  echo "prove-memory: qdrant did not answer" >&2
  docker logs "$prefix-qdrant" 2>&1 | tail -20 >&2
  exit 1
fi

docker run --rm --network "$net" \
  -e POSTGRES_HOST=friday-prove-postgres \
  -e POSTGRES_PORT=5432 \
  -e POSTGRES_DB=memories \
  -e POSTGRES_USER=memory \
  -e POSTGRES_PASSWORD \
  -e QDRANT_URL=http://friday-prove-qdrant:6333 \
  -e QDRANT_API_KEY \
  -v "$PWD/scripts/prove_memory.py:/prove.py:ro" \
  --entrypoint python \
  friday-os-stack/memory-mcp:0.1.0 /prove.py

live_after="$(docker ps --filter name=friday-os-stack- --format '{{.Names}}' | sort)"
if [ "$live_before" != "$live_after" ]; then
  echo "prove-memory: the existing friday-os-stack containers changed" >&2
  exit 1
fi
