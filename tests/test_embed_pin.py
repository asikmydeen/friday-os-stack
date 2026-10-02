"""The embed pin is nomic-embed-text. These tests do not call Ollama."""

import importlib.util
import json
import unittest
from pathlib import Path

from friday.model import embed_ok
from image.setup import pinned_embed
from memoryd.embed import vector_from_payload


def _bootstrap():
    path = Path(__file__).resolve().parents[1] / "scripts" / "bootstrap_memory.py"
    spec = importlib.util.spec_from_file_location("bootstrap_memory_pin", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _body(model, count=768, *, nested=True):
    vector = [0] * count
    if nested:
        payload = {"model": model, "embeddings": [vector]}
    else:
        payload = {"model": model, "embedding": vector}
    return json.dumps(payload).encode()


class PinnedEmbed(unittest.TestCase):
    def test_the_pin_and_a_tag_are_accepted(self) -> None:
        self.assertEqual(pinned_embed(_body("nomic-embed-text")), "ok")
        self.assertEqual(pinned_embed(_body("nomic-embed-text:latest")), "ok")
        self.assertEqual(pinned_embed(_body("nomic-embed-text", nested=False)), "ok")

    def test_another_768_model_and_a_missing_id_are_refused(self) -> None:
        self.assertEqual(pinned_embed(_body("other-embed")), "embed_model")
        self.assertEqual(pinned_embed(_body("nomic-embed-text-extra")), "embed_model")
        self.assertEqual(pinned_embed(_body(" nomic-embed-text")), "embed_model")
        self.assertEqual(pinned_embed(_body("nomic-embed-text:")), "embed_model")
        self.assertEqual(pinned_embed(_body("nomic-embed-text:" + "a" * 65)), "embed_model")
        naked = json.dumps({"embeddings": [[0] * 768]}).encode()
        self.assertEqual(pinned_embed(naked), "embed_model")
        self.assertEqual(pinned_embed(_body("nomic-embed-text", 3)), "embed_dimensions")
        flagged = json.dumps({"model": "nomic-embed-text", "embedding": [True] + [0] * 767}).encode()
        self.assertEqual(pinned_embed(flagged), "embed_dimensions")

    def test_friday_asks_api_embed_and_refuses_the_other_model(self) -> None:
        seen = {}

        def transport(url, body):
            seen["url"] = url
            seen["body"] = body
            return _body("other-embed")

        self.assertEqual(embed_ok("http://ollama:11434", transport), "embed_model")
        self.assertTrue(seen["url"].endswith("/api/embed"))
        self.assertIn(b"nomic-embed-text", seen["body"])
        self.assertEqual(embed_ok("http://ollama:11434/", lambda url, body: _body("nomic-embed-text")), "")
        self.assertEqual(embed_ok("", lambda url, body: _body("nomic-embed-text")), "embed_not_ready")

    def test_the_memory_client_refuses_a_named_other_model(self) -> None:
        other = {"model": "other-embed", "embedding": [0] * 768}
        with self.assertRaises(OSError) as caught:
            vector_from_payload(other)
        self.assertEqual(str(caught.exception), "embed_model")
        kept = vector_from_payload({"embedding": [0] * 768})
        self.assertEqual(len(kept), 768)
        self.assertEqual(len(vector_from_payload({"model": "nomic-embed-text:latest", "embedding": [1] * 768})), 768)

    def test_bootstrap_requires_the_id_on_api_embed_only(self) -> None:
        boot = _bootstrap()
        pinned = {"model": "nomic-embed-text", "embeddings": [[0] * 768]}
        other = {"model": "other-embed", "embeddings": [[0] * 768]}
        anonymous = {"embedding": [0] * 768}
        self.assertEqual(boot.embed_verdict(pinned, require_model=True), "ok")
        self.assertEqual(boot.embed_verdict(other, require_model=True), "embed_model")
        self.assertEqual(boot.embed_verdict(anonymous, require_model=True), "embed_model")
        self.assertEqual(boot.embed_verdict(anonymous, require_model=False), "ok")
        self.assertEqual(boot.embed_verdict(other, require_model=False), "embed_model")
        short = {"model": "nomic-embed-text", "embedding": [0, 1]}
        self.assertEqual(boot.embed_verdict(short, require_model=True), "embed_dimensions")
        self.assertFalse(boot.pinned_model("nomic-embed-text:"))
        self.assertFalse(boot.pinned_model("nomic-embed-text:bad tag"))
        self.assertFalse(boot.pinned_model("nomic-embed-text:" + "a" * 65))
        self.assertTrue(boot.pinned_model("nomic-embed-text:latest"))

    def test_a_200_from_api_embed_does_not_fall_through(self) -> None:
        boot = _bootstrap()
        calls = []

        def fake(method, url, body=None, headers=None):
            calls.append(url)
            if url.endswith("/api/embed"):
                return 200, {"embeddings": [[0] * 768]}
            if url.endswith("/api/embeddings"):
                return 200, {"embedding": [0] * 768}
            raise AssertionError(url)

        boot.request = fake
        with self.assertRaises(boot.BootstrapError) as caught:
            boot.probe_embedding("http://ollama:11434")
        self.assertIn("nomic-embed-text", str(caught.exception))
        self.assertEqual(calls, ["http://ollama:11434/api/embed"])

    def test_tags_use_the_same_pin(self) -> None:
        boot = _bootstrap()

        def fake(method, url, body=None, headers=None):
            return 200, {"models": [{"name": "nomic-embed-text:bad tag"}, {"name": "other-embed"}]}

        boot.request = fake
        with self.assertRaises(boot.BootstrapError) as caught:
            boot.require_pinned_model("http://ollama:11434")
        self.assertIn("nomic-embed-text", str(caught.exception))
