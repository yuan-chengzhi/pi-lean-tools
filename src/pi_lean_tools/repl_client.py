"""Client for the persistent Lean REPL daemon.

The first probe against a project spawns the daemon in the background and
falls back to the cold lake/lean runner while the daemon warms up (importing
Mathlib once). Subsequent probes hit the warm daemon and return in
milliseconds. Any daemon problem degrades to the cold runner, never to a
probe failure.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from typing import Any

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
    response = _request(
        socket_path,
        {"imports": imports, "code": code, "timeout_sec": timeout_sec},
        timeout_sec=timeout_sec + 10.0,
    )
    if response is None:
        _spawn_daemon_once(project_root=project_root, repl_bin=repl_bin, socket_path=socket_path)
        return None
    if response.get("ok") is not True:
        return None
    return response


def _request(socket_path: Path, payload: dict[str, Any], *, timeout_sec: float) -> dict[str, Any] | None:
    if not socket_path.exists():
        return None
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(timeout_sec)
            client.connect(str(socket_path))
            client.sendall(json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n")
            chunks: list[bytes] = []
            while True:
                chunk = client.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
                if chunk.endswith(b"\n"):
                    break
        raw = b"".join(chunks)
        return json.loads(raw.decode("utf-8")) if raw.strip() else None
    except (OSError, json.JSONDecodeError):
        return None


def _spawn_daemon_once(*, project_root: Path, repl_bin: Path, socket_path: Path) -> None:
    state_path = state_path_for(socket_path)
    if _daemon_looks_alive(state_path):
        return
    lock_path = socket_path.with_name(socket_path.name + ".spawn.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        if _lock_is_stale(lock_path):
            lock_path.unlink(missing_ok=True)
        return
    try:
        os.write(fd, str(os.getpid()).encode("utf-8"))
    finally:
        os.close(fd)
    log_path = socket_path.with_name(socket_path.name + ".log")
    env = dict(os.environ)
    package_parent = str(Path(__file__).resolve().parents[1])
    env["PYTHONPATH"] = (
        package_parent
        if not env.get("PYTHONPATH")
        else f"{package_parent}{os.pathsep}{env['PYTHONPATH']}"
    )
    with log_path.open("a", encoding="utf-8") as log_handle:
        subprocess.Popen(
            [
                sys.executable,
                "-m",
                "pi_lean_tools.repl_daemon",
                "--project-root",
                str(project_root),
                "--repl-bin",
                str(repl_bin),
                "--socket",
                str(socket_path),
            ],
            env=env,
            stdout=log_handle,
            stderr=log_handle,
            start_new_session=True,
        )
    lock_path.unlink(missing_ok=True)


def _daemon_looks_alive(state_path: Path) -> bool:
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        pid = int(state["pid"])
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return False
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    return True


def _lock_is_stale(lock_path: Path, *, max_age_sec: float = 60.0) -> bool:
    try:
        return time.time() - lock_path.stat().st_mtime > max_age_sec
    except OSError:
        return False
