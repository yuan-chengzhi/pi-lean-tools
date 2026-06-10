# pi-lean-tools

`pi-lean-tools` is an advisory Lean API scout package for Pi agents.

It is not a prover, not a controller, and not proof authority. The tools help an
agent check Lean names, elaborate small snippets, search local declarations, and
turn Lean diagnostics into concrete search/check actions.

Every tool result carries:

```json
{
  "authority": {
    "usable_as_context": true,
    "usable_as_proof_evidence": false,
    "proof_authority": "none",
    "advisory_only": true
  },
  "final_verify_required": true
}
```

Final formal closure still belongs to the project verifier / FinalVerify path.

## P0 Tools

- `lean_check_names`: run `#check` probes for candidate Lean names.
- `lean_check_snippet`: elaborate a small Lean snippet in the current project.
  Failed snippets include an inline `error_explanation` (failure kind, missing
  names, suggested next probes), so a separate `lean_error_explain` call is
  rarely needed.
- `lean_decl_search`: search local project and local Mathlib source declarations.
- `lean_error_explain`: classify common Lean diagnostics and propose next tool calls.
- `lean_premise_search`: build route-local premise groups from local declarations.

The Pi extension exposes these as:

- `lean_scout_check_names`
- `lean_scout_check_snippet`
- `lean_scout_decl_search`
- `lean_scout_error_explain`
- `lean_scout_premise_search`

The package also exposes the `lean-api-scout` skill. The skill is a natural
entry point for agents writing Lean code: it tells them when to check names,
probe snippets, explain diagnostics, and search premise groups. The skill and
all tools remain advisory only.

## Natural Scout Triggers

Agents should consider using the scout tools when:

- a candidate Lean name is being guessed from memory,
- checker feedback reports `Unknown constant`, `Unknown identifier`, failed
  rewrite, or type mismatch,
- a small coercion/API theorem-shape probe would reduce edit risk,
- the proof task needs a premise bundle, for example finite image, injectivity,
  gcd/coprime, divisibility, parity, absolute value, or descent lemmas.

Tool use is optional. The agent may use, ignore, rewrite, or reject any scout
result. Scout output does not select a proof route and cannot close a proof.

## Default Project Root

All tools accept `projectRoot`. When an agent omits it, the Pi extension and
Python CLI use `PI_LEAN_TOOLS_PROJECT_ROOT` if that environment variable is set;
otherwise they fall back to the current working directory.

This is plumbing context only. It selects where API probes and local declaration
searches run; it does not select a proof route and does not create proof
authority.

The TypeScript Pi extension is a thin wrapper over the Python CLI. Core behavior
lives in `src/pi_lean_tools` so it can be tested and reused outside Pi.

## Probe Result Cache

`lean_scout_check_names` and `lean_scout_check_snippet` cache probe outcomes on
disk, keyed by probe source content plus the project's `lean-toolchain` and
Mathlib revision. Repeated probes (including identical probes from parallel
swarm attempts) return in milliseconds instead of re-elaborating `import
Mathlib` (~20-30s per cold probe on a Mathlib workspace).

- `PI_LEAN_TOOLS_CACHE_DIR` selects the cache directory. Point all attempts of
  a swarm run at the same directory to share probe results across workers.
  Default: `<tmpdir>/pi-lean-tools/probe_cache`.
- `PI_LEAN_TOOLS_PROBE_CACHE=off` disables the cache.

Only deterministic outcomes (`elaborated`, `elab_failed`) are cached; timeouts
and runner failures always re-run. Cached results carry `cache_hit: true` in
the run payload. The cache stores advisory probe observations only; it creates
no proof authority.

## Persistent REPL Daemon

When a leanprover-community/repl binary is available, probe tools route through
a persistent daemon that keeps the `import Mathlib` environment in memory, so
warm probes return in milliseconds instead of re-elaborating imports per call
(measured on a Mathlib workspace: ~23s cold vs 0.01-0.06s warm).

