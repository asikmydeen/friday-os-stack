"""Write the installed slot. Commands run only after the owner confirms a disk."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from pathlib import Path

from image.disks import (
    FSTAB_INSTALLED,
    SLOT_FILE,
    commands,
    grub_installed,
    valid_kernel_name,
)


def apply(disk: str, run: Callable[[list[str]], None]) -> list[list[str]]:
    if not valid_kernel_name(disk):
        raise ValueError(disk)
    planned = commands(disk)
    for cmd in planned:
        try:
            run(cmd)
        except Exception:
            if cmd[0] != "partprobe":
                raise
    return planned


def write_installed(root: Path, efi: Path, data: Path, boot_efi: Path) -> None:
    """Turn a copied installer tree into slot A. Secrets are not created here."""
    for name in ("dev", "proc", "sys", "run", "tmp", "boot/efi", "boot/grub", "var/lib/friday"):
        (root / name).mkdir(parents=True, exist_ok=True)
    os.chmod(root / "tmp", 0o1777)
    (root / "etc").mkdir(parents=True, exist_ok=True)
    (root / "etc/fstab").write_text(FSTAB_INSTALLED)
    (root / "etc/friday-role").write_text("installed\n")
    machine_id = root / "etc/machine-id"
    if machine_id.is_symlink():
        machine_id.unlink()
    machine_id.write_text("")
    dbus_id = root / "var/lib/dbus/machine-id"
    if dbus_id.is_symlink() or dbus_id.exists():
        dbus_id.unlink()
    ssh = root / "etc/ssh"
    if ssh.is_dir():
        for key in ssh.glob("ssh_host_*"):
            if key.is_file() or key.is_symlink():
                key.unlink()
    (root / "boot/grub/grub.cfg").write_text(grub_installed())
    destination = efi / "EFI/BOOT"
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(boot_efi, destination / "BOOTX64.EFI")
    (destination / "grub.cfg").write_text(grub_installed())
    (efi / "friday-slot.txt").write_text(SLOT_FILE)
    notes = data / "notes"
    secrets = data / "secrets"
    notes.mkdir(parents=True, exist_ok=True)
    secrets.mkdir(parents=True, exist_ok=True)
    os.chmod(secrets, 0o700)
