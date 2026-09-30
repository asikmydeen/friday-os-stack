#!/usr/bin/env bash
# Postgres on a throwaway bridge. An app container on a throwaway
# internal network. The app must fail by name and by address. A
# container on the Postgres network must succeed. A container attached
# to both must succeed.
#
# The app network is internal because a second ordinary bridge on this
# Docker can still forward the address. The check is the address, not
# only the name.
#
# Does not call Compose and does not attach to the friday-os-stack project.
set -euo pipefail

cd "$(dirname "$0")/.."

prefix=friday-packet
core=friday-packet-core
apps=friday-packet-apps
image=python:3.13-slim

cleanup() {
  docker rm -f "$prefix-postgres" "$prefix-both" >/dev/null 2>&1 || true
  docker network rm "$apps" "$core" >/dev/null 2>&1 || true
}
trap cleanup EXIT

live_before="$(docker ps --filter name=friday-os-stack- --format '{{.Names}}' | sort)"

if ! docker image inspect "$image" >/dev/null 2>&1; then
  echo "prove-isolation: ${image} is not local" >&2
  exit 1
fi
if ! docker image inspect postgres:16-alpine >/dev/null 2>&1; then
  echo "prove-isolation: postgres:16-alpine is not local" >&2
  exit 1
fi

cleanup
trap cleanup EXIT

docker network create "$core" >/dev/null
docker network create --internal "$apps" >/dev/null

pg_password="$(python3 -c 'import secrets; print(secrets.token_hex(16))')"

docker run -d --name "$prefix-postgres" --network "$core" \
  -e "POSTGRES_PASSWORD=${pg_password}" \
  -e POSTGRES_USER=memory \
  -e POSTGRES_DB=memories \
  postgres:16-alpine >/dev/null

ready=0
for _ in $(seq 1 40); do
  if docker exec "$prefix-postgres" pg_isready -U memory -d memories >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done
if [ "$ready" != 1 ]; then
  echo "prove-isolation: postgres did not become ready" >&2
  docker logs "$prefix-postgres" 2>&1 | tail -20 >&2
  exit 1
fi

probe_out=""
probe() {
  local net="$1" expect="$2" host="$3"
  if ! probe_out="$(docker run --rm --network "$net" \
    -v "$PWD/scripts/prove_isolation.py:/prove.py:ro" \
    --entrypoint python \
    "$image" /prove.py "$expect" "$host" 5432 2>&1)"; then
    return 1
  fi
  return 0
}

opened=0
for _ in $(seq 1 10); do
  if probe "$core" open "$prefix-postgres"; then
    opened=1
    break
  fi
  sleep 1
done
if [ "$opened" != 1 ]; then
  echo "prove-isolation: a container on the postgres network could not open it" >&2
  printf '%s\n' "$probe_out" | grep -v -F "$pg_password" >&2 || true
  exit 1
fi

ip="$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$prefix-postgres")"
if [[ ! "$ip" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "prove-isolation: postgres had no address" >&2
  exit 1
fi

if ! probe "$apps" closed "$prefix-postgres"; then
  echo "prove-isolation: the app reached postgres by name" >&2
  printf '%s\n' "$probe_out" | grep -v -F "$pg_password" >&2 || true
  exit 1
fi
if ! probe "$apps" closed "$ip"; then
  echo "prove-isolation: the app opened postgres by address" >&2
  printf '%s\n' "$probe_out" | grep -v -F "$pg_password" >&2 || true
  exit 1
fi

docker create --name "$prefix-both" --network "$core" \
  -v "$PWD/scripts/prove_isolation.py:/prove.py:ro" \
  --entrypoint python \
  "$image" /prove.py open "$prefix-postgres" 5432 >/dev/null
docker network connect "$apps" "$prefix-both"
if ! both_out="$(docker start -a "$prefix-both")"; then
  echo "prove-isolation: a container on both networks could not open postgres" >&2
  printf '%s\n' "$both_out" | grep -v -F "$pg_password" >&2 || true
  exit 1
fi

live_after="$(docker ps --filter name=friday-os-stack- --format '{{.Names}}' | sort)"
if [ "$live_before" != "$live_after" ]; then
  echo "prove-isolation: the existing friday-os-stack containers changed" >&2
  exit 1
fi

echo "prove-isolation: an app container left postgres closed, a container on the postgres network opened it, and a container on both networks opened it"
