"""A second person cannot read someone else's note through reflection or export."""

from __future__ import annotations

import json
import threading
import unittest

from memoryd.index import COLLECTIONS, collection_name
from memoryd.isolate import export_notes, lookup, reflect, search_for
from memoryd.server import app as memory_app
from memoryd.sqlstore import PostgresNotes
from memoryd.store import Decision, Notes
from runtime.http import serve

MEMORY = "memory-token"
QDRANT = "qdrant-token"
LIGHTHOUSE = "the project codename is lighthouse"
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
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read())
        finally:
            exc.close()
        return exc.code, body


class Closed:
    def recall(self, **kwargs):
        raise AssertionError(kwargs)

    def save(self, **kwargs):
        raise AssertionError(kwargs)


class IsolateTests(unittest.TestCase):
    def test_someone_else_gets_nothing_and_reflection_writes_nothing(self) -> None:
        notes = Notes()
        for index in range(9):
            notes.save(
                owner_id="owner-1",
                owner_kind="person",
                content=f"episode {index}",
                category="episode",
            )
        notes.save(owner_id="owner-1", owner_kind="person", content="not an episode", category="note")
        notes.save(owner_id="owner-1", owner_kind="person", content=LIGHTHOUSE, category="episode")
        notes.save(owner_id="owner-1", owner_kind="person", content=KEPT, category="episode")
        notes.save(owner_id="chief", owner_kind="role", content="role episode", category="episode")
        notes.save(owner_id="chief", owner_kind="person", content="person episode", category="episode")

        closed = Closed()
        for call in (
            lambda: reflect(closed, caller_id="owner-2", caller_kind="person", subject_id="owner-1", subject_kind="person"),
            lambda: export_notes(closed, caller_id="owner-2", caller_kind="person", subject_id="owner-1", subject_kind="person"),
            lambda: lookup(closed, caller_id="chief", caller_kind="role", subject_id="owner-1", subject_kind="person"),
            lambda: lookup(closed, caller_id="chief", caller_kind="role", subject_id="chief", subject_kind="person"),
            lambda: search_for(
                lambda **kwargs: (_ for _ in ()).throw(AssertionError(kwargs)),
                caller_id="owner-2",
                caller_kind="person",
                subject_id="owner-1",
                subject_kind="person",
                text=LIGHTHOUSE,
            ),
        ):
            decision = call()
            self.assertEqual((decision.outcome, decision.reason), ("ok", "other_owner"))
            self.assertEqual(decision.notes, ())
            self.assertNotIn(LIGHTHOUSE, str(decision))

        missing = reflect(closed, caller_id="", caller_kind="person")
        self.assertEqual(missing.reason, "missing_owner")
        self.assertEqual(export_notes(closed, caller_id="owner-2", caller_kind="nope").reason, "missing_owner")

        folded = reflect(notes, caller_id="owner-1", caller_kind="person")
        self.assertEqual(folded.reason, "created")
        profile = notes.recall(owner_id="owner-1", owner_kind="person", category="profile")
        self.assertEqual(len(profile.notes), 1)
        fact = profile.notes[0]["content"]
        self.assertIn(LIGHTHOUSE, fact)
        self.assertIn(KEPT, fact)
        self.assertIn("episode 8", fact)
        self.assertNotIn("not an episode", fact)
        self.assertNotIn("episode 0", fact)
        self.assertNotIn("role episode", fact)
        self.assertEqual(profile.notes[0]["visibility"], "master")
        self.assertEqual(collection_name("person", "profile"), "friday_profile")

        other = export_notes(notes, caller_id="owner-2", caller_kind="person")
        self.assertEqual(other.notes, ())
        self.assertNotIn(LIGHTHOUSE, str(other))
        asked = lookup(notes, caller_id="owner-2", caller_kind="person", subject_id="owner-1", subject_kind="person")
        self.assertEqual(asked.notes, ())

        role = reflect(notes, caller_id="chief", caller_kind="role")
        self.assertEqual(role.reason, "created")
        role_fact = notes.recall(owner_id="chief", owner_kind="role", category="profile")
        self.assertEqual(role_fact.notes[0]["content"], "role episode")
        self.assertEqual(role_fact.notes[0]["visibility"], "working")
        self.assertEqual(collection_name("role", "profile"), "cabinet_working")
        person = notes.recall(owner_id="chief", owner_kind="person", category="profile")
        self.assertEqual(person.notes, ())
        self.assertNotIn("family_shared", COLLECTIONS)
        self.assertFalse(any(name.startswith("role_profile_") for name in COLLECTIONS))

        own = lookup(notes, caller_id="chief", caller_kind="role", subject_id="chief", subject_kind="role")
        self.assertEqual([note["content"] for note in own.notes if note["category"] == "episode"], ["role episode"])
        self.assertNotIn("person episode", str(own))

    def test_a_credential_episode_is_not_folded(self) -> None:
        class Store:
            def recall(self, **kwargs):
                return Decision(
                    "ok",
                    "recalled",
                    notes=({
                        "content": "password is hunter22",
                        "category": "episode",
                        "owner_id": "owner-1",
                        "owner_kind": "person",
                    },),
                )

            def save(self, **kwargs):
                raise AssertionError(kwargs["content"])

        decision = reflect(Store(), caller_id="owner-1", caller_kind="person")
        self.assertEqual((decision.outcome, decision.reason), ("refused", "credential"))
        self.assertNotIn("hunter22", str(decision))

    def test_a_credential_line_is_left_out_of_the_folded_fact(self) -> None:
        class Store:
            def __init__(self) -> None:
                self.saved: list[str] = []

            def recall(self, **kwargs):
                return Decision(
                    "ok",
                    "recalled",
                    notes=(
                        {
                            "content": "password is hunter22",
                            "category": "episode",
                            "owner_id": "owner-1",
                            "owner_kind": "person",
                        },
                        {
                            "content": LIGHTHOUSE,
                            "category": "episode",
                            "owner_id": "owner-1",
                            "owner_kind": "person",
                        },
                    ),
                )

            def save(self, **kwargs):
                self.saved.append(kwargs["content"])
                return Decision("saved", "created", note_id="profile-1", revision=1)

        store = Store()
        decision = reflect(store, caller_id="owner-1", caller_kind="person")
        self.assertEqual(decision.reason, "created")
        self.assertEqual(store.saved, [LIGHTHOUSE])
        self.assertNotIn("hunter22", store.saved[0])

    def test_search_returns_the_caller_trimmed_and_skips_someone_else(self) -> None:
        seen = []

        def search(**kwargs):
            seen.append(kwargs)
            return Decision(
                "ok",
                "searched",
                notes=({
                    "id": "1",
                    "content": "x" * 2000,
                    "owner_id": "owner-1",
                    "owner_kind": "person",
                    "category": "note",
                },),
            )

        own = search_for(
            search,
            caller_id="owner-1",
            caller_kind="person",
            subject_id="owner-1",
            subject_kind="person",
            text="x",
            limit=100,
        )
        self.assertEqual(own.reason, "searched")
        self.assertEqual(len(own.notes[0]["content"]), 1200)
        self.assertEqual(seen, [{"owner_id": "owner-1", "owner_kind": "person", "text": "x", "limit": 8}])

    def test_postgres_recall_binds_the_category(self) -> None:
        class Capture:
            def __init__(self) -> None:
                self.sql = ""
                self.params = ()

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def execute(self, sql, params):
                self.sql = sql
                self.params = params
                return self

            def fetchall(self):
                return []

        box = Capture()
        notes = PostgresNotes(lambda: box)
        decision = notes.recall(owner_id="owner-1", owner_kind="person", category="episode")
        self.assertEqual(decision.reason, "recalled")
        self.assertIn("category = %s", box.sql)
        self.assertEqual(box.params, ("owner-1", "person", "episode", 8))
        self.assertNotIn("episode", box.sql.replace("category = %s", ""))


class IsolateHttpTests(unittest.TestCase):
    def test_reflect_and_export_stop_at_the_other_owner(self) -> None:
        notes = Notes()
        notes.save(owner_id="owner-1", owner_kind="person", content=LIGHTHOUSE, category="episode")
        seen = []

        def searcher(**kwargs):
            seen.append(kwargs)
            return Decision("ok", "searched", notes=({"content": LIGHTHOUSE, "owner_id": "owner-1"},))

        server = start(memory_app(
            notes,
            {"MEMORY_TOKEN": MEMORY, "QDRANT_API_KEY": QDRANT},
            searcher=searcher,
        ))
        try:
            port = server.server_address[1]
            headers = {"Friday-Memory": MEMORY}
            status, denied = post(port, "/export", {"caller_id": "owner-2", "caller_kind": "person"}, {})
            self.assertEqual(status, 401)
            self.assertNotIn(LIGHTHOUSE, json.dumps(denied))

            status, other = post(
                port,
                "/export",
                {
                    "caller_id": "owner-2",
                    "caller_kind": "person",
                    "subject_id": "owner-1",
                    "subject_kind": "person",
                    "confirmed": True,
                },
                headers,
            )
            self.assertEqual(status, 200, other)
            self.assertEqual(other["reason"], "other_owner")
            self.assertEqual(other["notes"], [])
            self.assertNotIn(LIGHTHOUSE, json.dumps(other))
            self.assertEqual(notes.recall(owner_id="owner-1", owner_kind="person", category="profile").notes, ())

            status, folded = post(
                port,
                "/reflect",
                {"owner_id": "owner-1", "owner_kind": "person", "confirmed": True},
                headers,
            )
            self.assertEqual(status, 200, folded)
            self.assertEqual(folded["reason"], "created")
            self.assertNotIn(LIGHTHOUSE, json.dumps(folded))
            profile = notes.recall(owner_id="owner-1", owner_kind="person", category="profile")
            self.assertIn(LIGHTHOUSE, profile.notes[0]["content"])

            status, exported = post(
                port,
                "/export",
                {"caller_id": "owner-1", "caller_kind": "person"},
                headers,
            )
            self.assertEqual(exported["reason"], "exported")
            self.assertIn(LIGHTHOUSE, json.dumps(exported["notes"]))
            self.assertNotIn(QDRANT, json.dumps(exported))

            status, searched = post(
                port,
                "/search",
                {
                    "caller_id": "owner-2",
                    "caller_kind": "person",
                    "subject_id": "owner-1",
                    "subject_kind": "person",
                    "text": LIGHTHOUSE,
                    "confirmed": True,
                },
                headers,
            )
            self.assertEqual(searched["reason"], "other_owner")
            self.assertEqual(searched["notes"], [])
            self.assertEqual(seen, [])
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
