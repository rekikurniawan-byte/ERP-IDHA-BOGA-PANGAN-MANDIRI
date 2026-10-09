"""Audit direct db.session.commit/rollback usage in application code.

This is a read-only inventory. It does not decide the final refactor, but it
highlights where transaction boundaries are currently spread across routes and
services so hardening can be planned in small, testable batches.
"""

from __future__ import annotations

import argparse
import ast
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_APP_DIR = ROOT / "app"
DEFAULT_OUTPUT = ROOT / "RINCIAN_AUDIT_COMMIT_TRANSACTION_ERP_IDHA_BOGA.md"

INFRA_SERVICE_NAMES = {
    "audit_log_service.py",
    "atomic_transaction_service.py",
    "backup_service.py",
    "production_logging_service.py",
    "production_runtime_health_service.py",
    "system_health_service.py",
    "scheduler_service.py",
    "visual_sweep_service.py",
    "final_visual_browser_qa_service.py",
}
CRITICAL_DOMAIN_TERMS = (
    "accounting",
    "finance",
    "cash",
    "bank",
    "invoice",
    "payment",
    "receivable",
    "payable",
    "field_transaction",
    "canteen",
    "stock",
    "logistics",
    "delivery",
    "operational",
    "production",
    "hpp",
    "hr",
    "payroll",
    "asset",
    "closing",
)


@dataclass(frozen=True)
class DbSessionCall:
    path: Path
    line: int
    method: str
    layer: str
    model_or_class: str
    function: str
    is_route_function: bool
    inside_atomic_wrapper: bool

    @property
    def relative_path(self) -> str:
        return self.path.relative_to(ROOT).as_posix()

    @property
    def function_key(self) -> tuple[str, str, str]:
        return (self.relative_path, self.model_or_class, self.function)


@dataclass(frozen=True)
class FunctionCall:
    path: Path
    line: int
    layer: str
    model_or_class: str
    function: str
    called_name: str
    commit_arg: str

    @property
    def relative_path(self) -> str:
        return self.path.relative_to(ROOT).as_posix()


@dataclass(frozen=True)
class CommitFinding:
    call: DbSessionCall
    function_commit_count: int
    function_rollback_count: int
    priority: str
    reason: str


def _attribute_chain(node: ast.AST) -> list[str]:
    chain: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        chain.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        chain.append(current.id)
    return list(reversed(chain))


def _is_db_session_method(node: ast.AST, method: str) -> bool:
    if not isinstance(node, ast.Call):
        return False
    chain = _attribute_chain(node.func)
    return chain == ["db", "session", method]


def _is_route_decorator(node: ast.AST) -> bool:
    target = node.func if isinstance(node, ast.Call) else node
    chain = _attribute_chain(target)
    return bool(chain and chain[-1] == "route")


def _is_atomic_business_action_context(item: ast.withitem) -> bool:
    context = item.context_expr
    if isinstance(context, ast.Call):
        chain = _attribute_chain(context.func)
    else:
        chain = _attribute_chain(context)
    return bool(chain and chain[-1] == "atomic_business_action")


def _layer_for_path(path: Path) -> str:
    parts = set(path.parts)
    if "routes" in parts:
        return "route"
    if "services" in parts:
        return "service"
    return "other"


