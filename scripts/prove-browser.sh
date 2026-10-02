#!/usr/bin/env bash
# Throwaway networks named friday-browserproof-*. The browser session sits
# on an internal network with one page. Postgres sits on another network.
# A read returns the page with the vault secret removed. Pay waits and is
# not fetched. Postgres stays closed. This does not call Compose and does
# not attach to the friday-os-stack project.
set -euo pipefail

cd "$(dirname "$0")/.."

prefix=friday-browserproof
core=${prefix}-core
browser_net=${prefix}-browser
base=python:3.13-slim

cleanup() {
  docker rm -f \
    ${prefix}-peer \
    ${prefix}-page \
    ${prefix}-browser \
    >/dev/null 2>&1 || true
  docker network rm "$browser_net" "$core" >/dev/null 2>&1 || true
}
trap cleanup EXIT

live_names() {
  docker ps --filter name=friday-os-stack- --format '{{.Names}}' | sort
}
live_before="$(live_names)"

if ! docker image inspect "$base" >/dev/null 2>&1; then
  echo "prove-browser: ${base} is not local" >&2
  exit 1
fi

cleanup
trap cleanup EXIT

echo "building browser image"
docker build -t friday-browserproof/browser:0.1.0 -f browser/Dockerfile .

docker network create "$core" >/dev/null
docker network create --internal "$browser_net" >/dev/null

docker run -d --name ${prefix}-peer \
  --network "$core" \
  --network-alias postgres \
  -v "$PWD/scripts/prove_browser.py:/prove.py:ro" \
  --entrypoint python \
  "$base" /prove.py hold >/dev/null

docker run -d --name ${prefix}-page \
  --network "$browser_net" \
  --network-alias shop \
  -v "$PWD/scripts/prove_browser.py:/prove.py:ro" \
  --entrypoint python \
  "$base" /prove.py page >/dev/null

browser_token="$(python3 -c 'import secrets; print(secrets.token_hex(16))')"

docker run -d --name ${prefix}-browser \
  --network "$browser_net" \
  --network-alias browser \
  -e BROWSER_ENABLED=yes \
  -e "BROWSER_TOKEN=${browser_token}" \
  -e SITE_HOST=shop \
  -e BIND_HOST=0.0.0.0 \
  -e PORT=8080 \
  -v "$PWD/scripts/prove_browser.py:/prove.py:ro" \
  friday-browserproof/browser:0.1.0 >/dev/null

ready=0
for _ in $(seq 1 30); do
  if docker exec ${prefix}-browser python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=2).read()" >/dev/null 2>&1 \
    && docker exec ${prefix}-page python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/count', timeout=2).read()" >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done
if [ "$ready" -ne 1 ]; then
  echo "prove-browser: listeners did not answer" >&2
  docker logs ${prefix}-browser >&2 || true
  docker logs ${prefix}-page >&2 || true
  exit 1
fi

if [ -n "$(docker port ${prefix}-browser)" ]; then
  echo "prove-browser: host port published" >&2
  exit 1
fi

postgres_ip="$(docker inspect -f "{{(index .NetworkSettings.Networks \"${core}\").IPAddress}}" ${prefix}-peer)"

docker run --rm --network "$browser_net" \
  -e BROWSER_URL=http://browser:8080 \
  -e PAGE_URL=http://shop:8080/item \
  -e COUNT_URL=http://shop:8080/count \
  -e "BROWSER_TOKEN=${browser_token}" \
  -e "POSTGRES_IP=${postgres_ip}" \
  -v "$PWD/scripts/prove_browser.py:/prove.py:ro" \
  --entrypoint python \
  "$base" /prove.py client

docker exec -e "POSTGRES_IP=${postgres_ip}" ${prefix}-browser python /prove.py closed

live_after="$(live_names)"
if [ "$live_before" != "$live_after" ]; then
  echo "prove-browser: live containers changed" >&2
  exit 1
fi

echo browser-ok
