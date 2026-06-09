"""Local Lean declaration search."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

from .policy import ToolEnvelope, make_provenance
from .project import mathlib_revision, project_lean_roots, read_lean_toolchain, resolve_project_root


DECL_RE = re.compile(
    r"^\s*(?P<kind>theorem|lemma|def|abbrev|class|structure|instance|inductive)\s+(?P<name>[A-Za-z0-9_'.]+)",
)
TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


@dataclass(frozen=True)
class DeclRecord:
    name: str
    kind: str
    file: Path
    line: int
    statement_head: str
    statement_snippet: str
    source: str

    def as_dict(self, project_root: Path, score_bucket: str) -> dict[str, Any]:
        rel = _relative_or_abs(self.file, project_root)
        return {
            "name": self.name,
            "kind": self.kind,
            "file": rel,
            "line": self.line,
            "statement_head": self.statement_head,
            "statement_snippet": self.statement_snippet,
            "source": self.source,
            "score_bucket": score_bucket,
            "verified_name": False,
            "recommended_check": f"#check {self.name}",
        }


def search_declarations(
    *,
    project_root: str | Path,
    query: str,
    limit: int = 20,
    include_mathlib: bool = True,
    include_local: bool = True,
) -> dict[str, Any]:
    root = resolve_project_root(project_root)
    matches = search_decl_records(
        root,
        query=query,
        include_mathlib=include_mathlib,
        include_local=include_local,
    )
    data_matches = [
        record.as_dict(root, _score_bucket(score))
        for record, score in matches[: max(1, min(limit, 100))]
    ]
    envelope = ToolEnvelope(
        tool="lean_decl_search",
        status="searched",
        data={
            "query": query,
            "result_count": len(data_matches),
            "matches": data_matches,
            "scores_hidden_by_default": True,
            "include_mathlib": include_mathlib,
            "include_local": include_local,
        },
        diagnostics=[],
        provenance=make_provenance(
            project_root=root,
            lean_toolchain=read_lean_toolchain(root),
            mathlib_revision=mathlib_revision(root),
            search_corpus_revision=mathlib_revision(root),
            sources_used=["local_project_declarations", "local_mathlib_declarations"] if include_mathlib else ["local_project_declarations"],
            inspected_paths=[str(record.file) for record, _score_value in matches[: max(1, min(limit, 100))]],
        ),
    )
    return envelope.as_dict()


def search_decl_records(
    project_root: Path,
    *,
    query: str,
    include_mathlib: bool = True,
    include_local: bool = True,
) -> list[tuple[DeclRecord, float]]:
    query_tokens = _tokens(query)
    records = list(_iter_decl_records(project_root, include_mathlib=include_mathlib, include_local=include_local))
    scored = [
        (record, _score(record, query, query_tokens))
        for record in records
    ]
    matches = [
        (record, score)
        for record, score in scored
        if score > 0
    ]
    matches.sort(key=lambda item: (-item[1], item[0].name))
    return matches


def score_bucket(score: float) -> str:
    return _score_bucket(score)


def _iter_decl_records(project_root: Path, *, include_mathlib: bool, include_local: bool) -> list[DeclRecord]:
    roots = project_lean_roots(project_root, include_mathlib=include_mathlib)
    records: list[DeclRecord] = []
    for root in roots:
        if not include_local and project_root in root.parents and ".lake" not in root.parts:
            continue
        files = [root] if root.is_file() else sorted(root.rglob("*.lean"))
        for path in files:
            if _is_banned_path(path):
                continue
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
            for index, line in enumerate(lines, start=1):
                match = DECL_RE.match(line)
                if not match:
                    continue
                snippet = _statement_snippet(lines, index - 1)
                records.append(
                    DeclRecord(
                        name=match.group("name"),
                        kind=match.group("kind"),
                        file=path,
                        line=index,
                        statement_head=line.strip(),
                        statement_snippet=snippet,
                        source="local_mathlib_source" if ".lake" in path.parts else "local_project_source",
                    )
                )
    return records


def _statement_snippet(lines: list[str], start_index: int) -> str:
    collected: list[str] = []
    for line in lines[start_index : min(len(lines), start_index + 5)]:
        if len(collected) > 0 and DECL_RE.match(line):
            break
        collected.append(line.strip())
        if ":=" in line or "where" in line:
            break
    return " ".join(item for item in collected if item)


def _score(record: DeclRecord, raw_query: str, query_tokens: set[str]) -> float:
    if not query_tokens:
        return 1.0
    name_lower = record.name.lower()
    snippet_lower = record.statement_snippet.lower()
    file_lower = str(record.file).lower()
    raw_lower = raw_query.lower()
    score = 0.0
    if raw_lower and raw_lower in name_lower:
        score += 8.0
    for token in query_tokens:
        if token in name_lower:
            score += 3.0
        if token in snippet_lower:
            score += 1.5
        if token in file_lower:
            score += 0.5
    if record.name.startswith("_"):
        score -= 2.0
    return score


def _tokens(text: str) -> set[str]:
    return {match.group(0).lower() for match in TOKEN_RE.finditer(text)}


def _score_bucket(score: float) -> str:
    if score >= 8:
        return "high"
    if score >= 3:
        return "medium"
    return "low"


def _relative_or_abs(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _is_banned_path(path: Path) -> bool:
    normalized = str(path).replace("\\", "/")
    return any(token in normalized for token in ("candidate_repaired.lean", "solution.lean", "Putnam2025/A1/solution.lean"))