- `PI_LEAN_TOOLS_REPL_BIN` points at the repl binary. Without it, the runner
  auto-detects `<project_root>/../repl/.lake/build/bin/repl` and
  `<project_root>/repl/.lake/build/bin/repl`.
- `PI_LEAN_TOOLS_REPL=off` disables the daemon path entirely.
- The first probe spawns the daemon in the background and falls back to the
  cold lake/lean runner while the daemon prewarms `Mathlib` (a few seconds of
  olean loading). Subsequent probes hit the warm daemon.
- Any daemon problem (missing binary, timeout, crash) degrades to the cold
  runner, never to a probe failure. On a probe timeout the daemon restarts its
  repl child.
- The daemon exits after two hours idle and holds one repl process per
  (project root, repl binary) pair. Probe results from the daemon carry
  `runner_mode: "repl_daemon"` and feed the same probe cache.

The repl binary must be built with the same toolchain as the target project
(`lean-toolchain` match), e.g. the prebuilt repl in the ContextSwarmJudge
lean-service workspace.

## Current Main-Repo Integration

Current swarm-level integration lives in the active main repository:

```text
/Users/ycz/Documents/pi-math-first-proof-swarm
```

This package owns advisory Lean API scout tools. It does not own proof
orchestration, route selection, formal verification, or controller decisions.

The main repo exposes these tools to Pi workers through the formal-loop Pi RPC
configuration:

```text
--lean-tools-project-root /path/to/lake/project
--pi-enable-extensions
--pi-extension-path /Users/ycz/Documents/pi-lean-tools/extensions/lean-tools.ts
--pi-enable-skills
--pi-skill-path /Users/ycz/Documents/pi-lean-tools/skills/lean-api-scout
--pi-tools write,lean_scout_check_names,lean_scout_check_snippet,lean_scout_decl_search,lean_scout_error_explain,lean_scout_premise_search
```

The main repo passes `PI_LEAN_TOOLS_PROJECT_ROOT` to Pi sessions when
`--lean-tools-project-root` is set. Worker use of these tools is telemetry and
advisory context only; final closure still requires the main repo verifier /
FinalVerify path.

## Setup

Install Python-side code by using `PYTHONPATH=src` during local development. The
Python package has no third-party runtime dependencies.

Install the Pi extension dependencies before typechecking or installing as a Pi
package:

```bash
cd /Users/ycz/Documents/pi-lean-tools
npm install
npm run typecheck
```

If network access is unavailable, Python validation can still run, but the
TypeScript Pi extension cannot be typechecked until npm dependencies are present.

## CLI Examples

```bash
PYTHONPATH=src python3 -m pi_lean_tools.cli check-names \
  --project-root /path/to/lean/project \
  --imports Lean \
  Nat.Coprime Lean.Name

PYTHONPATH=src python3 -m pi_lean_tools.cli check-snippet \
  --project-root /path/to/lean/project \
  --imports Lean \
  --code '#check Lean.Name'

PYTHONPATH=src python3 -m pi_lean_tools.cli decl-search \
  --project-root /path/to/lean/project \
  --query 'finite image'

PYTHONPATH=src python3 -m pi_lean_tools.cli error-explain \
  --error-message 'Unknown constant `Nat.not_coprime_iff_exists_prime_dvd.mp`'

PYTHONPATH=src python3 -m pi_lean_tools.cli premise-search \
  --project-root /path/to/lean/project \
  --natural-language-goal 'prove bad indices are finite using finite image and injectivity' \
  --query-term Set.Finite \
  --query-term Set.InjOn
```

For Mathlib projects, use `--imports Mathlib` or rely on the default import from
the Pi tool.

When `projectRoot` is a Lake project, probes run with `lake lean` and then
`lake env lean` as fallback. Outside a Lake project, probes fall back to bare
`lean`, which is enough for `import Lean` API smoke tests but not enough for
Mathlib-specific imports unless the local Lean environment can resolve them.
