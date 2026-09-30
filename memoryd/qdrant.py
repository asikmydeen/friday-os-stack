"""Qdrant calls for the memory service. The API key stays in this process."""

from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from memoryd.index import COLLECTIONS, VECTOR_SIZE


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
        if name not in COLLECTIONS:
            raise OSError("index_refused")
        status, payload = self._transport("GET", f"/collections/{name}", None)
        if status == 200 and isinstance(payload, dict):
            size, distance = vector_params(payload)
            if size != VECTOR_SIZE or distance != "Cosine":
                raise OSError("index_refused")
            return
        if status != 404:
            raise OSError("index_not_ready")
        status, _payload = self._transport(
            "PUT",
            f"/collections/{name}",
            {"vectors": {"size": VECTOR_SIZE, "distance": "Cosine", "on_disk": True}},
        )
        if status != 200:
            raise OSError("index_not_ready")
        for field in ("owner_id", "owner_kind", "topic", "source"):
            status, _payload = self._transport(
                "PUT",
                f"/collections/{name}/index",
                {"field_name": field, "field_schema": "keyword"},
            )
            if status != 200:
                raise OSError("index_not_ready")

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
