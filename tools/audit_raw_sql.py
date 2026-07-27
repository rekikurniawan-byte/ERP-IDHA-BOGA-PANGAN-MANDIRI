"""Audit dynamic raw SQL usage.

The audit is read-only. It flags raw SQL calls where identifiers or clauses are
assembled with Python string interpolation, because SQL parameters cannot safely
bind table names, column names, or ORDER BY fragments.
"""

from __future__ import annotations

import argparse
import ast
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCAN_ROOT = ROOT / "app"
DEFAULT_OUTPUT = ROOT / "RINCIAN_AUDIT_RAW_SQL_ERP_IDHA_BOGA.md"


@dataclass(frozen=True)
class RawSqlFinding:
    path: Path
    line: int
    kind: str
    expression: str
    priority: str

    @property
    def relative_path(self) -> str:
        try:
            return self.path.relative_to(ROOT).as_posix()
        except ValueError:
            return self.path.as_posix()


def _func_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _is_dynamic_sql_arg(node: ast.AST) -> bool:
    if isinstance(node, ast.JoinedStr):
        return True
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
        return True
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "format":
        return True
    return False


def _kind_for_arg(node: ast.AST) -> str:
    if isinstance(node, ast.JoinedStr):
        return "f-string SQL"
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
        return "percent-format SQL"
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "format":
        return "format SQL"
    return "dynamic SQL"


def _priority(path: Path, expression: str) -> str:
    text = expression.lower()
    if "{table" in text or "{where" in text or "order by {" in text or "from {" in text or "join {" in text:
        return "P1"
    if "select" in text or "update" in text or "delete" in text or "insert" in text:
        return "P2"
    return "review"


class RawSqlVisitor(ast.NodeVisitor):
    def __init__(self, path: Path, source: str) -> None:
        self.path = path
        self.source = source
        self.findings: list[RawSqlFinding] = []

    def visit_Call(self, node: ast.Call) -> None:
        name = _func_name(node.func)
        if name in {"text", "execute"} and node.args:
            first_arg = node.args[0]
            if _is_dynamic_sql_arg(first_arg):
                expression = ast.get_source_segment(self.source, first_arg) or ast.dump(first_arg)
                self.findings.append(
                    RawSqlFinding(
                        path=self.path,
                        line=node.lineno,
                        kind=f"{name} {_kind_for_arg(first_arg)}",
                        expression=" ".join(expression.split()),
                        priority=_priority(self.path, expression),
                    )
                )
        self.generic_visit(node)


def collect_raw_sql_findings(scan_root: Path = DEFAULT_SCAN_ROOT) -> list[RawSqlFinding]:
    findings: list[RawSqlFinding] = []
    for path in sorted(scan_root.rglob("*.py")):
        if any(part in {"__pycache__", ".pytest_cache"} for part in path.parts):
            continue
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        visitor = RawSqlVisitor(path, source)
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


def render_report(findings: list[RawSqlFinding]) -> str:
    by_priority = Counter(finding.priority for finding in findings)
    by_file = Counter(finding.relative_path for finding in findings)

    summary_rows = [
        ["Total temuan raw SQL dinamis", str(len(findings))],
        ["P1 perlu whitelist identifier", str(by_priority["P1"])],
        ["P2 perlu review", str(by_priority["P2"])],
        ["Review manual", str(by_priority["review"])],
    ]
    file_rows = [[path, str(count)] for path, count in by_file.most_common()]
    detail_rows = [
        [
            finding.priority,
            finding.relative_path,
            str(finding.line),
            finding.kind,
            finding.expression.replace("|", "\\|")[:180],
        ]
        for finding in findings
    ]

    return "\n\n".join([
        "# Audit Raw SQL Dinamis ERP Idha Boga",
        "Laporan ini read-only. Temuan P1 harus memakai whitelist eksplisit untuk identifier SQL seperti nama tabel, kolom, dan clause.",
        "## Ringkasan",
        _table(["Metrik", "Nilai"], summary_rows),
        "## Per File",
        _table(["File", "Temuan"], file_rows),
        "## Detail",
        _table(["Prioritas", "File", "Line", "Jenis", "Ekspresi"], detail_rows),
        "## Rekomendasi",
        "- Gunakan parameter SQL hanya untuk value, bukan identifier.",
        "- Untuk nama tabel, kolom, arah sort, dan where fragment, pakai whitelist hardcoded.",
        "- Jika SQL dinamis berasal dari input user, ubah menjadi mapping opsi yang dikontrol aplikasi.",
        "",
    ])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scan-root", type=Path, default=DEFAULT_SCAN_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    findings = collect_raw_sql_findings(args.scan_root)
    args.output.write_text(render_report(findings), encoding="utf-8")
    print(f"Raw SQL audit written: {args.output}")
    print(f"Total findings: {len(findings)}")


if __name__ == "__main__":
    main()
