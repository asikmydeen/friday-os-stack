"""Decide how a guest is installed, adopted, or removed.

The agent path is not running, so install_guest and the movies and TV
bundle return catalog_install_closed. Adopt records adopted and does
not start a second copy. Disconnect of an adopted app removes Friday's
URL, grants, and health check, and leaves the external app running.
A managed uninstall keeps the video files. record_removal records that
the Board removed that app's grants and one tunnel name. The library
stays. The container is not stopped. A separate confirm does not delete
the files. Chat cannot record either, and that refusal leaves the row.
A second record keeps the first names. A credential-shaped name is not
stored, including a percent-encoded or plus-encoded copy. Home Assistant is a separate entry, not part of the bundle.

confirmed=true is ignored. This module does not start or stop a
container, does not delete a file, does not call Cloudflare, and does
not open a socket. Friday's ask path does not call it.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import unquote_plus

from memoryd.store import credential_shape

PLAYERS = frozenset({"jellyfin", "plex"})
_LIMIT = 200


@dataclass(frozen=True)
class Decision:
    outcome: str
    reason: str
    mark: str | None = None
    running_here: bool | None = None
    app_id: str = ""
    grants: tuple[str, ...] = ()
    tunnel_name: str = ""
    files_kept: bool = False
    library_kept: bool = False
    stopped: bool = False
    deleted: bool = False
    started: bool = False
    called: bool = False


@dataclass(frozen=True)
class Removal:
    app_id: str
    grants: tuple[str, ...]
    tunnel_name: str


class Book:
    def __init__(self) -> None:
        self.rows: dict[str, Removal] = {}

    def __repr__(self) -> str:
        return "Book()"


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
        return Decision("refused", "not_managed", files_kept=True, library_kept=True)
    if delete_files:
        return _quiet("files_need_their_own_confirm")
    return _quiet("files_kept", outcome="recorded")


def record_removal(
    book: Book,
    *,
    actor: object,
    app_id: object,
    grants: object = (),
    tunnel_name: object = "",
    mark: object = "managed",
    delete_files: bool = False,
    confirmed: bool = False,
) -> Decision:
    """Record grant and tunnel removal. Do not stop the container or delete files."""
    del confirmed
    if _chat(actor):
        return _quiet("chat_cannot")
    if actor != "board":
        return _quiet("actor_cannot")
    name, reason = _label(app_id, "app_id")
    if reason:
        return _quiet(reason)
    kept, reason = _grant_names(grants)
    if reason:
        return _quiet(reason)
    tunnel, reason = _label(tunnel_name, "tunnel_name", empty=True)
    if reason:
        return _quiet(reason)
    if delete_files:
        return _quiet("files_need_their_own_confirm")
    if mark != "managed":
        return _quiet("not_managed")
    row = book.rows.get(name)
    if row is not None:
        return _from(row, "already")
    stored = Removal(name, kept, tunnel)
    book.rows[name] = stored
    return _from(stored, "files_kept")


def confirm_delete(
    book: Book,
    *,
    actor: object,
    app_id: object,
    confirmed: bool = False,
) -> Decision:
    """See a separate file-delete confirm. Delete nothing."""
    del confirmed
    if _chat(actor):
        return _quiet("chat_cannot")
    if actor != "board":
        return _quiet("actor_cannot")
    name, reason = _label(app_id, "app_id")
    if reason:
        return _quiet(reason)
    row = book.rows.get(name)
    if row is None:
        return _quiet("unknown_app")
    return _from(row, "files_not_deleted")


def _from(row: Removal, reason: str) -> Decision:
    return Decision(
        "recorded",
        reason,
        mark="managed",
        app_id=row.app_id,
        grants=row.grants,
        tunnel_name=row.tunnel_name,
        files_kept=True,
        library_kept=True,
        stopped=False,
        deleted=False,
        started=False,
        called=False,
    )


def _quiet(reason: str, *, outcome: str = "refused") -> Decision:
    return Decision(
        outcome,
        reason,
        files_kept=True,
        library_kept=True,
        stopped=False,
        deleted=False,
        started=False,
        called=False,
    )


def _chat(actor: object) -> bool:
    return isinstance(actor, str) and actor.strip().casefold() == "chat"


def _label(value: object, reason: str, *, empty: bool = False) -> tuple[str, str]:
    if not isinstance(value, str):
        return "", reason
    if value == "" and empty:
        return "", ""
    if value == "" or value != value.strip() or "\n" in value or len(value) > _LIMIT:
        return "", reason
    if _hidden(value):
        return "", "credential"
    return value, ""


def _grant_names(value: object) -> tuple[tuple[str, ...], str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
        return (), "grant_list"
    found: list[str] = []
    seen: set[str] = set()
    for item in value:
        name, reason = _label(item, "grant_name")
        if reason:
            return (), reason
        if name not in seen:
            seen.add(name)
            found.append(name)
    return tuple(found), ""


def _hidden(text: str) -> bool:
    seen = text
    for _ in range(3):
        if credential_shape(" ".join(seen.split())):
            return True
        decoded = unquote_plus(seen)
        if decoded == seen:
            return False
        seen = decoded
    return credential_shape(" ".join(seen.split()))
