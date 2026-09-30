"""Read a catalog snapshot that stays out of git.

The copy keeps ix-dev/stable and ix-dev/community. enterprise, dev, and
test are not copied. A secret filename is not copied. A file whose text
matches the image scan is not copied either. The pin written for the
image is a separate file. catalog/PIN in git stays empty, and discover()
on that file still lists nothing.
"""

from __future__ import annotations

import shutil
import stat
from pathlib import Path

from image.scan import MAX_TEXT, has_secret_text

TRAINS = ("stable", "community")
SECRET_NAMES = {
    ".env",
    "board_password",
    "provision.token",
    "wifi_psk",
    "model_api_key",
    "id_rsa",
    "id_ed25519",
    "id_ecdsa",
    "authorized_keys",
}


def pin_text(commit: str) -> str:
    text = commit.strip().lower()
    if len(text) != 40 or any(char not in "0123456789abcdef" for char in text):
        raise ValueError("commit")
    return f"commit: {text}\ntrains: [stable, community]\npinned_at: image-build\n"


def list_apps(root: Path) -> tuple[dict[str, str], ...]:
    base = Path(root) / "ix-dev"
    rows: list[dict[str, str]] = []
    for train in TRAINS:
        train_dir = base / train
        if not train_dir.is_dir():
            continue
        for app in sorted(train_dir.iterdir()):
            if app.is_dir() and (app / "app.yaml").is_file():
                rows.append({"name": app.name, "train": train})
    return tuple(rows)


def copy_trains(src: Path, dest: Path) -> int:
    """Copy the two trains. Returns how many apps were copied."""
    count = 0
    destination = Path(dest)
    for train in TRAINS:
        source = Path(src) / "ix-dev" / train
        if not source.is_dir():
            continue
        for app in sorted(source.iterdir()):
            if not app.is_dir() or not (app / "app.yaml").is_file():
                continue
            target = destination / "ix-dev" / train / app.name
            _copy_tree(app, target)
            if (target / "app.yaml").is_file():
                count += 1
    return count


def _secret_name(name: str) -> bool:
    return (
        name in SECRET_NAMES
        or name.startswith(".")
        or name.startswith("id_")
        or name.startswith("ssh_host_")
    )


def _secret_content(path: Path) -> bool:
    """True when the image scan would reject this file's text."""
    try:
        info = path.stat()
    except OSError:
        return True
    if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_TEXT:
        return False
    return has_secret_text(path.read_bytes())


def drop_secret_content(root: Path) -> int:
    """Remove files already on disk that the image scan would reject."""
    base = Path(root)
    if not base.exists():
        return 0
    removed = 0
    for path in sorted(base.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        if _secret_content(path):
            path.unlink()
            removed += 1
    return removed


def _copy_tree(src: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for path in sorted(src.rglob("*")):
        relative = path.relative_to(src)
        if any(_secret_name(part) for part in relative.parts):
            continue
        if path.is_symlink():
            continue
        target = dest / relative
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        if path.is_file():
            if _secret_content(path):
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
