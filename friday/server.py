"""Friday's HTTP process. It has no host port in Compose.

/ask recalls through the memory service and, when the owner asked for a
sensitive step, records a waiting task. It never calls the approval
endpoint.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from friday.ask import Answer, ask
from friday.model import embed_ok, post, prepare_chat, read_reply, resolve_host
from memoryd.store import Decision
from runtime.http import header, same

REQUIRED = ("FRIDAY_NOTIFY_TOKEN", "MEMORY_TOKEN")


def ready_secrets(env: dict[str, str]) -> str:
    if any(not env.get(name) for name in REQUIRED):
        return "secrets"
    return ""


def app(env: dict[str, str], *, notes=None, model=None, embed=None, tasks=None):
    charters = Path(env.get("CHARTERS_DIR", "/soul/agents"))
    soul_path = Path(env.get("SOUL_PATH", "/soul/SOUL.md"))

    def handle(method: str, path: str, headers, payload: dict) -> tuple[int, dict]:
        if path == "/health" and method == "GET":
            return 200, {"outcome": "ok", "reason": "health"}
        secret = ready_secrets(env)
        if path == "/ready" and method == "GET":
            if secret:
                return 503, {"outcome": "refused", "reason": secret}
            reason = _embed(env, embed)
            if reason:
                return 503, {"outcome": "refused", "reason": reason}
            return 200, {"outcome": "ok", "reason": "ready"}
        token = header(headers, "Friday-Notify")
        expected = env.get("FRIDAY_NOTIFY_TOKEN", "")
        if not expected or not token or not same(token, expected):
            return 401, {"outcome": "refused", "reason": "unauthenticated"}
        if secret:
            return 503, {"outcome": "refused", "reason": secret}
        if path != "/ask" or method != "POST":
            return 404, {"outcome": "refused", "reason": "unknown_path"}
        reason = _embed(env, embed)
        if reason:
            return 503, {"outcome": "refused", "reason": reason}
        answer = ask(
            text=str(payload.get("text") or ""),
            owner_id=str(payload.get("owner_id") or env.get("OWNER_ID") or "owner"),
            owner_kind=str(payload.get("owner_kind") or "person"),
            charters_dir=charters,
            soul_text=_soul(soul_path),
            recall=lambda **kwargs: _recall(env, notes, **kwargs),
            save=lambda **kwargs: _save(env, notes, **kwargs),
            model=lambda messages: _model(env, model, messages),
            embed_reason="",
            bootstrap=payload.get("bootstrap") is True,
            record_task=lambda **kwargs: _task(env, tasks, **kwargs),
        )
        status = 200 if answer.outcome in {"spoken", "waiting"} else 403
        return status, _public(answer)

    return handle


def _public(answer: Answer) -> dict:
    body = {
        "outcome": answer.outcome,
        "reason": answer.reason,
        "reply": answer.reply,
        "role": answer.role,
    }
    if answer.action:
        body["action"] = answer.action
        body["target"] = answer.target
        body["payload_digest"] = answer.payload_digest
    return body


def _soul(path: Path) -> str:
    if path.is_file():
        return path.read_text(encoding="utf-8")
    return "You are Friday."


def _embed(env: dict[str, str], embed) -> str:
    if embed is not None:
        return embed()
    return embed_ok(env.get("OLLAMA_URL", ""), lambda url, body: post(url, {"Content-Type": "application/json"}, body))


def _recall(env, notes, **kwargs):
    if notes is not None:
        return notes.recall(**kwargs)
    return _remote(env, "/recall", kwargs)


def _save(env, notes, **kwargs):
    if notes is not None:
        return notes.save(**kwargs)
    return _remote(env, "/save", kwargs)


def _remote(env, path: str, payload: dict) -> Decision:
    url = env.get("MEMORY_URL", "http://memory-mcp:8080").rstrip("/") + path
    raw = json.dumps(payload).encode()
    request = Request(
        url,
        data=raw,
        headers={
            "Content-Type": "application/json",
            "Friday-Memory": env.get("MEMORY_TOKEN", ""),
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=10) as response:
            data = json.loads(response.read())
    except HTTPError as exc:
        try:
            data = json.loads(exc.read())
        except (json.JSONDecodeError, OSError):
            return Decision("refused", "memory_unreachable")
    except OSError:
        return Decision("refused", "memory_unreachable")
    notes = tuple(data.get("notes") or ())
    return Decision(
        data.get("outcome", "refused"),
        data.get("reason", "memory"),
        notes=notes,
        note_id=data.get("id"),
        revision=data.get("revision"),
    )


def _model(env, model, messages):
    if model is not None:
        return model(messages)
    prepared = prepare_chat(
        env.get("MODEL_BASE_URL", ""),
        env.get("MODEL_API_KEY", ""),
        messages,
        resolve_host,
    )
    if isinstance(prepared, str):
        raise OSError(prepared)
    url, headers, body = prepared
    return read_reply(post(url, headers, body))


def _task(env, tasks, **kwargs) -> None:
    if tasks is not None:
        tasks.append(kwargs)
        return
    url = env.get("EXECUTOR_URL", "").rstrip("/")
    if not url:
        return
    raw = json.dumps(
        {
            "owner_id": kwargs["owner_id"],
            "role_id": kwargs["role_id"],
            "goal": kwargs["goal"],
            "steps": [{"name": kwargs["action"], "state": "pending"}],
        }
    ).encode()
    request = Request(
        url + "/tasks",
        data=raw,
        headers={
            "Content-Type": "application/json",
            "Friday-Notify": env.get("FRIDAY_NOTIFY_TOKEN", ""),
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=10):
            return
    except OSError:
        return


def main() -> None:
    from runtime.http import serve

    env = dict(os.environ)
    reason = ready_secrets(env)
    if reason:
        raise SystemExit(f"friday: {reason}")
    host = env.get("BIND_HOST", "0.0.0.0")
    port = int(env.get("PORT", "8080"))
    serve(app(env), host, port).serve_forever()
