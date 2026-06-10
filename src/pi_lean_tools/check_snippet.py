"""Elaborate small Lean snippets in a project context."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .diagnostics import contains_sorry_warning
from .error_explain import explain_error
from .policy import ToolEnvelope, make_provenance
from .project import has_lake_config, mathlib_revision, read_lean_toolchain, resolve_project_root
from .runner import lean_source, run_lean_probe


def check_snippet(
    *,
    project_root: str | Path,
    code: str,
    imports: list[str] | None = None,
    timeout_sec: int = 15,
    allow_sorry: bool = True,
    mode: str = "api_probe",
) -> dict[str, Any]:
    root = resolve_project_root(project_root)
    imports = imports or ["Mathlib"]
    run = run_lean_probe(
        project_root=root,
        source=lean_source(imports, code),
        timeout_sec=timeout_sec,
        imports=imports,
        code=code,
    )
    contains_sorry = contains_sorry_warning(run.diagnostics) or "sorry" in code
    status = run.status
    if status == "elaborated" and contains_sorry and not allow_sorry:
        status = "elab_failed"
    data: dict[str, Any] = {
        "mode": mode,
        "imports": imports,
        "contains_sorry": contains_sorry,
        "allow_sorry": allow_sorry,
        "snippet_has_proof_like_declaration": _has_proof_like_declaration(code),
        "run": run.as_dict(),
    }
    if run.first_error:
        explanation = explain_error(error_message=run.first_error, surrounding_code=code)
        data["error_explanation"] = {
            "failure_kind": explanation["data"]["failure_kind"],
            "missing_names": explanation["data"].get("missing_names", []),
            "suggested_actions": explanation["data"]["suggested_actions"],
        }
    envelope = ToolEnvelope(
        tool="lean_check_snippet",
        status=status,
        data=data,
        diagnostics=run.diagnostics,
        provenance=make_provenance(
            project_root=root,
            lean_toolchain=read_lean_toolchain(root),
            mathlib_revision=mathlib_revision(root),
            sources_used=["local_lean_snippet"],
            inspected_paths=[str(run.checked_file)],
        ),
    )
    envelope_dict = envelope.as_dict()
    envelope_dict["provenance"]["runner_context"] = "lake_project" if has_lake_config(root) else "plain_lean"
    return envelope_dict


def _has_proof_like_declaration(code: str) -> bool:
    lowered = code.lower()
    return any(token in lowered for token in ("theorem ", "lemma ", "example ", "by "))
