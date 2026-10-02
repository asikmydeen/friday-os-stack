"""Image Qdrant bootstrap. These tests do not open Qdrant."""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from image import qdrant_bootstrap
from image.qdrant_bootstrap import SMOKE_COLLECTION, SMOKE_ID
from memoryd.index import COLLECTIONS


class ImageBootstrapTests(unittest.TestCase):
    def test_an_empty_key_exits_before_a_request(self) -> None:
        with patch.dict("os.environ", {"QDRANT_API_KEY": ""}, clear=False):
            with patch.object(qdrant_bootstrap, "_request") as request:
                with self.assertRaises(SystemExit) as caught:
                    qdrant_bootstrap.main()
        self.assertEqual(str(caught.exception), "secrets")
        request.assert_not_called()

    def test_the_six_collections_are_indexed_and_points_stay(self) -> None:
        calls = []

        def request(base, key, method, path, body):
            calls.append((method, path, body, key))
            if method == "GET":
                return 200, {
                    "result": {
                        "points_count": 2,
                        "config": {"params": {"vectors": {"size": 768, "distance": "Cosine"}}},
                    }
                }
            return 200, {}

        with patch.object(qdrant_bootstrap, "_request", request):
            for name in COLLECTIONS:
                qdrant_bootstrap._ensure("http://qdrant:6333", "key", name)
        names = {path.split("/")[2] for _method, path, _body, _key in calls if path.startswith("/collections/")}
        self.assertEqual(names, set(COLLECTIONS))
        indexes = [body["field_name"] for method, path, body, _key in calls if path.endswith("/index")]
        self.assertEqual(indexes, ["owner_id", "owner_kind", "topic", "source"] * len(COLLECTIONS))
        self.assertTrue(all("points" not in path for _method, path, _body, _key in calls))
        self.assertTrue(all(key == "key" for _method, _path, _body, key in calls))
        self.assertNotIn("family_shared", names)

    def test_a_wrong_size_stays_a_collection_error(self) -> None:
        calls = []

        def request(base, key, method, path, body):
            calls.append(method)
            return 200, {
                "result": {"config": {"params": {"vectors": {"size": 3, "distance": "Cosine"}}}}
            }

        with patch.object(qdrant_bootstrap, "_request", request):
            with self.assertRaises(OSError) as caught:
                qdrant_bootstrap._ensure("http://qdrant:6333", "key", "knowledge")
        self.assertEqual(str(caught.exception), "collections")
        self.assertEqual(calls, ["GET"])

        calls.clear()

        def distance(base, key, method, path, body):
            calls.append(method)
            return 200, {
                "result": {"config": {"params": {"vectors": {"size": 768, "distance": "Dot"}}}}
            }

        with patch.object(qdrant_bootstrap, "_request", distance):
            with self.assertRaises(OSError) as caught:
                qdrant_bootstrap._ensure("http://qdrant:6333", "key", "knowledge")
        self.assertEqual(str(caught.exception), "collections")
        self.assertEqual(calls, ["GET"])

    def test_a_rejected_create_stays_rejected(self) -> None:
        def request(base, key, method, path, body):
            if method == "GET":
                return 404, None
            return 500, None

        with patch.object(qdrant_bootstrap, "_request", request):
            with self.assertRaises(OSError) as caught:
                qdrant_bootstrap._ensure("http://qdrant:6333", "key", "knowledge")
        self.assertEqual(str(caught.exception), "rejected")

    def test_a_zero_count_after_the_smoke_id_is_deleted_is_empty(self) -> None:
        box = _Box({name: 0 for name in COLLECTIONS})
        with patch.object(qdrant_bootstrap, "_request", box.request):
            result = qdrant_bootstrap._smoke(
                "http://qdrant:6333",
                "key",
                lambda: {"model": "nomic-embed-text", "embeddings": [[0] * 768]},
                pause=lambda _seconds: None,
                attempts=2,
            )
        self.assertTrue(result.empty)
        self.assertEqual(dict(result.counts), {name: 0 for name in COLLECTIONS})
        self.assertEqual(box.deleted, [[SMOKE_ID], [SMOKE_ID]])
        self.assertNotIn(SMOKE_ID, box.points)
        self.assertEqual(box.payload["text"], "bootstrap ok")
        self.assertEqual(box.payload["title"], "bootstrap ok")
        self.assertNotIn("api-key", box.payload)
        self.assertEqual(box.filters, [SMOKE_ID])

    def test_a_kept_point_is_not_called_empty_and_is_not_deleted(self) -> None:
        box = _Box({name: 0 for name in COLLECTIONS})
        box.counts["friday_profile"] = 2
        with patch.object(qdrant_bootstrap, "_request", box.request):
            result = qdrant_bootstrap._smoke(
                "http://qdrant:6333",
                "key",
                lambda: {"model": "nomic-embed-text:latest", "embeddings": [[0.0] * 768]},
                pause=lambda _seconds: None,
            )
        self.assertFalse(result.empty)
        self.assertEqual(dict(result.counts)["friday_profile"], 2)
        self.assertEqual(box.deleted, [[SMOKE_ID], [SMOKE_ID]])

    def test_a_low_score_deletes_the_smoke_id_and_does_not_say_empty(self) -> None:
        box = _Box({name: 0 for name in COLLECTIONS}, score=0.2)
        with patch.object(qdrant_bootstrap, "_request", box.request):
            with self.assertRaises(OSError) as caught:
                qdrant_bootstrap._smoke(
                    "http://qdrant:6333",
                    "key",
                    lambda: {"model": "nomic-embed-text", "embeddings": [[0] * 768]},
                    pause=lambda _seconds: None,
                )
        self.assertEqual(str(caught.exception), "smoke_point")
        self.assertNotIn(SMOKE_ID, box.points)
        self.assertGreaterEqual(len(box.deleted), 2)

    def test_a_short_vector_or_another_model_writes_nothing(self) -> None:
        box = _Box({name: 0 for name in COLLECTIONS})
        with patch.object(qdrant_bootstrap, "_request", box.request):
            with self.assertRaises(OSError) as caught:
                qdrant_bootstrap._smoke(
                    "http://qdrant:6333",
                    "key",
                    lambda: {"model": "other-embed", "embeddings": [[0] * 768]},
                    pause=lambda _seconds: None,
                )
            self.assertEqual(str(caught.exception), "embed_model")
            with self.assertRaises(OSError) as caught:
                qdrant_bootstrap._smoke(
                    "http://qdrant:6333",
                    "key",
                    lambda: {"model": "nomic-embed-text", "embeddings": [[0, 1, 2]]},
                    pause=lambda _seconds: None,
                )
        self.assertEqual(str(caught.exception), "embed_dimensions")
        self.assertEqual(box.upserts, [])
        self.assertEqual(box.deleted, [])

    def test_a_count_that_fell_is_not_empty(self) -> None:
        box = _Box({name: 0 for name in COLLECTIONS}, drop=1)
        box.counts[SMOKE_COLLECTION] = 3
        with patch.object(qdrant_bootstrap, "_request", box.request):
            with self.assertRaises(OSError) as caught:
                qdrant_bootstrap._smoke(
                    "http://qdrant:6333",
                    "key",
                    lambda: {"model": "nomic-embed-text", "embeddings": [[1] * 768]},
                    pause=lambda _seconds: None,
                    attempts=2,
                )
        self.assertEqual(str(caught.exception), "smoke_left")

    def test_main_prints_empty_without_opening_a_socket(self) -> None:
        box = _Box({name: 0 for name in COLLECTIONS})
        stdout = io.StringIO()
        with patch.dict("os.environ", {"QDRANT_API_KEY": "key"}, clear=False):
            with patch.object(qdrant_bootstrap, "_request", box.request):
                with patch.object(
                    qdrant_bootstrap,
                    "_ollama",
                    lambda: {"model": "nomic-embed-text", "embeddings": [[0] * 768]},
                ):
                    with redirect_stdout(stdout):
                        qdrant_bootstrap.main()
        self.assertIn("notes empty", stdout.getvalue().splitlines())
        self.assertNotIn(SMOKE_ID, box.points)
        self.assertNotIn("key", stdout.getvalue())


