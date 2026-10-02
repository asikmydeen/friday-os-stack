"""Index protocol. These tests do not open Postgres or Qdrant."""

from __future__ import annotations

import unittest

from memoryd.index import Claim, Memory, collection_name, drain, index_once, search
from memoryd.qdrant import PAYLOAD_INDEXES, Qdrant, ensure_collection


class _Tx:
    def __init__(self, claims, rows) -> None:
        self.claims = list(claims)
        self.rows = rows
        self.finished: list[int] = []
        self.indexed: list[tuple[str, int]] = []

    def claim(self, worker: str):
        self.worker = worker
        if not self.claims:
            return None
        return self.claims.pop(0)

    def fetch(self, memory_id: str):
        return self.rows.get(memory_id)

    def finish(self, queue_id: int) -> None:
        self.finished.append(queue_id)

    def mark_indexed(self, memory_id: str, revision: int) -> None:
        self.indexed.append((memory_id, revision))


class _Store:
    def __init__(self, tx: _Tx) -> None:
        self.tx = tx
        self.rollbacks = 0

    def transaction(self):
        store = self

        class _Bound:
            def __enter__(self):
                return store.tx

            def __exit__(self, exc_type, exc, tb):
                if exc_type is not None:
                    store.rollbacks += 1
                return False

        return _Bound()


class _Points:
    def __init__(self) -> None:
        self.upserts = []
        self.deletes = []
        self.points: dict[tuple[str, str], dict] = {}
        self.on_upsert = None

    def ensure(self, name: str) -> None:
        return None

    def upsert(self, name, point_id, vector, payload) -> None:
        self.points[(name, point_id)] = dict(payload)
        self.upserts.append((name, point_id, payload["owner_kind"]))
        if self.on_upsert is not None:
            self.on_upsert()

    def delete(self, name, point_id) -> None:
        self.points.pop((name, point_id), None)
        self.deletes.append((name, point_id))

    def delete_revision(self, name, point_id, revision: int) -> None:
        payload = self.points.get((name, point_id))
        if payload is None or payload.get("revision") != revision:
            return
        self.delete(name, point_id)


def _memory(
    deleted: bool = False,
    revision: int = 1,
    kind: str = "person",
    content: str = "lighthouse",
) -> Memory:
    return Memory(
        id="11111111-1111-4111-8111-111111111111",
        owner_id="owner-1",
        owner_kind=kind,
        revision=revision,
        content=content,
        visibility="master",
        category="note",
        deleted=deleted,
    )