class DbSessionCallVisitor(ast.NodeVisitor):
    def __init__(self, path: Path) -> None:
        self.path = path
        self.layer = _layer_for_path(path)
        self.class_stack: list[str] = []
        self.function_stack: list[tuple[str, bool]] = []
        self.atomic_depth = 0
        self.calls: list[DbSessionCall] = []
        self.function_calls: list[FunctionCall] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.class_stack.append(node.name)
        self.generic_visit(node)
        self.class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.function_stack.append((node.name, any(_is_route_decorator(decorator) for decorator in node.decorator_list)))
        self.generic_visit(node)
        self.function_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.visit_FunctionDef(node)

    def visit_With(self, node: ast.With) -> None:
        enters_atomic = any(_is_atomic_business_action_context(item) for item in node.items)
        if enters_atomic:
            self.atomic_depth += 1
        self.generic_visit(node)
        if enters_atomic:
            self.atomic_depth -= 1

    def visit_Call(self, node: ast.Call) -> None:
        chain = _attribute_chain(node.func)
        if chain:
            function_name, _ = self.function_stack[-1] if self.function_stack else ("<module>", False)
            self.function_calls.append(
                FunctionCall(
                    path=self.path,
                    line=node.lineno,
                    layer=self.layer,
                    model_or_class=self.class_stack[-1] if self.class_stack else "",
                    function=function_name,
                    called_name=chain[-1],
                    commit_arg=_commit_keyword_arg(node),
                )
            )
        for method in ("commit", "rollback"):
            if _is_db_session_method(node, method):
                function_name, is_route = self.function_stack[-1] if self.function_stack else ("<module>", False)
                self.calls.append(
                    DbSessionCall(
                        path=self.path,
                        line=node.lineno,
                        method=method,
                        layer=self.layer,
                        model_or_class=self.class_stack[-1] if self.class_stack else "",
                        function=function_name,
                        is_route_function=is_route,
                        inside_atomic_wrapper=self.atomic_depth > 0,
                    )
                )
        self.generic_visit(node)


