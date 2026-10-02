#!/usr/bin/env bash
# Throwaway networks named friday-reach-*. An app on the internal network
# must fail to open the executor, the gateway, Postgres, and Qdrant. A
# container on core must open the executor and read Jellyfin's health
# through the gateway. An app posts a webhook and the reply is the fixed
# sentence, without the raw body.
#
# Postgres and Qdrant here are listeners on the core network only, so a
# forwarded address would show up as open. This does not call Compose and
# does not attach to the friday-os-stack project.
set -euo pipefail

cd "$(dirname "$0")/.."

prefix=friday-reach
core=${prefix}-core
apps=${prefix}-apps
base=python:3.13-slim
marker=body-marker-not-for-the-model

cleanup() {
  docker rm -f \
    ${prefix}-peer \
    ${prefix}-executor \
    ${prefix}-gateway \
    ${prefix}-webhooks \
    ${prefix}-jellyfin \
    ${prefix}-health \
    >/dev/null 2>&1 || true
  docker network rm "$apps" "$core" >/dev/null 2>&1 || true
}
trap cleanup EXIT

live_names() {
  docker ps --filter name=friday-os-stack- --format '{{.Names}}' | sort
}
live_before="$(live_names)"

for image in "$base"; do
  if ! docker image inspect "$image" >/dev/null 2>&1; then
    echo "prove-reach: ${image} is not local" >&2
    exit 1
  fi
done

cleanup
trap cleanup EXIT

echo "building reach images"
docker build -t friday-reach/executor:0.1.0 -f executor/Dockerfile .
docker build -t friday-reach/gateway:0.1.0 -f gateway/Dockerfile .
docker build -t friday-reach/webhooks:0.1.0 -f webhooks/Dockerfile .

docker network create "$core" >/dev/null
docker network create --internal "$apps" >/dev/null

docker run -d --name ${prefix}-peer \
  --network "$core" \
  --network-alias postgres \
  --network-alias qdrant \
  -v "$PWD/scripts/prove_reach.py:/prove.py:ro" \
  --entrypoint python \
  "$base" /prove.py hold >/dev/null

jellyfin_secret="$(python3 -c 'import secrets; print(secrets.token_hex(16))')"
radarr_secret="$(python3 -c 'import secrets; print(secrets.token_hex(16))')"
approval_token="$(python3 -c 'import secrets; print(secrets.token_hex(16))')"
notify_token="$(python3 -c 'import secrets; print(secrets.token_hex(16))')"

docker create --name ${prefix}-executor \
  --network "$core" \
  --network-alias executor \
  -e BIND_HOST=core \
  -e CORE_PEER=postgres \
  -e "BOARD_APPROVAL_TOKEN=${approval_token}" \
  -e "FRIDAY_NOTIFY_TOKEN=${notify_token}" \
  friday-reach/executor:0.1.0 >/dev/null
docker network connect --alias executor "$apps" ${prefix}-executor
docker start ${prefix}-executor >/dev/null

docker create --name ${prefix}-gateway \
  --network "$core" \
  --network-alias gateway \
  -e BIND_HOST=core \
  -e CORE_PEER=postgres \
  -e WIRES_DIR=/wires \
  -v "$PWD/catalog/wires:/wires:ro" \
  friday-reach/gateway:0.1.0 >/dev/null
docker network connect --alias gateway "$apps" ${prefix}-gateway
docker start ${prefix}-gateway >/dev/null

docker run -d --name ${prefix}-webhooks \
  --network "$apps" \
  --network-alias webhooks \
  -e BIND_HOST=0.0.0.0 \
  -e "WEBHOOK_SECRET_JELLYFIN=${jellyfin_secret}" \
  -e "WEBHOOK_SECRET_RADARR=${radarr_secret}" \
  -e WEBHOOK_SECRET_SONARR=unused-sonarr-secret \
  friday-reach/webhooks:0.1.0 >/dev/null

docker run -d --name ${prefix}-jellyfin \
  --network "$apps" \
  --network-alias jellyfin \
  -v "$PWD/scripts/prove_reach.py:/prove.py:ro" \
  --entrypoint python \
  "$base" -c 'from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"jellyfin-health-ok"
        if self.path.split("?", 1)[0] != "/health":
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, fmt, *args):
        return
ThreadingHTTPServer(("0.0.0.0", 8096), H).serve_forever()' >/dev/null

port_probe() {
  docker run --rm --network "$1" \
    -v "$PWD/scripts/prove_isolation.py:/prove.py:ro" \
    --entrypoint python \
    "$base" /prove.py "$2" "$3" "$4"
}

