"""The core listen address is the one facing Postgres, never loopback."""

from __future__ import annotations

import unittest

from runtime.bind import bind_host


class BindTests(unittest.TestCase):
    def test_a_written_address_is_kept(self):
        self.assertEqual(bind_host({}), "0.0.0.0")
        self.assertEqual(bind_host({"BIND_HOST": ""}), "0.0.0.0")
        self.assertEqual(bind_host({"BIND_HOST": "0.0.0.0"}), "0.0.0.0")
        self.assertEqual(bind_host({"BIND_HOST": "127.0.0.1"}), "127.0.0.1")

    def test_core_uses_the_address_facing_the_peer(self):
        seen = []

        def resolve(peer: str) -> str:
            seen.append(peer)
            return "10.9.0.4"

        host = bind_host(
            {"BIND_HOST": "core", "CORE_PEER": "postgres"},
            resolve=resolve,
            pause=lambda _seconds: None,
        )
        self.assertEqual(host, "10.9.0.4")
        self.assertEqual(seen, ["postgres"])

    def test_the_default_peer_is_postgres(self):
        seen = []

        def resolve(peer: str) -> str:
            seen.append(peer)
            return "10.9.0.5"

        host = bind_host({"BIND_HOST": "core"}, resolve=resolve, pause=lambda _seconds: None)
        self.assertEqual(host, "10.9.0.5")
        self.assertEqual(seen, ["postgres"])

    def test_loopback_and_a_miss_are_refused(self):
        answers = iter(["127.0.0.1", ""])

        def resolve(_peer: str) -> str:
            return next(answers)

        with self.assertRaises(OSError) as caught:
            bind_host(
                {"BIND_HOST": "core"},
                resolve=resolve,
                attempts=2,
                pause=lambda _seconds: None,
            )
        self.assertEqual(str(caught.exception), "core_address")

    def test_a_lookup_error_retries_then_refuses(self):
        def resolve(_peer: str) -> str:
            raise OSError("down")

        with self.assertRaises(OSError) as caught:
            bind_host(
                {"BIND_HOST": "core"},
                resolve=resolve,
                attempts=2,
                pause=lambda _seconds: None,
            )
        self.assertEqual(str(caught.exception), "core_address")


if __name__ == "__main__":
    unittest.main()
