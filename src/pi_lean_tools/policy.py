"""Shared advisory policy envelope for all tool outputs."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any


BANNED_PATH_TOKENS = (
    "candidate_repaired.lean",
    "solution",
    "answer",
    "teacher",
)

GUARDED_DECLS_ENV = "PI_LEAN_TOOLS_GUARDED_DECLS"


def guarded_declarations() -> frozenset[str]:
    """Declaration names whose declaring files must never be indexed.

    The harness sets PI_LEAN_TOOLS_GUARDED_DECLS (comma- or
    whitespace-separated) from the theorem contract, so a solutions file is
    excluded by what it declares, not by what it happens to be named.
    """
    raw = os.environ.get(GUARDED_DECLS_ENV, "")
    return frozenset(item.strip() for item in raw.replace(",", " ").split() if item.strip())


def is_banned_path(path: Path | str) -> bool:
    normalized = str(path).replace("\\", "/").lower()
    return any(token in normalized for token in BANNED_PATH_TOKENS)


def authority() -> dict[str, Any]:
    return {
        "usable_as_context": True,
        "usable_as_proof_evidence": False,
        "proof_authority": "none",
        "advisory_only": True,
    }


def route_control() -> dict[str, Any]:
    return {
        "selects_unique_proof_route": False,
        "blocks_alternative_routes": False,
    }


@dataclass(frozen=True)
class ToolEnvelope:
    tool: str
    status: str
    data: dict[str, Any]
    diagnostics: list[dict[str, Any]]
    provenance: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "status": self.status,
            "data": self.data,
            "diagnostics": self.diagnostics,
            "provenance": self.provenance,
            "authority": authority(),
            "route_control": route_control(),
            "final_verify_required": True,
        }


def banned_sources_used(paths: list[str] | tuple[str, ...]) -> list[str]:
    return [raw for raw in paths if is_banned_path(raw)]


def make_provenance(
    *,
    project_root: Path | None,
    sources_used: list[str],
    lean_toolchain: str | None = None,
    mathlib_revision: str | None = None,
    search_corpus_revision: str | None = None,
    inspected_paths: list[str] | None = None,
) -> dict[str, Any]:
    inspected = inspected_paths or []
    return {
        "project_root": str(project_root.resolve()) if project_root is not None else None,
        "lean_toolchain": lean_toolchain,
        "mathlib_revision": mathlib_revision,
        "search_corpus_revision": search_corpus_revision,
        "sources_used": sources_used,
        "banned_sources_used": banned_sources_used(inspected),
        "inspected_paths": inspected,
    }


def truncate_text(text: str, max_chars: int = 12_000) -> str:
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}\n\n[truncated {len(text) - max_chars} chars]"
