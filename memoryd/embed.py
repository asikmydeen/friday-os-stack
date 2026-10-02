"""Local embed call. A vector that is not 768 long is refused.

The request names nomic-embed-text. A reply that names a different
model is refused, including when that vector is 768 long. The older
embeddings endpoint often omits the model id. That reply is still
accepted when the length is 768. This module does not change the pin.
"""

from __future__ import annotations

import json
import re
from urllib.request import Request, urlopen

from memoryd.index import VECTOR_SIZE

MODEL = "nomic-embed-text"
_TAG = re.compile(r"[A-Za-z0-9._-]{1,64}\Z")


def pinned_model(model: object) -> bool:
    if not isinstance(model, str):
        return False
    if model == MODEL:
        return True
    prefix = MODEL + ":"
    if not model.startswith(prefix):
        return False
    return _TAG.fullmatch(model[len(prefix) :]) is not None


def vector_from_payload(payload: object) -> list[float]:
    """Return the 768 numbers, or raise OSError. A named other model is refused."""
    if not isinstance(payload, dict):
        raise OSError("embed_not_ready")
    reported = payload.get("model")
    if reported is not None and not pinned_model(reported):
        raise OSError("embed_model")
    vector = payload.get("embedding")
    if not isinstance(vector, list):
        raise OSError("embed_not_ready")
    if (
        len(vector) != VECTOR_SIZE
        or any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in vector)
    ):
        raise OSError("embed_dimensions")
    return [float(item) for item in vector]


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
        return vector_from_payload(payload)

    return embed
