"""Friday reads fixed webhook sentences. The body stays out. Ask does not."""

from __future__ import annotations

import inspect
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import friday.announce as announce
import friday.ask as ask_mod
from friday.announce import spoken
from friday.server import app
from memoryd.store import Notes
from webhooks.receiver import SENTENCES

ROOT = Path(__file__).resolve().parents[1]
NOTIFY = "notify-secret"
SECRET = "password is hunter22"


def _env(**extra):
    base = {
        "FRIDAY_NOTIFY_TOKEN": NOTIFY,
        "MEMORY_TOKEN": "memory-token",
        "CHARTERS_DIR": str(ROOT / "charters"),
        "SOUL_PATH": str(ROOT / "soul" / "SOUL.example.md"),
    }
    base.update(extra)
    return base


class AnnounceTests(unittest.TestCase):
    def test_the_type_picks_the_sentence_and_the_body_is_dropped(self) -> None:
        self.assertEqual(announce.SENTENCES, SENTENCES)
        rows = spoken([
            {
                "source": "radarr",
                "event_type": "grab",
                "announcement": SECRET,
                "body": SECRET,
                "movie": "Inception",
            },
            {"source": "radarr", "event_type": "grab", "announcement": "downloading"},
            {"source": "postgres", "event_type": "grab", "announcement": "A download was grabbed."},
            {"source": "jellyfin", "event_type": "nope", "announcement": SECRET},
            "A download was grabbed.",
        ])
        self.assertEqual(rows, [
            {"source": "radarr", "event_type": "grab", "announcement": "A download was grabbed."},
            {"source": "radarr", "event_type": "grab", "announcement": "A download was grabbed."},
        ])
        self.assertNotIn("hunter22", repr(rows))
        self.assertNotIn("downloading", repr(rows))
        self.assertNotIn("Inception", repr(rows))
        self.assertEqual(spoken([{"source": "sonarr", "event_type": "grab"}] * 9).__len__(), 8)
        self.assertEqual(spoken("A download was grabbed."), [])

    def test_ask_does_not_read_announcements(self) -> None:
        source = inspect.getsource(ask_mod)
        self.assertNotIn("announce", source)
        self.assertNotIn("webhook", source)
        called = {"events": False}

        def events():
            called["events"] = True
            raise AssertionError("ask read announcements")

        handle = app(
            _env(),
            notes=Notes(),
            embed=lambda: "",
            model=lambda messages: "Ready.",
            events=events,
        )
        status, body = handle(
            "POST",
            "/ask",
            {"Friday-Notify": NOTIFY},
            {"text": "hello", "owner_id": "owner-1"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["reply"], "Ready.")
        self.assertNotIn("announcements", body)
        self.assertFalse(called["events"])
        refused, denied = handle(
            "POST",
            "/announcements",
            {"Friday-Notify": NOTIFY},
            {"announcement": "A download was grabbed.", "body": SECRET},
        )
        self.assertEqual(refused, 405)
        self.assertEqual(denied["reason"], "method_refused")
        self.assertNotIn("hunter22", repr(denied))
        self.assertFalse(called["events"])

    def test_a_read_uses_only_the_webhook_service(self) -> None:
        handle = app(_env(), events=lambda: [{
            "source": "sonarr",
            "event_type": "failure",
            "announcement": SECRET,
            "body_raw": SECRET,
        }])
        quiet, empty = handle("GET", "/announcements", {}, {})
        self.assertEqual(quiet, 401)
        status, body = handle("GET", "/announcements", {"Friday-Notify": NOTIFY}, {})
        self.assertEqual(status, 200)
        self.assertEqual(body["reason"], "announced")
        self.assertEqual(body["announcements"], [{
            "source": "sonarr",
            "event_type": "failure",
            "announcement": "A download failed.",
        }])
        self.assertFalse(body["started"])
        self.assertFalse(body["sent"])
        self.assertNotIn("hunter22", json.dumps(body))
        self.assertEqual(empty["reason"], "unauthenticated")

        unset = app(_env())
        status, body = unset("GET", "/announcements", {"Friday-Notify": NOTIFY}, {})
        self.assertEqual((status, body["reason"], body["announcements"]), (200, "unset", []))
        for raw in (
            "http://127.0.0.1:8080",
            "http://webhooks:8080/announcements",
            "https://webhooks:8080",
            "http://webhooks:8080?x=1",
            "http://postgres:5432",
            "http://169.254.169.254",
            "http://user:secret@webhooks:8080",
            "http://webhooks:9090",
        ):
            refused = app(_env(WEBHOOK_URL=raw))
            status, body = refused("GET", "/announcements", {"Friday-Notify": NOTIFY}, {})
            self.assertEqual(body["reason"], "url", raw)
            self.assertEqual(body["announcements"], [])
            self.assertNotIn("secret", json.dumps(body))

        class Response:
            status = 200

            def read(self, _limit):
                return json.dumps({
                    "announcements": [{
                        "source": "jellyfin",
                        "event_type": "health",
                        "announcement": "An app health state changed.",
                        "body": SECRET,
                    }],
                    "body": SECRET,
                }).encode()

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        seen = {}

        class Opener:
            def open(self, request, timeout):
                seen["url"] = request.full_url
                seen["method"] = request.get_method()
                seen["token"] = request.get_header("Friday-notify")
                seen["timeout"] = timeout
                return Response()

        with patch("friday.server.urllib.request.build_opener", return_value=Opener()):
            fetched = app(_env(WEBHOOK_URL="http://webhooks:8080"))
            status, body = fetched("GET", "/announcements", {"Friday-Notify": NOTIFY}, {})
        self.assertEqual(status, 200)
        self.assertEqual(seen["url"], "http://webhooks:8080/announcements")
        self.assertEqual(seen["method"], "GET")
        self.assertEqual(seen["token"], NOTIFY)
        self.assertEqual(body["announcements"][0]["announcement"], "An app health state changed.")
        self.assertNotIn("hunter22", json.dumps(body))
        self.assertNotIn(NOTIFY, json.dumps(body))


if __name__ == "__main__":
    unittest.main()
