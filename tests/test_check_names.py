from __future__ import annotations

from pathlib import Path
import unittest

from pi_lean_tools.check_names import check_names


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mini_lean_project"


class CheckNamesTests(unittest.TestCase):
    def test_check_names_reports_existing_and_missing(self) -> None:
        payload = check_names(
            project_root=FIXTURE,
            imports=["Lean"],
            names=["Lean.Name", "NoSuch.Lean.Name"],
            timeout_sec=20,
        )
        self.assertEqual(payload["status"], "partial")
        results = {item["name"]: item for item in payload["data"]["results"]}
        self.assertTrue(results["Lean.Name"]["exists"])
        self.assertFalse(results["NoSuch.Lean.Name"]["exists"])
        self.assertEqual(results["NoSuch.Lean.Name"]["suggested_next_actions"][0]["tool"], "lean_scout_decl_search")
        self.assertFalse(payload["authority"]["usable_as_proof_evidence"])

    def test_check_names_falls_back_to_plain_lean_outside_lake_project(self) -> None:
        payload = check_names(
            project_root=Path(__file__).resolve().parents[1],
            imports=["Lean"],
            names=["Lean.Name"],
            timeout_sec=20,
        )
        self.assertEqual(payload["status"], "elaborated")
        self.assertEqual(payload["provenance"]["runner_context"], "plain_lean")
        result = payload["data"]["results"][0]
        self.assertTrue(result["exists"])
        self.assertEqual(result["status"], "elaborated")


if __name__ == "__main__":
    unittest.main()
