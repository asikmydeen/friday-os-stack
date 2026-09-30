#!/usr/bin/env bash
# Build the four core images and run one conversation on a throwaway network.
# This does not call Compose and does not use the friday-os-stack project.
set -euo pipefail

cd "$(dirname "$0")/.."

prefix=friday-smoke
net=friday-os-smoke
board_port=18080
stub=/tmp/friday-smoke-stub.py

cleanup() {
  docker rm -f \
    "$prefix-board" \
    "$prefix-friday" \
    "$prefix-executor" \
    "$prefix-memory" \
    "$prefix-model" >/dev/null 2>&1 || true
  docker network rm "$net" >/dev/null 2>&1 || true
  rm -f "$stub"
}
trap cleanup EXIT

if python3 -c 'import socket,sys; s=socket.socket(); s.settimeout(0.2); busy=s.connect_ex(("127.0.0.1", 18080))==0; s.close(); sys.exit(1 if busy else 0)'; then
  :
else
  echo "smoke-core: 127.0.0.1:18080 is already in use" >&2
  exit 1
fi

set -a
eval "$(python3 - <<'PY'
import secrets
for name in (
    "MEMORY_TOKEN",
    "QDRANT_API_KEY",
    "BOARD_APPROVAL_TOKEN",
    "FRIDAY_NOTIFY_TOKEN",
    "BOARD_PASSWORD",
    "MODEL_API_KEY",
):
    print(f"{name}={secrets.token_hex(16)}")
PY
)"
set +a

docker build -f memoryd/Dockerfile -t friday-os-stack/memory-mcp:0.1.0 .
docker build -f executor/Dockerfile -t friday-os-stack/executor:0.1.0 .
docker build -f friday/Dockerfile -t friday-os-stack/friday:0.1.0 .
docker build -f board/Dockerfile -t friday-os-stack/board:0.1.0 .

cleanup
trap cleanup EXIT

docker network create "$net" >/dev/null

cat >"$stub" <<'PY'
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json

class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length") or "0")
        self.rfile.read(length)
        if self.path.startswith("/api/embeddings"):
            body = json.dumps({"embedding": [0.0] * 768}).encode()
        elif self.path.endswith("/chat/completions"):
            body = json.dumps(
                {"choices": [{"message": {"content": "What should we set up?"}}]}
            ).encode()
        else:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        return

ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
PY

docker run -d --name "$prefix-model" --network "$net" \
  -v "$stub:/stub.py:ro" \
  python:3.13-slim python /stub.py >/dev/null

docker run -d --name "$prefix-memory" --network "$net" \
  -e MEMORY_TOKEN \
  -e QDRANT_API_KEY \
  -e NOTES_PATH=/data/notes.json \
  -e BIND_HOST=0.0.0.0 \
  -e PORT=8080 \
  friday-os-stack/memory-mcp:0.1.0 >/dev/null

docker run -d --name "$prefix-executor" --network "$net" \
  -e BOARD_APPROVAL_TOKEN \
  -e FRIDAY_NOTIFY_TOKEN \
  -e STORE_PATH=/data/gate.json \
  -e BIND_HOST=0.0.0.0 \
  -e PORT=8080 \
  friday-os-stack/executor:0.1.0 >/dev/null

docker run -d --name "$prefix-friday" --network "$net" \
  -e FRIDAY_NOTIFY_TOKEN \
  -e MEMORY_TOKEN \
  -e MEMORY_URL=http://friday-smoke-memory:8080 \
  -e EXECUTOR_URL=http://friday-smoke-executor:8080 \
  -e MODEL_API_KEY \
  -e MODEL_BASE_URL=http://friday-smoke-model:8080/v1 \
  -e OLLAMA_URL=http://friday-smoke-model:8080 \
  -e BIND_HOST=0.0.0.0 \
  -e PORT=8080 \
  friday-os-stack/friday:0.1.0 >/dev/null

docker run -d --name "$prefix-board" --network "$net" \
  -p "127.0.0.1:${board_port}:8080" \
  -e BOARD_PASSWORD \
  -e FRIDAY_NOTIFY_TOKEN \
  -e BOARD_APPROVAL_TOKEN \
  -e FRIDAY_URL=http://friday-smoke-friday:8080 \
  -e EXECUTOR_URL=http://friday-smoke-executor:8080 \
  -e BIND_HOST=0.0.0.0 \
  -e PORT=8080 \
  friday-os-stack/board:0.1.0 >/dev/null

export BOARD_PORT="$board_port"
python3 - <<'PY'
import json, os, time, urllib.error, urllib.request

port = os.environ["BOARD_PORT"]
base = f"http://127.0.0.1:{port}"
password = os.environ["BOARD_PASSWORD"]
secrets = [
    password,
    os.environ["MEMORY_TOKEN"],
    os.environ["QDRANT_API_KEY"],
    os.environ["BOARD_APPROVAL_TOKEN"],
    os.environ["FRIDAY_NOTIFY_TOKEN"],
    os.environ["MODEL_API_KEY"],
]

