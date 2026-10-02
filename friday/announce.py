"""Fixed sentences from the webhook receiver.

The type picks the sentence. A stored sentence that was rewritten is
not repeated. The raw body is not copied. This module does not post,
does not call the executor, and does not open a socket.
"""

from __future__ import annotations

from urllib.parse import unquote_plus

from memoryd.store import credential_shape

CAP = 8
SOURCES = frozenset({"jellyfin", "radarr", "sonarr"})
SENTENCES = {
    "grab": "A download was grabbed.",
    "failure": "A download failed.",
    "health": "An app health state changed.",
    "other": "An app sent an event.",
}


def spoken(rows: object) -> list[dict]:
    """At most eight sentences. Anything else is dropped, not corrected into the reply."""
    kept: list[dict] = []
    if not isinstance(rows, (list, tuple)):
        return kept
    for row in rows:
        if not isinstance(row, dict):
            continue
        event_type = row.get("event_type")
        source = row.get("source")
        sentence = SENTENCES.get(event_type) if isinstance(event_type, str) else None
        if sentence is None or source not in SOURCES:
            continue
        if _secret(source) or _secret(event_type) or _secret(sentence):
            continue
        kept.append({"source": source, "event_type": event_type, "announcement": sentence})
        if len(kept) == CAP:
            break
    return kept


def _secret(text: str) -> bool:
    seen = text
    for _ in range(3):
        if credential_shape(" ".join(seen.split())):
            return True
        decoded = unquote_plus(seen)
        if decoded == seen:
            return False
        seen = decoded
    return credential_shape(" ".join(seen.split()))
