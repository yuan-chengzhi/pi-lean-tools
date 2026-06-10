from __future__ import annotations

import http.server
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
import urllib.parse

from pi_lean_tools.loogle_search import (
    LOOGLE_BIN_ENV,
    LOOGLE_REMOTE_ENV,
    LOOGLE_URL_ENV,
    loogle_search,
    loogle_socket_path,
)


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mini_lean_project"

CANNED_RESULT = {
    "count": 2,
    "header": "Found 2 declarations.",
    "hits": [
        {"name": "Nat.Coprime.gcd_eq_one", "type": "m.Coprime n → m.gcd n = 1", "module": "Init.Data.Nat.Coprime", "doc": None},
        {"name": "Nat.Coprime.gcd_eq_one'", "type": "...", "module": "Init.Data.Nat.Coprime", "doc": None},
    ],
}

FAKE_LOOGLE_BIN = '''#!/usr/bin/env python3
import json, sys
for line in sys.stdin:
    query = line.strip()
    if not query:
        continue
    if "bad" in query:
        sys.stdout.write(json.dumps({"error": "unknown identifier", "suggestions": ["Nat.gcd"]}) + "\\n")
    else:
        sys.stdout.write(json.dumps({
            "count": 1, "header": "Found 1 declaration.",
            "hits": [{"name": "Nat.Coprime.gcd_eq_one", "type": "t", "module": "m", "doc": None}],
        }) + "\\n")
    sys.stdout.flush()
'''


class _FakeLoogleHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - http.server API
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query).get("q", [""])[0]
        if parsed.path != "/json":
            self.send_error(404)
            return
        payload = {"error": "cannot parse", "suggestions": ['"gcd"']} if "bad" in query else CANNED_RESULT
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        pass


def _start_fake_server() -> tuple[http.server.HTTPServer, str]:
    server = http.server.HTTPServer(("127.0.0.1", 0), _FakeLoogleHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_port}"


def _clean_env() -> mock._patch_dict:
    return mock.patch.dict(
        os.environ,
        {LOOGLE_URL_ENV: "", LOOGLE_BIN_ENV: "/nonexistent/loogle", LOOGLE_REMOTE_ENV: ""},
        clear=False,
    )


class LoogleSearchServerBackendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server, self.url = _start_fake_server()
        self.addCleanup(self.server.shutdown)

    def test_no_backend_when_nothing_configured(self) -> None:
        with _clean_env():
            payload = loogle_search(project_root=FIXTURE, query="Nat.Coprime", verify_names=False)
        self.assertEqual(payload["status"], "no_backend")
        self.assertIn("decl_search", payload["data"]["note"])

    def test_server_backend_returns_hits(self) -> None:
        with _clean_env(), mock.patch.dict(os.environ, {LOOGLE_URL_ENV: self.url}):
            payload = loogle_search(project_root=FIXTURE, query="Nat.Coprime _ _", verify_names=False)
        self.assertEqual(payload["status"], "searched")
        self.assertEqual(payload["data"]["hits"][0]["name"], "Nat.Coprime.gcd_eq_one")
        self.assertTrue(payload["data"]["backend"].startswith("server:"))
        self.assertFalse(payload["authority"]["usable_as_proof_evidence"])

    def test_query_error_surfaces_suggestions(self) -> None:
        with _clean_env(), mock.patch.dict(os.environ, {LOOGLE_URL_ENV: self.url}):
            payload = loogle_search(project_root=FIXTURE, query="bad query", verify_names=False)
        self.assertEqual(payload["status"], "query_error")
        self.assertEqual(payload["data"]["suggestions"], ['"gcd"'])

    def test_hosted_backend_requires_opt_in(self) -> None:
        with _clean_env(), mock.patch("pi_lean_tools.loogle_search.HOSTED_LOOGLE_URL", self.url):
            off = loogle_search(project_root=FIXTURE, query="Nat.Coprime", verify_names=False)
            with mock.patch.dict(os.environ, {LOOGLE_REMOTE_ENV: "on"}):
                on = loogle_search(project_root=FIXTURE, query="Nat.Coprime", verify_names=False)
        self.assertEqual(off["status"], "no_backend")
        self.assertEqual(on["status"], "searched")
        self.assertTrue(on["data"]["backend"].startswith("hosted:"))

    def test_verification_annotates_hits(self) -> None:
        canned = {
            "data": {
                "results": [
                    {"name": "Nat.Coprime.gcd_eq_one", "exists": True},
                    {"name": "Nat.Coprime.gcd_eq_one'", "exists": False},
                ]
            }
        }
        with _clean_env(), mock.patch.dict(os.environ, {LOOGLE_URL_ENV: self.url}), mock.patch(
            "pi_lean_tools.loogle_search.check_names", return_value=canned
        ):
            payload = loogle_search(project_root=FIXTURE, query="Nat.Coprime _ _", verify_limit=2)
        hits = payload["data"]["hits"]
        self.assertTrue(hits[0]["exists_in_local_revision"])
        self.assertFalse(hits[1]["exists_in_local_revision"])
        self.assertEqual(payload["data"]["verification"]["verified_top_n"], 2)


class LoogleDaemonEndToEndTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.loogle_bin = Path(self._tmp.name) / "fake_loogle.py"
        self.loogle_bin.write_text(FAKE_LOOGLE_BIN, encoding="utf-8")
        self.loogle_bin.chmod(self.loogle_bin.stat().st_mode | stat.S_IXUSR)
        self.socket_path = loogle_socket_path(self.loogle_bin)
        self.daemon = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "pi_lean_tools.loogle_daemon",
                "--loogle-bin",
                str(self.loogle_bin),
                "--socket",
                str(self.socket_path),
            ],
            env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.addCleanup(self.daemon.kill)
        deadline = time.monotonic() + 15
        while not self.socket_path.exists():
            if time.monotonic() > deadline:
                raise AssertionError("loogle daemon socket never appeared")
            time.sleep(0.05)

    def test_local_daemon_round_trip(self) -> None:
        with _clean_env(), mock.patch.dict(os.environ, {LOOGLE_BIN_ENV: str(self.loogle_bin)}):
            payload = loogle_search(project_root=FIXTURE, query="Nat.Coprime _ _", verify_names=False)
        self.assertEqual(payload["status"], "searched")
        self.assertTrue(payload["data"]["backend"].startswith("local_daemon:"))
        self.assertEqual(payload["data"]["hits"][0]["name"], "Nat.Coprime.gcd_eq_one")

    def test_local_daemon_query_error(self) -> None:
        with _clean_env(), mock.patch.dict(os.environ, {LOOGLE_BIN_ENV: str(self.loogle_bin)}):
            payload = loogle_search(project_root=FIXTURE, query="bad query", verify_names=False)
        self.assertEqual(payload["status"], "query_error")
        self.assertEqual(payload["data"]["suggestions"], ["Nat.gcd"])


if __name__ == "__main__":
    unittest.main()
