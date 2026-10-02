"""Boot entry for the test image. The installer and the setup screen share one process."""

from __future__ import annotations

import os
import select
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from image.console import InstallerConsole, SetupConsole
from image.disks import Disk, parent_disk
from image.install import apply, write_installed
from image.kiosk import TOKEN_PATH, place_token
from image.provision import serve
from image.setup import Store, SystemRng, read_ifaces
from image.starter import CODES, publish_board, start_core
from image.wifi import join_wifi

DATA = Path("/var/lib/friday")
SYS_BLOCK = Path("/sys/block")
MOUNTS = Path("/proc/mounts")
MEMINFO = Path("/proc/meminfo")
OMITTED = Path("/etc/friday-omitted")
ROLE = Path("/etc/friday-role")
BOOT_EFI = Path("/usr/lib/friday/BOOTX64.EFI")


def run() -> None:
    role = ROLE.read_text().strip() if ROLE.is_file() else ""
    if role == "installer":
        run_installer()
    elif role == "installed":
        run_installed()
    else:
        _write("Friday role is not set.\n")
        raise SystemExit(1)


def run_installer() -> None:
    disks, known = live_disks()
    console = InstallerConsole(disks, installer_known=known, mem_total_kib=mem_total())
    _write(console.banner())
    for line in _lines():
        _write(console.line(line))
        if console.ready and console.phase == "copying":
            try:
                apply(console.chosen, _run)
                write_installed(
                    Path("/mnt/friday-a"),
                    Path("/mnt/friday-a/boot/efi"),
                    Path("/mnt/friday-data"),
                    BOOT_EFI,
                )
                for mount in ("/mnt/friday-a/boot/efi", "/mnt/friday-data", "/mnt/friday-a"):
                    subprocess.run(["umount", mount], check=False)
            except (OSError, subprocess.CalledProcessError, ValueError) as exc:
                console.phase = "failed"
                console.ready = False
                _write(f"Install failed: {exc}\n")
                continue
            console.phase = "reboot"
            _write("Installed onto slot A. Remove this stick, then type reboot.\n")
        if console.reboot:
            subprocess.run(["systemctl", "reboot"], check=False)
            return


def run_installed() -> None:
    if not data_mounted(MOUNTS.read_text() if MOUNTS.is_file() else ""):
        _write("The data partition is not mounted. Secrets were not created.\n")
        raise SystemExit(1)
    store = Store(DATA)
    store.ifaces = read_ifaces(Path("/sys/class/net"))
    store.zone_exists = zone_exists
    store.resolve = resolve
    store.transport = model_transport
    store.embed_transport = embed_transport
    store.load_or_mint(SystemRng(), _etc_machine_id())
    if OMITTED.is_file():
        store.omitted = [line for line in OMITTED.read_text().splitlines() if line]
    store.starter = start_core
    store.joiner = _join_wifi
    if store.wifi_ssid and store.wifi_password:
        try:
            store.joiner(store.wifi_ssid, store.wifi_password)
        except OSError:
            store.wifi_joined = False
            store._text("wifi_joined", "no")
        else:
            store.wifi_joined = True
            store._text("wifi_joined", "yes")
    _persist_machine_id(store.machine_id)
    _publish_kiosk_token(store)
    if store.server_note == "started":
        try:
            start_core(store)
            store.started = True
        except OSError as exc:
            store.started = False
            store.server_note = str(exc) if str(exc) in CODES else "start_failed"
            store._text("server_note", store.server_note)
            _write("The core did not start.\n")
    if store.provision_state == "complete":
        _publish(store)
        console = SetupConsole(store)
        _write(console.banner())
        for line in _lines():
            _write(console.line(line))
        return
    httpd = serve(store, 8080)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    def handoff() -> None:
        _publish_kiosk_token(store)

        def go() -> None:
            time.sleep(0.4)
            httpd.shutdown()
            _publish(store)

        threading.Thread(target=go, daemon=True).start()

    store.handoff = handoff
    console = SetupConsole(store)
    _write(console.banner())
    for line in _lines():
        _write(console.line(line))


