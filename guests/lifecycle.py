"""Decide how a guest is installed, adopted, or removed.

The agent path is not running, so install_guest and the movies and TV
bundle return catalog_install_closed. Adopt records adopted and does
not start a second copy. Disconnect of an adopted app removes Friday's
URL, grants, and health check, and leaves the external app running.
A managed uninstall keeps the video files. Deleting those files is a
separate confirm. Home Assistant is a separate entry, not part of the
bundle.

confirmed=true is ignored. This module does not start a container.
"""

from __future__ import annotations

from dataclasses import dataclass

PLAYERS = frozenset({"jellyfin", "plex"})


@dataclass(frozen=True)
class Decision:
    outcome: str
    reason: str
    mark: str | None = None
    running_here: bool | None = None


def install_guest(app_id: str, *, confirmed: bool = False) -> Decision:
    del app_id, confirmed
    return Decision("refused", "catalog_install_closed")


def bundle(player: str, *, confirmed: bool = False) -> Decision:
    del confirmed
    if player not in PLAYERS:
        return Decision("refused", "not_in_bundle")
    return Decision("refused", "catalog_install_closed")


def adopt(app_id: str) -> Decision:
    del app_id
    return Decision("recorded", "adopted", mark="adopted", running_here=False)


def disconnect(mark: str) -> Decision:
    if mark != "adopted":
        return Decision("refused", "not_adopted")
    return Decision("recorded", "left_running", running_here=True)


def uninstall(mark: str, *, delete_files: bool = False) -> Decision:
    if mark != "managed":
        return Decision("refused", "not_managed")
    if delete_files:
        return Decision("refused", "files_need_their_own_confirm")
    return Decision("recorded", "files_kept")
