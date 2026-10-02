"""Refuse an open-ended package upgrade. A reflash is not an upgrade.

Debian and kernel fixes belong in the signed system slot. This module
does not run apt, does not contact a mirror, and does not write that
slot. A sudo user, an env prefix, and quotes do not hide the upgrade.
Reflashing a disk is a new install. It does not erase the disk.
Chat cannot run either call. confirmed is ignored. A credential-shaped
command or disk name is not stored. Friday's ask path does not call it.
"""

from __future__ import annotations

from dataclasses import dataclass

from memoryd.store import credential_shape

_TOOLS = frozenset({"apt", "apt-get", "aptitude"})
_UPGRADE = frozenset({"upgrade", "dist-upgrade", "full-upgrade", "safe-upgrade"})
_WRAPPERS = frozenset({
    "sudo",
    "command",
    "env",
    "nice",
    "nohup",
    "timeout",
    "doas",
    "pkexec",
    "ionice",
    "stdbuf",
    "time",
    "fakeroot",
})
_TAKES_ARG = frozenset({
    "-u",
    "-g",
    "-p",
    "-h",
    "-c",
    "-n",
    "-t",
    "-s",
    "-r",
    "-w",
    "--user",
    "--group",
    "--prompt",
    "--chdir",
    "--role",
})


@dataclass(frozen=True)
class Decision:
    outcome: str
    reason: str
    name: str = ""
    applied: bool = False
    ran: bool = False
    erased: bool = False
    written: bool = False


def package_change(actor: str, command: object, *, confirmed: bool = False) -> Decision:
    """Refuse a package command. Nothing is downloaded or applied."""
    del confirmed
    if not isinstance(command, str):
        return _quiet("command")
    if credential_shape(command):
        return _quiet("credential")
    if actor != "board":
        return _quiet("board_only")
    text = command.strip()
    if text == "" or any(mark in text for mark in "\n\r\x00"):
        return _quiet("command")
    argv = _argv(text)
    if not argv or _tool(argv[0]) is None:
        return _quiet("not_a_package_change")
    verbs = [part.casefold() for part in argv[1:] if not part.startswith("-")]
    if any(verb in _UPGRADE for verb in verbs):
        return _quiet("apt_upgrade_refused")
    return _quiet("signed_slot_only")


def reflash(actor: str, target: object, *, confirmed: bool = False) -> Decision:
    """A reflash is a new install. This call does not erase or write."""
    del confirmed
    if not isinstance(target, str) or target == "" or target != target.strip():
        return _quiet("name")
    if any(mark in target for mark in "\n\r\x00"):
        return _quiet("name")
    if credential_shape(target):
        return _quiet("credential")
    if actor != "board":
        return _quiet("board_only")
    return Decision("refused", "not_an_upgrade", name=target)


def _quiet(reason: str) -> Decision:
    return Decision("refused", reason)


def _argv(text: str) -> list[str]:
    parts = [_bare(part) for part in text.split()]
    index = 0
    while index < len(parts):
        token = parts[index]
        folded = token.casefold()
        if folded in _WRAPPERS or _assignment(token):
            index += 1
            if folded in {"timeout", "nice", "ionice", "stdbuf"} and _plain(parts, index):
                index += 1
            continue
        if token.startswith("-"):
            index += 1
            if folded in _TAKES_ARG and _plain(parts, index):
                index += 1
            continue
        break
    return parts[index:]


def _plain(parts: list[str], index: int) -> bool:
    if index >= len(parts):
        return False
    token = parts[index]
    return _tool(token) is None and not token.startswith("-") and not _assignment(token)


def _assignment(token: str) -> bool:
    if "=" not in token or token.startswith("-"):
        return False
    name = token.split("=", 1)[0]
    return name.replace("_", "").isalnum() and name != ""


def _bare(token: str) -> str:
    if len(token) >= 2 and token[0] == token[-1] and token[0] in {'"', "'"}:
        return token[1:-1]
    return token


def _tool(token: str) -> str | None:
    base = _bare(token).casefold().rsplit("/", 1)[-1]
    if base in _TOOLS:
        return base
    return None
