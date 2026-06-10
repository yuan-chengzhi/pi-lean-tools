from __future__ import annotations

from pathlib import Path
import unittest

from pi_lean_tools.try_tactics import try_tactics


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mini_lean_project"


class TryTacticsTests(unittest.TestCase):
    def test_omega_closes_linear_arithmetic_goal(self) -> None:
        payload = try_tactics(
            project_root=FIXTURE,
            goal_declaration="example (a b : Nat) : a + b = b + a",
            imports=["Lean"],
            tactics=["omega"],
            timeout_sec=30,
        )
        self.assertEqual(payload["status"], "closed")
        self.assertEqual(payload["data"]["closing_tactics"], ["omega"])
        self.assertFalse(payload["authority"]["usable_as_proof_evidence"])

    def test_failing_tactic_reports_failed(self) -> None:
        payload = try_tactics(
            project_root=FIXTURE,
            goal_declaration="example (a b : Nat) : a + b = b + a",
            imports=["Lean"],
            tactics=["decide"],
            timeout_sec=30,
        )
        self.assertEqual(payload["status"], "no_tactic_closed")
        self.assertEqual(payload["data"]["attempts"][0]["outcome"], "failed")

    def test_unknown_tactic_reports_unavailable(self) -> None:
        payload = try_tactics(
            project_root=FIXTURE,
            goal_declaration="example : True",
            imports=["Lean"],
            tactics=["totally_fake_tactic"],
            timeout_sec=30,
        )
        self.assertEqual(payload["status"], "no_tactic_closed")
        self.assertEqual(payload["data"]["attempts"][0]["outcome"], "tactic_unavailable")

    def test_stop_after_first_close_short_circuits(self) -> None:
        payload = try_tactics(
            project_root=FIXTURE,
            goal_declaration="example (a b : Nat) : a + b = b + a",
            imports=["Lean"],
            tactics=["omega", "simp"],
            timeout_sec=30,
            stop_after_first_close=True,
        )
        self.assertEqual(payload["status"], "closed")
        self.assertEqual(payload["data"]["tactics_tried"], ["omega"])

    def test_trailing_assignment_marker_is_stripped(self) -> None:
        payload = try_tactics(
            project_root=FIXTURE,
            goal_declaration="example : True :=",
            imports=["Lean"],
            tactics=["trivial"],
            timeout_sec=30,
        )
        self.assertEqual(payload["status"], "closed")


if __name__ == "__main__":
    unittest.main()
