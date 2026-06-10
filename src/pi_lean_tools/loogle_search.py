"""Fuzzy declaration search backed by Loogle, with local-revision verification.

Loogle answers two query shapes the regex decl_search cannot:
type-pattern queries (`Nat.Coprime _ _ -> Nat.gcd _ _ = 1`) and indexed
name/constant queries. Backends, in resolution order:

1. ``PI_LEAN_TOOLS_LOOGLE_URL`` — any loogle JSON server (self-hosted or
   local), queried at ``<url>/json?q=...``.
2. A local loogle binary (``PI_LEAN_TOOLS_LOOGLE_BIN`` or auto-detected),
   wrapped in a persistent daemon so the index loads once.
3. ``https://loogle.lean-lang.org`` — ONLY when ``PI_LEAN_TOOLS_LOOGLE_REMOTE=on``.
   Off by default: hosted indexes track a different Mathlib revision and
   queries leak goal statements to an external service, which matters for
   blind evaluation runs.

Because any backend may index a different Mathlib revision than the local
workspace, the top hits are verified with local ``#check`` probes
(cache/daemon-fast) and annotated ``exists_in_local_revision``.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any
import urllib.parse
import urllib.request

from .check_names import check_names
from .daemon_util import request_json, spawn_daemon_once
from .loogle_daemon import state_path_for
from .policy import ToolEnvelope, make_provenance
from .project import mathlib_revision, read_lean_toolchain, resolve_project_root

LOOGLE_URL_ENV = "PI_LEAN_TOOLS_LOOGLE_URL"
LOOGLE_BIN_ENV = "PI_LEAN_TOOLS_LOOGLE_BIN"
LOOGLE_REMOTE_ENV = "PI_LEAN_TOOLS_LOOGLE_REMOTE"
HOSTED_LOOGLE_URL = "https://loogle.lean-lang.org"

_ON_VALUES = frozenset({"on", "1", "true", "yes"})
_LOOGLE_BIN_CANDIDATES = (
    Path.home() / "Documents" / "loogle" / ".lake" / "build" / "bin" / "loogle",
)


def loogle_search(
    *,
    project_root: str | Path,
    query: str,
    verify_names: bool = True,
    verify_limit: int = 8,
    timeout_sec: int = 30,
) -> dict[str, Any]:
    root = resolve_project_root(project_root)
    response, backend = _query_backends(query=query, timeout_sec=timeout_sec)

    if response is None:
        if _resolve_loogle_bin() is not None:
            status = "backend_warming"
            note = (
                "A local loogle daemon is starting and building its search index "
                "(first start takes a few minutes). Retry this query later in the "
                "turn, or use lean_scout_decl_search in the meantime."
            )
        else:
            status = "no_backend"
            note = (
                "No loogle backend available. Configure PI_LEAN_TOOLS_LOOGLE_URL, "
                "build a local loogle binary (PI_LEAN_TOOLS_LOOGLE_BIN), or "
                "explicitly opt into the hosted service with "
                "PI_LEAN_TOOLS_LOOGLE_REMOTE=on. Fall back to lean_scout_decl_search."
            )
        data: dict[str, Any] = {
            "query": query,
            "backend": backend,
            "hits": [],
            "note": note,
        }
    elif response.get("error"):
        status = "query_error"
        data = {
            "query": query,
            "backend": backend,
            "hits": [],
            "error": response.get("error"),
            "suggestions": response.get("suggestions") or [],
        }
    else:
        hits = [
            {
                "name": str(hit.get("name") or ""),
                "type": str(hit.get("type") or "").strip(),
                "module": str(hit.get("module") or ""),
                "doc": hit.get("doc"),
            }
            for hit in (response.get("hits") or [])
            if isinstance(hit, dict)
        ]
        if verify_names and hits:
            _verify_hits(hits[: max(0, verify_limit)], root=root, timeout_sec=timeout_sec)
        status = "searched"
        data = {
            "query": query,
            "backend": backend,
            "count": response.get("count"),
            "header": response.get("header"),
            "hits": hits,
            "verification": {
                "verified_top_n": min(len(hits), max(0, verify_limit)) if verify_names else 0,
                "method": "local #check probe",
                "note": (
                    "exists_in_local_revision=false means the backend's Mathlib "
                    "revision has the name but the local workspace does not; "
                    "search nearby names with lean_scout_decl_search."
                ),
            },
        }

    envelope = ToolEnvelope(
        tool="lean_loogle_search",
        status=status,
        data=data,
        diagnostics=[],
        provenance=make_provenance(
            project_root=root,
            lean_toolchain=read_lean_toolchain(root),
            mathlib_revision=mathlib_revision(root),
            sources_used=[f"loogle_backend:{backend}"] if backend else [],
            inspected_paths=[],
        ),
    )
    return envelope.as_dict()


def _verify_hits(hits: list[dict[str, Any]], *, root: Path, timeout_sec: int) -> None:
    names = [hit["name"] for hit in hits if hit.get("name")]
    if not names:
        return
    try:
        payload = check_names(project_root=root, names=names, timeout_sec=timeout_sec)
        results = {
            str(item.get("name")): bool(item.get("exists"))
            for item in payload.get("data", {}).get("results", [])
        }
    except Exception:
        results = {}
    for hit in hits:
        hit["exists_in_local_revision"] = results.get(hit["name"])


def _query_backends(*, query: str, timeout_sec: int) -> tuple[dict[str, Any] | None, str]:
    configured_url = os.environ.get(LOOGLE_URL_ENV, "").strip()
    if configured_url:
        response = _query_server(configured_url, query=query, timeout_sec=timeout_sec)
        if response is not None:
            return response, f"server:{configured_url}"

    loogle_bin = _resolve_loogle_bin()
    if loogle_bin is not None:
        response = _query_local_daemon(loogle_bin, query=query, timeout_sec=timeout_sec)
        if response is not None:
            return response, f"local_daemon:{loogle_bin}"

    if os.environ.get(LOOGLE_REMOTE_ENV, "").strip().lower() in _ON_VALUES:
        response = _query_server(HOSTED_LOOGLE_URL, query=query, timeout_sec=timeout_sec)
        if response is not None:
            return response, f"hosted:{HOSTED_LOOGLE_URL}"

    return None, ""


def _query_server(base_url: str, *, query: str, timeout_sec: int) -> dict[str, Any] | None:
    url = f"{base_url.rstrip('/')}/json?{urllib.parse.urlencode({'q': query})}"
    try:
        with urllib.request.urlopen(url, timeout=timeout_sec) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def _resolve_loogle_bin() -> Path | None:
    configured = os.environ.get(LOOGLE_BIN_ENV, "").strip()
    if configured:
        path = Path(configured).expanduser()
        return path if path.is_file() else None
    for candidate in _LOOGLE_BIN_CANDIDATES:
        if candidate.is_file():
            return candidate
    return None


def loogle_socket_path(loogle_bin: Path) -> Path:
    key = hashlib.sha256(str(loogle_bin).encode("utf-8")).hexdigest()[:16]
    return Path(tempfile.gettempdir()) / "pi-lean-tools" / "loogle" / f"{key}.sock"


def _query_local_daemon(loogle_bin: Path, *, query: str, timeout_sec: int) -> dict[str, Any] | None:
    socket_path = loogle_socket_path(loogle_bin)
    response = request_json(
        socket_path,
        {"query": query, "timeout_sec": timeout_sec},
        timeout_sec=timeout_sec + 10.0,
    )
    if response is None:
        spawn_daemon_once(
            module="pi_lean_tools.loogle_daemon",
            args=["--loogle-bin", str(loogle_bin), "--socket", str(socket_path)],
            socket_path=socket_path,
            state_path=state_path_for(socket_path),
        )
        return None
    if response.get("ok") is not True:
        return None
    return response
