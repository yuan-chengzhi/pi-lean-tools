"""Run a closing-tactic portfolio against a single Lean goal.

With the persistent REPL daemon warm, a full portfolio costs well under a
second, so this doubles as a practical premise search: `exact?`/`apply?`
report the exact Mathlib lemma closing the goal via their `Try this:`
suggestions.
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from .diagnostics import contains_sorry_warning
from .policy import ToolEnvelope, make_provenance
from .project import has_lake_config, mathlib_revision, read_lean_toolchain, resolve_project_root
from .runner import lean_source, run_lean_probe

DEFAULT_TACTICS = (
    "exact?",
    "simp",
    "simp_all",
    "omega",
    "norm_num",
    "positivity",
    "linarith",
    "ring",
    "aesop",
    "decide",
)

TRY_THIS_RE = re.compile(r"Try this:\s*(.+?)(?:\n|$)", re.S)
UNKNOWN_TACTIC_RE = re.compile(r"unknown tactic", re.I)
UNKNOWN_NAME_RE = re.compile(r"unknown identifier|unknown constant", re.I)


def try_tactics(
    *,
    project_root: str | Path,
    goal_declaration: str,
    imports: list[str] | None = None,
    tactics: list[str] | None = None,
    timeout_sec: int = 20,
    stop_after_first_close: bool = False,
) -> dict[str, Any]:
    root = resolve_project_root(project_root)
    imports = imports or ["Mathlib"]
    portfolio = list(tactics) if tactics else list(DEFAULT_TACTICS)
    declaration = goal_declaration.strip().removesuffix(":=").strip()

    attempts: list[dict[str, Any]] = []
    closing: list[dict[str, Any]] = []
    for tactic in portfolio:
        code = f"{declaration} := by {tactic}"
        run = run_lean_probe(
            project_root=root,
            source=lean_source(imports, code),
            timeout_sec=timeout_sec,
            imports=imports,
            code=code,
        )
        outcome = _attempt_outcome(tactic, run.status, run.diagnostics, run.first_error)
        attempt = {
            "tactic": tactic,
            "outcome": outcome,
            "status": run.status,
            "first_error": run.first_error,
            "suggestions": _try_this_suggestions(run.diagnostics),
            "elapsed_ms": run.elapsed_ms,
            "cache_hit": run.cache_hit,
            "runner_mode": run.runner_mode,
        }
        attempts.append(attempt)
        if outcome == "closed":
            closing.append(attempt)
            if stop_after_first_close:
                break

    envelope = ToolEnvelope(
        tool="lean_try_tactics",
        status="closed" if closing else "no_tactic_closed",
        data={
            "goal_declaration": declaration,
            "imports": imports,
            "tactics_tried": [item["tactic"] for item in attempts],
            "closing_tactics": [item["tactic"] for item in closing],
            "suggestions": [
                suggestion for item in attempts for suggestion in item["suggestions"]
            ],
            "attempts": attempts,
            "note": (
                "A closing tactic here is advisory probe evidence only. The "
                "candidate must still pass external FinalVerify, and tactics "
                "forbidden by the theorem contract must not be submitted."
            ),
        },
        diagnostics=[],
        provenance=make_provenance(
            project_root=root,
            lean_toolchain=read_lean_toolchain(root),
            mathlib_revision=mathlib_revision(root),
            sources_used=["local_lean_snippet"],
            inspected_paths=[],
        ),
    )
    envelope_dict = envelope.as_dict()
    envelope_dict["provenance"]["runner_context"] = "lake_project" if has_lake_config(root) else "plain_lean"
    return envelope_dict


def _attempt_outcome(
    tactic: str,
    status: str,
    diagnostics: list[dict[str, Any]],
    first_error: str | None,
) -> str:
    if status == "timeout":
        return "timeout"
    if status == "runner_failed":
        return "runner_failed"
    if status == "elaborated" and not contains_sorry_warning(diagnostics):
        return "closed"
    if first_error and UNKNOWN_TACTIC_RE.search(first_error):
        return "tactic_unavailable"
    tactic_token = tactic.split()[0].rstrip("?!") if tactic.split() else tactic
    if (
        first_error
        and UNKNOWN_NAME_RE.search(first_error)
        and tactic_token
        and tactic_token in first_error
    ):
        return "tactic_unavailable"
    return "failed"


def _try_this_suggestions(diagnostics: list[dict[str, Any]]) -> list[str]:
    suggestions: list[str] = []
    for item in diagnostics:
        message = str(item.get("message") or "")
        for match in TRY_THIS_RE.finditer(message):
            suggestion = match.group(1).strip()
            if suggestion and suggestion not in suggestions:
                suggestions.append(suggestion)
    return suggestions
