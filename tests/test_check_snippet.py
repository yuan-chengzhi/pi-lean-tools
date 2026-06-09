from __future__ import annotations

from pathlib import Path
import unittest

from pi_lean_tools.check_snippet import check_snippet


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mini_lean_project"


class CheckSnippetTests(unittest.TestCase):
    def test_elaborates_small_snippet(self) -> None:
        payload = check_snippet(project_root=FIXTURE, imports=["Lean"], code="#check Lean.Name", timeout_sec=20)
        self.assertEqual(payload["status"], "elaborated")
        self.assertFalse(payload["authority"]["usable_as_proof_evidence"])
        self.assertTrue(payload["final_verify_required"])
        self.assertIn("run", payload["data"])

    def test_failed_snippet_reports_first_error(self) -> None:
        payload = check_snippet(project_root=FIXTURE, imports=["Lean"], code="#check NoSuch.Lean.Name", timeout_sec=20)
        self.assertEqual(payload["status"], "elab_failed")
        self.assertIsNotNone(payload["data"]["run"]["first_error"])

    def test_check_snippet_falls_back_to_plain_lean_outside_lake_project(self) -> None:
        payload = check_snippet(
            project_root=Path(__file__).resolve().parents[1],
            imports=["Lean"],
            code="#check Lean.Name",
            timeout_sec=20,
        )
        self.assertEqual(payload["status"], "elaborated")
        self.assertEqual(payload["provenance"]["runner_context"], "plain_lean")
        self.assertEqual(payload["data"]["run"]["runner_mode"], "lean")


if __name__ == "__main__":
    unittest.main()
