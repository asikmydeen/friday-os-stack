"""Judge a caller-supplied catalog render. Nothing is applied.

The description is the reviewed manifest version: a 40-character
catalog pin, and a template hash and rendered digest of 40 or 64 hex
characters. Those three are recorded when they have that shape. Any
other value is refused and is not stored. This module does not render
Jinja, does not read the draft wires, does not fetch truenas/apps, and
does not write catalog/PIN.

Enterprise is omitted. An app that needs TrueNAS middleware is refused
and stays listed. A ZFS dataset is refused. A folder path standing in
for that dataset is refused. Host network, host PID, host IPC, a
privileged flag, an unlisted device, and an unlisted capability are
refused, and the app stays listed. A port that does not bind to
127.0.0.1 is refused. The image architecture must match the host
architecture the caller names. Those strings are not a measurement of
this machine. Declared memory above the caller's free RAM is refused,
including a boolean declared value.

A description that passes is recorded and not installed. confirmed=true
is ignored. The Board's accept still returns catalog_install_closed.
Chat cannot accept it. Friday's ask path does not call this module.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping

from gate.rules import DOCKER_SOCKET, FORBIDDEN_PREFIXES, canonicalize
from measure.ram import fits

TRAINS = frozenset({"stable", "community"})
DATA_ROOT = "/var/lib/friday"
FOLDER_KINDS = frozenset({"folder", "host_path", "hostpath", "path"})
DATASET_KINDS = frozenset({"dataset", "zfs", "zvol", "ix_volume"})
MIDDLEWARE = frozenset({"middleware", "truenas", "truenas_middleware", "ix_middleware"})
ARCH = {"amd64": "x86_64", "x86_64": "x86_64", "arm64": "aarch64", "aarch64": "aarch64"}


@dataclass(frozen=True)
class Decision:
    outcome: str
    reason: str
    app: str = ""
    train: str = ""
    listed: bool = False
    install: str = "refused"
    applied: bool = False
    started: bool = False
    jinja: bool = False
    pin_written: bool = False
    wires_read: bool = False
    portable: bool = False
    binds: tuple[str, ...] = ()
    image_arch: str = ""
    host_arch: str = ""
    arch_measured: bool = False
    storage_disk: str = ""
    declared: int | None = None
    free: int | None = None
    ram: str = ""
    measurement: str = ""
    approval: bool = False
    catalog_pin: str = ""
    template_hash: str = ""
    rendered_digest: str = ""


def judge_render(
    app_id: str,
    *,
    train: str,
    catalog_pin: str,
    template_hash: str,
    rendered_digest: str,
    storage_disk: str,
    storage_device: str,
    data_device: str,
    declared: int,
    free: int,
    image_arch: str,
    host_arch: str,
    middleware: bool = False,
    needs: object = None,
    storage: object = None,
    links: Mapping[str, str] | None = None,
    host_network: bool = False,
    host_pid: bool = False,
    host_ipc: bool = False,
    privileged: bool = False,
    network_mode: str = "bridge",
    pid_mode: str = "",
    ipc_mode: str = "",
    devices: object = (),
    capabilities: object = (),
    reviewed_devices: object = (),
    reviewed_capabilities: object = (),
    ports: object = None,
    confirmed: bool = False,
) -> Decision:
    del confirmed
    app = _app(app_id)
    if app == "":
        return _no("app_id", listed=False)
    train_name = _train(train)
    if train_name == "enterprise":
        return _no("enterprise_off", listed=False)
    if train_name not in TRAINS:
        return _no("train_refused", listed=False)
    if _middleware(middleware, needs):
        return _no("middleware_required", listed=True)
    disk, reason = _storage(storage, storage_disk, storage_device, data_device, links)
    if reason:
        return _no(reason, listed=True)
    reason = _privilege(
        host_network, host_pid, host_ipc, privileged, network_mode, pid_mode, ipc_mode
    )
    if reason:
        return _no(reason, listed=True)
    if _extra(devices, reviewed_devices):
        return _no("device_not_in_manifest", listed=True)
    if _extra(capabilities, reviewed_capabilities):
        return _no("capability_not_in_manifest", listed=True)
    binds, reason = _binds(ports)
    if reason:
        return _no(reason, listed=True)
    image, host, reason = _arches(image_arch, host_arch)
    if reason:
        return _no(reason, listed=True)
    fit = fits(declared=declared, free=free)
    if fit.outcome != "fits":
        return _no(fit.reason, listed=True)
    pin, template, digest, reason = _version(catalog_pin, template_hash, rendered_digest)
    if reason:
        return _no(reason, listed=True)
    return Decision(
        "recorded",
        "not_installed",
        app=app,
        train=train_name,
        listed=True,
        install="refused",
        portable=True,
        binds=binds,
        image_arch=image,
        host_arch=host,
        storage_disk=disk,
        declared=declared,
        free=free,
        ram=fit.reason,
        measurement="not_a_hardware_measurement",
        catalog_pin=pin,
        template_hash=template,
        rendered_digest=digest,
    )


def apply_render(decision: Decision | None = None, *, confirmed: bool = False) -> Decision:
    del decision, confirmed
    return Decision("refused", "catalog_install_closed")


def accept_render(actor: str, *, confirmed: bool = False) -> Decision:
    del confirmed
    if actor != "board":
        return Decision("refused", "actor_cannot_approve")
    return Decision("refused", "catalog_install_closed")


def _no(reason: str, *, listed: bool, portable: bool = False) -> Decision:
    return Decision("refused", reason, listed=listed, portable=portable)


def _app(value: object) -> str:
    if not isinstance(value, str):
        return ""
    name = value.strip().casefold()
    if name == "" or "/" in name or " " in name or ".." in name:
        return ""
    return name


def _train(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().casefold()


def _middleware(flag: object, needs: object) -> bool:
    if flag is not False:
        return True
    if needs is None:
        return False
    if isinstance(needs, str):
        return needs.strip().casefold() in MIDDLEWARE
    if not isinstance(needs, (list, tuple)):
        return True
    for item in needs:
        if not isinstance(item, str) or item.strip().casefold() in MIDDLEWARE:
            return True
    return False


def _version(
    pin: object,
    template_hash: object,
    rendered_digest: object,
) -> tuple[str, str, str, str]:
    commit = _hex(pin, 40)
    template = _hex(template_hash, 40, 64)
    digest = _hex(rendered_digest, 40, 64)
    if commit == "" or template == "" or digest == "":
        return "", "", "", "version_incomplete"
    return commit, template, digest, ""


def _hex(value: object, *lengths: int) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip().casefold()
    if re.fullmatch(r"[0-9a-f]+", text) is None or len(text) not in lengths:
        return ""
    return text


def _privilege(
    host_network: object,
    host_pid: object,
    host_ipc: object,
    privileged: object,
    network_mode: object,
    pid_mode: object,
    ipc_mode: object,
) -> str:
    if host_network is not False or network_mode == "host":
        return "host_network"
    if network_mode != "bridge":
        return "network_mode"
    if host_pid is not False or pid_mode == "host":
        return "host_pid"
    if pid_mode not in ("", "private"):
        return "pid_mode"
    if host_ipc is not False or ipc_mode == "host":
        return "host_ipc"
    if ipc_mode not in ("", "private"):
        return "ipc_mode"
    if privileged is not False:
        return "privileged"
    return ""


def _extra(requested: object, reviewed: object) -> bool:
    wanted = _names(requested)
    allowed = _names(reviewed)
    if wanted is None or allowed is None:
        return True
    known = set(allowed)
    return any(name not in known for name in wanted)


def _names(value: object) -> tuple[str, ...] | None:
    if value is None:
        return ()
    if isinstance(value, str):
        text = value.strip()
        return (text,) if text else ()
    if isinstance(value, bool) or not isinstance(value, (list, tuple)):
        return None
    names: list[str] = []
    for item in value:
        if not isinstance(item, str) or item.strip() == "":
            return None
        names.append(item.strip())
    return tuple(names)


def _binds(ports: object) -> tuple[tuple[str, ...], str]:
    if ports is None:
        return (), ""
    if isinstance(ports, (str, Mapping)) or not isinstance(ports, (list, tuple)):
        return (), "bind_not_loopback"
    binds: list[str] = []
    for port in ports:
        if isinstance(port, str):
            host = port
        elif isinstance(port, Mapping):
            host = port.get("host", "")
        else:
            return (), "bind_not_loopback"
        if not isinstance(host, str) or not host.startswith("127.0.0.1:"):
            return (), "bind_not_loopback"
        number = host.split(":", 1)[1]
        if not number.isdigit() or not 1 <= int(number) <= 65535:
            return (), "bind_not_loopback"
        binds.append(host)
    return tuple(binds), ""


def _arches(image: object, host: object) -> tuple[str, str, str]:
    image_name = _arch(image)
    host_name = _arch(host)
    if image_name is None or host_name is None:
        return "", "", "arch_missing"
    if image_name != host_name:
        return "", "", "arch_mismatch"
    return image_name, host_name, ""


def _arch(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    key = value.strip().casefold()
    if key == "":
        return None
    return ARCH.get(key, key)


def _storage(
    entries: object,
    storage_disk: object,
    storage_device: object,
    data_device: object,
    links: Mapping[str, str] | None,
) -> tuple[str, str]:
    if not isinstance(storage_device, str) or not isinstance(data_device, str):
        return "", "storage_device"
    storage_device = storage_device.strip()
    data_device = data_device.strip()
    if storage_device == "" or data_device == "":
        return "", "storage_device"
    if storage_device == data_device:
        return "", "storage_on_data_partition"
    if links is not None and not isinstance(links, Mapping):
        return "", "mount_not_absolute"
    if not isinstance(storage_disk, str) or storage_disk == "":
        return "", "storage_disk"
    try:
        disk = canonicalize(storage_disk, links)
    except ValueError as exc:
        return "", str(exc)
    if disk == "/":
        return "", "mount_root"
    if disk == DATA_ROOT or disk.startswith(DATA_ROOT + "/"):
        return "", "storage_on_data_partition"
    if _blocked(disk):
        return "", "mount_forbidden"
    if entries is None:
        return disk, ""
    if isinstance(entries, (str, Mapping)) or not isinstance(entries, (list, tuple)):
        return "", "storage_shape"
    for entry in entries:
        if not isinstance(entry, Mapping):
            return "", "storage_shape"
        kind = entry.get("kind", "")
        if not isinstance(kind, str):
            return "", "storage_shape"
        kind = kind.strip().casefold()
        if kind in DATASET_KINDS:
            return "", "dataset_not_portable"
        if entry.get("substitutes_dataset") not in (None, False) or entry.get("folder_substitutes_dataset") not in (None, False):
            return "", "folder_is_not_a_dataset"
        if kind not in FOLDER_KINDS:
            return "", "storage_shape"
        source = entry.get("source", "")
        if source == "":
            continue
        if not isinstance(source, str):
            return "", "mount_not_absolute"
        try:
            path = canonicalize(source, links)
        except ValueError as exc:
            return "", str(exc)
        if path == "/":
            return "", "mount_root"
        if path == DATA_ROOT or path.startswith(DATA_ROOT + "/"):
            return "", "storage_on_data_partition"
        if _blocked(path):
            return "", "mount_forbidden"
        if path != disk and not path.startswith(disk.rstrip("/") + "/"):
            return "", "mount_outside_disk"
    return disk, ""


def _blocked(path: str) -> bool:
    if path in {DOCKER_SOCKET, "/", DATA_ROOT} or path.startswith(DATA_ROOT + "/"):
        return True
    for root in FORBIDDEN_PREFIXES:
        base = root.rstrip("/")
        if path == base or path.startswith(base + "/"):
            return True
    return False
