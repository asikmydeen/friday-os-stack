#!/usr/bin/env bash
# Bring Postgres, Qdrant, and the pinned embed model up to docs/memory.md.
#
# 1. Wait until Qdrant and Ollama answer.
# 2. Refuse unless nomic-embed-text returns a 768-dimension vector.
#    A different model is not accepted, including another 768-dimension model.
# 3. Create the bootstrap collections if they are missing. An existing
#    collection is left in place, so a second run does not wipe notes.
# 4. Create keyword payload indexes on owner_id, owner_kind, topic, source.
# 5. Apply sql/memories.sql.
# 6. Write one smoke point, search it back, delete it, and exit 0 only then.
#
# This scaffold's Ollama image does not contain the weights, so a missing
# pin is pulled once. A release image is expected to already contain
# nomic-embed-text; this script still refuses any other name.
set -euo pipefail

root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
cd "$root"

if ! command -v docker >/dev/null 2>&1; then
  echo "bootstrap-memory: docker is required" >&2
  exit 1
fi

# Some clients reject `docker compose --profile` ("unknown flag: --profile")
# and ship Compose v2 as `docker-compose`. Use whichever form runs.
if docker compose version >/dev/null 2>&1; then
  compose() { docker compose --profile core "$@"; }
elif command -v docker-compose >/dev/null 2>&1 && docker-compose version >/dev/null 2>&1; then
  compose() { docker-compose --profile core "$@"; }
else
  echo "bootstrap-memory: docker compose is required" >&2
  exit 1
fi

if [ ! -f .env ]; then
  echo "bootstrap-memory: .env is missing. Copy .env.example and set POSTGRES_PASSWORD." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1091
. ./.env
set +a

if [ -z "${POSTGRES_PASSWORD:-}" ]; then
  echo "bootstrap-memory: POSTGRES_PASSWORD is empty. Postgres will not start." >&2
  exit 1
fi

db=${POSTGRES_DB:-memories}
user=${POSTGRES_USER:-postgres}
if [ -z "$user" ]; then
  user=postgres
fi

echo "bootstrap-memory: starting qdrant, ollama, and postgres" >&2
compose up -d qdrant ollama postgres

ready=0
for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30; do
  if compose exec -T postgres pg_isready -U "$user" -d "$db" >/dev/null 2>&1 \
    && compose exec -T ollama ollama list >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 2
done
if [ "$ready" != 1 ]; then
  echo "bootstrap-memory: postgres or ollama did not become ready" >&2
  exit 1
fi

if ! compose exec -T ollama ollama list | grep -q 'nomic-embed-text'; then
  echo "bootstrap-memory: pulling nomic-embed-text" >&2
  compose exec -T ollama ollama pull nomic-embed-text
fi

postgres_id=$(compose ps -q postgres)
if [ -z "$postgres_id" ]; then
  echo "bootstrap-memory: postgres is not running" >&2
  exit 1
fi
network=$(docker inspect -f '{{range $name, $_ := .NetworkSettings.Networks}}{{println $name}}{{end}}' "$postgres_id" | head -n 1)
if [ -z "$network" ]; then
  echo "bootstrap-memory: could not find the compose network" >&2
  exit 1
fi

run_phase() {
  docker run --rm \
    --network "$network" \
    -e QDRANT_URL=http://qdrant:6333 \
    -e OLLAMA_URL=http://ollama:11434 \
    -e QDRANT_API_KEY="${QDRANT_API_KEY:-}" \
    -v "$root/scripts/bootstrap_memory.py:/bootstrap_memory.py:ro" \
    python:3.12-alpine \
    python3 /bootstrap_memory.py "$1"
}

echo "bootstrap-memory: checking the embed model and creating collections" >&2
run_phase prepare

echo "bootstrap-memory: applying sql/memories.sql" >&2
compose exec -T postgres \
  psql -v ON_ERROR_STOP=1 -U "$user" -d "$db" \
  -f /docker-entrypoint-initdb.d/memories.sql
functions=$(compose exec -T postgres \
  psql -v ON_ERROR_STOP=1 -tA -U "$user" -d "$db" -c \
  "SELECT count(*) FROM pg_proc WHERE proname IN ('memory_save','memory_tombstone','memory_index_claim','memory_index_finish');")
functions=$(printf '%s' "$functions" | tr -d '[:space:]')
if [ "$functions" != "4" ]; then
  echo "bootstrap-memory: expected 4 memory functions, found ${functions:-none}" >&2
  exit 1
fi

echo "bootstrap-memory: smoke point" >&2
run_phase smoke
