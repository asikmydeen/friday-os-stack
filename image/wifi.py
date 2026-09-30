"""Join a saved Wi-Fi network when a wireless device is present.

The passphrase file is mode 0600. The password is not part of the error
text. No device raises wifi_no_device and does not start iwd.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def wireless_names(sysfs: Path) -> list[str]:
    names = []
    if not sysfs.is_dir():
        return names
    for entry in sorted(sysfs.iterdir()):
        if (entry / "wireless").exists() or (entry / "phy80211").exists():
            names.append(entry.name)
    return names


def join_wifi(ssid: str, password: str, *, sysfs: Path, iwd_dir: Path, run) -> None:
    if not ssid or not password or "/" in ssid or "\\" in ssid or "\x00" in ssid or ssid in {".", ".."}:
        raise OSError("wifi_missing")
    if not wireless_names(sysfs):
        raise OSError("wifi_no_device")
    iwd_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(iwd_dir, 0o700)
    path = iwd_dir / f"{ssid}.psk"
    _write(path, "[Security]\nPassphrase=" + password + "\n", 0o600)
    try:
        run(["systemctl", "start", "iwd"])
        run(["iwctl", "station", wireless_names(sysfs)[0], "connect", ssid])
    except (OSError, subprocess.SubprocessError):
        raise OSError("wifi_join_failed") from None


def _write(path: Path, value: str, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(temporary, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, mode)
    try:
        os.write(fd, value.encode())
    finally:
        os.close(fd)
    os.chmod(temporary, mode)
    os.replace(temporary, path)
    os.chmod(path, mode)
