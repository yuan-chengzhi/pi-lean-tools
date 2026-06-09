"""Batch `#check` candidate Lean names."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .diagnostics import extract_missing_names
from .policy import ToolEnvelope, make_provenance
from .project import has_lake_config, mathlib_revision, read_lean_toolchain, resolve_project_root
from .runner import lean_source, run_lean_probe


def check_names(
    *,
    project_root: str | Path,
    names: list[str],
    imports: list[str] | None = None,
    timeout_sec: int = 15,
) -> dict[str, Any]:
    root = resolve_project_root(project_root)
    imports = imports or ["Mathlib"]
    results: list[dict[str, Any]] = []
    all_diagnostics: list[dict[str, Any]] = []
    checked_paths: list[str] = []

    for name in names:
        source = lean_source(imports, f"#check {name}")
        run = run_lean_probe(project_root=root, source=source, timeout_sec=timeout_sec)
        checked_paths.append(str(run.checked_file))
        all_diagnostics.extend(run.diagnostics)
        exists = run.status == "elaborated"
        results.append(
            {
                "name": name,
                "exists": exists,
                "status": run.status,
                "check_output": run.stdout.strip() if exists else None,
                "error": run.first_error,
                "missing_names": extract_missing_names(run.first_error or ""),
                "diagnostics": run.diagnostics,
                "checked_file_ref": str(run.checked_file),
                "suggested_next_actions": [] if exists else _suggested_actions_for_missing(name),
            }
        )

    status = "elaborated" if all(item["exists"] for item in results) else "partial"
    envelope = ToolEnvelope(
        tool="lean_check_names",
        status=status,
        data={
            "imports": imports,
            "result_count": len(results),
            "results": results,
        },
        diagnostics=all_diagnostics,
        provenance=make_provenance(
            project_root=root,
            lean_toolchain=read_lean_toolchain(root),
            mathlib_revision=mathlib_revision(root),
            sources_used=["local_lean_snippet"],
            inspected_paths=checked_paths,
        ),
    )
    envelope_dict = envelope.as_dict()
    envelope_dict["provenance"]["runner_context"] = "lake_project" if has_lake_config(root) else "plain_lean"
    return envelope_dict


def _suggested_actions_for_missing(name: str) -> list[dict[str, Any]]:
    base = name.removesuffix(".mp").removesuffix(".mpr")
    tokens = base.replace(".", " ").replace("_", " ")
    actions: list[dict[str, Any]] = [
        {
                "tool": "lean_scout_decl_search",
                "args": {"query": tokens},
            }
    ]
    if base != name:
        actions.insert(
            0,
            {
                "tool": "lean_scout_check_names",
                "args": {"names": [base]},
            },
        )
    return actions
