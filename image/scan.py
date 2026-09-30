"""Scan an extracted installer tree before it is published.

The scan looks at the filesystem that will be on the stick. It does not
look at a container registry. A finding means the image is not released.
"""

from __future__ import annotations

import re
import stat
import sys
from pathlib import Path

# Four letters AKIA also name a hardware vendor in udev's hwdb.
ACCESS_KEY = re.compile(br"AKIA[0-9A-Z]{16}")
CONTENT = (
    b"aws_secret_access_key",
    b"BEGIN OPENSSH PRIVATE KEY",
    b"BEGIN RSA PRIVATE KEY",
    b"BEGIN PRIVATE KEY",
    b"BEGIN PGP PRIVATE KEY",
    b"POSTGRES_PASSWORD=",
    b"asikmydeen.com",
)
SECRET_NAMES = {
    "board_password",
    "provision.token",
    "wifi_psk",
    "model_api_key",
    "id_rsa",
    "id_ed25519",
    "id_ecdsa",
    "authorized_keys",
}
MAX_TEXT = 2_000_000
# Container layers and model bytes are not the installer's own config.
# A private-key filename in either place is still a finding.
SKIP_CONTENT = (
    ("var", "lib", "docker"),
    ("usr", "lib", "friday", "ollama-models"),
)


def scan(root: Path, *, expect_role: str = "installer") -> list[str]:
    findings: list[str] = []
    root = Path(root)
    machine = root / "etc/machine-id"
    if machine.is_file() and not machine.is_symlink() and machine.read_text().strip():
        findings.append("machine-id")
    dbus = root / "var/lib/dbus/machine-id"
    if dbus.is_file() and not dbus.is_symlink() and dbus.read_text().strip():
        findings.append("machine-id")
    role = root / "etc/friday-role"
    if not role.is_file() or role.read_text().strip() != expect_role:
        findings.append("role")
    arch = root / "etc/friday-arch"
    if arch.is_file() and arch.read_text().strip() != "amd64":
        findings.append("arch")
    shadow = root / "etc/shadow"
    if shadow.is_file():
        if not root_locked(shadow.read_text()):
            findings.append("root-password")
    else:
        findings.append("root-password")
    status = root / "var/lib/dpkg/status"
    if status.is_file() and openssh_server_installed(status.read_text()):
        findings.append("openssh-server")
    secrets = root / "var/lib/friday/secrets"
    if secrets.exists():
        for path in secrets.rglob("*"):
            if path.is_symlink():
                continue
            if path.is_file():
                findings.append("baked-secret")
                break
    for path in walk_files(root):
        name = path.name
        relative = path.relative_to(root).parts
        if name.startswith("ssh_host_") or name in SECRET_NAMES or name == ".env":
            findings.append("secret-file")
        if relative[:2] == ("root", ".ssh") or ".aws" in relative:
            findings.append("secret-file")
        try:
            info = path.lstat()
        except OSError:
            continue
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_TEXT:
            continue
        if any(relative[: len(prefix)] == prefix for prefix in SKIP_CONTENT):
            continue
        blob = path.read_bytes()
        if has_secret_text(blob):
            findings.append("secret-content")
    return sorted(set(findings))


def has_secret_text(blob: bytes) -> bool:
    """True when text contains a secret pattern. A NUL in the first 4 KiB is binary."""
    if b"\0" in blob[:4096]:
        return False
    return bool(ACCESS_KEY.search(blob) or any(pattern in blob for pattern in CONTENT))


def walk_files(root: Path):
    for path in root.rglob("*"):
        if path.is_symlink():
            continue
        if path.is_file():
            yield path


def root_locked(shadow: str) -> bool:
    for line in shadow.splitlines():
        if not line.startswith("root:"):
            continue
        field = line.split(":", 2)[1]
        return field in {"!", "*", "!!"} or field.startswith("!")
    return False


def openssh_server_installed(status: str) -> bool:
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in status.splitlines():
        if not line.strip():
            if current:
                blocks.append(current)
                current = []
            continue
        current.append(line)
    if current:
        blocks.append(current)
    for block in blocks:
        fields = {}
        for line in block:
            if ": " in line:
                key, value = line.split(": ", 1)
                fields[key] = value
        if fields.get("Package") == "openssh-server" and fields.get("Status") == "install ok installed":
            return True
    return False


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: scan.py ROOT", file=sys.stderr)
        return 2
    findings = scan(Path(argv[1]))
    if findings:
        for item in findings:
            print(item, file=sys.stderr)
        return 1
    print("scan-ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
