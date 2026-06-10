"""Run small Lean probes inside a Lean or Lake project."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
import tempfile
import time
from typing import Any
import uuid

from .diagnostics import first_error, parse_diagnostics
from .policy import truncate_text
from .probe_cache import load_cached_probe, probe_cache_key, store_cached_probe
from .project import has_lake_config, mathlib_revision, read_lean_toolchain


@dataclass(frozen=True)
class LeanRunResult:
    status: str
    exit_code: int | None
    stdout: str
    stderr: str
    diagnostics: list[dict[str, Any]]
    first_error: str | None
    elapsed_ms: int
    checked_file: Path
    command: list[str]
    runner_mode: str
    cache_hit: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "exit_code": self.exit_code,
            "stdout": truncate_text(self.stdout),
            "stderr": truncate_text(self.stderr),
            "diagnostics": self.diagnostics,
            "first_error": self.first_error,
            "elapsed_ms": self.elapsed_ms,
            "checked_file_ref": str(self.checked_file),
            "command": self.command,
            "runner_mode": self.runner_mode,
            "cache_hit": self.cache_hit,
        }


def lean_source(imports: list[str], code: str) -> str:
    import_lines = [f"import {item}" for item in imports if item.strip()]
    return "\n".join([*import_lines, "", code.rstrip(), ""]) + "\n"


def run_lean_probe(
    *,
    project_root: Path,
    source: str,
    timeout_sec: int = 15,
    prefer_lake_lean: bool = True,
) -> LeanRunResult:
    cache_key = probe_cache_key(
        source=source,
        project_root=project_root,
        lean_toolchain=read_lean_toolchain(project_root),
        mathlib_revision=mathlib_revision(project_root),
    )
    started_lookup = time.monotonic()
    cached = load_cached_probe(cache_key)
    if cached is not None:
        return _result_from_cache(cached["result"], lookup_elapsed_ms=int((time.monotonic() - started_lookup) * 1000))

    tmp_root = Path(tempfile.gettempdir()) / "pi-lean-tools"
    tmp_root.mkdir(parents=True, exist_ok=True)
    checked_file = tmp_root / f"probe_{uuid.uuid4().hex}.lean"
    checked_file.write_text(source, encoding="utf-8")

    commands: list[list[str]] = []
    lake_available = has_lake_config(project_root)
    if prefer_lake_lean and lake_available:
        commands.append(["lake", "lean", str(checked_file)])
        commands.append(["lake", "env", "lean", str(checked_file)])
    commands.append(["lean", str(checked_file)])

    last: LeanRunResult | None = None
    for command in commands:
        started = time.monotonic()
        try:
            completed = subprocess.run(
                command,
                cwd=str(project_root),
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout_sec,
            )
            elapsed = int((time.monotonic() - started) * 1000)
            diagnostics = parse_diagnostics(completed.stdout, completed.stderr)
            status = "elaborated" if completed.returncode == 0 else "elab_failed"
            result = LeanRunResult(
                status=status,
                exit_code=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
                diagnostics=diagnostics,
                first_error=first_error(diagnostics),
                elapsed_ms=elapsed,
                checked_file=checked_file,
                command=command,
                runner_mode=_runner_mode(command, lake_available),
            )
            if completed.returncode == 0 or _should_not_try_next_runner(completed.stderr):
                _store_probe_result(cache_key, result)
                return result
            last = result
        except subprocess.TimeoutExpired as error:
            elapsed = int((time.monotonic() - started) * 1000)
            stdout = (error.stdout or "") if isinstance(error.stdout, str) else ""
            stderr = (error.stderr or "") if isinstance(error.stderr, str) else ""
            return LeanRunResult(
                status="timeout",
                exit_code=None,
                stdout=stdout,
                stderr=stderr,
                diagnostics=parse_diagnostics(stdout, stderr),
                first_error="Lean probe timed out",
                elapsed_ms=elapsed,
                checked_file=checked_file,
                command=command,
                runner_mode=_runner_mode(command, lake_available),
            )
        except FileNotFoundError as error:
            elapsed = int((time.monotonic() - started) * 1000)
            result = LeanRunResult(
                status="runner_failed",
                exit_code=None,
                stdout="",
                stderr=str(error),
                diagnostics=[{"severity": "error", "message": str(error), "file": None, "line": None, "column": None}],
                first_error=str(error),
                elapsed_ms=elapsed,
                checked_file=checked_file,
                command=command,
                runner_mode=_runner_mode(command, lake_available),
            )
            last = result
    assert last is not None
    _store_probe_result(cache_key, last)
    return last


def _store_probe_result(cache_key: str, result: LeanRunResult) -> None:
    store_cached_probe(
        cache_key,
        result={
            "status": result.status,
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "diagnostics": result.diagnostics,
            "first_error": result.first_error,
            "elapsed_ms": result.elapsed_ms,
            "checked_file": str(result.checked_file),
            "command": result.command,
            "runner_mode": result.runner_mode,
        },
    )


def _result_from_cache(result: dict[str, Any], *, lookup_elapsed_ms: int) -> LeanRunResult:
    return LeanRunResult(
        status=str(result["status"]),
        exit_code=result.get("exit_code"),
        stdout=str(result.get("stdout") or ""),
        stderr=str(result.get("stderr") or ""),
        diagnostics=list(result.get("diagnostics") or []),
        first_error=result.get("first_error"),
        elapsed_ms=lookup_elapsed_ms,
        checked_file=Path(str(result.get("checked_file") or "")),
        command=list(result.get("command") or []),
        runner_mode=str(result.get("runner_mode") or "unknown"),
        cache_hit=True,
    )


def _runner_mode(command: list[str], lake_available: bool) -> str:
    if command[:2] == ["lake", "lean"]:
        return "lake_lean"
    if command[:3] == ["lake", "env", "lean"]:
        return "lake_env_lean"
    if command and command[0] == "lean":
        return "lean"
    return "unknown"


def _should_not_try_next_runner(stderr: str) -> bool:
    lower = stderr.lower()
    lake_config_missing = "no configuration file with a supported extension" in lower
    lake_unknown_lean = "unknown executable 'lean'" in lower
    return not (lake_config_missing or lake_unknown_lean)
