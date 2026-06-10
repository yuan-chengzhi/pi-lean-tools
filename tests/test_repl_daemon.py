from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from pi_lean_tools.probe_cache import CACHE_DIR_ENV
from pi_lean_tools.repl_client import REPL_BIN_ENV, repl_probe, socket_path_for
from pi_lean_tools.repl_daemon import ReplProcess
from pi_lean_tools.runner import run_lean_probe


FAKE_REPL = '''#!/usr/bin/env python3
import json, sys

imports_seen = 0
env_counter = 0

def reply(payload):
    sys.stdout.write(json.dumps(payload) + "\\n\\n")
    sys.stdout.flush()

buffer = []
for line in sys.stdin:
    if line.strip():
        buffer.append(line)
        continue
    if not buffer:
        continue
    request = json.loads("".join(buffer))
    buffer = []
    env_counter += 1
    if "env" not in request:
        imports_seen += 1
        reply({"env": env_counter})
    elif "NoSuch" in request.get("cmd", ""):
        reply({"messages": [{"severity": "error", "pos": {"line": 1, "column": 7},
                             "data": "Unknown identifier `NoSuch.Name`"}], "env": env_counter})
    elif "useSorry" in request.get("cmd", ""):
        reply({"messages": [], "sorries": [{"goal": "True"}], "env": env_counter})
    else:
        reply({"messages": [{"severity": "info", "pos": {"line": 1, "column": 0},
                             "data": "Nat : Type (imports_seen=%d)" % imports_seen}],
               "env": env_counter})
'''


def _write_fake_repl(directory: Path) -> Path:
    path = directory / "fake_repl.py"
    path.write_text(FAKE_REPL, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


class ReplProcessTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.repl_bin = _write_fake_repl(self.tmp)
        self.project_root = self.tmp / "project"
        self.project_root.mkdir()

    def _make_repl(self) -> ReplProcess:
        repl = ReplProcess(project_root=self.project_root, repl_bin=self.repl_bin)
        self.addCleanup(repl._restart)
        return repl

    def test_probe_reuses_import_environment(self) -> None:
        repl = self._make_repl()
        first = repl.probe(imports=["Mathlib"], code="#check Nat", timeout_sec=10)
        second = repl.probe(imports=["Mathlib"], code="#check Nat", timeout_sec=10)
        self.assertTrue(first["ok"])
        self.assertTrue(second["ok"])
        # The fake repl embeds how many import commands it saw; env reuse means one.
        self.assertIn("imports_seen=1", second["messages"][0]["data"])

    def test_probe_reports_errors(self) -> None:
        repl = self._make_repl()
        result = repl.probe(imports=["Mathlib"], code="#check NoSuch.Name", timeout_sec=10)
        self.assertTrue(result["ok"])
        self.assertEqual(result["messages"][0]["severity"], "error")


class ReplClientEndToEndTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.repl_bin = _write_fake_repl(self.tmp)
        self.project_root = self.tmp / "project"
        self.project_root.mkdir()
        env_patch = mock.patch.dict(
            os.environ,
            {REPL_BIN_ENV: str(self.repl_bin), CACHE_DIR_ENV: str(self.tmp / "cache")},
            clear=False,
        )
        env_patch.start()
        self.addCleanup(env_patch.stop)
        self.socket_path = socket_path_for(self.project_root, self.repl_bin)
        self.daemon = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "pi_lean_tools.repl_daemon",
                "--project-root",
                str(self.project_root),
                "--repl-bin",
                str(self.repl_bin),
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
                raise AssertionError("daemon socket never appeared")
            time.sleep(0.05)

    def test_repl_probe_round_trip(self) -> None:
        response = repl_probe(
            project_root=self.project_root,
            imports=["Mathlib"],
            code="#check Nat",
            timeout_sec=10.0,
        )
        self.assertIsNotNone(response)
        self.assertTrue(response["ok"])
        self.assertEqual(response["messages"][0]["severity"], "info")

    def test_run_lean_probe_uses_daemon_and_caches(self) -> None:
        result = run_lean_probe(
            project_root=self.project_root,
            source="import Mathlib\n\n#check Nat\n",
            timeout_sec=10,
            imports=["Mathlib"],
            code="#check Nat",
        )
        self.assertEqual(result.runner_mode, "repl_daemon")
        self.assertEqual(result.status, "elaborated")
        self.assertFalse(result.cache_hit)
        again = run_lean_probe(
            project_root=self.project_root,
            source="import Mathlib\n\n#check Nat\n",
            timeout_sec=10,
            imports=["Mathlib"],
            code="#check Nat",
        )
        self.assertTrue(again.cache_hit)
        self.assertEqual(again.runner_mode, "repl_daemon")

    def test_error_probe_maps_to_elab_failed(self) -> None:
        result = run_lean_probe(
            project_root=self.project_root,
            source="import Mathlib\n\n#check NoSuch.Name\n",
            timeout_sec=10,
            imports=["Mathlib"],
            code="#check NoSuch.Name",
        )
        self.assertEqual(result.status, "elab_failed")
        self.assertIn("NoSuch.Name", result.first_error or "")

    def test_sorries_surface_as_sorry_warning(self) -> None:
        result = run_lean_probe(
            project_root=self.project_root,
            source="import Mathlib\n\nuseSorry\n",
            timeout_sec=10,
            imports=["Mathlib"],
            code="useSorry",
        )
        self.assertEqual(result.status, "elaborated")
        self.assertTrue(
            any("declaration uses 'sorry'" in str(d.get("message")) for d in result.diagnostics)
        )


if __name__ == "__main__":
    unittest.main()