def collect_db_session_calls(app_dir: Path = DEFAULT_APP_DIR) -> list[DbSessionCall]:
    calls: list[DbSessionCall] = []
    app_dir = app_dir.resolve()
    for path in sorted(app_dir.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        visitor = DbSessionCallVisitor(path)
        visitor.visit(tree)
        calls.extend(visitor.calls)
    return calls


def collect_function_calls(app_dir: Path = DEFAULT_APP_DIR) -> list[FunctionCall]:
    function_calls: list[FunctionCall] = []
    app_dir = app_dir.resolve()
    for path in sorted(app_dir.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        visitor = DbSessionCallVisitor(path)
        visitor.visit(tree)
        function_calls.extend(visitor.function_calls)
    return function_calls


def _commit_keyword_arg(node: ast.Call) -> str:
    for keyword in node.keywords:
        if keyword.arg != "commit":
            continue
        if isinstance(keyword.value, ast.Constant):
            if keyword.value.value is True:
                return "true"
            if keyword.value.value is False:
                return "false"
        return "dynamic"
    return "omitted"


def _is_infra_call(call: DbSessionCall) -> bool:
    return call.path.name in INFRA_SERVICE_NAMES


def _is_critical_domain_call(call: DbSessionCall) -> bool:
    haystack = f"{call.relative_path} {call.function}".lower()
    return any(term in haystack for term in CRITICAL_DOMAIN_TERMS)


def _is_record_wrapper_call(call: FunctionCall) -> bool:
    return call.function.endswith("_record") and call.called_name == call.function.removesuffix("_record")


def _build_commit_findings(calls: list[DbSessionCall]) -> list[CommitFinding]:
    function_counts: dict[tuple[str, str, str], Counter] = defaultdict(Counter)
    for call in calls:
        function_counts[call.function_key][call.method] += 1

    findings: list[CommitFinding] = []
    for call in calls:
        if call.method != "commit":
            continue

        counts = function_counts[call.function_key]
        has_rollback = counts["rollback"] > 0
        multiple_commits = counts["commit"] > 1

        if call.layer == "route":
            priority = "P0"
            reason = "commit langsung di route; route sebaiknya hanya validasi dan memanggil service transaction boundary"
        elif _is_infra_call(call):
            priority = "P2"
            reason = "commit berada di service infrastruktur/audit; tetap perlu boundary jelas tetapi bukan alur bisnis utama"
        elif _is_critical_domain_call(call):
            priority = "P1"
            reason = "commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah"
        else:
            priority = "P2"
            reason = "commit berada di service non-kritis atau perlu review manual"

        if not has_rollback and priority != "P0":
            reason += "; tidak ada rollback eksplisit di fungsi yang sama"
        if multiple_commits:
            priority = "P0" if priority in {"P0", "P1"} else "P1"
            reason += "; fungsi memiliki lebih dari satu commit"
        if call.inside_atomic_wrapper:
            reason += "; commit berada di dalam block atomic_business_action"

        findings.append(
            CommitFinding(
                call=call,
                function_commit_count=counts["commit"],
                function_rollback_count=counts["rollback"],
                priority=priority,
                reason=reason,
            )
        )
    return findings


def _table(headers: list[str], rows: list[list[str]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def render_report(calls: list[DbSessionCall]) -> str:
    function_calls = collect_function_calls(DEFAULT_APP_DIR)
    findings = _build_commit_findings(calls)
    commit_calls = [call for call in calls if call.method == "commit"]
    rollback_calls = [call for call in calls if call.method == "rollback"]
    route_rollbacks = [call for call in rollback_calls if call.layer == "route"]
    by_layer = Counter(call.layer for call in commit_calls)
    by_file = Counter(call.relative_path for call in commit_calls)
    by_priority = Counter(finding.priority for finding in findings)
    functions_with_commit = {call.function_key for call in commit_calls}
    functions_with_commit_no_rollback = {
        finding.call.function_key
        for finding in findings
        if finding.function_rollback_count == 0
    }
    function_commit_counts = Counter(call.function_key for call in commit_calls)
    multi_commit_functions = [
        (key, count)
        for key, count in sorted(function_commit_counts.items())
        if count > 1
    ]
    service_commit_function_names = {
        call.function
        for call in commit_calls
        if call.layer == "service"
    }
    ignored_boundary_call_names = {"record_audit_log", "record_critical_audit_log"}
    nested_service_boundary_calls = [
        call
        for call in function_calls
        if call.layer == "service"
        and call.called_name in service_commit_function_names
        and call.called_name != call.function
        and call.called_name not in ignored_boundary_call_names
        and not call.called_name.startswith("_")
        and call.commit_arg != "false"
        and not _is_record_wrapper_call(call)
    ]
    commit_true_calls = [
        call
        for call in function_calls
        if call.commit_arg == "true"
        and call.called_name not in ignored_boundary_call_names
    ]

    summary_rows = [
        ["Total db.session.commit()", str(len(commit_calls))],
        ["Total db.session.rollback()", str(len(rollback_calls))],
        ["Fungsi dengan commit", str(len(functions_with_commit))],
        ["Fungsi commit tanpa rollback di fungsi yang sama", str(len(functions_with_commit_no_rollback))],
        ["Commit di route", str(by_layer["route"])],
        ["Rollback di route", str(len(route_rollbacks))],
        ["Commit di service", str(by_layer["service"])],
        ["Fungsi dengan lebih dari satu commit", str(len(multi_commit_functions))],
        ["Service call ke fungsi ber-commit", str(len(nested_service_boundary_calls))],
        ["Call eksplisit commit=True", str(len(commit_true_calls))],
        ["P0", str(by_priority["P0"])],
        ["P1", str(by_priority["P1"])],
        ["P2", str(by_priority["P2"])],
    ]

    file_rows = [[path, str(count)] for path, count in by_file.most_common()]
    p0_rows = [
        [
            finding.priority,
            f"{finding.call.relative_path}:{finding.call.line}",
            finding.call.function,
            str(finding.function_commit_count),
            str(finding.function_rollback_count),
            finding.reason,
        ]
        for finding in findings
        if finding.priority == "P0"
    ]
    all_rows = [
        [
            finding.priority,
            f"{finding.call.relative_path}:{finding.call.line}",
            finding.call.layer,
            finding.call.model_or_class or "-",
            finding.call.function,
            str(finding.function_commit_count),
            str(finding.function_rollback_count),
            "ya" if finding.call.inside_atomic_wrapper else "tidak",
            finding.reason,
        ]
        for finding in findings
    ]
    route_rollback_rows = [
        [f"{call.relative_path}:{call.line}", call.function, "ya" if call.inside_atomic_wrapper else "tidak"]
        for call in route_rollbacks
    ]
    multi_commit_rows = [
        [path, model_or_class or "-", function, str(count)]
        for (path, model_or_class, function), count in multi_commit_functions
    ]
    nested_service_rows = [
        [f"{call.relative_path}:{call.line}", call.function, call.called_name, call.commit_arg]
        for call in nested_service_boundary_calls
    ]
    commit_true_rows = [
        [f"{call.relative_path}:{call.line}", call.layer, call.function, call.called_name]
        for call in commit_true_calls
    ]

    return "\n\n".join(
        [
            "# Audit db.session.commit ERP Idha Boga",
            (
                "Laporan ini dibuat dari parsing AST `app/**/*.py`. Tidak ada perubahan perilaku aplikasi. "
                "Parser hanya menghitung call nyata, sehingga string/komentar yang memuat teks `db.session.commit()` tidak dihitung."
            ),
            "## Ringkasan",
            _table(["Metrik", "Nilai"], summary_rows),
            "## Sebaran Commit Per File",
            _table(["File", "Jumlah commit"], file_rows),
            "## Kandidat P0",
            (
                "P0 berarti commit langsung di route atau fungsi dengan lebih dari satu commit pada area berisiko. "
                "Target refactor: route memanggil service use-case, lalu satu boundary commit/rollback membungkus semua efek bisnis."
            ),
            _table(["Priority", "Lokasi", "Fungsi", "Commit/Fungsi", "Rollback/Fungsi", "Alasan"], p0_rows),
            "## Rollback Langsung Di Route",
            _table(["Lokasi", "Fungsi", "Dalam Atomic"], route_rollback_rows),
            "## Fungsi Dengan Lebih Dari Satu Commit",
            _table(["File", "Class", "Fungsi", "Jumlah Commit"], multi_commit_rows),
            "## Service Yang Memanggil Fungsi Ber-Commit",
            (
                "Daftar ini berbasis pencocokan nama fungsi AST, jadi wajib ditinjau manual. "
                "Audit log, helper privat, dan call `commit=False` dikeluarkan agar daftar lebih fokus pada potensi "
                "service helper yang diam-diam membuka transaction boundary sendiri."
            ),
            _table(["Lokasi", "Fungsi Pemanggil", "Fungsi Dipanggil", "Arg Commit"], nested_service_rows[:200]),
            "## Call Eksplisit commit=True",
            _table(["Lokasi", "Layer", "Fungsi Pemanggil", "Fungsi Dipanggil"], commit_true_rows[:200]),
            "## Rekomendasi Hardening",
            "- Jangan refactor semua commit sekaligus; mulai dari route P0 yang menyentuh invoice, payment, cash/bank, stock, posting jurnal, payroll, dan backup.",
            "- Jadikan helper bawah bebas commit. Helper sebaiknya hanya `add`, validasi, atau return object; commit dilakukan service use-case.",
            "- Untuk use case kritis, pakai satu boundary: `try -> semua mutasi -> commit`, `except -> rollback -> raise/return error` atau `atomic_business_action`.",
            "- Tambahkan regression test untuk partial failure: invoice dibuat tetapi jurnal gagal, payment masuk tetapi piutang gagal, stok bergerak tetapi HPP gagal.",
            "- Commit audit log boleh menjadi boundary tersendiri jika memang didesain begitu, tetapi jangan menutupi kegagalan transaksi bisnis utama.",
            "## Semua Commit",
            _table(
                [
                    "Priority",
                    "Lokasi",
                    "Layer",
                    "Class",
                    "Fungsi",
                    "Commit/Fungsi",
                    "Rollback/Fungsi",
                    "Dalam Atomic",
                    "Alasan",
                ],
                all_rows,
            ),
            "",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-dir", type=Path, default=DEFAULT_APP_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    calls = collect_db_session_calls(args.app_dir)
    report = render_report(calls)
    args.output.write_text(report, encoding="utf-8")
    print(f"DB commit audit written: {args.output}")
    print(f"Total db.session.commit(): {sum(1 for call in calls if call.method == 'commit')}")
    print(f"Total db.session.rollback(): {sum(1 for call in calls if call.method == 'rollback')}")


if __name__ == "__main__":
    main()
