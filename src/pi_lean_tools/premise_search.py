"""Route-local premise group search over local Lean declarations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .decl_search import DeclRecord, score_bucket, search_decl_records
from .policy import ToolEnvelope, make_provenance
from .project import mathlib_revision, read_lean_toolchain, resolve_project_root


@dataclass(frozen=True)
class SearchCategory:
    category_id: str
    description: str
    route_id: str
    role: str
    query_terms: tuple[str, ...]


BUILTIN_CATEGORIES: tuple[SearchCategory, ...] = (
    SearchCategory(
        category_id="nat_gcd_coprime",
        description="Nat gcd / coprime bridge",
        route_id="coprime_gcd_bridge",
        role="gcd_coprime_bridge",
        query_terms=("Nat Coprime gcd", "coprime iff gcd one", "not coprime gcd"),
    ),
    SearchCategory(
        category_id="prime_divisor_extraction",
        description="Prime divisor extraction from non-coprime or gcd facts",
        route_id="prime_divisor",
        role="prime_extraction",
        query_terms=("prime divisor natural", "prime dvd gcd", "exists prime dvd"),
    ),
    SearchCategory(
        category_id="divides_difference",
        description="Divisibility closure for differences",
        route_id="divides_difference",
        role="divisibility_difference",
        query_terms=("dvd subtraction", "divides difference", "dvd sub"),
    ),
    SearchCategory(
        category_id="finite_image",
        description="Finite set and finite image bridge",
        route_id="finite_image_injectivity",
        role="finite_image_bridge",
        query_terms=("Set Finite image", "finite image", "Finite subset"),
    ),
    SearchCategory(
        category_id="injectivity_bridge",
        description="Injectivity predicates and finite image reasoning",
        route_id="finite_image_injectivity",
        role="injectivity_bridge",
        query_terms=("Set InjOn", "Function Injective", "injective finite image"),
    ),
    SearchCategory(
        category_id="nat_descent",
        description="Descent or well-founded reasoning on Nat",
        route_id="nat_descent",
        role="descent_or_induction",
        query_terms=("Nat strong induction", "well founded Nat", "descent Nat"),
    ),
    SearchCategory(
        category_id="parity_factorization",
        description="Parity, oddness, and factorization support",
        route_id="odd_part_factorization",
        role="parity_factorization",
        query_terms=("Nat odd even", "Nat factorization", "two divides"),
    ),
)


def search_premise_groups(
    *,
    project_root: str | Path,
    natural_language_goal: str,
    lean_context: str | None = None,
    query_terms: list[str] | None = None,
    routes: list[dict[str, Any]] | None = None,
    limit_per_group: int = 5,
    include_mathlib: bool = True,
    include_local: bool = True,
) -> dict[str, Any]:
    root = resolve_project_root(project_root)
    custom_terms = tuple(query_terms or [])
    requested_routes = _normalize_routes(routes or [])
    categories = _select_categories(natural_language_goal, custom_terms, requested_routes)
    groups: list[dict[str, Any]] = []
    inspected_paths: list[str] = []

    for category in categories:
        query_pack = _query_pack(category, natural_language_goal, lean_context, custom_terms)
        candidate_map: dict[str, dict[str, Any]] = {}
        for query in query_pack:
            for record, score in search_decl_records(
                root,
                query=query,
                include_mathlib=include_mathlib,
                include_local=include_local,
            )[: max(1, limit_per_group * 3)]:
                inspected_paths.append(str(record.file))
                existing = candidate_map.get(record.name)
                candidate = _candidate_premise(root, record, score, category, query)
                if existing is None or _bucket_rank(candidate["confidence_bucket"]) > _bucket_rank(existing["confidence_bucket"]):
                    candidate_map[record.name] = candidate
        candidates = sorted(
            candidate_map.values(),
            key=lambda item: (_bucket_rank(item["confidence_bucket"]), item["name"]),
            reverse=True,
        )[: max(1, min(limit_per_group, 20))]
        groups.append(
            {
                "route_id": category.route_id,
                "category_id": category.category_id,
                "description": category.description,
                "route_selected_by_tool": False,
                "role": category.role,
                "query_pack": query_pack,
                "candidate_premises": candidates,
                "next_probe_snippets": [item["recommended_check"] for item in candidates],
                "coverage": _coverage_for(category, candidates),
            }
        )

    envelope = ToolEnvelope(
        tool="lean_premise_search",
        status="searched",
        data={
            "natural_language_goal": natural_language_goal,
            "lean_context_present": bool(lean_context),
            "query_terms": list(custom_terms),
            "premise_groups": groups,
            "group_count": len(groups),
            "verify_names_recommended": True,
            "next_recommended_tool": "lean_scout_check_names",
        },
        diagnostics=[],
        provenance=make_provenance(
            project_root=root,
            lean_toolchain=read_lean_toolchain(root),
            mathlib_revision=mathlib_revision(root),
            search_corpus_revision=mathlib_revision(root),
            sources_used=["local_project_declarations", "local_mathlib_declarations"],
            inspected_paths=sorted(set(inspected_paths)),
        ),
    )
    return envelope.as_dict()


def _normalize_routes(routes: list[dict[str, Any]]) -> tuple[str, ...]:
    ids: list[str] = []
    for route in routes:
        route_id = route.get("route_id") or route.get("id")
        description = route.get("description")
        for value in (route_id, description):
            if isinstance(value, str) and value:
                ids.append(value.lower())
    return tuple(ids)


def _select_categories(goal: str, query_terms: tuple[str, ...], routes: tuple[str, ...]) -> tuple[SearchCategory, ...]:
    text = " ".join((goal, *query_terms, *routes)).lower()
    text_tokens = {token for token in text.replace("_", " ").replace(".", " ").split() if len(token) >= 4}
    selected: list[SearchCategory] = []
    for category in BUILTIN_CATEGORIES:
        haystack = " ".join((category.category_id, category.description, category.route_id, category.role, *category.query_terms)).lower()
        category_tokens = set(_category_trigger_tokens(category))
        if category_tokens & text_tokens:
            selected.append(category)
    if selected:
        return tuple(dict.fromkeys(selected))
    return BUILTIN_CATEGORIES[:4]


def _category_trigger_tokens(category: SearchCategory) -> tuple[str, ...]:
    return tuple(
        token
        for item in (category.category_id, category.description, category.route_id, category.role, *category.query_terms)
        for token in item.lower().replace("_", " ").split()
        if len(token) >= 4
    )


def _query_pack(
    category: SearchCategory,
    natural_language_goal: str,
    lean_context: str | None,
    query_terms: tuple[str, ...],
) -> list[str]:
    pack = [*category.query_terms]
    if query_terms:
        pack.append(" ".join(query_terms))
    pack.append(natural_language_goal)
    if lean_context:
        pack.append(" ".join(lean_context.split()[:32]))
    seen: set[str] = set()
    result: list[str] = []
    for query in pack:
        normalized = " ".join(query.split())
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def _candidate_premise(
    project_root: Path,
    record: DeclRecord,
    score: float,
    category: SearchCategory,
    query: str,
) -> dict[str, Any]:
    return {
        "name": record.name,
        "kind": record.kind,
        "role": category.role,
        "file": _relative_or_abs(record.file, project_root),
        "line": record.line,
        "statement_snippet": record.statement_snippet,
        "retrieval_sources": [record.source, "local_decl_search"],
        "matched_query": query,
        "confidence_bucket": score_bucket(score),
        "verified_name": False,
        "recommended_check": f"#check {record.name}",
    }


def _coverage_for(category: SearchCategory, candidates: list[dict[str, Any]]) -> dict[str, bool]:
    names = " ".join(str(item.get("name", "")) for item in candidates).lower()
    snippets = " ".join(str(item.get("statement_snippet", "")) for item in candidates).lower()
    text = f"{names} {snippets}"
    if category.category_id in {"finite_image", "injectivity_bridge"}:
        return {
            "has_finite_image_lemma": "finite" in text and "image" in text,
            "has_inj_or_subset_bridge": "inj" in text or "subset" in text or "injective" in text,
            "has_domain_finiteness_bridge": "finite" in text,
        }
    if category.category_id == "nat_gcd_coprime":
        return {
            "has_coprime_item": "coprime" in text,
            "has_gcd_item": "gcd" in text,
            "has_rewrite_bridge": "iff" in text or "eq" in text,
        }
    if category.category_id == "prime_divisor_extraction":
        return {
            "has_prime_item": "prime" in text,
            "has_divisibility_item": "dvd" in text or "divides" in text,
            "has_exists_item": "exists" in text or "∃" in text,
        }
    return {
        "has_any_candidate": bool(candidates),
    }


def _relative_or_abs(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _bucket_rank(bucket: str) -> int:
    return {"high": 3, "medium": 2, "low": 1}.get(bucket, 0)
