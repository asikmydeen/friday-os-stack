"""Qdrant calls for the memory service. The API key stays in this process.

qdrant_store is refused. A point is written only by the index worker,
after memory_save has accepted the note. Ensuring a collection requests
the four keyword indexes and does not delete a point.
"""

from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from memoryd.index import COLLECTIONS, VECTOR_SIZE
from memoryd.store import Decision

PAYLOAD_INDEXES = ("owner_id", "owner_kind", "topic", "source")


def qdrant_store(*_args, **_kwargs) -> Decision:
    """Refuse a direct write. The caller does not name a collection that was stored."""
    return Decision("refused", "use_memory_save")


def vector_params(payload: dict) -> tuple[int | None, str | None]:
    params = (
        payload.get("result", {})
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


def missing_indexes(payload: object) -> tuple[str, ...]:
    """Keyword indexes the collection info does not already list.

    Only the four names. member_key and agent_id are not among them.
    """
    schema: dict = {}
    if isinstance(payload, dict):
        result = payload.get("result")
        if isinstance(result, dict) and isinstance(result.get("payload_schema"), dict):
            schema = result["payload_schema"]
    return tuple(field for field in PAYLOAD_INDEXES if field not in schema)


def ensure_collection(name: str, transport) -> None:
    """Create one of the six collections, then any missing keyword index.

    An existing collection is left in place, including its points. A
    missing index is still requested. A size other than 768, or a
    distance other than Cosine, is refused and nothing is written.
    """
    if name not in COLLECTIONS:
        raise OSError("index_refused")
    status, payload = transport("GET", f"/collections/{name}", None)
    if status == 200 and isinstance(payload, dict):
        size, distance = vector_params(payload)
        if size != VECTOR_SIZE or distance != "Cosine":
            raise OSError("index_refused")
        _put_indexes(name, transport, missing_indexes(payload))
        return
    if status != 404:
        raise OSError("index_not_ready")
    status, _payload = transport(
        "PUT",
        f"/collections/{name}",
        {"vectors": {"size": VECTOR_SIZE, "distance": "Cosine", "on_disk": True}},
    )
    if status != 200:
        raise OSError("index_not_ready")
    _put_indexes(name, transport, PAYLOAD_INDEXES)


def _put_indexes(name: str, transport, fields: tuple[str, ...]) -> None:
    for field in fields:
        status, _payload = transport(
            "PUT",
            f"/collections/{name}/index",
            {"field_name": field, "field_schema": "keyword"},
        )
        if status != 200:
            raise OSError("index_not_ready")


class Qdrant:
    def __init__(self, base: str, api_key: str, transport=None) -> None:
        self.base = base.rstrip("/")
        self.api_key = api_key
        self._transport = transport or self._http

    def _http(self, method: str, path: str, body: dict | None):
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["api-key"] = self.api_key
        data = None if body is None else json.dumps(body).encode()
        request = Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=20) as response:
                raw = response.read()
                status = response.status
        except HTTPError as exc:
            raw = exc.read()
            status = exc.code
        except URLError as exc:
            raise OSError("index_not_ready") from exc
        if not raw:
            return status, None
        try:
            return status, json.loads(raw)
        except json.JSONDecodeError:
            return status, None

    def ensure(self, name: str) -> None:
        ensure_collection(name, self._transport)

    def upsert(self, name: str, point_id: str, vector: list[float], payload: dict) -> None:
        status, _payload = self._transport(
            "PUT",
            f"/collections/{name}/points?wait=true",
            {"points": [{"id": point_id, "vector": vector, "payload": payload}]},
        )
        if status != 200:
            raise OSError("index_not_ready")

    def delete(self, name: str, point_id: str) -> None:
        status, _payload = self._transport(
            "POST",
            f"/collections/{name}/points/delete?wait=true",
            {"points": [point_id]},
        )
        if status not in (200, 404):
            raise OSError("index_not_ready")

    def delete_revision(self, name: str, point_id: str, revision: int) -> None:
        status, _payload = self._transport(
            "POST",
            f"/collections/{name}/points/delete?wait=true",
            {
                "filter": {
                    "must": [
                        {"has_id": [point_id]},
                        {"key": "revision", "match": {"value": revision}},
                    ]
                }
            },
        )
        if status != 200:
            raise OSError("index_not_ready")

    def query(self, name: str, vector: list[float], owner_id: str, owner_kind: str, limit: int) -> list[dict]:
        body = {
            "query": vector,
            "limit": limit,
            "with_payload": True,
            "filter": {
                "must": [
                    {"key": "owner_id", "match": {"value": owner_id}},
                    {"key": "owner_kind", "match": {"value": owner_kind}},
                ]
            },
        }
        status, payload = self._transport("POST", f"/collections/{name}/points/query", body)
        if status == 404:
            raise OSError("missing_collection")
        points = _points(status, payload)
        if points is None:
            legacy = {
                "vector": vector,
                "limit": limit,
                "with_payload": True,
                "filter": body["filter"],
            }
            status, payload = self._transport("POST", f"/collections/{name}/points/search", legacy)
            if status == 404:
                raise OSError("missing_collection")
            points = _points(status, payload)
        if points is None:
            raise OSError("index_not_ready")
        return points


def _points(status: int, payload) -> list[dict] | None:
    if status != 200 or not isinstance(payload, dict):
        return None
    result = payload.get("result")
    if isinstance(result, dict) and isinstance(result.get("points"), list):
        return result["points"]
    if isinstance(result, list):
        return result
    return None
