"""Plan the Movies and TV wiring. Nothing is applied.

The plan names one player. Jellyfin is the default. Plex is the plan
only when that player was chosen, and only then is the claim token
asked, as a name. The other player is left out. qBittorrent, Prowlarr,
Radarr, and Sonarr are always named. Home Assistant is not in the plan.
Bazarr is not in the base plan. Tautulli is offered only when Plex is
primary.

The quality profile is worst-first. Unknown is first and disallowed.
A best-first list is refused. Fetcher is named for the download-client
tools and Media for the player. No other advisor is named, and the
family role is blocked. The names are not turned on. Adding the other
player later keeps Radarr and Sonarr as the writers, names that
player's secret names, loopback bind, and wired health URL, and leaves
Media on the primary. Bazarr writes the subtitle paths. The chosen
player reads them.

Webhooks are the wired URLs and are not posted. Library paths sit on
the app storage disk. The data partition is refused. Settings pages
bind to 127.0.0.1. qBittorrent's settings page is 127.0.0.1:8081.
Refusing a public name does not stop the swarm. Prowlarr starts with
no indexers. A health probe is the wired URL. It is not opened. An add
call is not announced as a download.

confirmed=true is ignored. apply_plan returns catalog_install_closed.
This module does not open a socket, does not write a file, and does
not start a container. Friday's ask path does not call it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from gate.rules import DOCKER_SOCKET, FORBIDDEN_PREFIXES, canonicalize

ALWAYS = ("qbittorrent", "prowlarr", "radarr", "sonarr")
PLAYERS = frozenset({"jellyfin", "plex"})
STEPS = (
    "generate_api_keys",
    "generate_credentials",
    "point_clients",
    "point_prowlarr",
    "quality_profile",
    "register_webhook",
    "point_player",
    "grant_tools",
    "health_probes",
    "bind_uis",
)
DATA_ROOT = "/var/lib/friday"
BINDS = {
    "qbittorrent": "127.0.0.1:8081",
    "prowlarr": "127.0.0.1:9696",
    "radarr": "127.0.0.1:7878",
    "sonarr": "127.0.0.1:8989",
    "jellyfin": "127.0.0.1:8096",
    "plex": "127.0.0.1:32400",
    "bazarr": "127.0.0.1:6767",
}
PROBES = {
    "qbittorrent": "http://qbittorrent:8080/api/v2/app/version",
    "prowlarr": "http://prowlarr:9696/ping",
    "radarr": "http://radarr:7878/ping",
    "sonarr": "http://sonarr:8989/ping",
    "jellyfin": "http://jellyfin:8096/health",
    "plex": "http://plex:32400/identity",
    "bazarr": "http://bazarr:6767/api/system/ping",
}
SECRETS = {
    "radarr": ("RADARR_URL", "RADARR_API_KEY"),
    "sonarr": ("SONARR_URL", "SONARR_API_KEY"),
    "prowlarr": ("PROWLARR_URL", "PROWLARR_API_KEY"),
    "qbittorrent": ("QBITTORRENT_URL", "QBITTORRENT_USER", "QBITTORRENT_PASSWORD"),
    "jellyfin": ("JELLYFIN_URL", "JELLYFIN_API_KEY"),
    "plex": ("PLEX_CLAIM_TOKEN", "PLEX_SERVER_TOKEN"),
    "bazarr": ("BAZARR_URL", "BAZARR_API_KEY"),
}
ARR_WEBHOOK = "http://webhooks:8080/arr"
MEDIA_WEBHOOK = "http://webhooks:8080/media"
FETCHER = ("radarr", "sonarr", "prowlarr", "qbittorrent")
LEFT_OUT = ("home-assistant", "bazarr", "tautulli")


@dataclass(frozen=True)
class Decision:
    outcome: str
    reason: str
    player: str = ""
    primary: str = ""
    apps: tuple[str, ...] = ()
    omitted: tuple[str, ...] = ()
    steps: tuple[str, ...] = ()
    secrets: tuple[str, ...] = ()
    claim_asked: bool = False
    quality: str = ""
    unknown_first: bool = False
    unknown_disallowed: bool = False
    grants: tuple[tuple[str, tuple[str, ...]], ...] = ()
    tools_on: bool = False
    webhooks: tuple[str, ...] = ()
    posted: bool = False
    library: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = ()
    categories: tuple[tuple[str, str], ...] = ()
    storage_disk: str = ""
    binds: tuple[str, ...] = ()
    indexers: tuple[str, ...] = ()
    full_sync: bool = False
    probes: tuple[str, ...] = ()
    health: str = ""
    probed: bool = False
    read_write: bool = False
    attaches: tuple[str, ...] = ()
    applied: bool = False
    started: bool = False
    public_name: bool = False
    swarm_stopped: bool = False
    calls_stopped: bool = False
    said: str = ""


def plan_bundle(
    player: str = "jellyfin",
    *,
    storage_disk: str,
    storage_device: str,
    data_device: str,
    links: Mapping[str, str] | None = None,
    quality: str = "worst-first",
    confirmed: bool = False,
    claim_token: str = "",
) -> Decision:
    del confirmed, claim_token
    chosen = player.strip().casefold() if isinstance(player, str) else ""
    if chosen not in PLAYERS:
        return Decision("refused", "not_in_bundle")
    if quality == "best-first":
        return Decision("refused", "best_first_refused")
    if quality != "worst-first":
        return Decision("refused", "quality_order")
    disk, reason = _storage(storage_disk, storage_device, data_device, links)
    if reason:
        return Decision("refused", reason)
    other = "plex" if chosen == "jellyfin" else "jellyfin"
    apps = ALWAYS + (chosen,)
    secrets: list[str] = []
    for app in ("radarr", "sonarr", "prowlarr", "qbittorrent", chosen):
        secrets.extend(SECRETS[app])
    webhooks = [ARR_WEBHOOK]
    if chosen == "jellyfin":
        webhooks.append(MEDIA_WEBHOOK)
    return Decision(
        "recorded",
        "not_applied",
        player=chosen,
        primary=chosen,
        apps=apps,
        omitted=(other,) + LEFT_OUT,
        steps=STEPS,
        secrets=tuple(secrets),
        claim_asked=chosen == "plex",
        quality="worst-first",
        unknown_first=True,
        unknown_disallowed=True,
        grants=(("fetcher", FETCHER), ("media", (chosen,))),
        webhooks=tuple(webhooks),
        library=(
            ("library/downloads", ("qbittorrent",), ("radarr", "sonarr")),
            ("library/movies", ("radarr",), (chosen,)),
            ("library/tv", ("sonarr",), (chosen,)),
        ),
        categories=(("radarr", "radarr"), ("sonarr", "sonarr")),
        storage_disk=disk,
        binds=tuple(BINDS[app] for app in apps),
        full_sync=True,
        probes=tuple(PROBES[app] for app in apps),
    )


def tools_for(role: str, kind: str, player: str = "jellyfin") -> Decision:
    chosen = player.strip().casefold() if isinstance(player, str) else ""
    if chosen not in PLAYERS:
        return Decision("refused", "not_in_bundle")
    if role == "family":
        return Decision("refused", "family_blocked")
    if kind == "download" and role == "fetcher":
        return Decision("recorded", "fetcher", grants=(("fetcher", FETCHER),))
    if kind == "player" and role == "media":
        return Decision("recorded", "media", player=chosen, grants=(("media", (chosen,)),))
    return Decision("refused", "not_that_advisor")


def add_bazarr(
    *,
    storage_disk: str,
    storage_device: str,
    data_device: str,
    links: Mapping[str, str] | None = None,
    player: str = "jellyfin",
    confirmed: bool = False,
) -> Decision:
    del confirmed
    chosen = _player(player)
    if chosen == "":
        return Decision("refused", "not_in_bundle")
    disk, reason = _storage(storage_disk, storage_device, data_device, links)
    if reason:
        return Decision("refused", reason)
    return Decision(
        "recorded",
        "not_applied",
        player=chosen,
        apps=("bazarr",),
        secrets=SECRETS["bazarr"],
        grants=(("fetcher", ("bazarr",)),),
        library=(
            ("library/movies", ("bazarr",), (chosen,)),
            ("library/tv", ("bazarr",), (chosen,)),
        ),
        storage_disk=disk,
        binds=(BINDS["bazarr"],),
        probes=(PROBES["bazarr"],),
        read_write=True,
        attaches=("radarr", "sonarr"),
    )


def offer_tautulli(primary: str, *, confirmed: bool = False) -> Decision:
    del confirmed
    if _player(primary) != "plex":
        return Decision("refused", "not_plex_primary")
    return Decision("recorded", "not_applied", apps=("tautulli",), primary="plex")


def add_other_player(primary: str, *, confirmed: bool = False) -> Decision:
    del confirmed
    chosen = _player(primary)
    if chosen == "":
        return Decision("refused", "not_in_bundle")
    other = "plex" if chosen == "jellyfin" else "jellyfin"
    return Decision(
        "recorded",
        "not_applied",
        player=other,
        primary=chosen,
        apps=(other,),
        claim_asked=other == "plex",
        secrets=SECRETS[other],
        library=(
            ("library/movies", ("radarr",), (chosen, other)),
            ("library/tv", ("sonarr",), (chosen, other)),
        ),
        binds=(BINDS[other],),
        probes=(PROBES[other],),
    )


def wired_probe(app: str, supplied: str = "") -> Decision:
    del supplied
    health = PROBES.get(app)
    if health is None:
        return Decision("refused", "unknown_app")
    return Decision("recorded", "wired_url", health=health, probes=(health,))


def from_add_call(text: str = "") -> Decision:
    del text
    return Decision("refused", "not_from_the_add_call")


def publish_name(app: str, *, confirmed: bool = False) -> Decision:
    del app, confirmed
    return Decision("refused", "public_name_off")


def apply_plan(plan: Decision | None = None, *, confirmed: bool = False) -> Decision:
    del plan, confirmed
    return Decision("refused", "catalog_install_closed")


def _player(value: object) -> str:
    if not isinstance(value, str):
        return ""
    chosen = value.strip().casefold()
    if chosen not in PLAYERS:
        return ""
    return chosen


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
