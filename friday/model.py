"""OpenAI-compatible chat and the local embed check.

The key travels in a header. It is not written into the prompt. The URL
rules match the setup page: http(s), no userinfo, and no link-local,
metadata, multicast, unspecified, or reserved address.
"""

from __future__ import annotations

import json
import socket
from typing import Callable
from urllib.request import Request, urlopen

from image.setup import chat_url, embed_length, reply_text, vet_base

EMBED_MODEL = "nomic-embed-text"
EMBED_DIM = 768
Resolve = Callable[[str], list[str]]


def resolve_host(host: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except OSError:
        return []
    found: list[str] = []
    for item in infos:
        address = item[4][0]
        if address not in found:
            found.append(address)
    return found


def prepare_chat(
    base: str,
    key: str,
    messages: list[dict],
    resolve: Resolve,
) -> tuple[str, dict, bytes] | str:
    reason = vet_base(base, resolve)
    if reason:
        return reason
    if not key:
        return "model_required"
    body = json.dumps(
        {"model": "friday", "messages": messages},
        separators=(",", ":"),
    ).encode()
    if key.encode() in body:
        return "model_key_in_prompt"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}",
    }
    return chat_url(base), headers, body


def read_reply(raw: bytes) -> str:
    return reply_text(raw)


def embed_ok(base: str, transport: Callable[[str, bytes], bytes]) -> str:
    if not base:
        return "embed_not_ready"
    url = base.rstrip("/") + "/api/embeddings"
    body = json.dumps(
        {"model": EMBED_MODEL, "prompt": "friday"},
        separators=(",", ":"),
    ).encode()
    try:
        raw = transport(url, body)
    except OSError:
        return "embed_not_ready"
    if embed_length(raw) != EMBED_DIM:
        return "embed_dimensions"
    return ""


def post(url: str, headers: dict, body: bytes, timeout: float = 30) -> bytes:
    request = Request(url, data=body, headers=headers, method="POST")
    with urlopen(request, timeout=timeout) as response:
        return response.read()
