"""The TCP probe used by scripts/prove-isolation.sh. No Docker network."""

from __future__ import annotations

import socket
import subprocess
import sys
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "prove_isolation.py"


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        check=False,
        capture_output=True,
        text=True,
    )


class IsolationProbeTests(unittest.TestCase):
    def test_an_open_port_reports_open_and_a_refused_port_reports_closed(self) -> None:
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = str(server.getsockname()[1])
        try:
            opened = run("open", "127.0.0.1", port)
            self.assertEqual(opened.returncode, 0)
            self.assertEqual(opened.stdout.strip(), "open")
        finally:
            server.close()
        closed = run("closed", "127.0.0.1", port)
        self.assertEqual(closed.returncode, 0)
        self.assertEqual(closed.stdout.strip(), "closed")
        mismatch = run("open", "127.0.0.1", port)
        self.assertEqual(mismatch.returncode, 1)
        self.assertEqual(mismatch.stdout.strip(), "closed")

    def test_a_bad_request_exits_without_connecting(self) -> None:
        self.assertEqual(run().returncode, 2)
        self.assertEqual(run("open", "127.0.0.1", "0").returncode, 2)
        self.assertEqual(run("sideways", "127.0.0.1", "1").returncode, 2)
