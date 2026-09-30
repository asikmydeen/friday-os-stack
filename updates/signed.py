"""Refuse an update this cut cannot check, and keep the code profile off.

The owner sees an update on the Board. An empty signature is unsigned.
A non-empty signature is signature_not_checked, because this cut has no
verifier. Neither result is applied or shown as signed.

The code profile has no baked platform token. This function does not
read the environment. An empty Coder URL keeps the profile off. A URL
and a caller-supplied token still do not start taskrunner: the result
is waiting, not_started.

This module does not apply an update and does not start a container.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Decision:
    outcome: str
    reason: str


def propose(*, actor: str, signature: str) -> Decision:
    if actor != "board":
        return Decision("refused", "owner_must_see")
    if signature == "":
        return Decision("refused", "unsigned")
    return Decision("refused", "signature_not_checked")


def code_profile(
    *,
    enabled: bool = False,
    coder_url: str = "",
    token: str | None = None,
) -> Decision:
    if enabled is not True:
        return Decision("off", "profile_off")
    if coder_url == "":
        return Decision("off", "no_coder_url")
    if token is None or token == "":
        return Decision("refused", "token_required")
    return Decision("waiting", "not_started")
