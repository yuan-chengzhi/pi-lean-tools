# AGENTS

This repository provides advisory Lean tools for Pi agents.

## Boundaries

- Do not present any tool result as proof evidence.
- Do not call a snippet result "verified"; use "elaborated".
- Do not read teacher solution files, repaired candidates, benchmark solutions,
  or historical solved proof bodies.
- Keep tools route-neutral: they may suggest checks and searches, but they do
  not select a unique proof route or block alternatives.
- FinalVerify / the Lean project verifier remains the only formal proof
  authority.

## Validation

Run before reporting completion:

```bash
python3 -m compileall src tests
PYTHONPATH=src python3 -m unittest discover -s tests -v
npm run typecheck
git diff --check
```
