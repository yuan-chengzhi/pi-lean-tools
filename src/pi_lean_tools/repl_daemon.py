"""Persistent Lean REPL daemon.

Holds one leanprover-community/repl child process with import environments
kept in memory, so probes skip the per-call `import Mathlib` elaboration cost.
Each scout CLI invocation is a short-lived process, so the daemon runs
standalone and serves probe requests over a unix domain socket.

Protocol (one JSON line per request/response):
  request:  {"imports": ["Mathlib"], "code": "#check Nat", "timeout_sec": 30}
  response: {"ok": true, "messages": [...], "sorries": [...],
             "env_import_ms": 0, "elapsed_ms": 12}
            {"ok": false, "error": "..."}
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import socket
import socketserver
import subprocess
import sys
import threading
import time
from typing import Any

from .project import has_lake_config


def state_path_for(socket_path: Path) -> Path:
    return socket_path.with_name(socket_path.name + ".state.json")


class ReplProcess:
    """Owns the repl child process and its import-environment cache."""

    def __init__(self, *, project_root: Path, repl_bin: Path) -> None:
        self.project_root = project_root
        self.repl_bin = repl_bin
        self._lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None
        self._envs: dict[str, int] = {}

    def probe(self, *, imports: list[str], code: str, timeout_sec: float) -> dict[str, Any]:
        with self._lock:
            try:
                self._ensure_process()
                import_started = time.monotonic()
                env_id = self._ensure_env(imports, timeout_sec=max(timeout_sec, 300.0))
                env_import_ms = int((time.monotonic() - import_started) * 1000)
                started = time.monotonic()
                response = self._send({"cmd": code, "env": env_id}, timeout_sec=timeout_sec)
                return {
                    "ok": True,
                    "messages": response.get("messages") or [],
                    "sorries": response.get("sorries") or [],
                    "env_import_ms": env_import_ms,
                    "elapsed_ms": int((time.monotonic() - started) * 1000),
                }
            except _ReplTimeout as error:
                self._restart()
                return {"ok": False, "error": f"repl timeout: {error}"}
            except Exception as error:
                self._restart()
                return {"ok": False, "error": f"repl failure: {error}"}

    def _ensure_process(self) -> None:
        if self._process is not None and self._process.poll() is None:
            return
        command = [str(self.repl_bin)]
        if has_lake_config(self.project_root):
            command = ["lake", "env", str(self.repl_bin)]
        self._process = subprocess.Popen(
            command,
            cwd=str(self.project_root),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
        self._envs = {}

    def _ensure_env(self, imports: list[str], *, timeout_sec: float) -> int:
        key = "\n".join(sorted(set(item.strip() for item in imports if item.strip())))
        if key in self._envs:
            return self._envs[key]
        import_cmd = "\n".join(f"import {item}" for item in key.split("\n") if item)
        response = self._send({"cmd": import_cmd or "-- empty"}, timeout_sec=timeout_sec)
        env_id = response.get("env")
        if not isinstance(env_id, int):
            raise RuntimeError(f"repl returned no env for imports: {response}")
        self._envs[key] = env_id
        return env_id

    def _send(self, payload: dict[str, Any], *, timeout_sec: float) -> dict[str, Any]:
        process = self._process
        assert process is not None and process.stdin is not None and process.stdout is not None
        process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n\n")
        process.stdin.flush()

        result: dict[str, Any] = {}
        error: list[BaseException] = []

        def read_response() -> None:
            try:
                buffer: list[str] = []
                while True:
                    line = process.stdout.readline()
                    if not line:
                        raise RuntimeError("repl closed stdout")
                    if line.strip() == "" and buffer:
                        break
                    if line.strip() or buffer:
                        buffer.append(line)
                result.update(json.loads("".join(buffer)))
            except BaseException as exc:  # noqa: BLE001 - forwarded to caller thread
                error.append(exc)

        reader = threading.Thread(target=read_response, daemon=True)
        reader.start()
        reader.join(timeout=timeout_sec)
        if reader.is_alive():
            raise _ReplTimeout(f"no response within {timeout_sec}s")
        if error:
            raise RuntimeError(str(error[0]))
        return result

    def _restart(self) -> None:
        process = self._process
        self._process = None
        self._envs = {}
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                process.kill()


class _ReplTimeout(Exception):
    pass


def serve(
    *,
    project_root: Path,
    repl_bin: Path,
    socket_path: Path,
    idle_timeout_sec: float,
    prewarm_imports: list[str] | None = None,
) -> int:
    repl = ReplProcess(project_root=project_root, repl_bin=repl_bin)
    last_activity = [time.monotonic()]
    if prewarm_imports:
        def prewarm() -> None:
            repl.probe(imports=prewarm_imports, code="-- prewarm", timeout_sec=600.0)
            last_activity[0] = time.monotonic()

        threading.Thread(target=prewarm, daemon=True).start()
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    socket_path.unlink(missing_ok=True)
    state_path = state_path_for(socket_path)

    class Handler(socketserver.StreamRequestHandler):
        def handle(self) -> None:
            last_activity[0] = time.monotonic()
            try:
                raw = self.rfile.readline()
                request = json.loads(raw.decode("utf-8"))
                response = repl.probe(
                    imports=list(request.get("imports") or []),
                    code=str(request.get("code") or ""),
                    timeout_sec=float(request.get("timeout_sec") or 30.0),
                )
            except Exception as error:
                response = {"ok": False, "error": f"bad request: {error}"}
            self.wfile.write(json.dumps(response, ensure_ascii=False).encode("utf-8") + b"\n")
            last_activity[0] = time.monotonic()

    class Server(socketserver.ThreadingUnixStreamServer):
        daemon_threads = True

    server = Server(str(socket_path), Handler)

    def reap_when_idle() -> None:
        while True:
            time.sleep(15)
            if time.monotonic() - last_activity[0] > idle_timeout_sec:
                state_path.unlink(missing_ok=True)
                socket_path.unlink(missing_ok=True)
                os._exit(0)

    threading.Thread(target=reap_when_idle, daemon=True).start()
    state_path.write_text(
        json.dumps({
            "status": "ready",
            "pid": os.getpid(),
            "project_root": str(project_root),
            "repl_bin": str(repl_bin),
            "started_at": time.time(),
        }) + "\n",
        encoding="utf-8",
    )
    try:
        server.serve_forever()
    finally:
        state_path.unlink(missing_ok=True)
        socket_path.unlink(missing_ok=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pi-lean-tools-repl-daemon")
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--repl-bin", required=True, type=Path)
    parser.add_argument("--socket", required=True, type=Path)
    parser.add_argument("--idle-timeout-sec", type=float, default=7200.0)
    parser.add_argument(
        "--prewarm-imports",
        default="Mathlib",
        help="comma-separated imports to elaborate in the background at startup; empty disables",
    )
    args = parser.parse_args(argv)
    prewarm = [item.strip() for item in args.prewarm_imports.split(",") if item.strip()]
    return serve(
        project_root=args.project_root.resolve(),
        repl_bin=args.repl_bin.resolve(),
        socket_path=args.socket,
        idle_timeout_sec=args.idle_timeout_sec,
        prewarm_imports=prewarm or None,
    )


if __name__ == "__main__":
    sys.exit(main())
