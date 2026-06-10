"""Persistent local Loogle daemon.

Holds one `loogle --interactive --json` child so the Mathlib search index is
built once and kept in memory; queries then answer in milliseconds. The index
is persisted next to the daemon socket on first start and reloaded with
`--read-index` on later starts.

Protocol (one JSON line per request/response over a unix socket):
  request:  {"query": "Nat.Coprime _ _ -> Nat.gcd _ _ = 1", "timeout_sec": 30}
  response: the loogle JSON result, plus {"ok": true}
            {"ok": false, "error": "..."}
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import socketserver
import subprocess
import sys
import threading
import time
from typing import Any


def state_path_for(socket_path: Path) -> Path:
    return socket_path.with_name(socket_path.name + ".state.json")


def index_path_for(socket_path: Path) -> Path:
    return socket_path.with_name(socket_path.name + ".index")


class LoogleProcess:
    def __init__(self, *, loogle_bin: Path, index_path: Path | None) -> None:
        self.loogle_bin = loogle_bin
        self.index_path = index_path
        self._lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None

    def query(self, *, query: str, timeout_sec: float) -> dict[str, Any]:
        with self._lock:
            try:
                self._ensure_process()
                started = time.monotonic()
                response = self._send(query, timeout_sec=timeout_sec)
                response["ok"] = True
                response["elapsed_ms"] = int((time.monotonic() - started) * 1000)
                return response
            except Exception as error:
                self._restart()
                return {"ok": False, "error": f"loogle failure: {error}"}

    def warm(self, *, timeout_sec: float = 1800.0) -> None:
        self.query(query="Nat", timeout_sec=timeout_sec)

    def _ensure_process(self) -> None:
        if self._process is not None and self._process.poll() is None:
            return
        command = [str(self.loogle_bin), "--interactive", "--json"]
        if self.index_path is not None and self.index_path.is_file():
            command.extend(["--read-index", str(self.index_path)])
        elif self.index_path is not None:
            command.extend(["--write-index", str(self.index_path)])
        self._process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            start_new_session=True,
        )

    def _send(self, query: str, *, timeout_sec: float) -> dict[str, Any]:
        process = self._process
        assert process is not None and process.stdin is not None and process.stdout is not None
        process.stdin.write(query.replace("\n", " ").strip() + "\n")
        process.stdin.flush()

        result: dict[str, Any] = {}
        error: list[BaseException] = []

        def read_response() -> None:
            try:
                while True:
                    line = process.stdout.readline()
                    if not line:
                        raise RuntimeError("loogle closed stdout")
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        parsed = json.loads(stripped)
                    except json.JSONDecodeError:
                        # Banner lines like "Loogle is ready." are not JSON.
                        continue
                    if isinstance(parsed, dict):
                        result.update(parsed)
                        return
            except BaseException as exc:  # noqa: BLE001 - forwarded to caller thread
                error.append(exc)

        reader = threading.Thread(target=read_response, daemon=True)
        reader.start()
        reader.join(timeout=timeout_sec)
        if reader.is_alive():
            raise TimeoutError(f"no loogle response within {timeout_sec}s")
        if error:
            raise RuntimeError(str(error[0]))
        return result

    def _restart(self) -> None:
        process = self._process
        self._process = None
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                process.kill()


def serve(
    *,
    loogle_bin: Path,
    socket_path: Path,
    idle_timeout_sec: float,
) -> int:
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    socket_path.unlink(missing_ok=True)
    state_path = state_path_for(socket_path)
    loogle = LoogleProcess(loogle_bin=loogle_bin, index_path=index_path_for(socket_path))
    last_activity = [time.monotonic()]

    class Handler(socketserver.StreamRequestHandler):
        def handle(self) -> None:
            last_activity[0] = time.monotonic()
            try:
                request = json.loads(self.rfile.readline().decode("utf-8"))
                response = loogle.query(
                    query=str(request.get("query") or ""),
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
    threading.Thread(target=loogle.warm, daemon=True).start()
    state_path.write_text(
        json.dumps({
            "status": "ready",
            "pid": os.getpid(),
            "loogle_bin": str(loogle_bin),
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
    parser = argparse.ArgumentParser(prog="pi-lean-tools-loogle-daemon")
    parser.add_argument("--loogle-bin", required=True, type=Path)
    parser.add_argument("--socket", required=True, type=Path)
    parser.add_argument("--idle-timeout-sec", type=float, default=7200.0)
    args = parser.parse_args(argv)
    return serve(
        loogle_bin=args.loogle_bin.resolve(),
        socket_path=args.socket,
        idle_timeout_sec=args.idle_timeout_sec,
    )


if __name__ == "__main__":
    sys.exit(main())
