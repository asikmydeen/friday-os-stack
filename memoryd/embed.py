"""Local embed call. A vector that is not 768 long is refused."""

from __future__ import annotations

import json
from urllib.request import Request, urlopen

from memoryd.index import VECTOR_SIZE

MODEL = "nomic-embed-text"


def ollama_embed(base: str):
    def embed(text: str) -> list[float]:
        if not base:
            raise OSError("embed_not_ready")
        url = base.rstrip("/") + "/api/embeddings"
        body = json.dumps({"model": MODEL, "prompt": text}, separators=(",", ":")).encode()
        request = Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urlopen(request, timeout=30) as response:
                raw = response.read()
        except OSError as exc:
            raise OSError("embed_not_ready") from exc
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise OSError("embed_not_ready") from exc
        vector = payload.get("embedding") if isinstance(payload, dict) else None
        if not isinstance(vector, list):
            raise OSError("embed_not_ready")
        if len(vector) != VECTOR_SIZE:
            raise OSError("embed_dimensions")
        return [float(item) for item in vector]

    return embed
