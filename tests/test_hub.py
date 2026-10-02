"""Hub search reads two collections for one owner. It does not open Qdrant."""

from __future__ import annotations

import json
import threading
import unittest

from memoryd.hub import HUB, hub_search
from memoryd.server import app as memory_app
from memoryd.store import Notes
from runtime.http import serve

MEMORY = "memory-token"
QDRANT = "qdrant-token"
KEPT = "The password is kept outside the machine"


def start(handler):
    server = serve(handler, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def post(port: int, path: str, payload: dict, headers: dict) -> tuple[int, dict]:
    import urllib.error
    import urllib.request

    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode())


class _Q:
    def __init__(self, rows=None, missing=()):
        self.rows = rows or {}
        self.missing = set(missing)
        self.calls = []
        self.ensured = False

    def ensure(self, _name):
        self.ensured = True
        raise AssertionError("ensure")

    def query(self, name, vector, owner_id, owner_kind, limit):
        self.calls.append((name, owner_id, owner_kind, len(vector), limit))
        if name in self.missing:
            raise OSError("missing_collection")
        if name not in HUB:
            raise AssertionError(name)
        return list(self.rows.get(name, []))


def _hit(content, owner="owner-1", kind="person", topic="decision", score=0.5, note_id="n1", revision=1):
    return {
        "score": score,
        "payload": {
            "owner_id": owner,
            "owner_kind": kind,
            "content": content,
            "topic": topic,
            "memory_id": note_id,
            "revision": revision,
        },
    }


class HubTests(unittest.TestCase):
    def test_a_missing_owner_is_refused_before_any_call(self) -> None:
        store = _Q()

        def explode(_text):
            raise AssertionError("embed")

        for owner, kind in (("", "person"), (" owner-1", "person"), ("owner-1\n", "person"), ("owner-1", "Person"), (1, "person")):
            decision = hub_search(store, explode, owner_id=owner, owner_kind=kind, text="lighthouse")
            self.assertEqual(decision.reason, "missing_owner")
            self.assertEqual(decision.notes, ())
        self.assertEqual(store.calls, [])
        self.assertFalse(store.ensured)

    def test_another_owner_is_not_searched(self) -> None:
        store = _Q()
        decision = hub_search(
            store,
            lambda _text: [0.1] * 768,
            owner_id="chief",
            owner_kind="role",
            subject_id="owner-1",
            subject_kind="person",
            text="lighthouse",
            confirmed=True,
        )
        self.assertEqual(decision.reason, "other_owner")
        self.assertEqual(decision.notes, ())
        self.assertEqual(store.calls, [])

        other = hub_search(
            store,
            lambda _text: [0.1] * 768,
            owner_id="owner-2",
            owner_kind="person",
            subject_id="owner-1",
            subject_kind="person",
            text="lighthouse",
        )
        self.assertEqual(other.reason, "other_owner")
        self.assertEqual(store.calls, [])

    def test_a_credential_shaped_query_is_not_sent(self) -> None:
        store = _Q()

        def explode(_text):
            raise AssertionError("embed")

        samples = (
            ("owner-1", "person", "token=abcd", None),
            ("owner-1", "person", "password is hunter22", None),
            ("owner-1", "person", "token%3Dabcd", None),
            ("owner-1", "person", "token+is+abcd1", None),
            ("token=abcd", "person", KEPT, None),
            ("token%3Dabcd", "person", KEPT, None),
            ("password%20is%20hunter22", "person", "light", None),
            ("owner-1", "person", KEPT, "token=abcd"),
            ("owner-1", "person", "light", "password%20is%20hunter22"),
        )
        for owner, kind, text, topic in samples:
            decision = hub_search(store, explode, owner_id=owner, owner_kind=kind, text=text, topic=topic)
            self.assertEqual(decision.reason, "credential", text)
            self.assertEqual(decision.notes, ())
            self.assertNotIn("abcd", repr(decision))
            self.assertNotIn("hunter22", repr(decision))
        self.assertEqual(store.calls, [])

    def test_only_the_two_hub_collections_are_queried(self) -> None:
        store = _Q({
            "friday_findings": [_hit("a finding", topic="research", score=0.4, note_id="f1")],
            "knowledge": [_hit(KEPT, topic="decision", score=0.9, note_id="k1")],
            "friday_profile": [_hit("not hub", note_id="p1")],
            "cabinet_working": [_hit("scratch", note_id="c1")],
        })
        decision = hub_search(
            store,
            lambda text: [0.2] * 768,
            owner_id="owner-1",
            owner_kind="person",
            text=KEPT,
            confirmed=True,
        )
        self.assertEqual(decision.reason, "searched")
        self.assertEqual([note["id"] for note in decision.notes], ["k1", "f1"])
        self.assertEqual(decision.notes[0]["content"], KEPT)
        self.assertEqual([call[0] for call in store.calls], list(HUB))
        self.assertEqual(store.calls[0][1:], ("owner-1", "person", 768, 8))
        self.assertFalse(store.ensured)

    def test_a_foreign_payload_and_another_topic_are_dropped(self) -> None:
        store = _Q({
            "knowledge": [
                _hit("secret", owner="owner-2", score=0.99, note_id="x"),
                _hit("other topic", topic="else", score=0.8, note_id="y"),
                _hit("lighthouse", topic="decision", score=0.2, note_id="z"),
            ],
            "friday_findings": [],
        })
        decision = hub_search(
            store,
            lambda _text: [0.1] * 768,
            owner_id="owner-1",
            owner_kind="person",
            text="light",
            topic="decision",
        )
        self.assertEqual([note["content"] for note in decision.notes], ["lighthouse"])
        self.assertNotIn("secret", repr(decision))

    def test_the_pack_is_eight_notes_of_1200_characters(self) -> None:
        long = "word " * 400
        rows = [
            _hit(long, score=index, note_id=f"n{index}")
            for index in range(9)
        ]
        store = _Q({"knowledge": rows, "friday_findings": []})
        decision = hub_search(
            store,
            lambda _text: [0.1] * 768,
            owner_id="owner-1",
            owner_kind="person",
            text="word",
            limit=100,
        )
        self.assertEqual(len(decision.notes), 8)
        self.assertEqual(len(decision.notes[0]["content"]), 1200)
        self.assertEqual(decision.notes[0]["id"], "n8")
        self.assertNotIn(long, decision.notes[0]["content"])
        self.assertEqual(store.calls[0][4], 8)

    def test_a_credential_shaped_hit_is_not_shown(self) -> None:
        store = _Q({
            "knowledge": [_hit("token=abcd", score=0.9, note_id="bad"), _hit("lighthouse", score=0.1, note_id="ok")],
            "friday_findings": [],
        })
        decision = hub_search(store, lambda _text: [0.1] * 768, owner_id="owner-1", owner_kind="person", text="light")
        self.assertEqual([note["content"] for note in decision.notes], ["lighthouse"])
        self.assertNotIn("abcd", repr(decision))

        leaked = _Q({
            "knowledge": [
                _hit("lighthouse", topic="password is hunter22", note_id="topic"),
                _hit("password%20is%20hunter22", note_id="enc"),
                _hit("the shelf is oak", score=0.4, note_id="ok2"),
                _hit(KEPT, topic=KEPT, score=0.2, note_id="kept"),
            ],
            "friday_findings": [],
        })
        again = hub_search(leaked, lambda _text: [0.1] * 768, owner_id="owner-1", owner_kind="person", text="light")
        self.assertEqual([note["id"] for note in again.notes], ["ok2", "kept"])
        self.assertNotIn("hunter22", repr(again))
        self.assertNotIn("password%20", repr(again))

    def test_a_missing_collection_is_not_created(self) -> None:
        store = _Q(missing=HUB)
        decision = hub_search(store, lambda _text: [0.1] * 768, owner_id="owner-1", owner_kind="person", text="light")
        self.assertEqual(decision.reason, "index_not_ready")
        self.assertEqual([call[0] for call in store.calls], list(HUB))
        self.assertFalse(store.ensured)

        one = _Q(
            {"knowledge": [_hit("lighthouse", note_id="k1")]},
            missing={"friday_findings"},
        )
        found = hub_search(one, lambda _text: [0.1] * 768, owner_id="owner-1", owner_kind="person", text="light")
        self.assertEqual([note["id"] for note in found.notes], ["k1"])
        self.assertFalse(one.ensured)

    def test_a_bad_vector_does_not_query(self) -> None:
        store = _Q()
        decision = hub_search(store, lambda _text: [0.1] * 3, owner_id="owner-1", owner_kind="person", text="light")
        self.assertEqual(decision.reason, "embed_dimensions")
        self.assertEqual(store.calls, [])
        blank = hub_search(store, lambda _text: [0.1] * 768, owner_id="owner-1", owner_kind="person", text="  ")
        self.assertEqual(blank.reason, "empty_content")
        named = hub_search(store, lambda _text: True, owner_id="owner-1", owner_kind="person", text="light", topic=True)
        self.assertEqual(named.reason, "topic")
        self.assertEqual(store.calls, [])


