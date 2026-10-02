"""Create the six Qdrant collections, then prove one smoke point.

The key stays in the environment. An existing collection is left in
place, including its points. A missing keyword index is still requested.
The only point this script deletes is the fixed smoke id. It does not
write Postgres.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from memoryd.index import COLLECTIONS
from memoryd.qdrant import ensure_collection

PINNED_MODEL = "nomic-embed-text"
PROBE_TEXT = "bootstrap ok"
SMOKE_ID = "b0075700-0000-4000-8000-000000000001"
SMOKE_COLLECTION = "friday_episodes"
SCORE_MIN = 0.9
_TAG = re.compile(r"[A-Za-z0-9._-]{1,64}\Z")
_RETRY = frozenset({"unreachable", "rejected", "embed_not_ready"})


def plain_env(value: str) -> str:
    """docker run --env-file keeps the quotes Compose removes."""
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    return text


def main() -> None:
    base = plain_env(os.environ.get("QDRANT_URL", "http://qdrant:6333")).rstrip("/")
    key = plain_env(os.environ.get("QDRANT_API_KEY", ""))
    if not key:
        raise SystemExit("secrets")
    deadline = time.time() + 180
    last = "unreachable"
    while time.time() < deadline:
        try:
            for name in COLLECTIONS:
                _ensure(base, key, name)
            result = _smoke(base, key, _ollama)
        except OSError as exc:
            last = str(exc) or "unreachable"
            if last not in _RETRY:
                raise SystemExit(last) from None
            time.sleep(2)
            continue
        for name, count in result.counts:
            print(f"{name} {count}")
        print("notes empty" if result.empty else "notes kept")
        return
    raise SystemExit(last)


@dataclass(frozen=True)
class Smoke:
    counts: tuple[tuple[str, int], ...]
    empty: bool


def _smoke(base: str, key: str, embed, pause=time.sleep, attempts: int = 8) -> Smoke:
    """Write the smoke id, find it, and delete only that id."""
    vector = _vector(embed())
    _delete_smoke(base, key)
    baseline = _count(base, key, SMOKE_COLLECTION)
    _upsert(base, key, vector)
    try:
        _require_hit(base, key, vector)
    except OSError:
        _delete_smoke(base, key)
        raise
    _delete_smoke(base, key)
    gone = False
    for _ in range(attempts):
        count = _count(base, key, SMOKE_COLLECTION)
        if not _present(base, key) and count >= baseline:
            gone = True
            break
        pause(0.2)
    if not gone:
        raise OSError("smoke_left")
    counts = tuple((name, _count(base, key, name)) for name in COLLECTIONS)
    return Smoke(counts, all(count == 0 for _name, count in counts))


def _upsert(base: str, key: str, vector: list[float]) -> None:
    status, _payload = _request(
        base,
        key,
        "PUT",
        f"/collections/{SMOKE_COLLECTION}/points?wait=true",
        {
            "points": [
                {
                    "id": SMOKE_ID,
                    "vector": vector,
                    "payload": {
                        "text": PROBE_TEXT,
                        "title": PROBE_TEXT,
                        "kind": "episode",
                        "topic": "bootstrap",
                        "source": "bootstrap",
                        "owner_id": "bootstrap",
                        "owner_kind": "person",
                        "memory_id": SMOKE_ID,
                        "revision": 1,
                    },
                }
            ]
        },
    )
    if status != 200:
        raise OSError("smoke_point")


def _require_hit(base: str, key: str, vector: list[float]) -> None:
    if not _stored(base, key):
        raise OSError("smoke_point")
    body = {
        "query": vector,
        "limit": 1,
        "with_payload": False,
        "filter": {"must": [{"has_id": [SMOKE_ID]}]},
    }
    status, payload = _request(
        base,
        key,
        "POST",
        f"/collections/{SMOKE_COLLECTION}/points/query?wait=true",
        body,
    )
    if status == 404:
        status, payload = _request(
            base,
            key,
            "POST",
            f"/collections/{SMOKE_COLLECTION}/points/search?wait=true",
            {
                "vector": vector,
                "limit": 1,
                "with_payload": False,
                "filter": body["filter"],
            },
        )
    if status != 200 or not _scored(payload):
        raise OSError("smoke_point")


def _stored(base: str, key: str) -> bool:
    status, payload = _request(
        base,
        key,
        "POST",
        f"/collections/{SMOKE_COLLECTION}/points",
        {"ids": [SMOKE_ID], "with_payload": True, "with_vector": False},
    )
    if status != 200:
        raise OSError("rejected")
    for hit in _hits(payload):
        if str(hit.get("id")) != SMOKE_ID:
            continue
        body = hit.get("payload")
        if not isinstance(body, dict):
            return False
        return body.get("text") == PROBE_TEXT and body.get("title") == PROBE_TEXT
    return False


def _present(base: str, key: str) -> bool:
    status, payload = _request(
        base,
        key,
        "POST",
        f"/collections/{SMOKE_COLLECTION}/points",
        {"ids": [SMOKE_ID], "with_payload": False, "with_vector": False},
    )
    if status != 200:
        raise OSError("rejected")
    return any(str(hit.get("id")) == SMOKE_ID for hit in _hits(payload))


def _scored(payload: object) -> bool:
    hits = _hits(payload)
    if len(hits) != 1 or str(hits[0].get("id")) != SMOKE_ID:
        return False
    score = hits[0].get("score")
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        return False
    return score >= SCORE_MIN


def _hits(payload: object) -> list:
    if not isinstance(payload, dict):
        return []
    result = payload.get("result")
    if isinstance(result, dict) and isinstance(result.get("points"), list):
        return [hit for hit in result["points"] if isinstance(hit, dict)]
    if isinstance(result, list):
        return [hit for hit in result if isinstance(hit, dict)]
    return []


def _delete_smoke(base: str, key: str) -> None:
    status, _payload = _request(
        base,
        key,
        "POST",
        f"/collections/{SMOKE_COLLECTION}/points/delete?wait=true",
        {"points": [SMOKE_ID]},
    )
    if status not in (200, 404):
        raise OSError("rejected")


def _count(base: str, key: str, name: str) -> int:
    status, payload = _request(base, key, "GET", f"/collections/{name}", None)
    if status != 200 or not isinstance(payload, dict):
        raise OSError("rejected")
    count = (payload.get("result") or {}).get("points_count")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise OSError("rejected")
    return count


def _vector(data: object) -> list[float]:
    if not isinstance(data, dict):
        raise OSError("embed_not_ready")
    if not _pinned_model(data.get("model")):
        raise OSError("embed_model")
    vector = _one_vector(data)
    if vector is None or len(vector) != 768 or not _numbers(vector):
        raise OSError("embed_dimensions")
    return [float(item) for item in vector]


def _pinned_model(model: object) -> bool:
    if not isinstance(model, str):
        return False
    if model == PINNED_MODEL:
        return True
    prefix = PINNED_MODEL + ":"
    if not model.startswith(prefix):
        return False
    return _TAG.fullmatch(model[len(prefix) :]) is not None


def _one_vector(data: dict) -> list | None:
    if "embeddings" in data:
        embeddings = data.get("embeddings")
        if isinstance(embeddings, list) and len(embeddings) == 1 and isinstance(embeddings[0], list):
            return embeddings[0]
        return None
    embedding = data.get("embedding")
    if isinstance(embedding, list):
        return embedding
    return None


def _numbers(vector: list) -> bool:
    return all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in vector)


def _ollama() -> dict:
    base = plain_env(os.environ.get("OLLAMA_URL", "http://ollama:11434")).rstrip("/")
    if not base:
        raise OSError("embed_not_ready")
    request = Request(
        base + "/api/embed",
        data=json.dumps({"model": PINNED_MODEL, "input": PROBE_TEXT}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            raw = response.read()
    except HTTPError as exc:
        raw = exc.read()
    except URLError as exc:
        raise OSError("embed_not_ready") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise OSError("embed_not_ready") from exc
    if not isinstance(data, dict):
        raise OSError("embed_not_ready")
    return data


def _request(base: str, key: str, method: str, path: str, body: dict | None):
    data = None if body is None else json.dumps(body).encode()
    request = Request(
        base + path,
        data=data,
        headers={"Content-Type": "application/json", "api-key": key},
        method=method,
    )
    try:
        with urlopen(request, timeout=10) as response:
            raw = response.read()
            status = response.status
    except HTTPError as exc:
        raw = exc.read()
        status = exc.code
    except URLError as exc:
        raise OSError("unreachable") from exc
    if not raw:
        return status, None
    try:
        return status, json.loads(raw)
    except json.JSONDecodeError:
        return status, None


def _ensure(base: str, key: str, name: str) -> None:
    def transport(method: str, path: str, body: dict | None):
        return _request(base, key, method, path, body)

    try:
        ensure_collection(name, transport)
    except OSError as exc:
        reason = str(exc)
        if reason == "index_refused":
            raise OSError("collections") from None
        if reason == "index_not_ready":
            raise OSError("rejected") from None
        raise


if __name__ == "__main__":
    main()
