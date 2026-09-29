#!/usr/bin/env python3
"""Qdrant and Ollama half of scripts/bootstrap-memory.sh.

Runs inside the compose network. Postgres is applied by the shell between
the "prepare" and "smoke" phases. Talks only to the compose DNS names.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

PINNED_MODEL = "nomic-embed-text"
VECTOR_SIZE = 768
PROBE_TEXT = "bootstrap ok"
SMOKE_ID = "b0075700-0000-4000-8000-000000000001"
SMOKE_COLLECTION = "friday_episodes"
SCORE_THRESHOLD = 0.9

# Created at bootstrap. Role and person collections, family_shared, and
# messages are created later, on purpose, by the paths in docs/memory.md.
COLLECTIONS = (
    "friday_profile",
    "friday_episodes",
    "friday_findings",
    "friday_persona",
    "knowledge",
    "cabinet_working",
)
PAYLOAD_INDEXES = ("owner_id", "owner_kind", "topic", "source")


class BootstrapError(Exception):
    pass


def log(message: str) -> None:
    print(message, file=sys.stderr)


def qdrant_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    key = os.environ.get("QDRANT_API_KEY", "").strip()
    if key:
        headers["api-key"] = key
    return headers


def request(method: str, url: str, body: object | None = None, headers: dict[str, str] | None = None) -> tuple[int, object]:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            raw = response.read()
            status = response.status
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        status = exc.code
    if not raw:
        return status, None
    try:
        return status, json.loads(raw)
    except json.JSONDecodeError:
        return status, raw.decode(errors="replace")


def wait_ready(qdrant: str, ollama: str) -> None:
    deadline = time.time() + 120
    last = "not started"
    while time.time() < deadline:
        q_status, _ = request("GET", f"{qdrant}/readyz")
        o_status, _ = request("GET", f"{ollama}/api/tags")
        if q_status == 200 and o_status == 200:
            return
        last = f"qdrant={q_status} ollama={o_status}"
        time.sleep(2)
    raise BootstrapError(f"Qdrant or Ollama did not become ready ({last})")


def require_pinned_model(ollama: str) -> None:
    status, payload = request("GET", f"{ollama}/api/tags")
    if status != 200 or not isinstance(payload, dict):
        raise BootstrapError(f"Ollama /api/tags returned {status}")
    names = []
    for model in payload.get("models") or []:
        name = str(model.get("name") or model.get("model") or "")
        names.append(name)
        if name == PINNED_MODEL or name.startswith(PINNED_MODEL + ":"):
            return
    raise BootstrapError(
        f"{PINNED_MODEL} is not installed (have: {', '.join(names) or 'none'}). "
        "A different 768-dimension model is refused."
    )


def probe_embedding(ollama: str) -> list[float]:
    status, payload = request(
        "POST",
        f"{ollama}/api/embed",
        {"model": PINNED_MODEL, "input": PROBE_TEXT},
        {"Content-Type": "application/json"},
    )
    vector = None
    if status == 200 and isinstance(payload, dict):
        embeddings = payload.get("embeddings")
        if isinstance(embeddings, list) and embeddings and isinstance(embeddings[0], list):
            vector = embeddings[0]
        elif isinstance(payload.get("embedding"), list):
            vector = payload["embedding"]
    if vector is None:
        # Older Ollama builds expose /api/embeddings.
        status, payload = request(
            "POST",
            f"{ollama}/api/embeddings",
            {"model": PINNED_MODEL, "prompt": PROBE_TEXT},
            {"Content-Type": "application/json"},
        )
        if status == 200 and isinstance(payload, dict) and isinstance(payload.get("embedding"), list):
            vector = payload["embedding"]
    if vector is None:
        raise BootstrapError(f"embed probe failed (status {status})")
    if len(vector) != VECTOR_SIZE:
        raise BootstrapError(
            f"probe embedding length is {len(vector)}, not {VECTOR_SIZE}. "
            "Refusing to create or write collections."
        )
    return [float(item) for item in vector]


def vector_params(collection: dict) -> tuple[int | None, str | None]:
    params = (
        collection.get("result", {})
        .get("config", {})
        .get("params", {})
        .get("vectors")
    )
    if isinstance(params, dict) and "size" in params:
        return params.get("size"), params.get("distance")
    if isinstance(params, dict) and params:
        first = next(iter(params.values()))
        if isinstance(first, dict):
            return first.get("size"), first.get("distance")
    return None, None


def ensure_collection(qdrant: str, name: str) -> None:
    status, payload = request("GET", f"{qdrant}/collections/{name}", headers=qdrant_headers())
    if status == 200 and isinstance(payload, dict):
        size, distance = vector_params(payload)
        if size != VECTOR_SIZE or distance != "Cosine":
            raise BootstrapError(
                f"collection {name} is size={size} distance={distance}. "
                "Leaving it in place. Recreate the Qdrant volume before mixing in a new embed model."
            )
        log(f"collection {name} already exists; left in place")
        return
    if status not in (404,):
        raise BootstrapError(f"could not read collection {name} (status {status})")
    status, payload = request(
        "PUT",
        f"{qdrant}/collections/{name}",
        {"vectors": {"size": VECTOR_SIZE, "distance": "Cosine", "on_disk": True}},
        qdrant_headers(),
    )
    if status not in (200,):
        raise BootstrapError(f"could not create collection {name} (status {status}: {payload})")
    log(f"created collection {name}")


def ensure_indexes(qdrant: str, name: str) -> None:
    status, payload = request("GET", f"{qdrant}/collections/{name}", headers=qdrant_headers())
    if status != 200 or not isinstance(payload, dict):
        raise BootstrapError(f"could not read indexes for {name} (status {status})")
    existing = (payload.get("result") or {}).get("payload_schema") or {}
    for field in PAYLOAD_INDEXES:
        if field in existing:
            continue
        status, body = request(
            "PUT",
            f"{qdrant}/collections/{name}/index",
            {"field_name": field, "field_schema": "keyword"},
            qdrant_headers(),
        )
        if status not in (200,):
            raise BootstrapError(f"could not index {name}.{field} (status {status}: {body})")
        log(f"indexed {name}.{field}")


def point_count(qdrant: str, name: str) -> int:
    status, payload = request("GET", f"{qdrant}/collections/{name}", headers=qdrant_headers())
    if status != 200 or not isinstance(payload, dict):
        raise BootstrapError(f"could not count {name} (status {status})")
    result = payload.get("result") or {}
    count = result.get("points_count")
    if not isinstance(count, int):
        raise BootstrapError(f"collection {name} did not report points_count")
    return count


def delete_smoke(qdrant: str) -> None:
    status, payload = request(
        "POST",
        f"{qdrant}/collections/{SMOKE_COLLECTION}/points/delete?wait=true",
        {"points": [SMOKE_ID]},
        qdrant_headers(),
    )
    if status not in (200,):
        raise BootstrapError(f"could not delete smoke point (status {status}: {payload})")


def search_smoke(qdrant: str, vector: list[float]) -> tuple[str | None, float | None]:
    query_body = {"query": vector, "limit": 1, "with_payload": True}
    status, payload = request(
        "POST",
        f"{qdrant}/collections/{SMOKE_COLLECTION}/points/query",
        query_body,
        qdrant_headers(),
    )
    points = None
    if status == 200 and isinstance(payload, dict):
        result = payload.get("result")
        if isinstance(result, dict):
            points = result.get("points")
        elif isinstance(result, list):
            points = result
    if status == 404:
        status, payload = request(
            "POST",
            f"{qdrant}/collections/{SMOKE_COLLECTION}/points/search",
            {"vector": vector, "limit": 1, "with_payload": True},
            qdrant_headers(),
        )
        if status == 200 and isinstance(payload, dict) and isinstance(payload.get("result"), list):
            points = payload["result"]
    if points is None:
        raise BootstrapError(f"smoke search failed (status {status}: {payload})")
    if not points:
        return None, None
    hit = points[0]
    return str(hit.get("id")), hit.get("score")


def prepare(qdrant: str, ollama: str) -> None:
    wait_ready(qdrant, ollama)
    require_pinned_model(ollama)
    # Dimension check happens before any collection is created, so a wrong
    # model cannot land in an empty store.
    probe_embedding(ollama)
    for name in COLLECTIONS:
        ensure_collection(qdrant, name)
        ensure_indexes(qdrant, name)
    log("prepare ok")


def smoke(qdrant: str, ollama: str) -> None:
    wait_ready(qdrant, ollama)
    vector = probe_embedding(ollama)
    for name in COLLECTIONS:
        ensure_collection(qdrant, name)
    before = point_count(qdrant, SMOKE_COLLECTION)
    delete_smoke(qdrant)
    baseline = point_count(qdrant, SMOKE_COLLECTION)
    status, payload = request(
        "PUT",
        f"{qdrant}/collections/{SMOKE_COLLECTION}/points?wait=true",
        {
            "points": [
                {
                    "id": SMOKE_ID,
                    "vector": vector,
                    "payload": {
                        "text": PROBE_TEXT,
                        "title": "bootstrap ok",
                        "kind": "episode",
                        "topic": "bootstrap",
                        "source": "bootstrap",
                        "owner_id": "bootstrap",
                        "owner_kind": "person",
                        "memory_id": SMOKE_ID,
                        "revision": 1,
                        "ts": int(time.time()),
                    },
                }
            ]
        },
        qdrant_headers(),
    )
    if status not in (200,):
        raise BootstrapError(f"smoke upsert failed (status {status}: {payload})")
    found_id, score = search_smoke(qdrant, vector)
    if found_id != SMOKE_ID or not isinstance(score, (int, float)) or score < SCORE_THRESHOLD:
        delete_smoke(qdrant)
        raise BootstrapError(f"smoke search returned id={found_id} score={score}")
    delete_smoke(qdrant)
    # A second search must not bring the smoke point back. Count can lag
    # the delete by a moment even when wait=true is set.
    found_id = SMOKE_ID
    after = baseline + 1
    for _ in range(10):
        found_id, _score = search_smoke(qdrant, vector)
        after = point_count(qdrant, SMOKE_COLLECTION)
        if found_id != SMOKE_ID and after == baseline:
            break
        time.sleep(0.5)
    if found_id == SMOKE_ID:
        raise BootstrapError("smoke point was still the top hit after delete")
    if after != baseline:
        raise BootstrapError(
            f"{SMOKE_COLLECTION} count went from {before} to {after}; smoke point was not removed"
        )
    for name in COLLECTIONS:
        print(f"{name} {point_count(qdrant, name)}")


def main() -> int:
    phase = sys.argv[1] if len(sys.argv) > 1 else ""
    qdrant = os.environ.get("QDRANT_URL", "http://qdrant:6333").rstrip("/")
    ollama = os.environ.get("OLLAMA_URL", "http://ollama:11434").rstrip("/")
    try:
        if phase == "prepare":
            prepare(qdrant, ollama)
        elif phase == "smoke":
            smoke(qdrant, ollama)
        else:
            raise BootstrapError("usage: bootstrap_memory.py prepare|smoke")
    except BootstrapError as exc:
        log(f"bootstrap-memory: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
