"""Refuse an update this cut cannot apply, and keep the code profile off.

The owner sees an update on the Board. An empty signature is unsigned.
With no verifier configured, a non-empty signature is
signature_not_checked. A verifier is handed the checksum line and the
signature. A match is checked_not_applied. A mismatch is
signature_rejected. None of these results is applied or shown as signed.
This module reads no key file.

The code profile has no baked platform token. This function does not
read the environment. An empty Coder URL keeps the profile off. A URL
and a caller-supplied token still do not start taskrunner: the result
is waiting, not_started.

This module does not apply an update and does not start a container.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_DIGEST = re.compile(r"[0-9a-f]{64}")
_FILENAME = re.compile(r"[A-Za-z0-9._-]{1,128}")


@dataclass(frozen=True)
class Decision:
    outcome: str
    reason: str


def checksum_line(digest: str, filename: str) -> str | None:
    if _DIGEST.fullmatch(digest) is None or _FILENAME.fullmatch(filename) is None:
        return None
    return f"{digest}  {filename}\n"


def propose(
    *,
    actor: str,
    signature: str,
    checksum: str = "",
    filename: str = "",
    verifier=None,
) -> Decision:
    if actor != "board":
        return Decision("refused", "owner_must_see")
    if signature == "":
        return Decision("refused", "unsigned")
    if verifier is None:
        return Decision("refused", "signature_not_checked")
    line = checksum_line(checksum, filename)
    if line is None:
        return Decision("refused", "checksum_missing")
    try:
        ok = verifier(line, signature)
    except Exception:
        return Decision("refused", "signature_not_checked")
    if ok is not True:
        return Decision("refused", "signature_rejected")
    return Decision("refused", "checked_not_applied")


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
