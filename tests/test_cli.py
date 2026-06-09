from __future__ import annotations

import os
import json
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "mini_lean_project"


class CliTests(unittest.TestCase):
    def test_error_explain_cli_returns_json(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pi_lean_tools.cli",
                "error-explain",
                "--error-message",
                "Unknown constant `Foo.bar`",
            ],
            cwd=ROOT,
            env={"PYTHONPATH": str(ROOT / "src")},
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["data"]["failure_kind"], "unknown_identifier")

    def test_decl_search_cli_returns_json(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pi_lean_tools.cli",
                "decl-search",
                "--project-root",
                str(FIXTURE),
                "--query",
                "demo identity",
                "--no-mathlib",
            ],
            cwd=ROOT,
            env={"PYTHONPATH": str(ROOT / "src")},
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["tool"], "lean_decl_search")

    def test_cli_project_root_defaults_to_environment(self) -> None:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT / "src")
        env["PI_LEAN_TOOLS_PROJECT_ROOT"] = str(FIXTURE)
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pi_lean_tools.cli",
                "decl-search",
                "--query",
                "demo identity",
                "--no-mathlib",
            ],
            cwd=ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["provenance"]["project_root"], str(FIXTURE.resolve()))
        names = [item["name"] for item in payload["data"]["matches"]]
        self.assertIn("demo_identity", names)

    def test_premise_search_cli_returns_groups(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pi_lean_tools.cli",
                "premise-search",
                "--project-root",
                str(FIXTURE),
                "--natural-language-goal",
                "finite image injectivity bridge",
                "--query-term",
                "Set.Finite",
                "--query-term",
                "Set.InjOn",
            ],
            cwd=ROOT,
            env={"PYTHONPATH": str(ROOT / "src")},
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["tool"], "lean_premise_search")
        self.assertGreaterEqual(payload["data"]["group_count"], 1)


if __name__ == "__main__":
    unittest.main()
