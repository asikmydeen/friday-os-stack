"""A mesh pre-auth key is recorded by name. Nothing is attached."""

from __future__ import annotations

import inspect
import os
import unittest
from pathlib import Path

import doors.peers as peers
from doors.peers import (
    KEPT,
    Book,
    accept_tool,
    attach,
    endpoint,
    for_machine,
    grant_endpoint,
    matches,
    names,
    record_key,
    show,
    tools_of,
)

TOKEN = "token=abcd"
HUNTER = "password is hunter22"
HEX = "a" * 64
OTHER = "b" * 64
PHONE = "MESH_PREAUTH_PHONE"
LAPTOP = "MESH_PREAUTH_LAPTOP"
URL = "https://peer.example/mcp"


class Seq:
    def __init__(self, values: tuple[str, ...]) -> None:
        self.values = list(values)
        self.calls = 0

    def token_hex(self, nbytes: int) -> str:
        if nbytes != 32:
            raise ValueError("nbytes")
        self.calls += 1
        if not self.values:
            raise IndexError("empty")
        return self.values.pop(0)


class Boom:
    def token_hex(self, nbytes: int) -> str:
        del nbytes
        raise RuntimeError("token=abcd")


def _record(book: Book, peer: str = "phone", **kwargs):
    fields = {"actor": "board", "rng": Seq((HEX,))}
    fields.update(kwargs)
    return record_key(book, peer, **fields)


def _grant(book: Book, peer: str = "phone", **kwargs):
    fields = {
        "actor": "board",
        "address": URL,
        "role": "media",
        "tools": ["recall", "status"],
    }
    fields.update(kwargs)
    return grant_endpoint(book, peer, **fields)