class IndexTests(unittest.TestCase):
    def test_a_role_does_not_share_the_person_collection(self) -> None:
        self.assertEqual(collection_name("person", "note"), "friday_profile")
        self.assertEqual(collection_name("role", "note"), "cabinet_working")
        self.assertEqual(collection_name("person", "knowledge"), "knowledge")

    def test_a_tombstone_deletes_the_point_and_does_not_embed(self) -> None:
        row = _memory(deleted=True)
        tx = _Tx([Claim(1, row.id, 1, True)], {row.id: row})
        points = _Points()

        def embed(_text):
            raise AssertionError("embed")

        reason = index_once(_Store(tx), points, embed)
        self.assertEqual(reason, "deleted")
        self.assertEqual(points.deletes, [("friday_profile", row.id)])
        self.assertEqual(tx.finished, [1])
        self.assertEqual(points.upserts, [])

    def test_a_short_vector_rolls_back_the_claim(self) -> None:
        row = _memory()
        tx = _Tx([Claim(7, row.id, 1, False)], {row.id: row})
        store = _Store(tx)
        points = _Points()
        reason = index_once(store, points, lambda _text: [0.0])
        self.assertEqual(reason, "embed_dimensions")
        self.assertEqual(store.rollbacks, 1)
        self.assertEqual(tx.finished, [])
        self.assertEqual(points.upserts, [])

    def test_a_delete_during_embed_does_not_recreate_the_point(self) -> None:
        row = _memory()
        tx = _Tx([Claim(4, row.id, 1, False)], {row.id: row})
        points = _Points()

        def embed(_text: str):
            tx.rows[row.id] = _memory(deleted=True, revision=2)
            return [0.1] * 768

        reason = index_once(_Store(tx), points, embed)
        self.assertEqual(reason, "deleted")
        self.assertEqual(points.upserts, [])
        self.assertEqual(points.deletes, [("friday_profile", row.id)])
        self.assertNotIn(("friday_profile", row.id), points.points)
        self.assertEqual(tx.indexed, [])
        self.assertEqual(tx.finished, [4])

    def test_revision_one_does_not_replace_revision_two(self) -> None:
        row = _memory()
        newer = _memory(revision=2, content="newer")
        tx = _Tx(
            [Claim(1, row.id, 1, False), Claim(2, row.id, 2, False)],
            {row.id: row},
        )
        points = _Points()
        points.points[("friday_profile", row.id)] = {"revision": 2, "content": "newer"}

        def embed(text: str):
            if text == "lighthouse":
                tx.rows[row.id] = newer
            return [0.1] * 768

        first = index_once(_Store(tx), points, embed)
        self.assertEqual(first, "stale")
        self.assertEqual(points.upserts, [])
        self.assertEqual(points.points[("friday_profile", row.id)]["content"], "newer")
        second = index_once(_Store(tx), points, embed)
        self.assertEqual(second, "indexed")
        self.assertEqual(points.upserts, [("friday_profile", row.id, "person")])
        self.assertEqual(points.points[("friday_profile", row.id)]["revision"], 2)
        self.assertEqual(points.points[("friday_profile", row.id)]["content"], "newer")
        self.assertEqual(tx.indexed, [(row.id, 2)])
        self.assertEqual(tx.finished, [1, 2])

    def test_a_stale_payload_is_removed_and_a_newer_one_stays(self) -> None:
        row = _memory()
        tx = _Tx([Claim(8, row.id, 1, False)], {row.id: row})
        points = _Points()

        def embed(_text: str):
            return [0.1] * 768

        def replace_with_newer() -> None:
            points.points[("friday_profile", row.id)] = {
                "revision": 2,
                "content": "newer",
                "owner_kind": "person",
            }
            tx.rows[row.id] = _memory(revision=2, content="newer")

        points.on_upsert = replace_with_newer
        reason = index_once(_Store(tx), points, embed)
        self.assertEqual(reason, "stale")
        self.assertEqual(points.points[("friday_profile", row.id)]["revision"], 2)
        self.assertEqual(points.points[("friday_profile", row.id)]["content"], "newer")
        self.assertEqual(tx.indexed, [])

        kept = _memory()
        late = _Tx([Claim(9, kept.id, 1, False)], {kept.id: kept})
        late_points = _Points()

        def move_row() -> None:
            late.rows[kept.id] = _memory(revision=2, content="newer")

        late_points.on_upsert = move_row
        dropped = index_once(_Store(late), late_points, embed)
        self.assertEqual(dropped, "stale")
        self.assertNotIn(("friday_profile", kept.id), late_points.points)
        self.assertEqual(late.indexed, [])

    def test_a_matching_revision_is_indexed_once(self) -> None:
        row = _memory()
        tx = _Tx([Claim(3, row.id, 1, False)], {row.id: row})
        points = _Points()
        reason = drain(_Store(tx), points, lambda _text: [0.1] * 768)
        self.assertEqual(reason, "idle")
        self.assertEqual(points.upserts, [("friday_profile", row.id, "person")])
        self.assertEqual(tx.indexed, [(row.id, 1)])
        self.assertEqual(tx.finished, [3])

    def test_search_refuses_a_missing_owner_before_any_call(self) -> None:
        def explode(*_args, **_kwargs):
            raise AssertionError("called")

        decision = search(explode, explode, owner_id="", owner_kind="person", text="hello")
        self.assertEqual(decision.reason, "missing_owner")

    def test_a_foreign_payload_is_dropped(self) -> None:
        class _Q:
            def query(self, name, vector, owner_id, owner_kind, limit):
                return [
                    {
                        "score": 0.9,
                        "payload": {
                            "owner_id": "owner-2",
                            "owner_kind": "person",
                            "content": "secret",
                            "memory_id": "x",
                        },
                    },
                    {
                        "score": 0.2,
                        "payload": {
                            "owner_id": owner_id,
                            "owner_kind": owner_kind,
                            "content": "lighthouse",
                            "memory_id": "y",
                            "visibility": "master",
                            "topic": "note",
                            "revision": 1,
                        },
                    },
                ]

        decision = search(_Q(), lambda _text: [0.1] * 768, owner_id="owner-1", owner_kind="person", text="light")
        self.assertEqual([note["content"] for note in decision.notes], ["lighthouse"])

    def test_the_query_carries_the_owner_filter(self) -> None:
        seen = {}

        def transport(method, path, body):
            seen["path"] = path
            seen["body"] = body
            return 200, {"result": {"points": []}}

        Qdrant("http://qdrant", "key", transport).query("knowledge", [0.0] * 768, "owner-1", "role", 8)
        must = seen["body"]["filter"]["must"]
        self.assertEqual(must[0]["match"]["value"], "owner-1")
        self.assertEqual(must[1]["match"]["value"], "role")
        self.assertEqual(seen["path"], "/collections/knowledge/points/query")

    def test_a_wrong_collection_size_is_refused(self) -> None:
        def transport(method, path, body):
            return 200, {"result": {"config": {"params": {"vectors": {"size": 3, "distance": "Cosine"}}}}}

        with self.assertRaises(OSError) as caught:
            Qdrant("http://qdrant", "key", transport).ensure("knowledge")
        self.assertEqual(str(caught.exception), "index_refused")

    def test_delete_revision_matches_the_revision_in_one_call(self) -> None:
        seen = {}

        def transport(method, path, body):
            seen["method"] = method
            seen["path"] = path
            seen["body"] = body
            return 200, {}

        Qdrant("http://qdrant", "key", transport).delete_revision("knowledge", "id-1", 1)
        self.assertEqual(seen["method"], "POST")
        self.assertEqual(seen["path"], "/collections/knowledge/points/delete?wait=true")
        must = seen["body"]["filter"]["must"]
        self.assertEqual(must, [
            {"has_id": ["id-1"]},
            {"key": "revision", "match": {"value": 1}},
        ])

        def missing(method, path, body):
            return 404, None

        with self.assertRaises(OSError) as caught:
            Qdrant("http://qdrant", "key", missing).delete_revision("knowledge", "id-1", 1)
        self.assertEqual(str(caught.exception), "index_not_ready")