def _publish_kiosk_token(store: Store) -> None:
    try:
        place_token(store.provision_token, TOKEN_PATH)
    except OSError:
        _write("The monitor token was not published.\n")


def _publish(store: Store) -> None:
    try:
        publish_board(store)
    except OSError:
        _write("The Board did not take the screen.\n")
    else:
        _write("The Board is on 127.0.0.1:8080.\n")


def live_disks() -> tuple[list[Disk], bool]:
    installer = installer_names()
    known = bool(installer)
    disks = []
    if not SYS_BLOCK.is_dir():
        return disks, False
    for entry in sorted(SYS_BLOCK.iterdir()):
        name = entry.name
        if name.startswith(("loop", "ram", "fd", "sr", "nbd", "zram", "dm-")):
            continue
        try:
            sectors = int((entry / "size").read_text().strip())
        except (OSError, ValueError):
            continue
        disks.append(Disk(name, sectors * 512, name in installer))
    return disks, known


def installer_names() -> set[str]:
    mounts = MOUNTS.read_text() if MOUNTS.is_file() else ""
    device = root_device(mounts)
    if device in {None, "root"}:
        label = Path("/dev/disk/by-label/friday-installer")
        if label.exists():
            device = os.path.realpath(label).rsplit("/", 1)[-1]
        else:
            return set()
    if not device:
        return set()
    return {parent_disk(device)}


def root_device(mounts: str) -> str | None:
    for line in mounts.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "/" and parts[0].startswith("/dev/"):
            return parts[0].rsplit("/", 1)[-1]
    return None


def data_mounted(mounts: str) -> bool:
    for line in mounts.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "/var/lib/friday":
            return True
    return False


def mem_total() -> int:
    if not MEMINFO.is_file():
        return 0
    for line in MEMINFO.read_text().splitlines():
        if line.startswith("MemTotal:"):
            return int(line.split()[1])
    return 0


def zone_exists(name: str) -> bool:
    root = Path("/usr/share/zoneinfo").resolve()
    candidate = (root / name).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return candidate.is_file()


def resolve(host: str) -> list[str]:
    found = []
    try:
        for item in socket.getaddrinfo(host, None):
            found.append(item[4][0])
    except socket.gaierror:
        return []
    return found


def model_transport(url: str, key: str, model: str) -> tuple[int, bytes]:
    import json

    payload = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": "Reply with the word ready."}],
            "max_tokens": 16,
        }
    ).encode()
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, response.read(1024 * 1024)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(4096)


def embed_transport() -> tuple[int, bytes]:
    import json

    payload = json.dumps({"model": "nomic-embed-text", "input": "ready"}).encode()
    request = urllib.request.Request(
        "http://127.0.0.1:11434/api/embed",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, response.read(2_000_000)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(4096)


def _persist_machine_id(machine_id: str) -> None:
    path = Path("/etc/machine-id")
    if path.is_symlink():
        return
    current = path.read_text().strip() if path.is_file() else ""
    if machine_id and current != machine_id:
        path.write_text(machine_id + "\n")


def _join_wifi(ssid: str, password: str) -> None:
    join_wifi(ssid, password, sysfs=Path("/sys/class/net"), iwd_dir=DATA / "iwd", run=_run)


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def _etc_machine_id() -> str:
    path = Path("/etc/machine-id")
    if not path.is_file() or path.is_symlink():
        return ""
    try:
        return path.read_text()
    except OSError:
        return ""


def _write(text: str) -> None:
    data = text.encode()
    os.write(1, data)
    try:
        fd = os.open("/dev/ttyS0", os.O_WRONLY | os.O_NOCTTY)
    except OSError:
        return
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


def _lines():
    buffer = ""
    while True:
        ready, _, _ = select.select([0], [], [], 3600)
        if not ready:
            continue
        chunk = os.read(0, 4096)
        if not chunk:
            if buffer:
                yield buffer
            return
        buffer += chunk.decode(errors="replace").replace("\r", "")
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            yield line


if __name__ == "__main__":
    run()
