"""Lean project discovery helpers."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess


PROJECT_MARKERS = ("lakefile.lean", "lakefile.toml", "lean-toolchain")
LAKE_MARKERS = ("lakefile.lean", "lakefile.toml")
DEFAULT_PROJECT_ROOT_ENV = "PI_LEAN_TOOLS_PROJECT_ROOT"


def resolve_project_root(path: str | Path | None) -> Path:
    start = Path(path or os.environ.get(DEFAULT_PROJECT_ROOT_ENV) or ".").expanduser().resolve()
    if start.is_file():
        start = start.parent
    current = start
    while True:
        if any((current / marker).exists() for marker in PROJECT_MARKERS):
            return current
        if current.parent == current:
            return start
        current = current.parent


def read_lean_toolchain(project_root: Path) -> str | None:
    path = project_root / "lean-toolchain"
    if path.is_file():
        return path.read_text(encoding="utf-8").strip() or None
    return None


def has_lake_config(project_root: Path) -> bool:
    return any((project_root / marker).is_file() for marker in LAKE_MARKERS)


def mathlib_revision(project_root: Path) -> str | None:
    mathlib = project_root / ".lake" / "packages" / "mathlib"
    if not mathlib.exists():
        return None
    try:
        result = subprocess.run(
            ["git", "-C", str(mathlib), "rev-parse", "HEAD"],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
    except Exception:
        return None
    if result.returncode == 0:
        return result.stdout.strip() or None
    return None


def project_lean_roots(project_root: Path, include_mathlib: bool = True) -> list[Path]:
    roots: list[Path] = []
    for child in sorted(project_root.iterdir() if project_root.exists() else []):
        if child.name.startswith("."):
            continue
        if child.is_dir() and any(grand.suffix == ".lean" for grand in child.rglob("*.lean")):
            roots.append(child)
        elif child.is_file() and child.suffix == ".lean":
            roots.append(child)
    if include_mathlib:
        mathlib_root = project_root / ".lake" / "packages" / "mathlib" / "Mathlib"
        if mathlib_root.exists():
            roots.append(mathlib_root)
    return roots