def _collection(schema: dict | None, *, size: int = 768, distance: str = "Cosine") -> dict:
    result = {
        "points_count": 4,
        "config": {"params": {"vectors": {"size": size, "distance": distance}}},
    }
    if schema is not None:
        result["payload_schema"] = schema
    return {"result": result}


class EnsureIndexTests(unittest.TestCase):
    def test_a_new_collection_gets_four_keyword_indexes_and_no_delete(self) -> None:
        calls = []

        def transport(method, path, body):
            calls.append((method, path, body))
            if method == "GET":
                return 404, None
            return 200, {"result": True}

        ensure_collection("knowledge", transport)
        self.assertEqual(calls[0][0], "GET")
        self.assertEqual(
            calls[1],
            (
                "PUT",
                "/collections/knowledge",
                {"vectors": {"size": 768, "distance": "Cosine", "on_disk": True}},
            ),
        )
        indexed = [call[2]["field_name"] for call in calls[2:]]
        self.assertEqual(indexed, list(PAYLOAD_INDEXES))
        self.assertTrue(all(call[2]["field_schema"] == "keyword" for call in calls[2:]))
        self.assertNotIn("member_key", indexed)
        self.assertNotIn("agent_id", indexed)
        self.assertTrue(all("points" not in call[1] for call in calls))

    def test_an_existing_collection_keeps_its_points_and_adds_a_missing_index(self) -> None:
        calls = []

        def transport(method, path, body):
            calls.append((method, path, body))
            if method == "GET":
                return 200, _collection({"owner_id": {}, "owner_kind": {}, "topic": {}})
            return 200, {}

        Qdrant("http://qdrant", "key", transport).ensure("friday_profile")
        self.assertEqual([call[0] for call in calls], ["GET", "PUT"])
        self.assertEqual(calls[1][1], "/collections/friday_profile/index")
        self.assertEqual(calls[1][2]["field_name"], "source")
        self.assertNotIn("/collections/friday_profile", [call[1] for call in calls[1:]])

    def test_a_complete_schema_does_not_request_another_index(self) -> None:
        calls = []

        def transport(method, path, body):
            calls.append((method, path, body))
            schema = {field: {} for field in PAYLOAD_INDEXES}
            return 200, _collection(schema)

        ensure_collection("cabinet_working", transport)
        self.assertEqual([call[0] for call in calls], ["GET"])

    def test_a_wrong_size_writes_nothing(self) -> None:
        calls = []

        def transport(method, path, body):
            calls.append(path)
            return 200, _collection({}, size=3)

        with self.assertRaises(OSError) as caught:
            ensure_collection("knowledge", transport)
        self.assertEqual(str(caught.exception), "index_refused")
        self.assertEqual(calls, ["/collections/knowledge"])

        calls.clear()

        def distance(method, path, body):
            del method, body
            calls.append(path)
            return 200, _collection({}, distance="Dot")

        with self.assertRaises(OSError) as caught:
            ensure_collection("knowledge", distance)
        self.assertEqual(str(caught.exception), "index_refused")
        self.assertEqual(calls, ["/collections/knowledge"])

    def test_another_collection_name_is_refused(self) -> None:
        def transport(method, path, body):
            raise AssertionError(path)

        for name in ("family_shared", "role_profile_cto", "person_profile_owner"):
            with self.assertRaises(OSError) as caught:
                ensure_collection(name, transport)
            self.assertEqual(str(caught.exception), "index_refused")

    def test_a_failed_index_request_does_not_delete_a_point(self) -> None:
        calls = []

        def transport(method, path, body):
            calls.append(path)
            if method == "GET":
                return 404, None
            if path.endswith("/index"):
                return 400, {"status": "already"}
            return 200, {}

        with self.assertRaises(OSError) as caught:
            ensure_collection("knowledge", transport)
        self.assertEqual(str(caught.exception), "index_not_ready")
        self.assertTrue(all("points" not in path for path in calls))


if __name__ == "__main__":
    unittest.main()
