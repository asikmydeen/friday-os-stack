"""POST one JSON body to Friday, and check the address first.

Friday is the only host these callers may use. Redirects are refused.
The token is a header and is not copied into an error. BIND_HOST=core
is refused: these processes are not on the core network.
"""

from __future__ import annotations

import json
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


def listen_host(env: dict[str, str]) -> str:
    host = env.get("BIND_HOST", "0.0.0.0") or "0.0.0.0"
    if host == "core":
        raise OSError("core_address")
    return host


def friday_base(raw: str) -> str:
    parts = urlsplit((raw or "").strip())
    if parts.scheme != "http" or parts.hostname != "friday" or parts.port != 8080:
        raise OSError("friday_url")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise OSError("friday_url")
    if parts.path not in {"", "/"}:
        raise OSError("friday_url")
    return "http://friday:8080"


class _RefuseRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        raise OSError("redirect")


def post_json(url: str, header_name: str, token: str, payload: dict) -> tuple[int, dict]:
    raw = json.dumps(payload).encode()
    request = Request(
        url,
        data=raw,
        headers={"Content-Type": "application/json", header_name: token},
        method="POST",
    )
    opener = build_opener(_RefuseRedirect)
    try:
        with opener.open(request, timeout=20) as response:
            body = json.loads(response.read())
            status = response.status
    except HTTPError as exc:
        try:
            body = json.loads(exc.read())
        except (json.JSONDecodeError, OSError):
            raise OSError("friday_unreachable") from None
        status = exc.code
    except (OSError, json.JSONDecodeError):
        raise OSError("friday_unreachable") from None
    if not isinstance(body, dict):
        raise OSError("friday_unreachable")
    return status, body
