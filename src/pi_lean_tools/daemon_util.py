"""Shared helpers for unix-socket daemon clients (REPL, Loogle)."""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from typing import Any


def request_json(socket_path: Path, payload: dict[str, Any], *, timeout_sec: float) -> dict[str, Any] | None:
    """One JSON-line round trip over a unix socket; None on any failure."""
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


def spawn_daemon_once(*, module: str, args: list[str], socket_path: Path, state_path: Path) -> None:
    """Spawn a daemon module detached, at most once per socket path."""
    if daemon_looks_alive(state_path):
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
            [sys.executable, "-m", module, *args],
            env=env,
            stdout=log_handle,
            stderr=log_handle,
            start_new_session=True,
        )
    lock_path.unlink(missing_ok=True)


def daemon_looks_alive(state_path: Path) -> bool:
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
