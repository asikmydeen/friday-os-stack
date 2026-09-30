#!/bin/bash
# Boot the installed-role lab disk and ask it to create the server.
# The serial console is only how this lab types. The USB image keeps the keyboard.
set -euo pipefail

OUT="${FRIDAY_IMAGE_OUT:-/tmp/friday-image}"
DISK="$OUT/work/installed-lab.img"
QEMU="${QEMU:-/opt/homebrew/bin/qemu-system-x86_64}"
CODE="/opt/homebrew/share/qemu/edk2-x86_64-code.fd"
VARS_SRC="/opt/homebrew/share/qemu/edk2-i386-vars.fd"
RUN=/tmp/friday-qemu
VARS="$RUN/vars-lab.fd"
LOG="$RUN/lab-serial.log"
QLOG="$RUN/lab-qemu.log"
PORT=4445

if [ ! -s "$DISK" ]; then
  echo "lab disk missing: $DISK" >&2
  exit 1
fi
mkdir -p "$RUN"
cp "$VARS_SRC" "$VARS"
: > "$LOG"
if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "port $PORT is already in use" >&2
  exit 1
fi

"$QEMU" \
  -machine q35,accel=tcg \
  -m 8192 -cpu max -smp 2 -no-reboot \
  -drive if=pflash,format=raw,readonly=on,file="$CODE" \
  -drive if=pflash,format=raw,file="$VARS" \
  -drive if=none,id=stick,format=raw,file="$DISK" \
  -device qemu-xhci,id=xhci \
  -device usb-storage,bus=xhci.0,drive=stick,bootindex=0 \
  -serial tcp:127.0.0.1:"$PORT",server=on,wait=off \
  -display none -vga none \
  >"$QLOG" 2>&1 &
qpid=$!
cleanup() {
  kill "$qpid" 2>/dev/null || true
  wait "$qpid" 2>/dev/null || true
}
trap cleanup EXIT

python3 - "$PORT" "$LOG" <<'PY'
import socket
import sys
import time

port = int(sys.argv[1])
log_path = sys.argv[2]
buf = ""
sock = None
prompt_deadline = time.time() + 900

def take(chunk: bytes) -> None:
    global buf
    text = chunk.decode("utf-8", "replace")
    buf += text
    with open(log_path, "a", encoding="utf-8") as handle:
        handle.write(text)

while time.time() < prompt_deadline:
    if sock is None:
        try:
            sock = socket.create_connection(("127.0.0.1", port), timeout=5)
            sock.settimeout(5)
        except OSError:
            time.sleep(1)
            continue
    try:
        chunk = sock.recv(4096)
    except (TimeoutError, socket.timeout):
        continue
    except OSError:
        time.sleep(1)
        continue
    if not chunk:
        time.sleep(1)
        continue
    take(chunk)
    if "Type the kernel name" in buf:
        print("BOOTED_INSTALLER")
        sys.exit(2)
    if "Commands:" in buf:
        break
else:
    print("NO_PROMPT")
    sys.exit(1)

sock.sendall(b"server\n")
end = time.time() + 2700
while time.time() < end:
    try:
        chunk = sock.recv(4096)
    except (TimeoutError, socket.timeout):
        continue
    except OSError:
        time.sleep(1)
        continue
    if not chunk:
        time.sleep(1)
        continue
    take(chunk)
    if "The core on this computer was started" in buf:
        print("CORE_STARTED")
        sys.exit(0)
    if any(
        mark in buf
        for mark in (
            "The core did not start",
            "start_failed",
            "core_not_in_image",
            "embed_not_ready",
            "embed_weights_missing",
            "core_images_missing",
            "Kernel panic",
        )
    ):
        print("CORE_FAILED")
        sys.exit(1)
print("TIMEOUT")
sys.exit(1)
PY
