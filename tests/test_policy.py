from __future__ import annotations

import unittest

from pi_lean_tools.policy import authority, banned_sources_used, route_control


class PolicyTests(unittest.TestCase):
    def test_authority_is_never_proof_evidence(self) -> None:
        payload = authority()
        self.assertTrue(payload["usable_as_context"])
        self.assertFalse(payload["usable_as_proof_evidence"])
        self.assertEqual(payload["proof_authority"], "none")
        self.assertTrue(payload["advisory_only"])

    def test_route_control_does_not_lock_route(self) -> None:
        payload = route_control()
        self.assertFalse(payload["selects_unique_proof_route"])
        self.assertFalse(payload["blocks_alternative_routes"])

    def test_banned_sources_detect_teacher_paths(self) -> None:
        found = banned_sources_used(["foo/candidate_repaired.lean", "ok.lean"])
        self.assertEqual(found, ["foo/candidate_repaired.lean"])


if __name__ == "__main__":
    unittest.main()
