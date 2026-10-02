"""Start the core that shipped in the image. Nothing is downloaded.

The embed check runs after the listeners answer. A reply that is
nomic-embed-text at 768 numbers is recorded on the setup screen. A
check that returns nothing is not recorded. A wrong model or a short
vector is not recorded as passed. The collection step writes one smoke
point, searches that id, and deletes only that id. Notes: empty is
recorded only when that step says every count is zero.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from image.mesh import (
    choose_create,
    choose_join,
    images_for,
    preauth_argv,
    render_headscale_config,
    serve_argv,
    take_key,
    user_create_argv,
    user_id,
    user_list_argv,
)

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
    "friday-os-stack/door:0.1.0-amd64",
    "friday-os-stack/mcp:0.1.0-amd64",
    "friday-os-stack/browser:0.1.0-amd64",
)
CODES = (
    "embed_not_ready",
    "embed_model",
    "embed_dimensions",
    "embed_weights_missing",
    "core_images_missing",
    "secrets",
    "unreachable",
    "rejected",
    "collections",
    "listeners",
    "reach_started",
    "start_failed",
    "smoke_point",
    "smoke_left",
    "mesh_images_missing",
    "mesh_not_up",
    "mesh_url",
    "mesh_port",
    "mesh_key_missing",
)


def start_core(store, run=None, root: Path | None = None, embed_check=None, pause=None) -> None:
    """Load bundled images if needed, then start them. Raises OSError with a short code."""
    runner = run or _run
    try:
        _start(
            store,
            runner,
            Path("/") if root is None else Path(root),
            embed_check,
            pause or time.sleep,
        )
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


def _start(store, run, root: Path, embed_check, pause) -> None:
    _require_secrets(store)
    mode = _mesh_mode(store)
    if mode == "join":
        _reject_mesh(choose_join(getattr(store, "mesh_url", ""), getattr(store, "mesh_auth_key", "")))
    elif mode == "create":
        _reject_mesh(choose_create(getattr(store, "mesh_url", "")))
        _write_headscale_config(store)
    env_path = Path(store.root) / "core.env"
    _write_env(store, env_path)
    _seed_weights(store, root)
    _dirs(store)
    run(["systemctl", "start", "docker"])
    _ensure_images(run, root, IMAGES, "core_images_missing")
    if mode in {"join", "create"}:
        _ensure_images(run, root, images_for(mode), "mesh_images_missing")
    if mode == "create":
        _compose(run, root, env_path, (), (), ("mesh-server",))
        if not _mesh_keys_ready(store):
            _mint_mesh(store, run, pause)
        _write_env(store, env_path)
        _compose(run, root, env_path, (), (), ("mesh",))
        _serve_board(run, pause)
    elif mode == "join":
        _compose(run, root, env_path, (), (), ("mesh",))
        _serve_board(run, pause)
    else:
        _compose(run, root, env_path, extra=(), services=())
    _reach_stays_off(run)
    _wait_listeners(run)
    notes = _collections(run, root, env_path)
    check = embed_check if embed_check is not None else _wait_embed
    try:
        body = check()
    except OSError:
        store._mark_embed(False)
        raise
    _keep_embed(store, body)
    if notes:
        store.mark_notes(notes)
    _log(store, "started")


def _compose(
    run,
    root: Path,
    env_path: Path,
    extra: tuple[Path, ...],
    services: tuple[str, ...],
    profiles: tuple[str, ...] = (),
) -> None:
    compose = root / "usr/lib/friday/compose.yml"
    argv = ["docker", "compose", "-p", PROJECT, "-f", str(compose)]
    for path in extra:
        argv.extend(["-f", str(path)])
    for profile in profiles:
        argv.extend(["--profile", profile])
    argv.extend(["--env-file", str(env_path), "up", "-d", "--pull", "never"])
    argv.extend(services)
    run(argv)


def _reach_stays_off(run) -> None:
    """Profile reach is packed and is not started with the core."""
    text = run(["docker", "ps", "-a", "--format", "{{.Names}}"]) or ""
    running = {line.strip() for line in str(text).splitlines()}
    if {"friday-door-1", "friday-mcp-1", "friday-browser-1", "friday-outbound-1"} & running:
        raise OSError("reach_started")


def _mesh_mode(store) -> str:
    mode = getattr(store, "mesh_mode", "") or ""
    if mode in {"join", "create"}:
        return mode
    return ""


def _reject_mesh(choice) -> None:
    if choice.reason:
        raise OSError(choice.reason)


def _ensure_images(run, root: Path, names: tuple[str, ...], code: str) -> None:
    if all(_has_image(run, image) for image in names):
        return
    tar = root / "usr/lib/friday/images/core-images.tar"
    if not tar.is_file() or tar.stat().st_size == 0:
        raise OSError(code)
    run(["docker", "load", "-i", str(tar)])
    if not all(_has_image(run, image) for image in names):
        raise OSError(code)


def _write_headscale_config(store) -> None:
    port = int(getattr(store, "mesh_port", "") or "0")
    text = render_headscale_config(store.mesh_url, port)
    path = Path(store.root) / "headscale" / "config" / "config.yaml"
    _write(path, text, 0o644)
    lib = Path(store.root) / "headscale" / "lib"
    lib.mkdir(parents=True, exist_ok=True)
    os.chmod(lib, 0o750)
    try:
        os.chown(lib, 65532, 65532)
    except PermissionError:
        pass
    state = Path(store.root) / "tailscale"
    state.mkdir(parents=True, exist_ok=True)


def _mesh_keys_ready(store) -> bool:
    return bool(
        getattr(store, "mesh_auth_key", "")
        and getattr(store, "mesh_phone_key", "")
        and getattr(store, "mesh_laptop_key", "")
    )


def _mint_mesh(store, run, pause, attempts: int = 8) -> None:
    """Ask the Headscale on this computer for one user and three one-time keys."""
    if attempts < 1:
        raise OSError("mesh_not_up")
    for attempt in range(attempts):
        uid = ""
        try:
            uid = user_id(run(user_create_argv()) or "")
        except OSError:
            uid = ""
        if not uid:
            try:
                uid = user_id(run(user_list_argv()) or "")
            except OSError:
                uid = ""
        box = phone = laptop = ""
        if uid:
            try:
                box = take_key(run(preauth_argv(uid)) or "")
                phone = take_key(run(preauth_argv(uid)) or "")
                laptop = take_key(run(preauth_argv(uid)) or "")
            except OSError:
                box = phone = laptop = ""
        if box and phone and laptop:
            store.save_mesh_keys(box, phone, laptop)
            if _mesh_keys_ready(store):
                return
        if attempt + 1 == attempts:
            raise OSError("mesh_not_up")
        pause(2)


def _serve_board(run, pause, attempts: int = 8) -> None:
    """Publish the local Board onto the tailnet. Postgres stays off that path."""
    if attempts < 1:
        raise OSError("mesh_not_up")
    argv = serve_argv()
    for attempt in range(attempts):
        try:
            run(argv)
            return
        except OSError:
            if attempt + 1 == attempts:
                raise OSError("mesh_not_up")
            pause(2)


def _env_mode(store) -> str:
    mode = getattr(store, "mesh_mode", "") or ""
    if mode in {"local", "join", "create"}:
        return mode
    return "local"


def _env_key(store) -> str:
    if _env_mode(store) not in {"join", "create"}:
        return ""
    return getattr(store, "mesh_auth_key", "") or ""


def _env_extra(store) -> str:
    url = getattr(store, "mesh_url", "") or ""
    key = _env_key(store)
    if _env_mode(store) not in {"join", "create"} or not url or not key:
        return ""
    return f"--login-server={url} --accept-dns=false --hostname=friday"


def _wait_listeners(run, attempts: int = 30, pause=time.sleep) -> None:
    """Executor and gateway must answer on the core network before the start counts."""
    probe = [
        "docker",
        "run",
        "--rm",
        "--network",
        f"{PROJECT}_core",
        "--entrypoint",
        "python",
        "friday-os-stack/executor:0.1.0-amd64",
        "-c",
        (
            "import urllib.request\n"
            "urllib.request.urlopen('http://executor:8080/health', timeout=3).read()\n"
            "urllib.request.urlopen('http://gateway:8090/health', timeout=3).read()\n"
        ),
    ]
    if attempts < 1:
        raise OSError("listeners")
    for attempt in range(attempts):
        try:
            run(probe)
        except (OSError, subprocess.CalledProcessError):
            if attempt + 1 == attempts:
                raise OSError("listeners")
            pause(2)
        else:
            return


def _collections(run, root: Path, env_path: Path) -> str:
    script = root / "usr/lib/friday/qdrant_bootstrap.py"
    image = "friday-os-stack/memory-mcp:0.1.0-amd64"
    try:
        text = run(
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
                "-e",
                "OLLAMA_URL=http://ollama:11434",
                "-v",
                f"{script}:/bootstrap.py:ro",
                image,
                "python",
                "/bootstrap.py",
            ]
        )
    except OSError as exc:
        raise _bootstrap_failure(exc) from None
    return _note_mark(text or "")


def _note_mark(text: str) -> str:
    found = ""
    for line in str(text).splitlines():
        stripped = line.strip()
        if stripped == "notes empty":
            found = "empty"
        elif stripped == "notes kept":
            found = "kept"
    return found


def _bootstrap_failure(exc: OSError) -> OSError:
    text = str(exc).strip()
    last = text.splitlines()[-1].strip() if text else ""
    if last in CODES:
        return OSError(last)
    return OSError(text or "start_failed")


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
        "soul_apply_token",
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
        "SOUL_APPLY_TOKEN": store.soul_apply_token,
        "MESH_MODE": _env_mode(store),
        "MESH_PORT": getattr(store, "mesh_port", "") or "8443",
        "MESH_URL": getattr(store, "mesh_url", "") or "",
        "MESH_AUTHKEY": _env_key(store),
        "MESH_EXTRA_ARGS": _env_extra(store),
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


def _keep_embed(store, body) -> None:
    """Record the pin only for a reply this start actually returned."""
    store._mark_embed(False)
    if body is None:
        return
    if not isinstance(body, (bytes, bytearray)):
        raise OSError("embed_not_ready")
    from image.setup import pinned_embed

    reason = pinned_embed(bytes(body))
    if reason != "ok":
        raise OSError(reason)
    store._mark_embed(True)


def _wait_embed() -> bytes:
    from image.setup import pinned_embed, pinned_model

    body = json.dumps({"model": "nomic-embed-text", "input": "ready"}).encode()
    deadline = time.time() + 600
    while time.time() < deadline:
        request = Request(
            "http://127.0.0.1:11434/api/embed",
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
        if pinned_embed(raw) == "ok":
            return raw
        reported = _reported_model(raw)
        if reported and not pinned_model(reported):
            raise OSError("embed_model")
        time.sleep(3)
    raise OSError("embed_not_ready")


def _reported_model(raw: bytes) -> str:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return ""
    if not isinstance(payload, dict):
        return ""
    model = payload.get("model")
    if not isinstance(model, str):
        return ""
    return model.strip()


def _run(argv: list[str]) -> str:
    proc = subprocess.run(argv, check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise OSError(detail[-400:] or f"exit {proc.returncode}")
    return proc.stdout or ""


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
        "soul_apply_token",
        "mesh_auth_key",
        "mesh_phone_key",
        "mesh_laptop_key",
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
