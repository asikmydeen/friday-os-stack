"""Start the core that shipped in the image. Nothing is downloaded."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PROJECT = "friday"
IMAGES = (
    "friday-os-stack/friday:0.1.0-amd64",
    "friday-os-stack/board:0.1.0-amd64",
    "friday-os-stack/memory-mcp:0.1.0-amd64",
    "friday-os-stack/executor:0.1.0-amd64",
    "friday-os-stack/postgres:16-amd64",
    "friday-os-stack/qdrant:pinned-amd64",
    "friday-os-stack/ollama:pinned-amd64",
    "friday-os-stack/webhooks:0.1.0-amd64",
    "friday-os-stack/gateway:0.1.0-amd64",
)
CODES = (
    "embed_not_ready",
    "embed_weights_missing",
    "core_images_missing",
    "secrets",
    "unreachable",
    "rejected",
    "collections",
    "start_failed",
)


def start_core(store, run=None, root: Path | None = None, embed_check=None) -> None:
    """Load bundled images if needed, then start them. Raises OSError with a short code."""
    runner = run or _run
    try:
        _start(store, runner, Path("/") if root is None else Path(root), embed_check)
    except OSError as exc:
        text = _redact(store, str(exc))
        _log(store, text)
        for code in CODES:
            if code in text:
                raise OSError(code) from None
        raise OSError("start_failed") from None


def publish_board(store, run=None, root: Path | None = None) -> None:
    """Publish the Board on 127.0.0.1:8080 after setup has released that port."""
    runner = run or _run
    base = Path("/") if root is None else Path(root)
    env_path = Path(store.root) / "core.env"
    if not env_path.is_file():
        _write_env(store, env_path)
    _compose(
        runner,
        base,
        env_path,
        extra=(base / "usr/lib/friday/compose.board.yml",),
        services=("board",),
    )


def _start(store, run, root: Path, embed_check) -> None:
    _require_secrets(store)
    env_path = Path(store.root) / "core.env"
    _write_env(store, env_path)
    _seed_weights(store, root)
    _dirs(store)
    run(["systemctl", "start", "docker"])
    if not all(_has_image(run, image) for image in IMAGES):
        tar = root / "usr/lib/friday/images/core-images.tar"
        if not tar.is_file() or tar.stat().st_size == 0:
            raise OSError("core_images_missing")
        run(["docker", "load", "-i", str(tar)])
        if not all(_has_image(run, image) for image in IMAGES):
            raise OSError("core_images_missing")
    _compose(run, root, env_path, extra=(), services=())
    _collections(run, root, env_path)
    check = embed_check if embed_check is not None else _wait_embed
    check()
    _log(store, "started")


def _compose(run, root: Path, env_path: Path, extra: tuple[Path, ...], services: tuple[str, ...]) -> None:
    compose = root / "usr/lib/friday/compose.yml"
    argv = ["docker", "compose", "-p", PROJECT, "-f", str(compose)]
    for path in extra:
        argv.extend(["-f", str(path)])
    argv.extend(["--env-file", str(env_path), "up", "-d", "--pull", "never"])
    argv.extend(services)
    run(argv)


def _collections(run, root: Path, env_path: Path) -> None:
    script = root / "usr/lib/friday/qdrant_bootstrap.py"
    image = "friday-os-stack/memory-mcp:0.1.0-amd64"
    run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            f"{PROJECT}_core",
            "--env-file",
            str(env_path),
            "-e",
            "QDRANT_URL=http://qdrant:6333",
            "-v",
            f"{script}:/bootstrap.py:ro",
            image,
            "python",
            "/bootstrap.py",
        ]
    )


def _require_secrets(store) -> None:
    names = (
        "postgres_password",
        "qdrant_key",
        "memory_token",
        "notify_token",
        "approval_token",
        "board_password",
        "webhook_jellyfin",
        "webhook_radarr",
        "webhook_sonarr",
    )
    if any(not getattr(store, name, "") for name in names):
        raise OSError("secrets")


def _write_env(store, path: Path) -> None:
    fields = {
        "FRIDAY_DATA": str(store.root),
        "POSTGRES_PASSWORD": store.postgres_password,
        "POSTGRES_USER": "postgres",
        "POSTGRES_DB": "memories",
        "QDRANT_API_KEY": store.qdrant_key,
        "QDRANT_URL": "http://qdrant:6333",
        "MEMORY_TOKEN": store.memory_token,
        "FRIDAY_NOTIFY_TOKEN": store.notify_token,
        "BOARD_PASSWORD": store.board_password,
        "BOARD_APPROVAL_TOKEN": store.approval_token,
        "MODEL_API_KEY": store.model_key,
        "MODEL_BASE_URL": store.model_base,
        "MODEL_FAST": store.model_fast,
        "MODEL_THINK": store.model_think,
        "OLLAMA_URL": "http://ollama:11434",
        "WEBHOOK_SECRET_JELLYFIN": store.webhook_jellyfin,
        "WEBHOOK_SECRET_RADARR": store.webhook_radarr,
        "WEBHOOK_SECRET_SONARR": store.webhook_sonarr,
    }
    lines = [f"{key}={_quote(value)}" for key, value in fields.items()]
    _write(path, "\n".join(lines) + "\n", 0o600)


def _quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _seed_weights(store, root: Path) -> None:
    src = root / "usr/lib/friday/ollama-models"
    if not _has_nomic(src):
        raise OSError("embed_weights_missing")
    dest = Path(store.root) / "ollama"
    if _has_nomic(dest):
        return
    dest.mkdir(parents=True, exist_ok=True)
    for child in src.iterdir():
        target = dest / child.name
        if child.is_dir():
            shutil.copytree(child, target, dirs_exist_ok=True)
        elif not target.exists():
            shutil.copy2(child, target)
    if not _has_nomic(dest):
        raise OSError("embed_weights_missing")


def _has_nomic(path: Path) -> bool:
    manifests = path / "models" / "manifests"
    if not manifests.is_dir():
        return False
    return any("nomic-embed-text" in part for item in manifests.rglob("*") for part in item.parts)


def _dirs(store) -> None:
    root = Path(store.root)
    for name in ("qdrant", "postgres", "ollama"):
        (root / name).mkdir(parents=True, exist_ok=True)
    for name in ("friday", "executor"):
        path = root / name
        path.mkdir(parents=True, exist_ok=True)
        try:
            os.chown(path, 65534, 65534)
        except PermissionError:
            pass


def _has_image(run, name: str) -> bool:
    try:
        run(["docker", "image", "inspect", name])
    except OSError:
        return False
    return True


def _wait_embed() -> None:
    body = json.dumps({"model": "nomic-embed-text", "prompt": "ready"}).encode()
    deadline = time.time() + 600
    while time.time() < deadline:
        request = Request(
            "http://127.0.0.1:11434/api/embeddings",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=30) as response:
                raw = response.read()
        except HTTPError:
            time.sleep(3)
            continue
        except URLError:
            time.sleep(3)
            continue
        except OSError:
            time.sleep(3)
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            time.sleep(3)
            continue
        vector = payload.get("embedding") if isinstance(payload, dict) else None
        if isinstance(vector, list) and len(vector) == 768:
            return
        time.sleep(3)
    raise OSError("embed_not_ready")


def _run(argv: list[str]) -> None:
    proc = subprocess.run(argv, check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise OSError(detail[-400:] or f"exit {proc.returncode}")


def _redact(store, text: str) -> str:
    for name in (
        "board_password",
        "notify_token",
        "memory_token",
        "qdrant_key",
        "postgres_password",
        "approval_token",
        "model_key",
        "wifi_password",
        "provision_token",
        "webhook_jellyfin",
        "webhook_radarr",
        "webhook_sonarr",
    ):
        secret = getattr(store, name, "") or ""
        if secret:
            text = text.replace(secret, "redacted")
    return text


def _log(store, text: str) -> None:
    path = Path(store.root) / "start.log"
    previous = path.read_text() if path.is_file() else ""
    _write(path, previous + text.strip() + "\n", 0o600)


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
