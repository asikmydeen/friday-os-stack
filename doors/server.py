"""Deliver one turn to Friday. This process cannot approve.

It listens only when DOOR_ENABLED is yes. The caller presents Friday-Door.
The process calls Friday's /ask with Friday-Notify and forwards only the
reply fields. It has no executor URL and no Postgres URL. confirmed=true
is dropped before this handler runs.
"""

from __future__ import annotations

import os

from runtime.forward import friday_base, listen_host, post_json
from runtime.http import header, same

PUBLIC = ("outcome", "reason", "reply", "role", "action", "target", "payload_digest")


def listening(env: dict[str, str]) -> bool:
    return env.get("DOOR_ENABLED") == "yes"


def app(env: dict[str, str], ask_url: str, send):
    def handle(method: str, path: str, headers, payload: dict) -> tuple[int, dict]:
        if path == "/health" and method == "GET":
            return 200, {"outcome": "ok", "reason": "health"}
        if not listening(env):
            return 403, {"outcome": "refused", "reason": "door_off"}
        token = env.get("DOOR_TOKEN", "")
        presented = header(headers, "Friday-Door")
        if not token or not presented or not same(presented, token):
            return 401, {"outcome": "refused", "reason": "unauthenticated"}
        if path != "/turn" or method != "POST":
            return 404, {"outcome": "refused", "reason": "unknown_path"}
        text = str(payload.get("text") or "").strip()
        owner_id = str(payload.get("owner_id") or "").strip()
        owner_kind = str(payload.get("owner_kind") or "person")
        if not text or not owner_id or owner_kind not in {"person", "role"}:
            return 400, {"outcome": "refused", "reason": "turn"}
        try:
            status, body = send(
                ask_url,
                env.get("FRIDAY_NOTIFY_TOKEN", ""),
                {"text": text, "owner_id": owner_id, "owner_kind": owner_kind},
            )
        except OSError:
            return 502, {"outcome": "refused", "reason": "friday_unreachable"}
        if status not in {200, 202, 403}:
            return 502, {"outcome": "refused", "reason": "friday_unreachable"}
        return status, _public(body)

    return handle


def _public(body: dict) -> dict:
    out = {}
    for key in PUBLIC:
        value = body.get(key)
        if value not in (None, ""):
            out[key] = value
    if "outcome" not in out:
        return {"outcome": "refused", "reason": "friday_unreachable"}
    return out


def main() -> None:
    from runtime.http import serve

    env = dict(os.environ)
    if not listening(env):
        raise SystemExit(0)
    if not env.get("DOOR_TOKEN") or not env.get("FRIDAY_NOTIFY_TOKEN"):
        raise SystemExit("door: secrets")
    try:
        ask_url = friday_base(env.get("FRIDAY_URL", "http://friday:8080")) + "/ask"
        host = listen_host(env)
    except OSError as exc:
        raise SystemExit(f"door: {exc}") from None
    port = int(env.get("PORT", "8080"))

    def send(url: str, token: str, payload: dict) -> tuple[int, dict]:
        return post_json(url, "Friday-Notify", token, payload)

    serve(app(env, ask_url, send), host, port).serve_forever()
