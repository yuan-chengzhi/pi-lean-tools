from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from pi_lean_tools.probe_cache import (
    CACHE_DIR_ENV,
    CACHE_MODE_ENV,
    load_cached_probe,
    probe_cache_key,
    store_cached_probe,
)
from pi_lean_tools.runner import run_lean_probe


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mini_lean_project"


def _result(status: str = "elaborated") -> dict:
    return {
        "status": status,
        "exit_code": 0,
        "stdout": "",
        "stderr": "",
        "diagnostics": [],
        "first_error": None,
        "elapsed_ms": 1234,
        "checked_file": "/tmp/probe.lean",
        "command": ["lean", "/tmp/probe.lean"],
        "runner_mode": "lean",
    }


class ProbeCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch.dict(os.environ, {CACHE_DIR_ENV: self._tmp.name}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)

    def test_store_and_load_roundtrip(self) -> None:
        key = probe_cache_key(source="#check Nat", project_root=FIXTURE, lean_toolchain="t1", mathlib_revision="r1")
        self.assertTrue(store_cached_probe(key, result=_result()))
        cached = load_cached_probe(key)
        self.assertIsNotNone(cached)
        self.assertEqual(cached["result"]["status"], "elaborated")

    def test_key_depends_on_source_and_revisions(self) -> None:
        base = dict(source="#check Nat", project_root=FIXTURE, lean_toolchain="t1", mathlib_revision="r1")
        key = probe_cache_key(**base)
        self.assertNotEqual(key, probe_cache_key(**{**base, "source": "#check Int"}))
        self.assertNotEqual(key, probe_cache_key(**{**base, "lean_toolchain": "t2"}))
        self.assertNotEqual(key, probe_cache_key(**{**base, "mathlib_revision": "r2"}))

    def test_nondeterministic_statuses_not_cached(self) -> None:
        key = probe_cache_key(source="x", project_root=FIXTURE, lean_toolchain=None, mathlib_revision=None)
        self.assertFalse(store_cached_probe(key, result=_result(status="timeout")))
        self.assertFalse(store_cached_probe(key, result=_result(status="runner_failed")))
        self.assertIsNone(load_cached_probe(key))

    def test_cache_disabled_by_env(self) -> None:
        key = probe_cache_key(source="x", project_root=FIXTURE, lean_toolchain=None, mathlib_revision=None)
        with mock.patch.dict(os.environ, {CACHE_MODE_ENV: "off"}, clear=False):
            self.assertFalse(store_cached_probe(key, result=_result()))
            self.assertIsNone(load_cached_probe(key))

    def test_run_lean_probe_second_call_hits_cache(self) -> None:
        source = "import Lean\n\n#check Lean.Name\n"
        first = run_lean_probe(project_root=FIXTURE, source=source, timeout_sec=60)
        self.assertEqual(first.status, "elaborated")
        self.assertFalse(first.cache_hit)
        second = run_lean_probe(project_root=FIXTURE, source=source, timeout_sec=60)
        self.assertTrue(second.cache_hit)
        self.assertEqual(second.status, first.status)
        self.assertEqual(second.as_dict()["cache_hit"], True)
        self.assertLess(second.elapsed_ms, first.elapsed_ms)


if __name__ == "__main__":
    unittest.main()
