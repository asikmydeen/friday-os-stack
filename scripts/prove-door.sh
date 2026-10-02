#!/usr/bin/env bash
# Throwaway networks named friday-doorproof-*. The door and the MCP listener
# sit on an internal network with Friday. Postgres sits on another network.
# A turn reaches Friday. A mutating tool waits and is not forwarded. Postgres
# stays closed. This does not call Compose and does not attach to the
# friday-os-stack project.
set -euo pipefail

cd "$(dirname "$0")/.."

prefix=friday-doorproof
core=${prefix}-core
doors=${prefix}-doors
base=python:3.13-slim

cleanup() {
  docker rm -f \
    ${prefix}-peer \
    ${prefix}-friday \
    ${prefix}-door \
    ${prefix}-mcp \
    >/dev/null 2>&1 || true
  docker network rm "$doors" "$core" >/dev/null 2>&1 || true
}
trap cleanup EXIT

live_names() {
  docker ps --filter name=friday-os-stack- --format '{{.Names}}' | sort
}
live_before="$(live_names)"

if ! docker image inspect "$base" >/dev/null 2>&1; then
  echo "prove-door: ${base} is not local" >&2
  exit 1
fi

cleanup
trap cleanup EXIT

echo "building door images"
docker build -t friday-doorproof/door:0.1.0 -f doors/Dockerfile .
docker build -t friday-doorproof/mcp:0.1.0 -f mcpbus/Dockerfile .

docker network create "$core" >/dev/null
docker network create --internal "$doors" >/dev/null

docker run -d --name ${prefix}-peer \
  --network "$core" \
  --network-alias postgres \
  -v "$PWD/scripts/prove_door.py:/prove.py:ro" \
  --entrypoint python \
  "$base" /prove.py hold >/dev/null

docker run -d --name ${prefix}-friday \
  --network "$doors" \
  --network-alias friday \
  -v "$PWD/scripts/prove_door.py:/prove.py:ro" \
  --entrypoint python \
  "$base" /prove.py friday >/dev/null

door_token="$(python3 -c 'import secrets; print(secrets.token_hex(16))')"
mcp_token="$(python3 -c 'import secrets; print(secrets.token_hex(16))')"
notify_token="$(python3 -c 'import secrets; print(secrets.token_hex(16))')"

docker run -d --name ${prefix}-door \
  --network "$doors" \
  --network-alias door \
  -e DOOR_ENABLED=yes \
  -e "DOOR_TOKEN=${door_token}" \
  -e "FRIDAY_NOTIFY_TOKEN=${notify_token}" \
  -e FRIDAY_URL=http://friday:8080 \
  -e BIND_HOST=0.0.0.0 \
  -e PORT=8080 \
  -v "$PWD/scripts/prove_door.py:/prove.py:ro" \
  friday-doorproof/door:0.1.0 >/dev/null

docker run -d --name ${prefix}-mcp \
  --network "$doors" \
  --network-alias mcp \
  -e MCP_ENABLED=yes \
  -e "MCP_TOKEN=${mcp_token}" \
  -e "FRIDAY_NOTIFY_TOKEN=${notify_token}" \
  -e FRIDAY_URL=http://friday:8080 \
  -e GRANTED_TOOLS=recall,send \
  -e BIND_HOST=0.0.0.0 \
  -e PORT=8080 \
  -v "$PWD/scripts/prove_door.py:/prove.py:ro" \
  friday-doorproof/mcp:0.1.0 >/dev/null

ready=0
for _ in $(seq 1 30); do
  if docker exec ${prefix}-door python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=2).read()" >/dev/null 2>&1 \
    && docker exec ${prefix}-mcp python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=2).read()" >/dev/null 2>&1 \
    && docker exec ${prefix}-friday python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=2).read()" >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done
if [ "$ready" -ne 1 ]; then
  echo "prove-door: listeners did not answer" >&2
  docker logs ${prefix}-door >&2 || true
  docker logs ${prefix}-mcp >&2 || true
  exit 1
fi

if [ -n "$(docker port ${prefix}-door)" ] || [ -n "$(docker port ${prefix}-mcp)" ]; then
  echo "prove-door: host port published" >&2
  exit 1
fi

postgres_ip="$(docker inspect -f "{{(index .NetworkSettings.Networks \"${core}\").IPAddress}}" ${prefix}-peer)"

docker run --rm --network "$doors" \
  -e DOOR_URL=http://door:8080 \
  -e MCP_URL=http://mcp:8080 \
  -e FRIDAY_URL=http://friday:8080 \
  -e "DOOR_TOKEN=${door_token}" \
  -e "MCP_TOKEN=${mcp_token}" \
  -e "FRIDAY_NOTIFY_TOKEN=${notify_token}" \
  -e "POSTGRES_IP=${postgres_ip}" \
  -v "$PWD/scripts/prove_door.py:/prove.py:ro" \
  --entrypoint python \
  "$base" /prove.py client

docker exec -e "POSTGRES_IP=${postgres_ip}" ${prefix}-door python /prove.py closed
docker exec -e "POSTGRES_IP=${postgres_ip}" ${prefix}-mcp python /prove.py closed

live_after="$(live_names)"
if [ "$live_before" != "$live_after" ]; then
  echo "prove-door: live containers changed" >&2
  exit 1
fi

echo door-ok
