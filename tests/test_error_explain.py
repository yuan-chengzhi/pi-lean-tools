from __future__ import annotations

import unittest

from pi_lean_tools.error_explain import classify_error, explain_error


class ErrorExplainTests(unittest.TestCase):
    def test_unknown_constant_generates_actions_and_negative_name(self) -> None:
        payload = explain_error(error_message="Unknown constant `Nat.not_coprime_iff_exists_prime_dvd.mp`")
        self.assertEqual(payload["status"], "classified")
        data = payload["data"]
        self.assertEqual(data["failure_kind"], "unknown_identifier")
        self.assertIn("Nat.not_coprime_iff_exists_prime_dvd.mp", data["do_not_repeat_exact_name"])
        actions = data["suggested_actions"]
        self.assertEqual(actions[0]["tool"], "lean_scout_check_names")
        self.assertEqual(actions[1]["tool"], "lean_scout_decl_search")
        self.assertFalse(payload["authority"]["usable_as_proof_evidence"])

    def test_classifies_common_failure_kinds(self) -> None:
        self.assertEqual(classify_error("type mismatch\n  h\nhas type A\nbut is expected to have type B"), "type_mismatch")
        self.assertEqual(classify_error("failed to synthesize OfNat Foo 1"), "failed_to_synthesize_instance")
        self.assertEqual(classify_error("Invalid field notation: Type is not of the form"), "invalid_field")
        self.assertEqual(classify_error("unsolved goals"), "tactic_api_failure")


if __name__ == "__main__":
    unittest.main()
