---
name: lean-api-scout
description: Use when writing Lean code and you need to check Mathlib names, elaborate a small API snippet, explain a Lean diagnostic, find premise groups, or fill a proof worker report's needed_external_checks before relying on guessed Lean APIs.
---

# Lean API Scout

Use this skill when a Lean proof attempt depends on Mathlib/API details that are
easy to guess incorrectly.

This skill is advisory only. A successful probe is context, not proof evidence.
FinalVerify or the project verifier remains the only formal proof authority.

If a proof loop provides a `worker_report.json` path, use the report to expose
API uncertainty and scout needs. Do not leave important API/name uncertainty
only in comments when it can be reported as `needed_external_checks`.

## When To Scout

Scout when any of these apply:

- You are about to use a theorem, definition, namespace, or field name you are
  not sure exists.
- The checker reported `Unknown constant`, `Unknown identifier`, failed rewrite,
  type mismatch, coercion mismatch, or an unexpected theorem shape.
- You need a small API/type-shape probe before editing a larger Lean proof
  region.
- You know the mathematical role but not the Mathlib premise group, such as
  finite image, injectivity, gcd/coprime, divisibility, parity, absolute value,
  or well-founded descent.
- You are writing a worker report and can name a concrete API/name/snippet or
  premise-search check that would reduce uncertainty for a current frontier.

## Tool Map

- Use `lean_scout_error_explain` first for a concrete Lean diagnostic. Follow
  its suggested scout calls when useful.
- Use `lean_scout_decl_search` when you know keywords but not exact names.
- Use `lean_scout_check_names` before relying on candidate declaration names.
- Use `lean_scout_check_snippet` for focused code probes involving coercions,
  theorem shapes, rewrite syntax, or local API combinations.
- Use `lean_scout_premise_search` when the task needs a group of related
  premises rather than one exact theorem.

When a scout result changes what you trust, reflect that in the next Lean
candidate or in `worker_report.json`:

- Put unresolved API/name/snippet questions in `needed_external_checks`.
- Put still-open mathematical or formalization points in `open_frontiers`.
- Put only support you actually materialized in Lean in `claimed_closed_supports`.

If `projectRoot` is omitted, the tools use `PI_LEAN_TOOLS_PROJECT_ROOT` when the
runner configured it. You may still pass `projectRoot` explicitly when you need
a different Lean/Lake project.

## Boundaries

- Do not treat scout output as a verified proof.
- Do not let scout output select a unique proof route.
- You may use, ignore, rewrite, or reject any scout result.
- Preserve the proof loop artifact contract when one is present: write the
  required candidate file before ending the turn.
- A worker report is context for the board, not a substitute for Lean code.
