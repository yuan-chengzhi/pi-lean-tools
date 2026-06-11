from __future__ import annotations

import unittest
from unittest import mock

from pi_lean_tools.policy import (
    GUARDED_DECLS_ENV,
    authority,
    banned_sources_used,
    guarded_declarations,
    is_banned_path,
    route_control,
)


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

    def test_banned_path_tokens_are_case_insensitive(self) -> None:
        self.assertTrue(is_banned_path("Putnam2025/A5/Solution.lean"))
        self.assertTrue(is_banned_path("notes/putnam_2025_a5_ANSWER.lean"))
        self.assertTrue(is_banned_path("bench\\Teacher\\hints.lean"))
        self.assertFalse(is_banned_path("Mathlib/Data/Nat/Basic.lean"))

    def test_guarded_declarations_parse_comma_and_whitespace(self) -> None:
        with mock.patch.dict("os.environ", {GUARDED_DECLS_ENV: "putnam_2025_a5, f  putnam_2025_a5_solution"}):
            self.assertEqual(
                guarded_declarations(),
                frozenset({"putnam_2025_a5", "f", "putnam_2025_a5_solution"}),
            )

    def test_guarded_declarations_empty_without_env(self) -> None:
        with mock.patch.dict("os.environ", {GUARDED_DECLS_ENV: ""}):
            self.assertEqual(guarded_declarations(), frozenset())


if __name__ == "__main__":
    unittest.main()
