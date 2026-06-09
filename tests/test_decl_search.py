from __future__ import annotations

from pathlib import Path
import unittest

from pi_lean_tools.decl_search import search_declarations


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mini_lean_project"


class DeclSearchTests(unittest.TestCase):
    def test_searches_local_project_declarations(self) -> None:
        payload = search_declarations(project_root=FIXTURE, query="demo add zero", include_mathlib=False)
        self.assertEqual(payload["status"], "searched")
        names = [item["name"] for item in payload["data"]["matches"]]
        self.assertIn("demo_add_zero", names)
        self.assertFalse(payload["authority"]["usable_as_proof_evidence"])
        self.assertFalse(payload["route_control"]["selects_unique_proof_route"])

    def test_searches_mathlib_like_source(self) -> None:
        payload = search_declarations(project_root=FIXTURE, query="coprime bridge", include_mathlib=True)
        names = [item["name"] for item in payload["data"]["matches"]]
        self.assertIn("demo_coprime_bridge", names)
        match = next(item for item in payload["data"]["matches"] if item["name"] == "demo_coprime_bridge")
        self.assertFalse(match["verified_name"])
        self.assertEqual(match["recommended_check"], "#check demo_coprime_bridge")

    def test_search_skips_solution_and_repaired_candidate_paths(self) -> None:
        payload = search_declarations(project_root=FIXTURE, query="hidden teacher", include_mathlib=True)
        inspected = payload["provenance"]["inspected_paths"]
        self.assertFalse(any("solution.lean" in path for path in inspected))
        self.assertFalse(any("candidate_repaired.lean" in path for path in inspected))
        names = [item["name"] for item in payload["data"]["matches"]]
        self.assertNotIn("hidden_teacher_solution", names)


if __name__ == "__main__":
    unittest.main()
