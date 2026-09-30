"""Create the six empty Qdrant collections. The key stays in the environment."""

from __future__ import annotations

import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from memoryd.index import COLLECTIONS, VECTOR_SIZE
from memoryd.qdrant import vector_params


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
        except OSError as exc:
            last = str(exc) or "unreachable"
            time.sleep(2)
            continue
        print("collections ready")
        return
    raise SystemExit(last)


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
    status, payload = _request(base, key, "GET", f"/collections/{name}", None)
    if status == 200 and isinstance(payload, dict):
        size, distance = vector_params(payload)
        if size != VECTOR_SIZE or distance != "Cosine":
            raise OSError("collections")
        return
    if status != 404:
        raise OSError("rejected")
    status, _payload = _request(
        base,
        key,
        "PUT",
        f"/collections/{name}",
        {"vectors": {"size": VECTOR_SIZE, "distance": "Cosine", "on_disk": True}},
    )
    if status != 200:
        raise OSError("rejected")


if __name__ == "__main__":
    main()