def call(path, method="GET", payload=None, auth=True):
    data = None if payload is None else json.dumps(payload).encode()
    headers = {}
    if auth:
        headers["Friday-Board"] = password
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read()
            return response.status, raw, response.headers.get_content_type()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), exc.headers.get_content_type()

def js(path, method="GET", payload=None, auth=True):
    status, raw, _type = call(path, method, payload, auth)
    body = json.loads(raw.decode() or "{}")
    text = json.dumps(body)
    for secret in secrets:
        if secret and secret in text:
            raise SystemExit(f"secret echoed from {path}")
    return status, body

deadline = time.time() + 40
page = b""
while time.time() < deadline:
    try:
        status, page, _type = call("/", auth=False)
    except OSError:
        time.sleep(0.5)
        continue
    if status == 200 and b"Let Friday speak first" in page:
        break
    time.sleep(0.5)
else:
    raise SystemExit("board did not serve the page")

for secret in secrets:
    if secret.encode() in page:
        raise SystemExit("secret appeared in the page")

status, body = js("/api/status", auth=False)
if status != 401:
    raise SystemExit(f"open status was {status}")
status, body = js("/api/status")
if status != 200 or "Catalog install stays closed" not in body.get("reply", ""):
    raise SystemExit(f"status: {status} {body}")

deadline = time.time() + 40
status, body = 0, {}
while time.time() < deadline:
    try:
        status, body = js("/api/ask", "POST", {"bootstrap": True, "text": "", "confirmed": True})
    except OSError:
        time.sleep(1)
        continue
    if status == 200 and body.get("reply") == "What should we set up?":
        break
    time.sleep(1)
else:
    raise SystemExit(f"bootstrap: {status} {body}")
if "confirmed" in body:
    raise SystemExit("confirmed was stored")

status, body = js("/api/ask", "POST", {"text": "remember the project codename is lighthouse"})
if body.get("reply") != "I'll remember that.":
    raise SystemExit(f"remember: {status} {body}")

status, body = js("/api/ask", "POST", {"text": "send the note to sam@example.com", "confirmed": True})
if body.get("outcome") != "waiting" or body.get("action") != "send":
    raise SystemExit(f"send: {status} {body}")

status, recorded = js("/api/approve", "POST", {
    "action": body["action"],
    "target": body["target"],
    "payload_digest": body["payload_digest"],
})
if recorded.get("reply") != "Recorded on the Board. Nothing was sent." or recorded.get("started") is not False:
    raise SystemExit(f"approve: {status} {recorded}")

status, closed = js("/api/approve", "POST", {"action": "install"})
if closed.get("reply") != "Catalog install is closed.":
    raise SystemExit(f"install: {status} {closed}")
print("board conversation ok")
PY

docker restart "$prefix-memory" >/dev/null
docker restart "$prefix-executor" >/dev/null
sleep 2

docker exec -i "$prefix-friday" python - <<'PY'
import json, os, urllib.request
token = os.environ["MEMORY_TOKEN"]
request = urllib.request.Request(
    "http://friday-smoke-memory:8080/recall",
    data=json.dumps({"owner_id": "owner", "owner_kind": "person", "limit": 8}).encode(),
    headers={"Content-Type": "application/json", "Friday-Memory": token},
    method="POST",
)
with urllib.request.urlopen(request, timeout=10) as response:
    body = json.loads(response.read())
notes = body.get("notes") or []
if not notes or notes[0]["content"] != "the project codename is lighthouse":
    raise SystemExit(f"recall after restart failed: {body.get('reason')}")
print("memory file kept the note")
PY

docker exec -i "$prefix-executor" python - <<'PY'
import json
from pathlib import Path
raw = json.loads(Path("/data/gate.json").read_text())
if len(raw.get("approvals") or {}) != 1:
    raise SystemExit("approval was not kept")
if len(raw.get("tasks") or {}) != 1:
    raise SystemExit("task was not kept")
print("executor file kept the approval")
PY

docker exec -i "$prefix-friday" python - <<'PY'
import json, os, urllib.error, urllib.request
request = urllib.request.Request(
    "http://friday-smoke-executor:8080/approvals",
    data=b"{}",
    headers={
        "Content-Type": "application/json",
        "Friday-Notify": os.environ["FRIDAY_NOTIFY_TOKEN"],
    },
    method="POST",
)
try:
    urllib.request.urlopen(request, timeout=10)
except urllib.error.HTTPError as exc:
    body = json.loads(exc.read())
    if exc.code != 401 or body.get("reason") != "unauthenticated":
        raise SystemExit(f"notify token was not refused: {exc.code}")
else:
    raise SystemExit("notify token created an approval")
print("friday cannot approve")
PY

echo "smoke-core: one conversation on ${net}"
