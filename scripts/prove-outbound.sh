#!/usr/bin/env bash
# Throwaway networks named friday-outboundproof-*. Outbound MCP sits on an
# internal network with one granted peer. Postgres sits on another network.
# tools/list returns only the granted intersection. send waits and is not
# forwarded. Postgres stays closed. This does not call Compose and does not
# attach to the friday-os-stack project.
set -euo pipefail

cd "$(dirname "$0")/.."

prefix=friday-outboundproof
core=${prefix}-core
net=${prefix}-net
base=python:3.13-slim

cleanup() {
  docker rm -f \
    ${prefix}-peer \
    ${prefix}-page \
    ${prefix}-outbound \
    >/dev/null 2>&1 || true
  docker network rm "$net" "$core" >/dev/null 2>&1 || true
}
trap cleanup EXIT

live_names() {
  docker ps --filter name=friday-os-stack- --format '{{.Names}}' | sort
}
live_before="$(live_names)"

if ! docker image inspect "$base" >/dev/null 2>&1; then
  echo "prove-outbound: ${base} is not local" >&2
  exit 1
fi

cleanup
trap cleanup EXIT

echo "building outbound image"
docker build -t friday-outboundproof/mcp:0.1.0 -f mcpbus/Dockerfile .

docker network create "$core" >/dev/null
docker network create --internal "$net" >/dev/null

docker run -d --name ${prefix}-peer \
  --network "$core" \
  --network-alias postgres \
  -v "$PWD/scripts/prove_outbound.py:/prove.py:ro" \
  --entrypoint python \
  "$base" /prove.py hold >/dev/null

docker run -d --name ${prefix}-page \
  --network "$net" \
  --network-alias peer \
  -v "$PWD/scripts/prove_outbound.py:/prove.py:ro" \
  --entrypoint python \
  "$base" /prove.py peer >/dev/null

token="$(python3 -c 'import secrets; print(secrets.token_hex(16))')"

docker run -d --name ${prefix}-outbound \
  --network "$net" \
  --network-alias outbound \
  -e OUTBOUND_ENABLED=yes \
  -e "OUTBOUND_TOKEN=${token}" \
  -e GRANTED_TOOLS=status,send \
  -e GRANTED_SERVERS=http://peer:8080/mcp \
  -e BIND_HOST=0.0.0.0 \
  -e PORT=8080 \
  -v "$PWD/scripts/prove_outbound.py:/prove.py:ro" \
  --entrypoint python \
  friday-outboundproof/mcp:0.1.0 -m mcpbus.outbound >/dev/null

ready=0
for _ in $(seq 1 30); do
  if docker exec ${prefix}-outbound python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=2).read()" >/dev/null 2>&1 \
    && docker exec ${prefix}-page python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/count', timeout=2).read()" >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done
if [ "$ready" -ne 1 ]; then
  echo "prove-outbound: listeners did not answer" >&2
  docker logs ${prefix}-outbound >&2 || true
  docker logs ${prefix}-page >&2 || true
  exit 1
fi

if [ -n "$(docker port ${prefix}-outbound)" ]; then
  echo "prove-outbound: host port published" >&2
  exit 1
fi

postgres_ip="$(docker inspect -f "{{(index .NetworkSettings.Networks \"${core}\").IPAddress}}" ${prefix}-peer)"

docker run --rm --network "$net" \
  -e OUTBOUND_URL=http://outbound:8080 \
  -e SERVER_URL=http://peer:8080/mcp \
  -e COUNT_URL=http://peer:8080/count \
  -e "OUTBOUND_TOKEN=${token}" \
  -e "POSTGRES_IP=${postgres_ip}" \
  -v "$PWD/scripts/prove_outbound.py:/prove.py:ro" \
  --entrypoint python \
  "$base" /prove.py client

docker exec -e "POSTGRES_IP=${postgres_ip}" ${prefix}-outbound python /prove.py closed

live_after="$(live_names)"
if [ "$live_before" != "$live_after" ]; then
  echo "prove-outbound: live containers changed" >&2
  exit 1
fi

echo outbound-ok
