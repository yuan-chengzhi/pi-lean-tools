"""Client for the persistent Lean REPL daemon.

The first probe against a project spawns the daemon in the background and
falls back to the cold lake/lean runner while the daemon warms up (importing
Mathlib once). Subsequent probes hit the warm daemon and return in
milliseconds. Any daemon problem degrades to the cold runner, never to a
probe failure.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import tempfile
from typing import Any

from .daemon_util import request_json, spawn_daemon_once
from .repl_daemon import state_path_for

REPL_MODE_ENV = "PI_LEAN_TOOLS_REPL"
REPL_BIN_ENV = "PI_LEAN_TOOLS_REPL_BIN"

_OFF_VALUES = frozenset({"off", "0", "false", "no", "disabled"})
_REPL_BIN_CANDIDATES = (
    Path("..") / "repl" / ".lake" / "build" / "bin" / "repl",
    Path("repl") / ".lake" / "build" / "bin" / "repl",
)


def repl_enabled() -> bool:
    return os.environ.get(REPL_MODE_ENV, "").strip().lower() not in _OFF_VALUES


def resolve_repl_bin(project_root: Path) -> Path | None:
    configured = os.environ.get(REPL_BIN_ENV, "").strip()
    if configured:
        path = Path(configured).expanduser()
        return path if path.is_file() else None
    for candidate in _REPL_BIN_CANDIDATES:
        path = (project_root / candidate).resolve()
        if path.is_file():
            return path
    return None


def socket_path_for(project_root: Path, repl_bin: Path) -> Path:
    key = hashlib.sha256(f"{project_root}\n{repl_bin}".encode("utf-8")).hexdigest()[:16]
    return Path(tempfile.gettempdir()) / "pi-lean-tools" / "repl" / f"{key}.sock"


def repl_probe(
    *,
    project_root: Path,
    imports: list[str],
    code: str,
    timeout_sec: float,
) -> dict[str, Any] | None:
    """Return a daemon probe response, or None when the cold runner should run."""
    if not repl_enabled():
        return None
    repl_bin = resolve_repl_bin(project_root)
    if repl_bin is None:
        return None
    socket_path = socket_path_for(project_root, repl_bin)
    response = request_json(
        socket_path,
        {"imports": imports, "code": code, "timeout_sec": timeout_sec},
        timeout_sec=timeout_sec + 10.0,
    )
    if response is None:
        spawn_daemon_once(
            module="pi_lean_tools.repl_daemon",
            args=[
                "--project-root",
                str(project_root),
                "--repl-bin",
                str(repl_bin),
                "--socket",
                str(socket_path),
            ],
            socket_path=socket_path,
            state_path=state_path_for(socket_path),
        )
        return None
    if response.get("ok") is not True:
        return None
    return response
