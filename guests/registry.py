"""Read an app registry the caller already has.

A row records id, train, version, status, image, ports, folders, health
URL, declared memory limit, and wire level. observe records an adopted
app and does not start it. install writes nothing. check_service and
what's running read the rows and do not open a health URL. What's using
RAM is that declared limit, not a measurement. Stopping an adopted app
leaves it running. Chat cannot stop a managed row. The Board's stop
does not change that row. A health name is kept only with the addresses
the caller resolved. A managed row names its storage disk and two
different devices.

confirmed=true is ignored. This module does not open SQLite, does not
resolve DNS, does not probe a port, and does not start or stop a
container. Friday's ask path does not call it.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from typing import Mapping, Sequence
from urllib.parse import urlsplit

from gate.rules import DOCKER_SOCKET, FORBIDDEN_PREFIXES, canonicalize
from netpolicy.paths import CORE_NAMES, vet_adopted

TRAINS = frozenset({"stable", "community"})
STATUSES = frozenset({"running", "stopped"})
LEVELS = frozenset({"known", "listed", "proposed"})
MARKS = frozenset({"managed", "adopted"})
DATA_ROOT = "/var/lib/friday"
_ID = re.compile(r"[a-z][a-z0-9-]{0,63}\Z")
_VERSION = re.compile(r"[A-Za-z0-9._-]{1,64}\Z")
_IMAGE = re.compile(r"[A-Za-z0-9._:@/-]{1,200}\Z")
_PORT = re.compile(r"127\.0\.0\.1:([0-9]{1,5})\Z")


@dataclass(frozen=True)
class App:
    id: str
    train: str
    version: str
    status: str
    image: str
    ports: tuple[str, ...]
    folders: tuple[str, ...]
    health_url: str
    memory_limit: int
    wire_level: str
    mark: str


@dataclass(frozen=True)
class Decision:
    outcome: str
    reason: str
    app_id: str = ""
    status: str = ""
    health_url: str = ""
    wire_level: str = ""
    mark: str = ""
    memory_limit: int | None = None
    running: tuple[str, ...] = ()
    tools_on: bool = False
    stopped: bool = False


class Book:
    def __init__(self) -> None:
        self.apps: dict[str, App] = {}


def observe(
    book: Book,
    fields: Mapping,
    *,
    links: Mapping[str, str] | None = None,
    resolved: Mapping[str, Sequence[str]] | None = None,
    confirmed: bool = False,
) -> Decision:
    del confirmed
    if fields.get("mark") not in (None, "adopted"):
        return Decision("refused", "not_adopted")
    app, reason = _row(fields, links, "adopted", resolved)
    if reason:
        return Decision("refused", reason)
    if app.id in book.apps:
        return Decision("refused", "already_recorded", app_id=app.id)
    book.apps[app.id] = app
    return Decision("recorded", "adopted", app_id=app.id, mark="adopted", status=app.status)


def install(book: Book, fields: Mapping, *, confirmed: bool = False) -> Decision:
    del book, fields, confirmed
    return Decision("refused", "catalog_install_closed")


def restore(
    book: Book,
    rows: list[Mapping],
    *,
    links: Mapping[str, str] | None = None,
    resolved: Mapping[str, Sequence[str]] | None = None,
) -> Decision:
    if isinstance(rows, (str, bytes)) or not isinstance(rows, (list, tuple)):
        return Decision("refused", "registry_mark")
    if len(rows) == 0:
        return Decision("refused", "empty")
    parsed: list[App] = []
    seen: set[str] = set()
    for fields in rows:
        if not isinstance(fields, Mapping):
            return Decision("refused", "registry_mark")
        mark = fields.get("mark")
        if mark not in MARKS:
            return Decision("refused", "registry_mark")
        app, reason = _row(fields, links, mark, resolved)
        if reason:
            return Decision("refused", reason)
        if app.id in seen:
            return Decision("refused", "duplicate")
        seen.add(app.id)
        parsed.append(app)
    book.apps = {app.id: app for app in parsed}
    return Decision("recorded", "restored")


def check_service(book: Book, app_id: str) -> Decision:
    if _core(app_id):
        return Decision("refused", "core_locked", app_id=app_id)
    app = book.apps.get(app_id)
    if app is None:
        return Decision("refused", "unknown_app")
    return Decision(
        "recorded",
        "not_probed",
        app_id=app.id,
        status=app.status,
        health_url=app.health_url,
        wire_level=app.wire_level,
        mark=app.mark,
        memory_limit=app.memory_limit,
    )


def whats_running(book: Book) -> Decision:
    running = tuple(app.id for app in book.apps.values() if app.status == "running")
    return Decision("recorded", "registry", running=running)


def memory_use(book: Book, app_id: str) -> Decision:
    if _core(app_id):
        return Decision("refused", "core_locked", app_id=app_id)
    app = book.apps.get(app_id)
    if app is None:
        return Decision("refused", "unknown_app")
    return Decision(
        "recorded",
        "declared_not_measured",
        app_id=app.id,
        memory_limit=app.memory_limit,
    )


def stop(book: Book, app_id: str, *, actor: str, confirmed: bool = False) -> Decision:
    del confirmed
    if _core(app_id):
        return Decision("refused", "core_locked", app_id=app_id)
    app = book.apps.get(app_id)
    if app is None:
        return Decision("refused", "unknown_app")
    if app.mark == "adopted":
        return Decision(
            "refused",
            "left_running",
            app_id=app.id,
            status=app.status,
            mark=app.mark,
        )
    if actor != "board":
        return Decision(
            "refused",
            "actor_cannot_approve",
            app_id=app.id,
            status=app.status,
            mark=app.mark,
        )
    return Decision(
        "waiting",
        "not_stopped",
        app_id=app.id,
        status=app.status,
        mark=app.mark,
    )


def _core(app_id: object) -> bool:
    return isinstance(app_id, str) and app_id.casefold() in CORE_NAMES


def _row(
    fields: Mapping,
    links: Mapping[str, str] | None,
    mark: str,
    resolved: Mapping[str, Sequence[str]] | None,
) -> tuple[App | None, str]:
    app_id = fields.get("id")
    if _core(app_id) or not isinstance(app_id, str) or _ID.fullmatch(app_id) is None:
        return None, "core_locked" if _core(app_id) else "app_id"
    train = fields.get("train")
    if train not in TRAINS:
        return None, "train"
    version = fields.get("version")
    if not isinstance(version, str) or _VERSION.fullmatch(version) is None:
        return None, "version"
    status = fields.get("status")
    if status not in STATUSES:
        return None, "status"
    image = fields.get("image")
    if not isinstance(image, str) or _IMAGE.fullmatch(image) is None or ".." in image:
        return None, "image"
    ports, reason = _ports(fields.get("ports"))
    if reason:
        return None, reason
    folders, reason = _folders(fields.get("folders"), fields.get("storage_disk"), links, mark)
    if reason:
        return None, reason
    device_reason = _device_reason(fields, mark)
    if device_reason:
        return None, device_reason
    level = fields.get("wire_level")
    if level not in LEVELS:
        return None, "wire_level"
    health, reason = _health(fields.get("health_url"), required=level == "known", resolved=resolved)
    if reason:
        return None, reason
    limit = fields.get("memory_limit")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        return None, "memory_limit"
    return App(
        app_id,
        train,
        version,
        status,
        image,
        ports,
        folders,
        health,
        limit,
        level,
        mark,
    ), ""


def _device_reason(fields: Mapping, mark: str) -> str:
    if mark != "managed" and "storage_device" not in fields and "data_device" not in fields:
        return ""
    storage = fields.get("storage_device")
    data = fields.get("data_device")
    if not isinstance(storage, str) or not isinstance(data, str) or storage == "" or data == "":
        return "storage_device"
    if storage == data:
        return "storage_on_data_partition"
    return ""


def _ports(value: object) -> tuple[tuple[str, ...] | None, str]:
    if value is None:
        value = ()
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        return None, "ports"
    found: list[str] = []
    for item in value:
        if not isinstance(item, str):
            return None, "ports"
        matched = _PORT.fullmatch(item)
        if matched is None:
            return None, "ports"
        number = int(matched.group(1))
        if number < 1 or number > 65535:
            return None, "ports"
        if item not in found:
            found.append(item)
    return tuple(found), ""


def _folders(
    value: object,
    storage_disk: object,
    links: Mapping[str, str] | None,
    mark: str,
) -> tuple[tuple[str, ...] | None, str]:
    if value is None:
        value = ()
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        return None, "folders"
    disk = None
    if storage_disk is not None:
        if not isinstance(storage_disk, str):
            return None, "storage_disk"
        try:
            disk = canonicalize(storage_disk, links)
        except ValueError as exc:
            return None, str(exc)
        if _blocked(disk):
            return None, "mount_forbidden" if not _on_data(disk) else "storage_on_data_partition"
    found: list[str] = []
    for item in value:
        if not isinstance(item, str):
            return None, "folders"
        try:
            path = canonicalize(item, links)
        except ValueError as exc:
            return None, str(exc)
        if path == "/":
            return None, "mount_root"
        if _blocked(path):
            return None, "data_partition" if _on_data(path) and path != DOCKER_SOCKET else "mount_forbidden"
        if disk is not None and path != disk and not path.startswith(disk.rstrip("/") + "/"):
            return None, "mount_outside_disk"
        if path not in found:
            found.append(path)
    if mark == "managed" and disk is None:
        return None, "storage_disk"
    return tuple(found), ""


def _blocked(path: str) -> bool:
    if path == DOCKER_SOCKET or path == "/" or _on_data(path):
        return True
    for root in FORBIDDEN_PREFIXES:
        base = root.rstrip("/")
        if path == base or path.startswith(base + "/"):
            return True
    return False


def _on_data(path: str) -> bool:
    return path == DATA_ROOT or path.startswith(DATA_ROOT + "/")


def _health(
    value: object,
    *,
    required: bool,
    resolved: Mapping[str, Sequence[str]] | None,
) -> tuple[str, str]:
    if value in (None, ""):
        if required:
            return "", "health_url"
        return "", ""
    if not isinstance(value, str) or "\\" in value or " " in value:
        return "", "health_url"
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
        return "", "health_url"
    if parsed.query or parsed.fragment or not parsed.hostname:
        return "", "health_url"
    addresses, reason = _addresses(resolved, parsed.hostname)
    if reason:
        return "", reason
    vetted = vet_adopted(parsed.hostname, addresses)
    if vetted.outcome != "allowed":
        return "", vetted.reason
    if not _is_ip(parsed.hostname) and not addresses:
        return "", "resolved"
    return value, ""


def _addresses(
    resolved: Mapping[str, Sequence[str]] | None,
    host: str,
) -> tuple[tuple[str, ...] | None, str]:
    if resolved is None:
        return (), ""
    if isinstance(resolved, (str, bytes)) or not isinstance(resolved, Mapping):
        return None, "resolved"
    key = host.rstrip(".").casefold()
    found = None
    for item, value in resolved.items():
        if isinstance(item, str) and item.rstrip(".").casefold() == key:
            found = value
            break
    if found is None:
        return (), ""
    if isinstance(found, (str, bytes)) or not isinstance(found, (list, tuple)):
        return None, "resolved"
    if any(not isinstance(item, str) or item.strip() == "" for item in found):
        return None, "resolved"
    return tuple(found), ""


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host.rstrip("."))
    except ValueError:
        return False
    return True
