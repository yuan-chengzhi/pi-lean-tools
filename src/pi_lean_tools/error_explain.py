"""Turn Lean diagnostics into concrete next scout actions."""

from __future__ import annotations

from typing import Any
import re

from .diagnostics import extract_missing_names
from .policy import ToolEnvelope, make_provenance


TYPE_MISMATCH_RE = re.compile(r"type mismatch", re.I)
SYNTH_RE = re.compile(r"failed to synthesize|failed to infer", re.I)
INVALID_FIELD_RE = re.compile(r"invalid field notation|invalid field", re.I)
TACTIC_RE = re.compile(r"tactic .* failed|unknown tactic|unsolved goals", re.I)


def explain_error(*, error_message: str, surrounding_code: str | None = None) -> dict[str, Any]:
    failure_kind = classify_error(error_message)
    data: dict[str, Any] = {
        "failure_kind": failure_kind,
        "error_message": error_message,
        "surrounding_code_present": bool(surrounding_code),
        "suggested_actions": [],
        "do_not_repeat_exact_name": [],
    }
    if failure_kind == "unknown_identifier":
        data.update(_unknown_identifier_payload(error_message))
    elif failure_kind == "type_mismatch":
        data["suggested_actions"] = _generic_search_actions(_tokens_from_error(error_message))
    elif failure_kind == "failed_to_synthesize_instance":
        data["suggested_actions"] = [
            {"tool": "lean_scout_check_snippet", "args": {"code": "#synth <replace_with_target_instance>"}},
            {"tool": "lean_scout_decl_search", "args": {"query": _tokens_from_error(error_message)}},
        ]
    elif failure_kind in {"invalid_field", "tactic_api_failure"}:
        data["suggested_actions"] = _generic_search_actions(_tokens_from_error(error_message))
    else:
        data["suggested_actions"] = [
            {"tool": "lean_scout_decl_search", "args": {"query": _tokens_from_error(error_message)}},
        ]
    envelope = ToolEnvelope(
        tool="lean_error_explain",
        status="classified",
        data=data,
        diagnostics=[],
        provenance=make_provenance(
            project_root=None,
            sources_used=["lean_diagnostic_text"],
        ),
    )
    return envelope.as_dict()


def classify_error(error_message: str) -> str:
    if extract_missing_names(error_message):
        return "unknown_identifier"
    if TYPE_MISMATCH_RE.search(error_message):
        return "type_mismatch"
    if SYNTH_RE.search(error_message):
        return "failed_to_synthesize_instance"
    if INVALID_FIELD_RE.search(error_message):
        return "invalid_field"
    if TACTIC_RE.search(error_message):
        return "tactic_api_failure"
    return "unknown"


def _unknown_identifier_payload(error_message: str) -> dict[str, Any]:
    missing = extract_missing_names(error_message)
    normalized: list[dict[str, str]] = []
    for name in missing:
        base = name.removesuffix(".mp").removesuffix(".mpr")
        if base != name:
            normalized.append({"name": base, "reason": "stripped .mp/.mpr suffix"})
    names_to_check = [item["name"] for item in normalized] or missing
    query = " ".join(name.replace(".", " ").replace("_", " ") for name in names_to_check)
    return {
        "missing_names": missing,
        "normalized_name_hypotheses": normalized,
        "suggested_actions": [
            {"tool": "lean_scout_check_names", "args": {"names": names_to_check}},
            {"tool": "lean_scout_decl_search", "args": {"query": query}},
            {"tool": "lean_scout_check_snippet", "args": {"code": "\n".join(f"#check {name}" for name in names_to_check)}},
        ],
        "do_not_repeat_exact_name": missing,
    }


def _generic_search_actions(query: str) -> list[dict[str, Any]]:
    return [
        {"tool": "lean_scout_decl_search", "args": {"query": query}},
        {"tool": "lean_scout_check_snippet", "args": {"code": "-- Replace this with a focused API probe\n#check Nat"}},
    ]


def _tokens_from_error(error_message: str) -> str:
    words = re.findall(r"[A-Za-z0-9_.]+", error_message)
    return " ".join(words[:24])
