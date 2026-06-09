from __future__ import annotations

from pathlib import Path
import unittest

from pi_lean_tools.premise_search import search_premise_groups


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mini_lean_project"


class PremiseSearchTests(unittest.TestCase):
    def test_premise_search_builds_route_local_groups(self) -> None:
        payload = search_premise_groups(
            project_root=FIXTURE,
            natural_language_goal="prove bad indices are finite using finite image and injectivity",
            query_terms=["Set.Finite", "Set.InjOn"],
            routes=[{"route_id": "finite_image_injectivity"}],
            limit_per_group=4,
        )
        self.assertEqual(payload["status"], "searched")
        self.assertFalse(payload["authority"]["usable_as_proof_evidence"])
        self.assertFalse(payload["route_control"]["selects_unique_proof_route"])
        self.assertEqual(payload["data"]["next_recommended_tool"], "lean_scout_check_names")
        groups = payload["data"]["premise_groups"]
        self.assertGreaterEqual(len(groups), 1)
        route_ids = {group["route_id"] for group in groups}
        self.assertIn("finite_image_injectivity", route_ids)
        finite_group = next(group for group in groups if group["route_id"] == "finite_image_injectivity")
        self.assertFalse(finite_group["route_selected_by_tool"])
        self.assertTrue(finite_group["candidate_premises"])
        self.assertTrue(all(not item["verified_name"] for item in finite_group["candidate_premises"]))
        self.assertTrue(any("demo_finite_image" in item["name"] for item in finite_group["candidate_premises"]))

    def test_premise_search_covers_coprime_category(self) -> None:
        payload = search_premise_groups(
            project_root=FIXTURE,
            natural_language_goal="use gcd and coprime bridge to analyze common factors",
            query_terms=["Nat.Coprime", "gcd"],
            limit_per_group=3,
        )
        groups = payload["data"]["premise_groups"]
        self.assertTrue(any(group["category_id"] == "nat_gcd_coprime" for group in groups))
        names = [
            item["name"]
            for group in groups
            for item in group["candidate_premises"]
        ]
        self.assertIn("demo_coprime_bridge", names)


if __name__ == "__main__":
    unittest.main()