http_get() {
  docker run --rm --network "$1" \
    -v "$PWD/scripts/prove_reach.py:/prove.py:ro" \
    --entrypoint python \
    "$base" /prove.py get "$2" "$3"
}

http_post() {
  docker run --rm --network "$1" \
    -e "WEBHOOK_SECRET=$2" \
    -e "WEBHOOK_BODY=$3" \
    -v "$PWD/scripts/prove_reach.py:/prove.py:ro" \
    --entrypoint python \
    "$base" /prove.py post "$4" "$5" "$6"
}

ready=0
for _ in $(seq 1 30); do
  if http_get "$core" http://executor:8080/health health >/tmp/friday-reach-executor.txt 2>/tmp/friday-reach-executor.err \
    && http_get "$core" http://gateway:8090/jellyfin/health jellyfin-health-ok >/tmp/friday-reach-gateway.txt 2>/tmp/friday-reach-gateway.err; then
    ready=1
    break
  fi
  sleep 1
done
if [ "$ready" != 1 ]; then
  echo "prove-reach: executor or gateway did not answer on core" >&2
  docker logs ${prefix}-executor 2>&1 | tail -30 >&2 || true
  docker logs ${prefix}-gateway 2>&1 | tail -30 >&2 || true
  cat /tmp/friday-reach-executor.txt /tmp/friday-reach-gateway.txt >&2 || true
  exit 1
fi

peer_ip="$(docker inspect -f "{{(index .NetworkSettings.Networks \"${core}\").IPAddress}}" ${prefix}-peer)"
exec_core="$(docker inspect -f "{{(index .NetworkSettings.Networks \"${core}\").IPAddress}}" ${prefix}-executor)"
exec_apps="$(docker inspect -f "{{(index .NetworkSettings.Networks \"${apps}\").IPAddress}}" ${prefix}-executor)"
gw_core="$(docker inspect -f "{{(index .NetworkSettings.Networks \"${core}\").IPAddress}}" ${prefix}-gateway)"
gw_apps="$(docker inspect -f "{{(index .NetworkSettings.Networks \"${apps}\").IPAddress}}" ${prefix}-gateway)"

port_probe "$apps" closed postgres 5432
port_probe "$apps" closed qdrant 6333
port_probe "$apps" closed "$peer_ip" 5432
port_probe "$apps" closed "$peer_ip" 6333
port_probe "$apps" closed executor 8080
port_probe "$apps" closed "$exec_apps" 8080
port_probe "$apps" closed "$exec_core" 8080
port_probe "$apps" closed gateway 8090
port_probe "$apps" closed "$gw_apps" 8090
port_probe "$apps" closed "$gw_core" 8090

port_probe "$core" open postgres 5432
port_probe "$core" open qdrant 6333
port_probe "$core" open executor 8080
port_probe "$core" open gateway 8090

http_post "$apps" "$jellyfin_secret" \
  "{\"NotificationType\":\"Health\",\"note\":\"${marker}\"}" \
  http://webhooks:8080/media "An app health state changed." "$marker"
http_post "$apps" "$radarr_secret" \
  "{\"eventType\":\"Grab\",\"note\":\"${marker}\"}" \
  http://webhooks:8080/arr "A download was grabbed." "$marker"

# The executor's position: on core and on apps, reading the app's health URL.
docker create --name ${prefix}-health \
  --network "$core" \
  --entrypoint python \
  friday-reach/executor:0.1.0 \
  -c 'import urllib.request
body = urllib.request.urlopen("http://jellyfin:8096/health", timeout=5).read().decode()
raise SystemExit(0 if "jellyfin-health-ok" in body else 1)' >/dev/null
docker network connect "$apps" ${prefix}-health
docker start -a ${prefix}-health >/dev/null

# A POST is not a wire health call.
docker run --rm --network "$core" --entrypoint python "$base" -c '
import urllib.request
req = urllib.request.Request("http://gateway:8090/jellyfin/health", data=b"{}", method="POST")
try:
    urllib.request.urlopen(req, timeout=5)
    raise SystemExit(1)
except Exception as exc:
    code = getattr(exc, "code", None)
    body = exc.read().decode() if hasattr(exc, "read") else ""
    print(code)
    print(body)
    raise SystemExit(0 if code == 403 and "not_allowed" in body else 1)
'

live_after="$(live_names)"
if [ "$live_before" != "$live_after" ]; then
  echo "prove-reach: live containers changed" >&2
  echo "before: $live_before" >&2
  echo "after: $live_after" >&2
  exit 1
fi

echo "reach-ok"
