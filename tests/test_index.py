"""Index protocol. These tests do not open Postgres or Qdrant."""

from __future__ import annotations

import unittest

from memoryd.index import Claim, Memory, collection_name, drain, index_once, search
from memoryd.qdrant import Qdrant


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

    def ensure(self, name: str) -> None:
        return None

    def upsert(self, name, point_id, vector, payload) -> None:
        self.upserts.append((name, point_id, payload["owner_kind"]))

    def delete(self, name, point_id) -> None:
        self.deletes.append((name, point_id))


def _memory(deleted: bool = False, revision: int = 1, kind: str = "person") -> Memory:
    return Memory(
        id="11111111-1111-4111-8111-111111111111",
        owner_id="owner-1",
        owner_kind=kind,
        revision=revision,
        content="lighthouse",
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


if __name__ == "__main__":
    unittest.main()
