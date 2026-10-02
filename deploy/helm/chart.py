"""Write the core Helm chart. One fire, core services only.

The chart is for someone who already runs Kubernetes. It is not how a
phone reaches this appliance. Headscale, cloudflared, and the browser
session stay out. Coder is not a workload. Catalog apps stay out.

Every deployment is one replica with a recreate strategy, so the old
pod is gone before the new one mounts a volume. The Friday volume is
mounted only by friday. The claim uses ReadWriteOncePod when the
cluster supports it, and ReadWriteOnce otherwise. The embed worker
(ollama) and the index reconciler (memory-mcp) use that same singleton
rule. This module does not contact a cluster, does not start a pod,
and does not store a sentence.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote_plus

from image import VERSION
from memoryd.store import credential_shape

CORE = (
    "qdrant",
    "ollama",
    "postgres",
    "memory-mcp",
    "executor",
    "friday",
    "board",
    "webhooks",
    "gateway",
)
EXCLUDED = (
    "headscale",
    "cloudflared",
    "browser",
    "door",
    "mcp",
    "outbound",
    "coder",
    "taskrunner",
)
SINGLETONS = ("friday", "ollama", "memory-mcp")
CHART_FILES = (
    "Chart.yaml",
    "values.yaml",
    "README.md",
    "templates/workloads.yaml",
    "templates/pvc.yaml",
)
_SECRET = "friday-core"


@dataclass(frozen=True)
class Service:
    name: str
    image: str
    port: int
    role: str
    volume: str | None = None
    mount: str | None = None
    size: str | None = None
    env: tuple[tuple[str, str], ...] = ()
    secrets: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class Decision:
    outcome: str
    reason: str
    services: tuple[str, ...] = ()
    strategy: str = ""
    access_mode: str = ""
    applied: bool = False
    started: bool = False
    written: bool = False


@dataclass(frozen=True)
class Sample:
    phase: str
    pods: tuple[tuple[str, tuple[str, ...]], ...]
    mounting: tuple[str, ...]


_SERVICES = (
    Service(
        "qdrant",
        "qdrant/qdrant:latest",
        6333,
        "core",
        volume="qdrant",
        mount="/qdrant/storage",
        size="10Gi",
        secrets=(("QDRANT__SERVICE__API_KEY", "qdrant-api-key"),),
    ),
    Service(
        "ollama",
        "ollama/ollama:latest",
        11434,
        "embed-worker",
        volume="ollama",
        mount="/root/.ollama",
        size="20Gi",
    ),
    Service(
        "postgres",
        "postgres:16-alpine",
        5432,
        "core",
        volume="postgres",
        mount="/var/lib/postgresql/data",
        size="10Gi",
        env=(("POSTGRES_DB", "memories"), ("POSTGRES_USER", "postgres")),
        secrets=(("POSTGRES_PASSWORD", "postgres-password"),),
    ),
    Service(
        "memory-mcp",
        "friday-os-stack/memory-mcp:0.1.0",
        8080,
        "index-reconciler",
        env=(
            ("QDRANT_URL", "http://qdrant:6333"),
            ("OLLAMA_URL", "http://ollama:11434"),
            ("POSTGRES_HOST", "postgres"),
            ("POSTGRES_PORT", '"5432"'),
            ("POSTGRES_DB", "memories"),
            ("POSTGRES_USER", "postgres"),
            ("BIND_HOST", '"0.0.0.0"'),
            ("PORT", '"8080"'),
        ),
        secrets=(
            ("MEMORY_TOKEN", "memory-token"),
            ("QDRANT_API_KEY", "qdrant-api-key"),
            ("POSTGRES_PASSWORD", "postgres-password"),
        ),
    ),
    Service(
        "executor",
        "friday-os-stack/executor:0.1.0",
        8080,
        "core",
        volume="executor",
        mount="/data",
        size="1Gi",
        env=(
            ("STORE_PATH", "/data/gate.json"),
            ("BIND_HOST", '"0.0.0.0"'),
            ("PORT", '"8080"'),
            ("POSTGRES_HOST", "postgres"),
            ("POSTGRES_PORT", '"5432"'),
            ("POSTGRES_DB", "memories"),
            ("POSTGRES_USER", "postgres"),
        ),
        secrets=(
            ("BOARD_APPROVAL_TOKEN", "board-approval-token"),
            ("FRIDAY_NOTIFY_TOKEN", "friday-notify-token"),
            ("POSTGRES_PASSWORD", "postgres-password"),
        ),
    ),
    Service(
        "friday",
        "friday-os-stack/friday:0.1.0",
        8080,
        "friday",
        volume="friday",
        mount="/data",
        size="1Gi",
        env=(
            ("FRIDAY_STATE", "/data/friday.sqlite"),
            ("MEMORY_URL", "http://memory-mcp:8080"),
            ("EXECUTOR_URL", "http://executor:8080"),
            ("OLLAMA_URL", "http://ollama:11434"),
            ("WEBHOOK_URL", "http://webhooks:8080"),
            ("BIND_HOST", '"0.0.0.0"'),
            ("PORT", '"8080"'),
        ),
        secrets=(
            ("FRIDAY_NOTIFY_TOKEN", "friday-notify-token"),
            ("MEMORY_TOKEN", "memory-token"),
            ("MODEL_API_KEY", "model-api-key"),
        ),
    ),
    Service(
        "board",
        "friday-os-stack/board:0.1.0",
        8080,
        "core",
        env=(
            ("FRIDAY_URL", "http://friday:8080"),
            ("EXECUTOR_URL", "http://executor:8080"),
            ("BIND_HOST", '"0.0.0.0"'),
            ("PORT", '"8080"'),
        ),
        secrets=(
            ("BOARD_PASSWORD", "board-password"),
            ("FRIDAY_NOTIFY_TOKEN", "friday-notify-token"),
            ("BOARD_APPROVAL_TOKEN", "board-approval-token"),
            ("SOUL_APPLY_TOKEN", "soul-apply-token"),
        ),
    ),
    Service(
        "webhooks",
        "friday-os-stack/webhooks:0.1.0",
        8080,
        "core",
        env=(
            ("BIND_HOST", '"0.0.0.0"'),
            ("PORT", '"8080"'),
            ("POSTGRES_HOST", "postgres"),
            ("POSTGRES_PORT", '"5432"'),
            ("POSTGRES_DB", "memories"),
            ("POSTGRES_USER", "postgres"),
        ),
        secrets=(
            ("FRIDAY_NOTIFY_TOKEN", "friday-notify-token"),
            ("POSTGRES_PASSWORD", "postgres-password"),
            ("WEBHOOK_SECRET_JELLYFIN", "webhook-secret-jellyfin"),
            ("WEBHOOK_SECRET_RADARR", "webhook-secret-radarr"),
            ("WEBHOOK_SECRET_SONARR", "webhook-secret-sonarr"),
        ),
    ),
    Service(
        "gateway",
        "friday-os-stack/gateway:0.1.0",
        8090,
        "core",
        env=(("BIND_HOST", '"0.0.0.0"'), ("PORT", '"8090"')),
    ),
)


def access_mode(cluster_supports_rwop: bool) -> str:
    if cluster_supports_rwop is True:
        return "ReadWriteOncePod"
    return "ReadWriteOnce"


def fire(
    destination: object,
    *,
    actor: object,
    confirmed: bool = False,
    cluster_supports_rwop: bool = True,
    note: object = None,
) -> Decision:
    del confirmed
    if _secret(note):
        return _quiet("credential")
    if _chat(actor):
        return _quiet("chat_cannot_write")
    if actor != "board":
        return _quiet("actor_cannot_write")
    dest, reason = _directory(destination)
    if reason or dest is None:
        return _quiet(reason or "path")
    files = _files(cluster_supports_rwop)
    if _blocked(dest, files):
        return _quiet("path")
    _write(dest, files)
    return Decision(
        "written",
        "core",
        services=CORE,
        strategy="Recreate",
        access_mode=access_mode(cluster_supports_rwop),
        applied=False,
        started=False,
        written=True,
    )


def rollout(workloads: str, direction: str) -> tuple[Sample, ...]:
    """Recreate releases the volume before the next pod mounts it.

    Upgrade and rollback use the same order. A chart that is not one
    recreate replica, or that mounts the Friday volume from two
    deployments, is reported as both pods mounting it together.
    """
    if direction not in {"upgrade", "rollback"}:
        raise ValueError(direction)
    old, new = ("old", "new") if direction == "upgrade" else ("current", "previous")
    if not _singleton_chart(workloads):
        both = ("friday-old", "friday-new")
        pods = tuple((name, (f"{name}-old", f"{name}-new")) for name in SINGLETONS)
        return (Sample("overlap", pods, both),)

    def pods(tag: str) -> tuple[tuple[str, tuple[str, ...]], ...]:
        if tag == "":
            return tuple((name, ()) for name in SINGLETONS)
        return tuple((name, (f"{name}-{tag}",)) for name in SINGLETONS)

    mounting = () if old == "" else (f"friday-{old}",)
    return (
        Sample("running", pods(old), mounting),
        Sample("released", pods(""), ()),
        Sample("started", pods(new), (f"friday-{new}",)),
    )


def _singleton_chart(workloads: str) -> bool:
    if not isinstance(workloads, str):
        return False
    if workloads.count("claimName: friday") != 1:
        return False
    found = set()
    deployments = 0
    for doc in _documents(workloads):
        if _kind(doc) != "Deployment":
            continue
        deployments += 1
        name = _meta_name(doc)
        if "type: Recreate" not in doc or "replicas: 1" not in doc:
            return False
        if "RollingUpdate" in doc or "hostNetwork" in doc or "hostPort" in doc:
            return False
        if name in SINGLETONS:
            found.add(name)
        if name != "friday" and "claimName: friday" in doc:
            return False
    return deployments == len(CORE) and found == set(SINGLETONS)


def _documents(text: str) -> tuple[str, ...]:
    return tuple(chunk.strip() for chunk in text.split("---") if chunk.strip())


def _kind(doc: str) -> str:
    for line in doc.splitlines():
        if line.startswith("kind:"):
            return line.split(":", 1)[1].strip()
    return ""


def _meta_name(doc: str) -> str:
    in_meta = False
    for line in doc.splitlines():
        if line.startswith("metadata:"):
            in_meta = True
            continue
        if in_meta and line.startswith("  name:"):
            return line.split(":", 1)[1].strip()
        if in_meta and line and not line.startswith(" "):
            break
    return ""


def _files(cluster_supports_rwop: bool) -> dict[str, str]:
    flag = "true" if cluster_supports_rwop is True else "false"
    return {
        "Chart.yaml": _chart(),
        "values.yaml": _values(flag),
        "README.md": _readme(),
        "templates/workloads.yaml": _workloads(),
        "templates/pvc.yaml": _pvc(),
    }


def _chart() -> str:
    return (
        "apiVersion: v2\n"
        "name: friday-core\n"
        "description: Core services for an existing Kubernetes cluster. Not a phone path.\n"
        "type: application\n"
        f"version: {VERSION}\n"
        f'appVersion: "{VERSION}"\n'
    )


def _values(flag: str) -> str:
    lines = [
        f"clusterSupportsReadWriteOncePod: {flag}",
        "volumes:",
    ]
    for service in _SERVICES:
        if service.volume is None:
            continue
        lines.append(f"  - name: {service.volume}")
        lines.append(f"    size: {service.size}")
        lines.append(f"    mount: {service.name}")
    return "\n".join(lines) + "\n"


def _readme() -> str:
    return """# friday-core