class PeerTests(unittest.TestCase):
    def test_the_board_records_the_name_and_chat_does_not(self) -> None:
        book = Book()
        for actor in ("chat", "friday", "adapter"):
            refused = _record(book, actor=actor, confirmed=True)
            self.assertEqual(refused.reason, "board_only")
            self.assertEqual(refused.name, "")
            self.assertFalse(refused.started)
            self.assertFalse(refused.joined)
            self.assertFalse(refused.called)
        self.assertEqual(names(book), ())
        self.assertFalse(matches(book, "phone", HEX))

        stored = _record(book, "Phone", confirmed=True)
        self.assertEqual((stored.outcome, stored.reason), ("recorded", "name_only"))
        self.assertEqual(stored.name, PHONE)
        self.assertFalse(stored.started)
        self.assertFalse(stored.joined)
        self.assertFalse(stored.called)
        self.assertNotIn(HEX, repr(stored))
        self.assertNotIn(HEX, repr(book))
        self.assertEqual(repr(book), "Book()")
        self.assertTrue(matches(book, "phone", HEX))
        self.assertFalse(matches(book, "phone", OTHER))
        self.assertFalse(matches(book, "phone", ""))
        self.assertFalse(matches(book, "laptop", HEX))
        self.assertEqual(names(book), (PHONE,))
        shown = show(book, "phone")
        self.assertEqual(shown.reason, "value_hidden")
        self.assertEqual(shown.name, PHONE)
        self.assertNotIn(HEX, repr(shown))
        self.assertEqual(for_machine(book, "phone").name, PHONE)
        chat = _record(book, actor="chat", supplied=TOKEN, confirmed=True)
        self.assertEqual(chat.reason, "board_only")
        self.assertEqual(chat.name, PHONE)
        self.assertNotIn(TOKEN, repr(chat))
        self.assertNotIn("abcd", repr(chat))
        self.assertTrue(matches(book, "phone", HEX))

    def test_a_second_record_keeps_the_first_and_laptop_does_not_share_it(self) -> None:
        book = Book()
        rng = Seq((HEX, OTHER))
        first = record_key(book, "phone", actor="board", rng=rng)
        self.assertEqual(first.reason, "name_only")
        again = record_key(book, "phone", actor="board", rng=rng, confirmed=True)
        self.assertEqual(again.reason, "name_only")
        self.assertEqual(rng.calls, 1)
        self.assertTrue(matches(book, "phone", HEX))
        self.assertFalse(matches(book, "phone", OTHER))
        caller = record_key(book, "phone", actor="board", rng=rng, supplied="pasted")
        self.assertEqual(caller.reason, "caller_value")
        self.assertEqual(caller.name, PHONE)
        self.assertNotIn("pasted", repr(caller))
        self.assertTrue(matches(book, "phone", HEX))
        poisoned = record_key(book, "phone", actor="board", rng=rng, supplied=TOKEN)
        self.assertEqual(poisoned.reason, "name_only")
        self.assertNotIn(TOKEN, repr(poisoned))
        self.assertNotIn("abcd", repr(poisoned))
        self.assertTrue(matches(book, "phone", HEX))

        laptop = record_key(book, "laptop", actor="board", rng=Seq((HEX, OTHER)))
        self.assertEqual(laptop.name, LAPTOP)
        self.assertTrue(matches(book, "laptop", OTHER))
        self.assertFalse(matches(book, "laptop", HEX))
        self.assertTrue(matches(book, "phone", HEX))
        self.assertEqual(names(book), (PHONE, LAPTOP))
        stuck = Book()
        record_key(stuck, "phone", actor="board", rng=Seq((HEX,)))
        refused = record_key(stuck, "laptop", actor="board", rng=Seq((HEX, HEX)))
        self.assertEqual(refused.reason, "not_minted")
        self.assertEqual(names(stuck), (PHONE,))
        self.assertFalse(matches(stuck, "laptop", HEX))

    def test_a_caller_value_or_a_credential_draw_is_not_stored(self) -> None:
        book = Book()
        for supplied in (KEPT, TOKEN, HUNTER, "   ", True):
            refused = _record(book, supplied=supplied)
            reason = "credential" if supplied in (TOKEN, HUNTER) else "caller_value"
            self.assertEqual(refused.reason, reason)
            self.assertNotIn("abcd", repr(refused))
            self.assertNotIn("hunter22", repr(refused))
            self.assertNotIn(KEPT, repr(refused))
        self.assertEqual(names(book), ())
        self.assertFalse(matches(book, "phone", KEPT))
        leaked = _record(book, "token=abcd")
        self.assertEqual(leaked.reason, "credential")
        self.assertEqual(leaked.name, "")
        self.assertNotIn("abcd", repr(leaked))
        self.assertEqual(_record(book, "password is hunter22").reason, "credential")
        self.assertNotIn("hunter22", repr(_record(Book(), "password is hunter22")))
        self.assertEqual(_record(book, "coder-workspace").reason, "not_reused")
        self.assertEqual(_record(book, "nas").reason, "not_a_peer")
        self.assertEqual(_record(book, "box").reason, "not_a_peer")
        self.assertEqual(_record(book, " phone").reason, "peer_name")
        self.assertEqual(_record(book, "phone\n").reason, "peer_name")
        self.assertEqual(names(book), ())
        bad = _record(book, rng=Seq((HUNTER, TOKEN)))
        self.assertEqual(bad.reason, "not_minted")
        self.assertNotIn("hunter22", repr(bad))
        self.assertNotIn("abcd", repr(bad))
        self.assertEqual(_record(book, rng=Seq(("A" * 64,))).reason, "not_minted")
        self.assertEqual(_record(book, rng=Boom()).reason, "not_minted")
        self.assertEqual(_record(book, rng=None).reason, "not_minted")
        self.assertEqual(names(book), ())

        kept = _record(book, rng=Seq((KEPT,)))
        self.assertEqual(kept.reason, "name_only")
        self.assertTrue(matches(book, "phone", KEPT))
        self.assertNotIn(KEPT, repr(kept))
        self.assertNotIn(KEPT, repr(book))
        shared = Book()
        distinct = record_key(
            shared,
            "phone",
            actor="board",
            rng=Seq((HEX, OTHER)),
            notify_token=HEX,
        )
        self.assertEqual(distinct.reason, "name_only")
        self.assertTrue(matches(shared, "phone", OTHER))
        self.assertFalse(matches(shared, "phone", HEX))
        self.assertNotIn(HEX, repr(distinct))

    def test_the_key_is_not_reused_for_a_coder_machine(self) -> None:
        book = Book()
        _record(book)
        coder = for_machine(book, "coder-workspace")
        self.assertEqual(coder.reason, "not_reused")
        self.assertEqual(coder.name, "")
        self.assertFalse(coder.started)
        self.assertFalse(coder.called)
        self.assertEqual(names(book), (PHONE,))
        self.assertTrue(matches(book, "phone", HEX))
        self.assertFalse(matches(book, "coder-workspace", HEX))
        self.assertEqual(for_machine(book, "Coder-ABC").reason, "not_reused")
        self.assertEqual(for_machine(book, TOKEN).reason, "credential")
        self.assertNotIn("abcd", repr(for_machine(book, TOKEN)))
        self.assertEqual(for_machine(book, "nas").reason, "not_a_peer")
        self.assertEqual(for_machine(Book(), "phone").reason, "no_key")

    def test_a_mount_is_refused_and_the_endpoint_is_a_grant(self) -> None:
        book = Book()
        missing = _grant(book)
        self.assertEqual(missing.reason, "no_key")
        self.assertEqual(endpoint(book, "phone"), ("", "", ""))
        _record(book)
        for kind in ("filesystem", "disk", "usb", "host_network", "docker_socket"):
            refused = attach(book, actor="board", peer="phone", kind=kind, confirmed=True)
            self.assertEqual(refused.reason, "mount_refused", kind)
            self.assertFalse(refused.started)
            self.assertFalse(refused.joined)
            self.assertFalse(refused.called)
        self.assertEqual(attach(book, actor="chat", peer="phone", kind="usb").reason, "mount_refused")
        self.assertEqual(attach(book, actor="board", peer="phone", kind="shell").reason, "not_a_mount")
        secret_kind = attach(book, actor="board", peer="phone", kind=TOKEN)
        self.assertEqual(secret_kind.reason, "credential")
        self.assertNotIn("abcd", repr(secret_kind))
        self.assertTrue(matches(book, "phone", HEX))
        self.assertEqual(endpoint(book, "phone"), ("", "", ""))

        for fields in (
            {"address": "/mnt/peer"},
            {"address": "file:/etc/passwd"},
            {"address": "usb:/dev/bus/usb"},
            {"address": "https://peer.example/var/run/docker.sock"},
            {"host_network": True},
            {"host_network": "false"},
            {"network_mode": "host"},
            {"device": "/dev/bus/usb"},
        ):
            refused = _grant(book, **fields)
            self.assertEqual(refused.reason, "mount_refused")
            self.assertFalse(refused.called)
            self.assertEqual(endpoint(book, "phone"), ("", "", ""))

        self.assertEqual(_grant(book, address="https://127.0.0.1/mcp").reason, "loopback")
        self.assertEqual(_grant(book, address="https://localhost/mcp").reason, "loopback")
        self.assertEqual(_grant(book, address="https://[::1]/mcp").reason, "loopback")
        self.assertEqual(_grant(book, address="https://169.254.1.1/mcp").reason, "link_local")
        self.assertEqual(_grant(book, address="https://postgres/mcp").reason, "not_core")
        self.assertEqual(_grant(book, address="https://qdrant:6333/mcp").reason, "not_core")
        self.assertEqual(_grant(book, address="https://user:pass@peer.example/mcp").reason, "address")
        leaked = _grant(book, address="https://peer.example/?token=abcd")
        self.assertEqual(leaked.reason, "credential")
        self.assertNotIn("abcd", repr(leaked))
        self.assertEqual(endpoint(book, "phone"), ("", "", ""))

        chat = _grant(book, actor="chat", confirmed=True)
        self.assertEqual(chat.reason, "board_only")
        self.assertEqual(chat.name, PHONE)
        self.assertFalse(chat.called)
        self.assertEqual(endpoint(book, "phone"), ("", "", ""))

        granted = _grant(book, secret_ref=None, confirmed=True)
        self.assertEqual(granted.reason, "name_only")
        self.assertEqual(granted.name, PHONE)
        self.assertFalse(granted.started)
        self.assertFalse(granted.joined)
        self.assertFalse(granted.called)
        self.assertEqual(endpoint(book, "phone"), (URL, PHONE, "media"))
        self.assertEqual(tools_of(book, "phone"), (("recall", "off"), ("status", "off")))
        self.assertNotIn(HEX, repr(granted))

        pasted = _grant(book, secret_ref="pasted-secret")
        self.assertEqual(pasted.reason, "caller_value")
        self.assertNotIn("pasted-secret", repr(pasted))
        self.assertEqual(endpoint(book, "phone"), (URL, PHONE, "media"))
        poisoned = _grant(book, address=TOKEN)
        self.assertEqual(poisoned.reason, "name_only")
        self.assertNotIn(TOKEN, repr(poisoned))
        self.assertEqual(endpoint(book, "phone")[0], URL)
        listed = _grant(book, tools="recall")
        self.assertEqual(listed.reason, "tool_list")
        self.assertEqual(tools_of(book, "phone"), (("recall", "off"), ("status", "off")))
        replaced = _grant(book, address="https://other.example/mcp", tools=["other"])
        self.assertEqual(replaced.reason, "name_only")
        self.assertEqual(endpoint(book, "phone"), (URL, PHONE, "media"))
        self.assertEqual(tools_of(book, "phone"), (("recall", "off"), ("status", "off")))

    def test_a_tool_stays_off_until_the_board_accepts_that_name(self) -> None:
        book = Book()
        _record(book)
        _grant(book)
        chat = accept_tool(book, actor="chat", peer="phone", name="recall", confirmed=True)
        self.assertEqual(chat.reason, "board_only")
        self.assertFalse(chat.called)
        self.assertEqual(tools_of(book, "phone"), (("recall", "off"), ("status", "off")))
        accepted = accept_tool(book, actor="board", peer="phone", name="recall", confirmed=True)
        self.assertEqual(accepted.reason, "owner_accepted")
        self.assertEqual(accepted.name, "recall")
        self.assertFalse(accepted.started)
        self.assertFalse(accepted.called)
        self.assertEqual(tools_of(book, "phone"), (("recall", "on"), ("status", "off")))
        other = accept_tool(book, actor="board", peer="phone", name="other")
        self.assertEqual(other.reason, "not_listed")
        self.assertEqual(tools_of(book, "phone"), (("recall", "on"), ("status", "off")))
        refused = accept_tool(book, actor="chat", peer="phone", name="status", confirmed=True)
        self.assertEqual(refused.reason, "board_only")
        self.assertEqual(tools_of(book, "phone"), (("recall", "on"), ("status", "off")))
        secret = accept_tool(book, actor="board", peer="phone", name=TOKEN)
        self.assertEqual(secret.reason, "credential")
        self.assertNotIn("abcd", repr(secret))
        self.assertEqual(tools_of(book, "phone"), (("recall", "on"), ("status", "off")))
        self.assertEqual(_grant(book, tools=["status"]).reason, "name_only")
        self.assertEqual(tools_of(book, "phone"), (("recall", "on"), ("status", "off")))

    def test_the_kept_sentence_can_be_an_address_and_the_ask_path_stays_put(self) -> None:
        book = Book()
        _record(book, rng=Seq((OTHER,)))
        granted = _grant(book, address=KEPT, role=KEPT, tools=[])
        self.assertEqual(granted.reason, "name_only")
        self.assertEqual(endpoint(book, "phone"), (KEPT, PHONE, KEPT))
        self.assertNotIn(KEPT, repr(granted))
        self.assertNotIn(KEPT, repr(book))
        self.assertEqual(tools_of(book, "phone"), ())
        lan = Book()
        _record(lan)
        local = _grant(lan, address="https://192.168.1.9/mcp")
        self.assertEqual(local.reason, "name_only")
        self.assertFalse(local.called)
        self.assertFalse(local.joined)
        self.assertEqual(endpoint(lan, "phone")[0], "https://192.168.1.9/mcp")

        previous = os.environ.get(PHONE)
        os.environ[PHONE] = "preset-value"
        try:
            fresh = Book()
            self.assertEqual(_record(fresh, rng=Boom()).reason, "not_minted")
            self.assertEqual(os.environ[PHONE], "preset-value")
            self.assertFalse(matches(fresh, "phone", "preset-value"))
            _record(fresh)
            self.assertEqual(os.environ[PHONE], "preset-value")
            self.assertFalse(matches(fresh, "phone", "preset-value"))
            self.assertTrue(matches(fresh, "phone", HEX))
        finally:
            if previous is None:
                os.environ.pop(PHONE, None)
            else:
                os.environ[PHONE] = previous
        source = inspect.getsource(peers)
        self.assertNotIn("os.environ", source)
        self.assertNotIn("import socket", source)
        self.assertNotIn("urlopen", source)
        self.assertNotIn("psycopg", source)
        self.assertNotIn("sqlite3", source)
        self.assertNotIn("HEADSCALE_URL", source)
        ask = Path("friday/ask.py").read_text(encoding="utf-8")
        self.assertNotIn("doors.peers", ask)
        self.assertNotIn("record_key", ask)
        page = Path("board/server.js").read_text(encoding="utf-8")
        self.assertNotIn("MESH_PREAUTH", page)
        self.assertNotIn("doors/peers", page)


if __name__ == "__main__":
    unittest.main()
