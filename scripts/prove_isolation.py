"""Say whether a TCP port accepts a connection.

Usage: prove_isolation.py open|closed HOST PORT

Prints open or closed. Exits 0 when that word matches the request.
A refused connection, a missing name, and a timeout are closed.
"""

from __future__ import annotations

import socket
import sys


def outcome(host: str, port: int, timeout: float = 2) -> str:
    sock = socket.socket()
    sock.settimeout(timeout)
    try:
        sock.connect((host, port))
    except OSError:
        return "closed"
    else:
        return "open"
    finally:
        sock.close()


def main(argv: list[str]) -> int:
    if len(argv) != 4 or argv[1] not in {"open", "closed"}:
        return 2
    try:
        port = int(argv[3])
    except ValueError:
        return 2
    if port <= 0 or port > 65535:
        return 2
    got = outcome(argv[2], port)
    print(got)
    return 0 if got == argv[1] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
