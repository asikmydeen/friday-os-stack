"""OpenAI-compatible chat and the local embed check.

The key travels in a header. It is not written into the prompt. The URL
rules match the setup page: http(s), no userinfo, and no link-local,
metadata, multicast, unspecified, or reserved address. An ordinary turn
posts the owner's fast model name. The think name is posted only when
the caller sets think exactly true and that name is set. A
credential-shaped name is refused and is not posted. No model id is
baked in. The embed reply has to name nomic-embed-text and carry 768
numbers. Another model id is refused.
"""

from __future__ import annotations

import json
import socket
from typing import Callable
from urllib.request import Request, urlopen

from image.setup import MODEL_NAME_LIMIT as MODEL_LIMIT
from image.setup import accept_model_name, chat_url, pinned_embed, reply_text, vet_base

EMBED_MODEL = "nomic-embed-text"
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


def choose_model(fast: str, think: str = "", *, think_turn: bool = False) -> tuple[str, str]:
    """Return (name, reason). Reason is empty when name is the id to post.

    An ordinary turn uses the fast name. The think name is used only when
    think_turn is exactly true and that name is set. An empty think name
    leaves the turn on fast. The words inside the messages are not read.
    A credential-shaped name is refused and is not returned.
    """
    if think_turn is True and isinstance(think, str) and think.strip() != "":
        chosen = think
    else:
        chosen = fast
    name, reason = accept_model_name(chosen)
    if reason:
        return "", reason
    return name, ""


def prepare_chat(
    base: str,
    key: str,
    messages: list[dict],
    resolve: Resolve,
    *,
    fast: str,
    think: str = "",
    think_turn: bool = False,
) -> tuple[str, dict, bytes] | str:
    reason = vet_base(base, resolve)
    if reason:
        return reason
    if not key:
        return "model_required"
    model_name, model_reason = choose_model(fast, think, think_turn=think_turn)
    if model_reason:
        return model_reason
    body = json.dumps(
        {"model": model_name, "messages": messages},
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
    url = base.rstrip("/") + "/api/embed"
    body = json.dumps(
        {"model": EMBED_MODEL, "input": "friday"},
        separators=(",", ":"),
    ).encode()
    try:
        raw = transport(url, body)
    except OSError:
        return "embed_not_ready"
    verdict = pinned_embed(raw)
    if verdict != "ok":
        return verdict
    return ""


def post(url: str, headers: dict, body: bytes, timeout: float = 30) -> bytes:
    request = Request(url, data=body, headers=headers, method="POST")
    with urlopen(request, timeout=timeout) as response:
        return response.read()
