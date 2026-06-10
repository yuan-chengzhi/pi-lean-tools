"""Shared on-disk cache for Lean probe results.

Each tool call runs in a fresh CLI process, so the cache lives on disk and is
keyed by probe source content plus the toolchain/Mathlib revisions that could
change its outcome. Parallel swarm attempts pointed at the same cache directory
(via PI_LEAN_TOOLS_CACHE_DIR) share probe results automatically.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any
import uuid

CACHE_DIR_ENV = "PI_LEAN_TOOLS_CACHE_DIR"
CACHE_MODE_ENV = "PI_LEAN_TOOLS_PROBE_CACHE"
SCHEMA_VERSION = "probe_cache_v1"

_CACHEABLE_STATUSES = frozenset({"elaborated", "elab_failed"})
_OFF_VALUES = frozenset({"off", "0", "false", "no", "disabled"})


def cache_enabled() -> bool:
    return os.environ.get(CACHE_MODE_ENV, "").strip().lower() not in _OFF_VALUES


def resolve_cache_dir() -> Path:
    configured = os.environ.get(CACHE_DIR_ENV, "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path(tempfile.gettempdir()) / "pi-lean-tools" / "probe_cache"


def probe_cache_key(
    *,
    source: str,
    project_root: Path,
    lean_toolchain: str | None,
    mathlib_revision: str | None,
) -> str:
    payload = json.dumps(
        {
            "schema": SCHEMA_VERSION,
            "source": source,
            "project_root": str(project_root),
            "lean_toolchain": lean_toolchain,
            "mathlib_revision": mathlib_revision,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_cached_probe(key: str) -> dict[str, Any] | None:
    if not cache_enabled():
        return None
    path = resolve_cache_dir() / f"{key}.json"
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        return None
    result = payload.get("result")
    if not isinstance(result, dict) or result.get("status") not in _CACHEABLE_STATUSES:
        return None
    return payload


def store_cached_probe(key: str, *, result: dict[str, Any]) -> bool:
    if not cache_enabled():
        return False
    if result.get("status") not in _CACHEABLE_STATUSES:
        return False
    cache_dir = resolve_cache_dir()
    payload = {
        "schema_version": SCHEMA_VERSION,
        "cached_at": datetime.now(UTC).isoformat(),
        "result": result,
    }
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        # Atomic publish so concurrent attempts never read a partial entry.
        tmp_path = cache_dir / f".{key}.{uuid.uuid4().hex}.tmp"
        tmp_path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        tmp_path.replace(cache_dir / f"{key}.json")
    except OSError:
        return False
    return True
