"""Inbound MCP tools. Granted names are listed. Mutating calls wait.

The process listens only when MCP_ENABLED is yes. The caller presents
Friday-Harness. Recall is forwarded to Friday's /recall. A mutating tool
returns waiting and is not executed. This process does not create an
approval and does not hold the Qdrant key. confirmed=true is ignored.
"""

from __future__ import annotations

import os

from mcpbus.grants import MUTATING, inbound, visible
from runtime.forward import friday_base, listen_host, post_json
from runtime.http import header, same

OFFERED = ("recall",) + tuple(sorted(MUTATING))


def listening(env: dict[str, str]) -> bool:
    return env.get("MCP_ENABLED") == "yes"


def granted_names(env: dict[str, str]) -> tuple[str, ...]:
    raw = env.get("GRANTED_TOOLS", "")
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def app(env: dict[str, str], recall_url: str, send):
    granted = granted_names(env)

    def handle(method: str, path: str, headers, payload: dict) -> tuple[int, dict]:
        if path == "/health" and method == "GET":
            return 200, {"outcome": "ok", "reason": "health"}
        if not listening(env):
            return 403, {"outcome": "refused", "reason": "mcp_off"}
        token = env.get("MCP_TOKEN", "")
        presented = header(headers, "Friday-Harness")
        if not token or not presented or not same(presented, token):
            return 401, {"outcome": "refused", "reason": "unauthenticated"}
        if path != "/mcp" or method != "POST":
            return 404, {"outcome": "refused", "reason": "unknown_path"}
        rpc_id = payload.get("id")
        rpc_method = str(payload.get("method") or "")
        if rpc_method == "tools/list":
            names = visible(granted, OFFERED)
            return 200, _rpc(rpc_id, {"tools": [{"name": name} for name in names]})
        if rpc_method != "tools/call":
            return 404, _refused(rpc_id, "unknown_method")
        params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
        params.pop("confirmed", None)
        name = str(params.get("name") or "")
        decision = inbound(name, granted, OFFERED)
        if decision.outcome == "waiting":
            return 202, _rpc(rpc_id, {"outcome": "waiting", "reason": decision.reason, "started": False})
        if decision.outcome != "allowed":
            return 403, _refused(rpc_id, decision.reason)
        if name != "recall":
            return 403, _refused(rpc_id, "not_forwarded")
        arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        arguments.pop("confirmed", None)
        owner_id = str(arguments.get("owner_id") or "").strip()
        owner_kind = str(arguments.get("owner_kind") or "person")
        if not owner_id or owner_kind not in {"person", "role"}:
            return 403, _refused(rpc_id, "missing_owner")
        try:
            status, body = send(
                recall_url,
                env.get("FRIDAY_NOTIFY_TOKEN", ""),
                {"owner_id": owner_id, "owner_kind": owner_kind},
            )
        except OSError:
            return 502, _refused(rpc_id, "friday_unreachable")
        if status != 200 or body.get("outcome") != "ok":
            reason = str(body.get("reason") or "friday_unreachable")
            return 502, _refused(rpc_id, reason)
        return 200, _rpc(rpc_id, {"outcome": "ok", "reason": "recall", "notes": _notes(body)})

    return handle


def _notes(body: dict) -> list[dict]:
    found = []
    for note in list(body.get("notes") or [])[:8]:
        if not isinstance(note, dict):
            continue
        found.append({
            "id": str(note.get("id") or ""),
            "content": str(note.get("content") or "")[:1200],
        })
    return found


def _rpc(rpc_id, result: dict) -> dict:
    body = {"jsonrpc": "2.0", "id": rpc_id, "result": result, "outcome": result.get("outcome", "ok")}
    if "reason" in result:
        body["reason"] = result["reason"]
    return body


def _refused(rpc_id, reason: str) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "error": {"code": -32003, "message": reason},
        "outcome": "refused",
        "reason": reason,
    }


def main() -> None:
    from runtime.http import serve

    env = dict(os.environ)
    if not listening(env):
        raise SystemExit(0)
    if not env.get("MCP_TOKEN") or not env.get("FRIDAY_NOTIFY_TOKEN"):
        raise SystemExit("mcp: secrets")
    try:
        recall_url = friday_base(env.get("FRIDAY_URL", "http://friday:8080")) + "/recall"
        host = listen_host(env)
    except OSError as exc:
        raise SystemExit(f"mcp: {exc}") from None
    port = int(env.get("PORT", "8080"))

    def send(url: str, token: str, payload: dict) -> tuple[int, dict]:
        return post_json(url, "Friday-Notify", token, payload)

    serve(app(env, recall_url, send), host, port).serve_forever()
