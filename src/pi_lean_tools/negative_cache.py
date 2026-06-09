"""Run-local negative evidence cache for missing Lean names."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class MissingConstantEvidence:
    name: str
    checked_with: str
    project_revision: str | None
    mathlib_revision: str | None
    first_seen_turn: int | None = None
    last_seen_turn: int | None = None
    do_not_retry_exact: bool = True
    retry_allowed_if_imports_change: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": "missing_constant",
            "name": self.name,
            "checked_with": self.checked_with,
            "project_revision": self.project_revision,
            "mathlib_revision": self.mathlib_revision,
            "first_seen_turn": self.first_seen_turn,
            "last_seen_turn": self.last_seen_turn,
            "do_not_retry_exact": self.do_not_retry_exact,
            "retry_allowed_if_imports_change": self.retry_allowed_if_imports_change,
        }


def load_negative_cache(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"negative_evidence": []}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return {"negative_evidence": []}
    if not isinstance(payload.get("negative_evidence"), list):
        payload["negative_evidence"] = []
    return payload


def append_missing_constants(path: Path, evidence: list[MissingConstantEvidence]) -> dict[str, Any]:
    payload = load_negative_cache(path)
    existing = {
        str(item.get("name")): item
        for item in payload["negative_evidence"]
        if isinstance(item, dict)
    }
    for item in evidence:
        existing[item.name] = item.as_dict()
    payload["negative_evidence"] = sorted(existing.values(), key=lambda item: str(item.get("name")))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload
