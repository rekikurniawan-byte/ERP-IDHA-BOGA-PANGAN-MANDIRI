"""Audit generic ``except Exception`` usage.

The audit is read-only. It inventories broad exception handlers so critical ERP
flows can be narrowed to specific exceptions or, at minimum, logged explicitly.
"""

from __future__ import annotations

import argparse
import ast
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCAN_ROOT = ROOT / "app"
DEFAULT_OUTPUT = ROOT / "RINCIAN_AUDIT_GENERIC_EXCEPTIONS_ERP_IDHA_BOGA.md"


@dataclass(frozen=True)
class GenericExceptionFinding:
    path: Path
    line: int
    scope: str
    logged: bool
    reraised: bool
    priority: str

    @property
    def relative_path(self) -> str:
        try:
            return self.path.relative_to(ROOT).as_posix()
        except ValueError:
            return self.path.as_posix()


def _is_exception_type(node: ast.AST | None) -> bool:
    if node is None:
        return False
    if isinstance(node, ast.Name):
        return node.id == "Exception"
    if isinstance(node, ast.Attribute):
        return node.attr == "Exception"
    if isinstance(node, ast.Tuple):
        return any(_is_exception_type(item) for item in node.elts)
    return False


def _scope(path: Path) -> str:
    rel = path.as_posix().lower()
    if rel.endswith("app/__init__.py"):
        return "app_factory/context/error_handler"
    if "/routes/" in rel:
        return "route"
    if "/services/" in rel:
        if "dashboard" in rel or "notification" in rel or "reminder" in rel:
            return "dashboard/background-read"
        if "backup" in rel or "recovery" in rel:
            return "backup/recovery"
        return "service"
    return "other"


def _body_has_logger_call(body: list[ast.stmt]) -> bool:
    for node in ast.walk(ast.Module(body=body, type_ignores=[])):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in {"exception", "error", "warning", "critical"}:
            return True
    return False


def _body_reraises(body: list[ast.stmt]) -> bool:
    return any(isinstance(node, ast.Raise) for statement in body for node in ast.walk(statement))


def _priority(scope: str, logged: bool, reraised: bool) -> str:
    if reraised:
        return "P2"
    if scope in {"route", "app_factory/context/error_handler"} and not logged:
        return "P1"
    if scope in {"service", "backup/recovery"} and not logged:
        return "P1"
    return "P2"


class GenericExceptionVisitor(ast.NodeVisitor):
    def __init__(self, path: Path) -> None:
        self.path = path
        self.findings: list[GenericExceptionFinding] = []

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if _is_exception_type(node.type):
            scope = _scope(self.path)
            logged = _body_has_logger_call(node.body)
            reraised = _body_reraises(node.body)
            self.findings.append(
                GenericExceptionFinding(
                    path=self.path,
                    line=node.lineno,
                    scope=scope,
                    logged=logged,
                    reraised=reraised,
                    priority=_priority(scope, logged, reraised),
                )
            )
        self.generic_visit(node)


def collect_generic_exception_findings(scan_root: Path = DEFAULT_SCAN_ROOT) -> list[GenericExceptionFinding]:
    findings: list[GenericExceptionFinding] = []
    for path in sorted(scan_root.rglob("*.py")):
        if any(part in {"__pycache__", ".pytest_cache"} for part in path.parts):
            continue
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        visitor = GenericExceptionVisitor(path)
        visitor.visit(tree)
        findings.extend(visitor.findings)
    return findings


def _table(headers: list[str], rows: list[list[str]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def render_report(findings: list[GenericExceptionFinding]) -> str:
    by_priority = Counter(finding.priority for finding in findings)
    by_scope = Counter(finding.scope for finding in findings)
    unlogged = [finding for finding in findings if not finding.logged and not finding.reraised]

    summary_rows = [
        ["Total except Exception", str(len(findings))],
        ["P1 perlu logging/exception spesifik", str(by_priority["P1"])],
        ["P2 review bertahap", str(by_priority["P2"])],
        ["Handler tanpa logger dan tanpa raise", str(len(unlogged))],
    ]
    scope_rows = [[scope, str(count)] for scope, count in by_scope.most_common()]
    detail_rows = [
        [
            finding.priority,
            finding.relative_path,
            str(finding.line),
            finding.scope,
            "ya" if finding.logged else "tidak",
            "ya" if finding.reraised else "tidak",
        ]
        for finding in findings
    ]

    return "\n\n".join([
        "# Audit Generic Exception ERP Idha Boga",
        "Laporan ini read-only. Fokus P1 adalah handler yang menangkap semua Exception tanpa logger dan tanpa raise pada route, service transaksi, dashboard, backup, dan context processor.",
        "## Ringkasan",
        _table(["Metrik", "Nilai"], summary_rows),
        "## Per Scope",
        _table(["Scope", "Jumlah"], scope_rows),
        "## Detail",
        _table(["Prioritas", "File", "Line", "Scope", "Logged", "Reraised"], detail_rows),
        "## Rekomendasi",
        "- Ganti generic exception dengan exception spesifik untuk validasi, database operational error, integrity error, dan file I/O.",
        "- Jika fallback tetap diperlukan, gunakan logger.exception agar kegagalan tidak terlihat sebagai kondisi normal.",
        "- Hindari mengubah kegagalan query ERP menjadi label aman seperti badge hijau tanpa sinyal error internal.",
        "",
    ])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scan-root", type=Path, default=DEFAULT_SCAN_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    findings = collect_generic_exception_findings(args.scan_root)
    args.output.write_text(render_report(findings), encoding="utf-8")
    print(f"Generic exception audit written: {args.output}")
    print(f"Total findings: {len(findings)}")


if __name__ == "__main__":
    main()