class _Box:
    def __init__(self, counts: dict[str, int], score: float = 1.0, drop: int = 0) -> None:
        self.counts = dict(counts)
        self.score = score
        self.drop = drop
        self.points: dict[str, dict] = {}
        self.deleted: list[list] = []
        self.upserts: list[dict] = []
        self.filters: list[str] = []
        self.payload: dict = {}
        self._dropped = False

    def request(self, base, key, method, path, body):
        self.assert_key(key)
        if method == "GET" and path.startswith("/collections/"):
            name = path.split("/")[2]
            extra = 1 if name == SMOKE_COLLECTION and SMOKE_ID in self.points else 0
            dropped = self.drop if self._dropped and name == SMOKE_COLLECTION else 0
            return 200, {
                "result": {
                    "points_count": self.counts.get(name, 0) + extra - dropped,
                    "config": {"params": {"vectors": {"size": 768, "distance": "Cosine"}}},
                    "payload_schema": {
                        "owner_id": {},
                        "owner_kind": {},
                        "topic": {},
                        "source": {},
                    },
                }
            }
        if method == "POST" and "/points/delete" in path:
            had = SMOKE_ID in self.points
            self.deleted.append(list(body["points"]))
            for ident in body["points"]:
                self.points.pop(ident, None)
            if self.drop and had:
                self._dropped = True
            return 200, {}
        if method == "PUT" and "/points" in path:
            point = body["points"][0]
            self.upserts.append(point)
            self.payload = dict(point["payload"])
            self.points[point["id"]] = point
            return 200, {}
        if method == "POST" and "/points/query" in path:
            self.filters.append(body["filter"]["must"][0]["has_id"][0])
            if SMOKE_ID not in self.points:
                return 200, {"result": {"points": []}}
            return 200, {"result": {"points": [{"id": SMOKE_ID, "score": self.score}]}}
        if method == "POST" and path.endswith("/points"):
            found = [self.points[ident] for ident in body["ids"] if ident in self.points]
            return 200, {"result": found}
        return 500, None

    def assert_key(self, key: str) -> None:
        if key != "key":
            raise AssertionError(key)


if __name__ == "__main__":
    unittest.main()