class HubHttpTests(unittest.TestCase):
    def test_the_route_keeps_the_owner_filter(self) -> None:
        notes = Notes()
        store = _Q({"knowledge": [_hit("lighthouse", note_id="k1")], "friday_findings": []})

        def hubber(**kwargs):
            return hub_search(store, lambda _text: [0.1] * 768, **kwargs)

        server = start(memory_app(
            notes,
            {"MEMORY_TOKEN": MEMORY, "QDRANT_API_KEY": QDRANT},
            hubber=hubber,
        ))
        try:
            port = server.server_address[1]
            headers = {"Friday-Memory": MEMORY}
            status, denied = post(port, "/hub", {"owner_id": "owner-1", "owner_kind": "person", "text": "light"}, {})
            self.assertEqual(status, 401)
            self.assertEqual(store.calls, [])

            status, other = post(
                port,
                "/hub",
                {
                    "caller_id": "chief",
                    "caller_kind": "role",
                    "subject_id": "owner-1",
                    "subject_kind": "person",
                    "text": "light",
                    "confirmed": True,
                },
                headers,
            )
            self.assertEqual(other["reason"], "other_owner")
            self.assertEqual(other.get("notes", []), [])
            self.assertEqual(store.calls, [])

            status, body = post(
                port,
                "/hub",
                {"owner_id": "owner-1", "owner_kind": "person", "text": "light", "confirmed": True},
                headers,
            )
            self.assertEqual(status, 200, body)
            self.assertEqual(body["reason"], "searched")
            self.assertEqual(body["notes"][0]["content"], "lighthouse")
            self.assertNotIn(QDRANT, json.dumps(body))
            self.assertEqual([call[0] for call in store.calls], list(HUB))
        finally:
            server.shutdown()

    def test_without_a_client_the_route_does_not_invent_one(self) -> None:
        server = start(memory_app(Notes(), {"MEMORY_TOKEN": MEMORY, "QDRANT_API_KEY": QDRANT}))
        try:
            port = server.server_address[1]
            status, body = post(
                port,
                "/hub",
                {"owner_id": "owner-1", "owner_kind": "person", "text": "light"},
                {"Friday-Memory": MEMORY},
            )
            self.assertEqual(status, 503)
            self.assertEqual(body["reason"], "index_not_ready")
        finally:
            server.shutdown()
