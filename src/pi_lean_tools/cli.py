"""Command line interface for pi-lean-tools."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from .check_names import check_names
from .check_snippet import check_snippet
from .decl_search import search_declarations
from .error_explain import explain_error
from .premise_search import search_premise_groups
from .project import DEFAULT_PROJECT_ROOT_ENV
from .try_tactics import try_tactics


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pi-lean-tools")
    subparsers = parser.add_subparsers(dest="command", required=True)

    check_names_parser = subparsers.add_parser("check-names")
    _add_project_args(check_names_parser)
    check_names_parser.add_argument("names", nargs="+")

    snippet_parser = subparsers.add_parser("check-snippet")
    _add_project_args(snippet_parser)
    snippet_parser.add_argument("--code", required=True)
    snippet_parser.add_argument("--allow-sorry", action="store_true", default=True)
    snippet_parser.add_argument("--no-allow-sorry", action="store_false", dest="allow_sorry")
    snippet_parser.add_argument("--mode", default="api_probe")

    search_parser = subparsers.add_parser("decl-search")
    _add_project_args(search_parser, include_timeout=False)
    search_parser.add_argument("--query", required=True)
    search_parser.add_argument("--limit", type=int, default=20)
    search_parser.add_argument("--no-mathlib", action="store_true")
    search_parser.add_argument("--no-local", action="store_true")

    error_parser = subparsers.add_parser("error-explain")
    error_parser.add_argument("--error-message", required=True)
    error_parser.add_argument("--surrounding-code")

    try_tactics_parser = subparsers.add_parser("try-tactics")
    _add_project_args(try_tactics_parser)
    try_tactics_parser.add_argument("--goal", required=True, help="declaration header without ':= by ...'")
    try_tactics_parser.add_argument("--tactic", action="append", default=[])
    try_tactics_parser.add_argument("--stop-after-first-close", action="store_true")

    premise_parser = subparsers.add_parser("premise-search")
    _add_project_args(premise_parser, include_timeout=False)
    premise_parser.add_argument("--natural-language-goal", required=True)
    premise_parser.add_argument("--lean-context")
    premise_parser.add_argument("--query-term", action="append", default=[])
    premise_parser.add_argument("--route", action="append", default=[])
    premise_parser.add_argument("--limit-per-group", type=int, default=5)
    premise_parser.add_argument("--no-mathlib", action="store_true")
    premise_parser.add_argument("--no-local", action="store_true")

    args = parser.parse_args(argv)
    try:
        payload = _dispatch(args)
    except Exception as error:  # pragma: no cover - defensive CLI envelope
        payload = {
            "tool": args.command,
            "status": "runner_failed",
            "data": {"error": str(error)},
            "diagnostics": [{"severity": "error", "message": str(error), "file": None, "line": None, "column": None}],
            "authority": {
                "usable_as_context": True,
                "usable_as_proof_evidence": False,
                "proof_authority": "none",
                "advisory_only": True,
            },
            "final_verify_required": True,
        }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def _add_project_args(parser: argparse.ArgumentParser, *, include_timeout: bool = True) -> None:
    parser.add_argument(
        "--project-root",
        default=None,
        help=f"Lean/Lake project root; defaults to ${DEFAULT_PROJECT_ROOT_ENV} when set, otherwise cwd",
    )
    parser.add_argument("--imports", action="append", default=[])
    if include_timeout:
        parser.add_argument("--timeout-sec", type=int, default=15)


def _dispatch(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "check-names":
        return check_names(
            project_root=args.project_root,
            names=args.names,
            imports=args.imports or ["Mathlib"],
            timeout_sec=args.timeout_sec,
        )
    if args.command == "check-snippet":
        return check_snippet(
            project_root=args.project_root,
            code=args.code,
            imports=args.imports or ["Mathlib"],
            timeout_sec=args.timeout_sec,
            allow_sorry=args.allow_sorry,
            mode=args.mode,
        )
    if args.command == "decl-search":
        return search_declarations(
            project_root=args.project_root,
            query=args.query,
            limit=args.limit,
            include_mathlib=not args.no_mathlib,
            include_local=not args.no_local,
        )
    if args.command == "error-explain":
        return explain_error(
            error_message=args.error_message,
            surrounding_code=args.surrounding_code,
        )
    if args.command == "try-tactics":
        return try_tactics(
            project_root=args.project_root,
            goal_declaration=args.goal,
            imports=args.imports or ["Mathlib"],
            tactics=args.tactic or None,
            timeout_sec=args.timeout_sec,
            stop_after_first_close=args.stop_after_first_close,
        )
    if args.command == "premise-search":
        return search_premise_groups(
            project_root=args.project_root,
            natural_language_goal=args.natural_language_goal,
            lean_context=args.lean_context,
            query_terms=args.query_term,
            routes=[{"route_id": item} for item in args.route],
            limit_per_group=args.limit_per_group,
            include_mathlib=not args.no_mathlib,
            include_local=not args.no_local,
        )
    raise ValueError(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
