"""HTTP checks for the throwaway reach proof, plus the core-side listeners.

Usage:
  prove_reach.py hold
  prove_reach.py get URL WANT
  prove_reach.py post URL WANT ABSENT

hold listens on 5432 and 6333 so a leaked route is an open port.
post reads WEBHOOK_SECRET and WEBHOOK_BODY from the environment.
A refused connection is a failure. The process prints the status and body.
"""

from __future__ import annotations

import os
import socket
import sys
import threading
import urllib.error
import urllib.request


def hold() -> None:
    def listen(port: int) -> None:
        server = socket.socket()
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("0.0.0.0", port))
        server.listen()
        while True:
            client, _addr = server.accept()
            client.close()

    threading.Thread(target=listen, args=(5432,), daemon=True).start()
    listen(6333)


def _read(url: str, method: str, body: bytes | None, header: str) -> tuple[int, str]:
    headers = {}
    if header:
        headers["Friday-Webhook"] = header
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, response.read(8192).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(8192).decode("utf-8", errors="replace")


def get(url: str, want: str) -> int:
    status, text = _read(url, "GET", None, "")
    print(status)
    print(text)
    return 0 if status == 200 and want in text else 1


def post(url: str, want: str, absent: str) -> int:
    secret = os.environ.get("WEBHOOK_SECRET", "")
    body = os.environ.get("WEBHOOK_BODY", "")
    status, text = _read(url, "POST", body.encode(), secret)
    print(status)
    print(text)
    if status != 200 or want not in text or (absent and absent in text):
        return 1
    return 0


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[1] == "hold":
        hold()
        return 0
    if len(argv) == 4 and argv[1] == "get":
        return get(argv[2], argv[3])
    if len(argv) == 5 and argv[1] == "post":
        return post(argv[2], argv[3], argv[4])
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
