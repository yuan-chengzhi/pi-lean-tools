"""Lean output parsing helpers."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any


DIAG_RE = re.compile(
    r"(?P<file>.*?):(?P<line>\d+):(?P<column>\d+): "
    r"(?P<severity>error|warning|information)(?:\([^)]*\))?: "
    r"(?P<message>.*?)(?=\n.*?:\d+:\d+: (?:error|warning|information)(?:\([^)]*\))?: |\Z)",
    re.S,
)

UNKNOWN_CONSTANT_RE = re.compile(r"Unknown constant [`']([^`']+)[`']")
UNKNOWN_IDENTIFIER_RE = re.compile(r"unknown identifier [`']?([^`'\n]+)[`']?", re.I)


@dataclass(frozen=True)
class LeanDiagnostic:
    severity: str
    message: str
    file: str | None = None
    line: int | None = None
    column: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "message": self.message,
            "file": self.file,
            "line": self.line,
            "column": self.column,
        }


def parse_diagnostics(stdout: str, stderr: str) -> list[dict[str, Any]]:
    text = f"{stdout}\n{stderr}".strip()
    diagnostics: list[LeanDiagnostic] = []
    for match in DIAG_RE.finditer(text):
        diagnostics.append(
            LeanDiagnostic(
                severity=match.group("severity"),
                message=match.group("message").strip(),
                file=match.group("file"),
                line=int(match.group("line")),
                column=int(match.group("column")),
            )
        )
    if not diagnostics and text:
        lower = text.lower()
        severity = "error" if "error:" in lower or "error(" in lower else "information"
        diagnostics.append(LeanDiagnostic(severity=severity, message=text))
    return [item.as_dict() for item in diagnostics]


def first_error(diagnostics: list[dict[str, Any]]) -> str | None:
    for item in diagnostics:
        if item.get("severity") == "error":
            return str(item.get("message") or "")
    return None


def contains_sorry_warning(diagnostics: list[dict[str, Any]]) -> bool:
    for item in diagnostics:
        if item.get("severity") == "warning" and "declaration uses 'sorry'" in str(item.get("message")):
            return True
    return False


def extract_missing_names(message: str) -> list[str]:
    names: list[str] = []
    for regex in (UNKNOWN_CONSTANT_RE, UNKNOWN_IDENTIFIER_RE):
        for match in regex.finditer(message):
            name = match.group(1).strip()
            if name and name not in names:
                names.append(name)
    return names
