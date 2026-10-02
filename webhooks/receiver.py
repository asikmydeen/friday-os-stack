"""Accept an app webhook and keep its body out of the prompt.

Routes match the wires: Jellyfin posts /media, Radarr and Sonarr post
/arr. The header Friday-Webhook is the secret generated for that one
app. A retry of the same body returns the same row.

speak() returns the sentence for the event type and does not read the
body. announcements() returns those sentences and does not copy the
body. This module does not call the executor and does not write an
approval.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import threading
import uuid
from dataclasses import dataclass
from typing import Mapping

from webhooks.queue import QueueError

HEADER = "Friday-Webhook"
MAX_BODY = 256 * 1024

ROUTES = {
    "media": frozenset({"jellyfin"}),
    "arr": frozenset({"radarr", "sonarr"}),
}

# eventType / NotificationType values that select a sentence.
# Anything else, including text from the body, stays "other".
ARR_TYPES = {
    "Grab": "grab",
    "Health": "health",
    "HealthRestored": "health",
    "ManualInteractionRequired": "failure",
    "DownloadFailed": "failure",
    "GrabFailed": "failure",
}
MEDIA_TYPES = {
    "Health": "health",
    "HealthChange": "health",
}

SENTENCES = {
    "grab": "A download was grabbed.",
    "failure": "A download failed.",
    "health": "An app health state changed.",
    "other": "An app sent an event.",
}


@dataclass(frozen=True)
class Receipt:
    outcome: str
    reason: str
    event_id: str | None = None
    event_type: str | None = None
    announcement: str | None = None


class MemoryStore:
    def __init__(self) -> None:
        self.events: dict[str, dict] = {}
        self.by_key: dict[tuple[str, str], str] = {}
        self._lock = threading.Lock()

    def insert_event(
        self,
        source: str,
        route: str,
        event_type: str,
        announcement: str,
        body_raw: str,
        digest: str,
    ) -> tuple[str, bool]:
        with self._lock:
            existing = self.by_key.get((source, digest))
            if existing is not None:
                return existing, False
            event_id = str(uuid.uuid4())
            self.events[event_id] = {
                "id": event_id,
                "source": source,
                "route": route,
                "event_type": event_type,
                "announcement": announcement,
                "body_raw": body_raw,
                "body_sha256": digest,
            }
            self.by_key[(source, digest)] = event_id
            return event_id, True

    def list_announcements(self) -> list[dict]:
        with self._lock:
            rows = list(self.events.values())
        rows.reverse()
        return rows


def announcements(store) -> list[dict]:
    """Newest sentences only. The body stays on the row and is not copied."""
    method = getattr(store, "list_announcements", None)
    if method is None:
        return []
    found = method()
    return _public(found)


def _public(rows: object) -> list[dict]:
    kept: list[dict] = []
    if not isinstance(rows, (list, tuple)):
        return kept
    for row in rows:
        if not isinstance(row, dict):
            continue
        event_type = row.get("event_type")
        source = row.get("source")
        sentence = SENTENCES.get(event_type) if isinstance(event_type, str) else None
        if sentence is None or source not in {"jellyfin", "radarr", "sonarr"}:
            continue
        kept.append({"source": source, "event_type": event_type, "announcement": sentence})
        if len(kept) == 8:
            break
    return kept


def receive(
    store,
    *,
    method: str,
    route: str,
    header: str | None,
    body: bytes | str,
    secrets: Mapping[str, str],
) -> Receipt:
    if method.upper() != "POST":
        return Receipt("refused", "method_refused")
    allowed = ROUTES.get(route)
    if allowed is None:
        return Receipt("refused", "unknown_route")
    raw = body.encode("utf-8") if isinstance(body, str) else bytes(body)
    if len(raw) > MAX_BODY:
        return Receipt("refused", "body_too_large")
    source = _match_source(route, header, secrets)
    if source is None:
        return Receipt("refused", "header_rejected")
    if source == "*":
        return Receipt("refused", "ambiguous_secret")
    event_type = _classify(route, raw)
    announcement = SENTENCES[event_type]
    digest = hashlib.sha256(source.encode("utf-8") + b"\n" + raw).hexdigest()
    try:
        event_id, created = store.insert_event(
            source,
            route,
            event_type,
            announcement,
            raw.decode("utf-8", errors="replace"),
            digest,
        )
    except QueueError as exc:
        return Receipt("refused", exc.reason)
    if not created:
        return Receipt("duplicate", "already_stored", event_id=event_id, event_type=event_type)
    return Receipt(
        "stored",
        "stored",
        event_id=event_id,
        event_type=event_type,
        announcement=announcement,
    )


def speak(event: Mapping) -> str | None:
    """The only text a webhook may contribute to a prompt."""
    return SENTENCES.get(str(event.get("event_type")))


def _match_source(route: str, header: str | None, secrets: Mapping[str, str]) -> str | None:
    if not isinstance(header, str) or header == "":
        return None
    matches = []
    for source in ROUTES[route]:
        secret = secrets.get(source, "")
        if not isinstance(secret, str) or secret == "":
            continue
        if _same(header, secret):
            matches.append(source)
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        return "*"
    return None


def _same(header: str, secret: str) -> bool:
    try:
        return hmac.compare_digest(header, secret)
    except (TypeError, ValueError):
        return False


def _classify(route: str, raw: bytes) -> str:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return "other"
    if not isinstance(payload, dict):
        return "other"
    if route == "arr":
        name = payload.get("eventType")
        table = ARR_TYPES
    else:
        name = payload.get("NotificationType")
        if not isinstance(name, str):
            name = payload.get("event")
        table = MEDIA_TYPES
    if not isinstance(name, str):
        return "other"
    return table.get(name, "other")