Chart for the core services, for someone who already runs Kubernetes.
It is not how a phone reaches this appliance. Compose stays the contract.

Every deployment has one replica and a recreate strategy. The Friday
volume is mounted only by the friday deployment. The claim uses
ReadWriteOncePod when the cluster supports it, and ReadWriteOnce
otherwise. Recreate still removes the old pod before the new one mounts,
so two pods do not hold that volume together.

The ollama deployment is the embed worker. The memory-mcp deployment is
the index reconciler. Both use the same singleton rule.

Headscale, cloudflared, and the browser session are not in this chart.
Coder is a dependency this chart does not deploy. Catalog apps stay out.
The image tags are local names, not a published registry. The chart does
not create the secret friday-core and does not contain its values. One
fire writes these files. It does not contact a cluster and does not
start a pod.
"""


def _pvc() -> str:
    return """{{- range .Values.volumes }}
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: {{ .name }}
  labels:
    app.kubernetes.io/instance: friday-core
spec:
  accessModes:
{{- if $.Values.clusterSupportsReadWriteOncePod }}
    - ReadWriteOncePod
{{- else }}
    - ReadWriteOnce
{{- end }}
  resources:
    requests:
      storage: {{ .size }}
---
{{- end }}
"""


def _workloads() -> str:
    parts = []
    for service in _SERVICES:
        parts.append(_deployment(service))
        parts.append(_service(service))
    return "---\n".join(parts) + "\n"


def _deployment(service: Service) -> str:
    volume = ""
    if service.volume is not None:
        volume = (
            "          volumeMounts:\n"
            f"            - name: {service.volume}\n"
            f"              mountPath: {service.mount}\n"
            "      volumes:\n"
            f"        - name: {service.volume}\n"
            "          persistentVolumeClaim:\n"
            f"            claimName: {service.volume}\n"
        )
    return (
        "apiVersion: apps/v1\n"
        "kind: Deployment\n"
        "metadata:\n"
        f"  name: {service.name}\n"
        "  labels:\n"
        f"    app.kubernetes.io/name: {service.name}\n"
        "    app.kubernetes.io/instance: friday-core\n"
        f"    friday.os/role: {service.role}\n"
        "spec:\n"
        "  replicas: 1\n"
        "  strategy:\n"
        "    type: Recreate\n"
        "  selector:\n"
        "    matchLabels:\n"
        f"      app.kubernetes.io/name: {service.name}\n"
        "  template:\n"
        "    metadata:\n"
        "      labels:\n"
        f"        app.kubernetes.io/name: {service.name}\n"
        f"        friday.os/role: {service.role}\n"
        "    spec:\n"
        "      containers:\n"
        f"        - name: {service.name}\n"
        f"          image: {service.image}\n"
        "          imagePullPolicy: IfNotPresent\n"
        "          ports:\n"
        "            - name: http\n"
        f"              containerPort: {service.port}\n"
        f"{_env(service)}"
        f"{volume}"
    )


def _env(service: Service) -> str:
    lines: list[str] = []
    for key, value in service.env:
        lines.append(f"            - name: {key}")
        lines.append(f"              value: {value}")
    for key, secret in service.secrets:
        lines.append(f"            - name: {key}")
        lines.append("              valueFrom:")
        lines.append("                secretKeyRef:")
        lines.append(f"                  name: {_SECRET}")
        lines.append(f"                  key: {secret}")
    if not lines:
        return ""
    return "          env:\n" + "\n".join(lines) + "\n"


def _service(service: Service) -> str:
    return (
        "apiVersion: v1\n"
        "kind: Service\n"
        "metadata:\n"
        f"  name: {service.name}\n"
        "  labels:\n"
        "    app.kubernetes.io/instance: friday-core\n"
        "spec:\n"
        "  type: ClusterIP\n"
        "  selector:\n"
        f"    app.kubernetes.io/name: {service.name}\n"
        "  ports:\n"
        "    - name: http\n"
        f"      port: {service.port}\n"
        "      targetPort: http\n"
    )


def _directory(destination: object) -> tuple[Path | None, str]:
    if isinstance(destination, Path):
        raw = str(destination)
        path = destination
    elif isinstance(destination, str):
        raw = destination
        path = Path(destination)
    else:
        return None, "path"
    if raw == "" or raw != raw.strip() or "\n" in raw or "\r" in raw or "\x00" in raw:
        return None, "path"
    if not path.is_absolute() or path.is_symlink():
        return None, "path"
    parent = path.parent
    if not parent.is_dir() or parent.is_symlink():
        return None, "path"
    if path.exists() and not path.is_dir():
        return None, "path"
    return path, ""


def _blocked(dest: Path, files: dict[str, str]) -> bool:
    for relative in files:
        parts = Path(relative).parts
        if not parts or ".." in parts or Path(relative).is_absolute():
            return True
        probe = dest
        for part in parts[:-1]:
            probe = probe / part
            if probe.is_symlink():
                return True
        if (dest / relative).is_symlink():
            return True
    return False


def _write(dest: Path, files: dict[str, str]) -> None:
    dest.mkdir(exist_ok=True)
    stage = dest / ".chart-write"
    try:
        for relative, text in files.items():
            target = dest / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            stage.write_text(text, encoding="utf-8")
            stage.replace(target)
    finally:
        if stage.is_symlink() or stage.exists():
            stage.unlink()


def _quiet(reason: str) -> Decision:
    return Decision("refused", reason)


def _chat(actor: object) -> bool:
    return isinstance(actor, str) and actor.strip().casefold() == "chat"


def _secret(note: object) -> bool:
    if not isinstance(note, str) or note == "":
        return False
    seen = note
    for _ in range(3):
        if credential_shape(" ".join(seen.split())):
            return True
        decoded = unquote_plus(seen)
        if decoded == seen:
            return False
        seen = decoded
    return credential_shape(" ".join(seen.split()))
