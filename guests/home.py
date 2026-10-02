"""Plan Home Assistant as its own catalog entry. Nothing is applied.

The entry is not part of the Movies and TV bundle. The plan names the
Home charter and the tools home_status and home_control for that role
only. No other advisor is named. The URL and the long-lived token are
secret names. A caller-supplied value is not stored.

The config path sits on the app storage disk. The data partition is
refused. The page binds to 127.0.0.1:8123. A health probe is the wired
URL and is not opened. Host network, host PID, and host IPC are
refused. A device or a capability the reviewed manifest does not list
is refused. Declared memory above the caller's free RAM is refused.
Those numbers are not a measurement of this machine.

A tool is on only after the Board accepts that name. A name the
manifest does not list stays off, and it does not inherit an earlier
acceptance. Chat cannot accept a name, and that refusal leaves a name
the Board already accepted. confirmed=true is ignored. apply_plan returns
catalog_install_closed. This module does not open a socket, does not
write a file, and does not start a container. Friday's ask path does
not call it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from gate.rules import DOCKER_SOCKET, FORBIDDEN_PREFIXES, canonicalize
from measure.ram import fits

APP = "home-assistant"
CHARTER = "home"
TOOLS = ("home_status", "home_control")
SECRETS = ("HOME_ASSISTANT_URL", "HOME_ASSISTANT_TOKEN")
BIND = "127.0.0.1:8123"
PROBE = "http://home-assistant:8123/api/"
WIRED_URL = "http://home-assistant:8123"
VOLUME = "home_assistant_config"
MOUNT = "/config"
DATA_ROOT = "/var/lib/friday"
STEPS = (
    "name_secrets",
    "name_home_charter",
    "name_tools",
    "bind_loopback",
    "wire_health",
)


@dataclass(frozen=True)
class Decision:
    outcome: str
    reason: str
    app: str = ""
    separate: bool = False
    in_bundle: bool = False
    charter: str = ""
    charter_on: bool = False
    apps: tuple[str, ...] = ()
    steps: tuple[str, ...] = ()
    secrets: tuple[str, ...] = ()
    url: str = ""
    grants: tuple[tuple[str, tuple[str, ...]], ...] = ()
    tools_on: bool = False
    on: tuple[str, ...] = ()
    storage_disk: str = ""
    volume: str = ""
    mount: str = ""
    binds: tuple[str, ...] = ()
    health: str = ""
    probed: bool = False
    auth: str = ""
    host_network: bool = False
    host_pid: bool = False
    host_ipc: bool = False
    devices: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    declared: int | None = None
    free: int | None = None
    ram: str = ""
    measurement: str = ""
    applied: bool = False
    started: bool = False
    public_name: bool = False
    approval: bool = False


def plan_home(
    *,
    storage_disk: str,
    storage_device: str,
    data_device: str,
    links: Mapping[str, str] | None = None,
    url: str = "",
    token: str = "",
    confirmed: bool = False,
    declared: int,
    free: int,
    host_network: bool = False,
    host_pid: bool = False,
    host_ipc: bool = False,
    network_mode: str = "bridge",
    pid_mode: str = "",
    ipc_mode: str = "",
    devices: tuple[str, ...] | list[str] = (),
    capabilities: tuple[str, ...] | list[str] = (),
    bind: str = BIND,
) -> Decision:
    del confirmed, url, token
    reason = _privilege(host_network, host_pid, host_ipc, network_mode, pid_mode, ipc_mode)
    if reason:
        return Decision("refused", reason)
    if _listed(devices):
        return Decision("refused", "device_not_in_manifest")
    if _listed(capabilities):
        return Decision("refused", "capability_not_in_manifest")
    if bind != BIND:
        return Decision("refused", "bind_not_loopback")
    disk, reason = _storage(storage_disk, storage_device, data_device, links)
    if reason:
        return Decision("refused", reason)
    fit = fits(declared=declared, free=free)
    if fit.outcome != "fits":
        return Decision("refused", fit.reason, started=False, applied=False)
    return Decision(
        "recorded",
        "not_applied",
        app=APP,
        separate=True,
        charter=CHARTER,
        apps=(APP,),
        steps=STEPS,
        secrets=SECRETS,
        url=WIRED_URL,
        grants=((CHARTER, TOOLS),),
        storage_disk=disk,
        volume=VOLUME,
        mount=MOUNT,
        binds=(BIND,),
        health=PROBE,
        auth="bearer",
        declared=declared,
        free=free,
        ram=fit.reason,
        measurement="not_a_hardware_measurement",
    )


def tools_for(role: str) -> Decision:
    if role == "family":
        return Decision("refused", "family_blocked")
    if role == CHARTER:
        return Decision(
            "recorded",
            "home",
            charter=CHARTER,
            grants=((CHARTER, TOOLS),),
            tools_on=False,
        )
    return Decision("refused", "not_that_advisor")


def accept_tool(
    actor: str,
    name: str,
    *,
    already: tuple[str, ...] = (),
    confirmed: bool = False,
) -> Decision:
    del confirmed
    kept = _accepted(already)
    if kept is None:
        return Decision("refused", "already", on=(), tools_on=False, approval=False)
    if actor != "board":
        return Decision("refused", "actor_cannot_approve", on=kept, tools_on=False, approval=False)
    if not isinstance(name, str) or name not in TOOLS:
        return Decision("refused", "not_in_manifest", on=kept, tools_on=False, approval=False)
    on = _accepted(kept + (name,))
    return Decision(
        "accepted",
        "owner_accepted",
        charter=CHARTER,
        on=on,
        tools_on=name in on,
        approval=False,
        started=False,
        applied=False,
    )


def wired_probe(supplied: str = "") -> Decision:
    del supplied
    return Decision("recorded", "wired_url", health=PROBE, probed=False)


def publish_name(*, confirmed: bool = False) -> Decision:
    del confirmed
    return Decision("refused", "public_name_off", public_name=False)


def apply_plan(plan: Decision | None = None, *, confirmed: bool = False) -> Decision:
    del plan, confirmed
    return Decision("refused", "catalog_install_closed", applied=False, started=False)


def _accepted(names: object) -> tuple[str, ...] | None:
    if isinstance(names, str) or not isinstance(names, (tuple, list)):
        return None
    if any(not isinstance(name, str) for name in names):
        return None
    wanted = {name for name in names if name in TOOLS}
    return tuple(name for name in TOOLS if name in wanted)


def _listed(value: object) -> bool:
    if isinstance(value, str):
        return value != ""
    if isinstance(value, (tuple, list)):
        return len(value) > 0
    return value is not None


def _privilege(
    host_network: object,
    host_pid: object,
    host_ipc: object,
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
    return ""


def _storage(
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
    return disk, ""


def _blocked(path: str) -> bool:
    if path in {DOCKER_SOCKET, "/", DATA_ROOT} or path.startswith(DATA_ROOT + "/"):
        return True
    for root in FORBIDDEN_PREFIXES:
        base = root.rstrip("/")
        if path == base or path.startswith(base + "/"):
            return True
    return False
