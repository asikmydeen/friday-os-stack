"""Disk choice and partition commands for the test installer.

The stick is never an accepted target. A name has to be the kernel
name from the list, such as sda, not a /dev path. The disk has to be
at least 64 GB and still have 16 GiB left after the EFI partition and
the two system slots. Nothing is erased unless a later step runs the
commands this module only describes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from image import VERSION

MiB = 1024 * 1024
GiB = 1024 * 1024 * 1024
EFI_BYTES = 512 * MiB
SLOT_BYTES = 16 * GiB
DATA_MIN = 16 * GiB
MIN_DISK = 64 * 1000**3
# Parted's MiB is 1024*1024. The next partition starts where the previous ends.
EFI_END_MIB = 1 + 512
SLOT_MIB = 16 * 1024
A_END_MIB = EFI_END_MIB + SLOT_MIB
B_END_MIB = A_END_MIB + SLOT_MIB

# FAT labels are 11 characters and cannot carry the hyphenated name the
# ext4 labels use. The EFI filesystem is mounted by its GPT partition name.
FAT_LABEL = "FRIDAYEFI"

CORE_IMAGES = (
    "friday",
    "board",
    "memory-mcp",
    "qdrant",
    "postgres",
    "ollama",
    "nomic-embed-text",
    "executor",
    "webhooks",
    "gateway",
)


@dataclass(frozen=True)
class Disk:
    name: str
    size_bytes: int
    installer: bool = False


@dataclass(frozen=True)
class Decision:
    ok: bool
    reason: str
    name: str = ""
    size_bytes: int = 0


def data_bytes(size_bytes: int) -> int:
    """Bytes left for the data partition, keeping 1 MiB for the backup GPT."""
    used = MiB + EFI_BYTES + SLOT_BYTES + SLOT_BYTES
    return size_bytes - used - MiB


def fits(size_bytes: int) -> bool:
    return size_bytes >= MIN_DISK and data_bytes(size_bytes) >= DATA_MIN


def parent_disk(name: str) -> str:
    matched = re.fullmatch(r"(nvme\d+n\d+)p\d+", name)
    if matched:
        return matched.group(1)
    matched = re.fullmatch(r"(mmcblk\d+)p\d+", name)
    if matched:
        return matched.group(1)
    matched = re.fullmatch(r"([a-z]+)(\d+)", name)
    if matched:
        return matched.group(1)
    return name


def valid_kernel_name(name: str) -> bool:
    if not re.fullmatch(r"[a-z][a-z0-9]*", name):
        return False
    if parent_disk(name) != name:
        return False
    if name.startswith(("loop", "ram", "fd", "sr", "nbd", "dm", "zram")):
        return False
    return True


def format_size(size_bytes: int) -> str:
    return f"{size_bytes / 1000**3:.1f} GB"


def choose(disks: list[Disk], typed: str, *, installer_known: bool) -> Decision:
    # Without a positive identification of the stick, refuse every disk.
    if not installer_known:
        return Decision(False, "installer_unknown")
    name = typed.strip()
    if not valid_kernel_name(name):
        return Decision(False, "not_kernel_name")
    match = next((disk for disk in disks if disk.name == name), None)
    if match is None:
        return Decision(False, "unknown_disk")
    if match.installer:
        return Decision(False, "installer_disk")
    if not fits(match.size_bytes):
        return Decision(False, "too_small")
    return Decision(True, "ok", match.name, match.size_bytes)


def partition_node(disk: str, index: int) -> str:
    if not valid_kernel_name(disk):
        raise ValueError(disk)
    if re.fullmatch(r"nvme\d+n\d+|mmcblk\d+", disk):
        return f"/dev/{disk}p{index}"
    return f"/dev/{disk}{index}"


def commands(disk: str) -> list[list[str]]:
    """Parted and mkfs commands. The caller runs them only after a second confirmation."""
    if not valid_kernel_name(disk):
        raise ValueError(disk)
    device = f"/dev/{disk}"
    efi = partition_node(disk, 1)
    slot_a = partition_node(disk, 2)
    slot_b = partition_node(disk, 3)
    data = partition_node(disk, 4)
    return [
        ["wipefs", "-a", device],
        ["parted", "-s", device, "mklabel", "gpt"],
        ["parted", "-s", device, "mkpart", "friday-efi", "fat32", "1MiB", f"{EFI_END_MIB}MiB"],
        ["parted", "-s", device, "set", "1", "esp", "on"],
        ["parted", "-s", device, "mkpart", "friday-a", "ext4", f"{EFI_END_MIB}MiB", f"{A_END_MIB}MiB"],
        ["parted", "-s", device, "mkpart", "friday-b", "ext4", f"{A_END_MIB}MiB", f"{B_END_MIB}MiB"],
        ["parted", "-s", device, "mkpart", "friday-data", "ext4", f"{B_END_MIB}MiB", "100%"],
        ["partprobe", device],
        ["sleep", "1"],
        ["mkfs.vfat", "-F", "32", "-n", FAT_LABEL, efi],
        ["mkfs.ext4", "-F", "-L", "friday-a", slot_a],
        ["mkfs.ext4", "-F", "-L", "friday-b", slot_b],
        ["mkfs.ext4", "-F", "-L", "friday-data", data],
        ["mkdir", "-p", "/mnt/friday-a", "/mnt/friday-efi", "/mnt/friday-data"],
        ["mount", slot_a, "/mnt/friday-a"],
        ["mkdir", "-p", "/mnt/friday-a/boot/efi"],
        ["mount", efi, "/mnt/friday-a/boot/efi"],
        ["mount", data, "/mnt/friday-data"],
        [
            "rsync",
            "-aH",
            "--numeric-ids",
            "--exclude=/proc",
            "--exclude=/sys",
            "--exclude=/dev",
            "--exclude=/run",
            "--exclude=/tmp",
            "--exclude=/mnt",
            "--exclude=/media",
            "--exclude=/boot/efi",
            "--exclude=/var/lib/friday",
            "/",
            "/mnt/friday-a/",
        ],
    ]


def parse_parted(text: str) -> list[dict]:
    """Rows from `parted -m unit B print`. End positions in that output are inclusive."""
    rows = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or not line[0].isdigit():
            continue
        if line.endswith(";"):
            line = line[:-1]
        parts = line.split(":")
        if len(parts) < 6:
            continue
        start = _bytes(parts[1])
        end = _bytes(parts[2])
        size = _bytes(parts[3])
        if size != end - start + 1:
            raise ValueError("parted size does not match the byte range")
        rows.append(
            {
                "number": int(parts[0]),
                "start": start,
                "end": end,
                "size": size,
                "fs": parts[4],
                "name": parts[5],
                "flags": parts[6] if len(parts) > 6 else "",
            }
        )
    return rows


def _bytes(token: str) -> int:
    return int(token.rstrip("B"))


def grub_stub() -> str:
    return (
        "search --file /EFI/BOOT/grub.cfg --set=root\n"
        "set prefix=($root)/EFI/BOOT\n"
        "configfile ($root)/EFI/BOOT/grub.cfg\n"
    )


def grub_installer() -> str:
    return (
        "serial --unit=0 --speed=115200 --word=8 --parity=no --stop=1\n"
        "terminal_input serial console\n"
        "terminal_output serial console\n"
        f"echo Friday {VERSION} test installer\n"
        "set timeout=3\n"
        "set default=0\n"
        f'menuentry "Friday {VERSION} test installer" {{\n'
        "  search --no-floppy --label friday-installer --set=root\n"
        "  linux /boot/vmlinuz root=LABEL=friday-installer rw console=ttyS0,115200 console=tty0\n"
        "  initrd /boot/initrd.img\n"
        "}\n"
    )


def grub_installed() -> str:
    return (
        "serial --unit=0 --speed=115200 --word=8 --parity=no --stop=1\n"
        "terminal_input serial console\n"
        "terminal_output serial console\n"
        f"echo Friday {VERSION} installed system\n"
        "set timeout=3\n"
        "set default=0\n"
        f'menuentry "Friday {VERSION}" {{\n'
        "  search --no-floppy --label friday-a --set=root\n"
        "  linux /boot/vmlinuz root=LABEL=friday-a rw console=ttyS0,115200 console=tty0\n"
        "  initrd /boot/initrd.img\n"
        "}\n"
    )


FSTAB_INSTALLER = (
    "LABEL=friday-installer / ext4 defaults 0 1\n"
    "PARTLABEL=friday-efi /boot/efi vfat umask=0077,fmask=0177 0 2\n"
)

FSTAB_INSTALLED = (
    "LABEL=friday-a / ext4 defaults 0 1\n"
    "PARTLABEL=friday-efi /boot/efi vfat umask=0077,fmask=0177 0 2\n"
    "LABEL=friday-data /var/lib/friday ext4 defaults 0 2\n"
)

SLOT_FILE = "current=A\ncommitted=yes\nattempts=3\n"

REASONS = {
    "not_kernel_name": "Type the kernel name from the list, such as sda. Do not type /dev.",
    "unknown_disk": "That name is not in the disk list.",
    "installer_disk": "That disk is this installer. It is not the internal disk.",
    "too_small": (
        "That disk cannot hold a 512 MB EFI partition, two 16 GB system slots, "
        "and a data partition of at least 16 GB. The disk also has to be at least 64 GB."
    ),
    "installer_unknown": "This installer cannot see the stick it booted from, so it will not erase a disk.",
}
