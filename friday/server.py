"""Friday's HTTP process. It has no host port in Compose.

/ask recalls through the memory service. Knowledge and findings come
from POST /hub on that service and join the same pack of at most 8.
A hub that is not ready leaves the note pack unchanged. A spoken turn
writes one episode through the same save. A credential-shaped turn is
not stored. /recall returns that owner's notes and nothing else. It
does not add hub notes. A sensitive step records a waiting task and
does not search. It never calls the approval endpoint. When a state
book is open, a spoken or waiting turn is written there after the
reply. The raw tool result is not that row. GET /announcements reads
the webhook receiver's fixed sentences. The raw body is not copied.
Ask does not call that read.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import urllib.request
from urllib.error import HTTPError
from urllib.parse import unquote_plus
from urllib.request import Request, urlopen

from friday.announce import spoken
from friday.ask import Answer, ask
from friday.durable import persist
from friday.hat import Hats
from friday.model import embed_ok, post, prepare_chat, read_reply, resolve_host
from friday.state import record_turn
from memoryd.store import RECALL_CAP, Decision, credential_shape
from runtime.http import header, same

REQUIRED = ("FRIDAY_NOTIFY_TOKEN", "MEMORY_TOKEN")


def ready_secrets(env: dict[str, str]) -> str:
    if any(not env.get(name) for name in REQUIRED):
        return "secrets"
    return ""


def app(env: dict[str, str], *, notes=None, model=None, embed=None, tasks=None, hub=None, state=None, events=None):
    charters = Path(env.get("CHARTERS_DIR", "/soul/agents"))
    soul_path = Path(env.get("SOUL_PATH", "/soul/SOUL.md"))
    hats = Hats()

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
        if path == "/recall" and method == "POST":
            return _recall_http(env, notes, embed, payload)
        if path == "/announcements" and method == "GET":
            return _announcements(env, events)
        if path == "/announcements":
            return 405, {"outcome": "refused", "reason": "method_refused", "announcements": [], "started": False, "sent": False}
        if path != "/ask" or method != "POST":
            return 404, {"outcome": "refused", "reason": "unknown_path"}
        reason = _embed(env, embed)
        if reason:
            return 503, {"outcome": "refused", "reason": reason}
        think_turn = payload.get("think") is True
        question = "" if payload.get("bootstrap") is True else str(payload.get("text") or "")
        owner_id = str(payload.get("owner_id") or env.get("OWNER_ID") or "owner")
        answer = ask(
            text=str(payload.get("text") or ""),
            owner_id=owner_id,
            owner_kind=str(payload.get("owner_kind") or "person"),
            charters_dir=charters,
            soul_text=_soul(soul_path),
            recall=lambda **kwargs: _ask_recall(env, notes, hub, question, **kwargs),
            save=lambda **kwargs: _save(env, notes, **kwargs),
            model=lambda messages: _model(env, model, messages, think_turn=think_turn),
            embed_reason="",
            bootstrap=payload.get("bootstrap") is True,
            record_task=lambda **kwargs: _task(env, tasks, **kwargs),
            hats=hats,
            tool_results=payload.get("tool_results"),
        )
        if state is not None and answer.outcome in {"spoken", "waiting"}:
            _conversation(state, owner_id, answer.role or "friday", "owner", question)
            _conversation(state, owner_id, answer.role or "friday", "friday", answer.reply)
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


def _recall_http(env, notes, embed, payload: dict) -> tuple[int, dict]:
    reason = _embed(env, embed)
    if reason:
        return 503, {"outcome": "refused", "reason": reason}
    owner_id = str(payload.get("owner_id") or "").strip()
    owner_kind = str(payload.get("owner_kind") or "person")
    packed = _recall(env, notes, owner_id=owner_id, owner_kind=owner_kind)
    if packed.outcome != "ok":
        return 403, {"outcome": "refused", "reason": packed.reason}
    public = []
    for note in packed.notes[:8]:
        public.append({
            "id": str(note.get("id") or ""),
            "content": str(note.get("content") or "")[:1200],
        })
    return 200, {"outcome": "ok", "reason": "recall", "notes": public}


def _ask_recall(env, notes, hub, question, **kwargs):
    packed = _recall(env, notes, **kwargs)
    if packed.outcome != "ok":
        return packed
    extra = _hub_notes(
        env,
        notes,
        hub,
        question,
        kwargs.get("owner_id"),
        kwargs.get("owner_kind"),
    )
    if not extra:
        return packed
    return Decision(packed.outcome, packed.reason, notes=_pack(packed.notes, extra))


def _hub_notes(env, notes, hub, question, owner_id, owner_kind):
    """Notes from knowledge and findings. A miss does not fail the turn."""
    if not isinstance(question, str) or question.strip() == "" or _secret(question):
        return ()
    if not isinstance(owner_id, str) or not isinstance(owner_kind, str):
        return ()
    try:
        if hub is not None:
            decision = hub(owner_id, owner_kind, question)
        elif notes is not None:
            return ()
        else:
            decision = _remote(
                env,
                "/hub",
                {"owner_id": owner_id, "owner_kind": owner_kind, "text": question},
            )
    except OSError:
        return ()
    if not isinstance(decision, Decision) or decision.outcome != "ok":
        return ()
    return tuple(decision.notes)


def _pack(primary, extra) -> tuple:
    seen: set[str] = set()
    packed = []
    for note in tuple(primary) + tuple(extra):
        if not isinstance(note, dict):
            continue
        content = note.get("content")
        if not isinstance(content, str):
            continue
        shown = " ".join(content.replace("\n", " ").split())[:1200]
        if shown == "" or _secret(shown):
            continue
        ident = note.get("id") if isinstance(note.get("id"), str) and note.get("id").strip() else shown
        if _secret(ident) or ident in seen:
            continue
        seen.add(ident)
        row = {"content": shown}
        if isinstance(note.get("id"), str) and note["id"].strip() and not _secret(note["id"]):
            row["id"] = note["id"]
        packed.append(row)
        if len(packed) >= RECALL_CAP:
            break
    return tuple(packed)


def _secret(text: str) -> bool:
    seen = text
    for _ in range(3):
        if credential_shape(" ".join(seen.split())):
            return True
        decoded = unquote_plus(seen)
        if decoded == seen:
            return False
        seen = decoded
    return credential_shape(" ".join(seen.split()))


def _recall(env, notes, **kwargs):
    if notes is not None:
        return notes.recall(**kwargs)
    return _remote(env, "/recall", kwargs)


def _save(env, notes, **kwargs):
    if notes is not None:
        return notes.save(**kwargs)
    return _remote(env, "/save", kwargs)


def _announcements(env, events) -> tuple[int, dict]:
    read = events
    if read is None:
        raw_url = env.get("WEBHOOK_URL", "")
        if raw_url == "":
            return 200, _event_body("unset", [])
        if raw_url != "http://webhooks:8080":
            return 403, _event_body("url", [])
        read = lambda: _fetch_announcements(env)
    try:
        rows = read()
    except OSError:
        return 503, _event_body("webhooks", [])
    kept = spoken(rows)
    return 200, _event_body("announced", kept)


def _event_body(reason: str, rows: list[dict]) -> dict:
    return {
        "outcome": "ok" if reason in {"unset", "announced"} else "refused",
        "reason": reason,
        "announcements": rows,
        "started": False,
        "sent": False,
    }


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def _fetch_announcements(env) -> list:
    request = Request(
        "http://webhooks:8080/announcements",
        headers={"Friday-Notify": env.get("FRIDAY_NOTIFY_TOKEN", "")},
        method="GET",
    )
    opener = urllib.request.build_opener(_NoRedirect())
    try:
        with opener.open(request, timeout=10) as response:
            raw = response.read(8192)
            status = getattr(response, "status", 200)
    except HTTPError as exc:
        exc.read(8192)
        raise OSError("webhooks") from None
    except OSError:
        raise OSError("webhooks") from None
    if status != 200:
        raise OSError("webhooks")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise OSError("webhooks") from None
    rows = data.get("announcements") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return []
    return rows


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


def _model(env, model, messages, *, think_turn: bool = False):
    if model is not None:
        return model(messages)
    prepared = prepare_chat(
        env.get("MODEL_BASE_URL", ""),
        env.get("MODEL_API_KEY", ""),
        messages,
        resolve_host,
        fast=env.get("MODEL_FAST", ""),
        think=env.get("MODEL_THINK", ""),
        think_turn=think_turn,
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


def _conversation(book, owner_id: str, role: str, speaker: str, text: str) -> None:
    if not isinstance(text, str) or text.strip() == "":
        return
    persist(
        book,
        record_turn,
        actor="friday",
        owner_id=owner_id,
        speaker=speaker,
        role=role,
        text=text,
    )


def main() -> None:
    from friday.durable import state_from_env
    from runtime.http import serve

    env = dict(os.environ)
    reason = ready_secrets(env)
    if reason:
        raise SystemExit(f"friday: {reason}")
    try:
        book = state_from_env(env)
    except OSError:
        raise SystemExit("friday: state") from None
    host = env.get("BIND_HOST", "0.0.0.0")
    port = int(env.get("PORT", "8080"))
    serve(app(env, state=book), host, port).serve_forever()
