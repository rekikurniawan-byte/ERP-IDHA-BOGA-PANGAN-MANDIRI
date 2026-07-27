"""Audit SQLAlchemy Float columns in app models.

The report is intentionally read-only. It classifies current Float columns so a
future migration can be planned without guessing which fields are money,
quantities, percentages, or ratios.
"""

from __future__ import annotations

import argparse
import ast
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODELS_DIR = ROOT / "app" / "models"
DEFAULT_OUTPUT = ROOT / "RINCIAN_AUDIT_FLOAT_NUMERIC_ERP_IDHA_BOGA.md"

RATIO_TERMS = (
    "percent",
    "percentage",
    "ratio",
    "factor",
    "multiplier",
    "yield",
    "waste",
)
QUANTITY_TERMS = ("qty", "quantity", "stock", "portion")
MONEY_TERMS = (
    "amount",
    "price",
    "subtotal",
    "paid",
    "remaining",
    "balance",
    "cash",
    "salary",
    "bonus",
    "deduction",
    "debit",
    "credit",
    "value",
    "cost",
    "hpp",
    "revenue",
    "depreciation",
    "principal",
    "interest",
    "admin",
    "expense",
    "income",
    "payment",
    "receivable",
    "debt",
)


@dataclass(frozen=True)
class FloatField:
    path: Path
    line: int
    model: str
    field: str
    category: str
    recommended_type: str
    priority: str

    @property
    def relative_path(self) -> str:
        try:
            return self.path.relative_to(ROOT).as_posix()
        except ValueError:
            return self.path.as_posix()


def migration_stage(field: FloatField) -> str:
    if field.category == "money":
        if field.relative_path in {"app/models/accounting.py", "app/models/finance.py"}:
            return "P0A - uang finance/accounting"
        return "P0B - uang operasional/domain lain"
    if field.category == "quantity":
        return "P1A - kuantitas/stok/porsi"
    if field.category == "ratio":
        return "P1B - rasio/persen"
    return "P2 - review manual"


def _is_db_column_float(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False

    func = node.func
    if not (isinstance(func, ast.Attribute) and func.attr == "Column"):
        return False

    for arg in node.args:
        if isinstance(arg, ast.Attribute) and arg.attr == "Float":
            return True
        if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Attribute) and arg.func.attr == "Float":
            return True
        if isinstance(arg, ast.Name) and arg.id == "Float":
            return True
        if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name) and arg.func.id == "Float":
            return True
    return False


def classify_field(field: str) -> tuple[str, str, str]:
    name = field.lower()

    if any(term in name for term in RATIO_TERMS):
        return "ratio", "db.Numeric(8, 4)", "P1"

    has_quantity_term = any(term in name for term in QUANTITY_TERMS)
    has_money_term = any(term in name for term in MONEY_TERMS)

    if has_quantity_term and not has_money_term:
        return "quantity", "db.Numeric(18, 4)", "P1"

    if has_money_term:
        return "money", "db.Numeric(18, 2)", "P0"

    if name.startswith("total_") and has_quantity_term:
        return "quantity", "db.Numeric(18, 4)", "P1"

    return "review", "manual review", "P2"


class FloatFieldVisitor(ast.NodeVisitor):
    def __init__(self, path: Path) -> None:
        self.path = path
        self.class_stack: list[str] = []
        self.fields: list[FloatField] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.class_stack.append(node.name)
        self.generic_visit(node)
        self.class_stack.pop()

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            if isinstance(target, ast.Name) and _is_db_column_float(node.value):
                self._append_field(node.lineno, target.id)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if isinstance(node.target, ast.Name) and node.value and _is_db_column_float(node.value):
            self._append_field(node.lineno, node.target.id)
        self.generic_visit(node)

    def _append_field(self, line: int, field_name: str) -> None:
        category, recommended_type, priority = classify_field(field_name)
        self.fields.append(
            FloatField(
                path=self.path,
                line=line,
                model=self.class_stack[-1] if self.class_stack else "",
                field=field_name,
                category=category,
                recommended_type=recommended_type,
                priority=priority,
            )
        )


def collect_float_fields(models_dir: Path) -> list[FloatField]:
    fields: list[FloatField] = []
    for path in sorted(models_dir.glob("*.py")):
        if path.name == "__init__.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        visitor = FloatFieldVisitor(path)
        visitor.visit(tree)
        fields.extend(visitor.fields)
    return fields


def _table(headers: list[str], rows: list[list[str]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def render_report(fields: list[FloatField]) -> str:
    by_category = Counter(field.category for field in fields)
    by_file = Counter(field.relative_path for field in fields)
    by_priority = Counter(field.priority for field in fields)
    by_stage = Counter(migration_stage(field) for field in fields)

    high_risk_fields = [
        field
        for field in fields
        if field.priority == "P0"
        and field.relative_path
        in {
            "app/models/accounting.py",
            "app/models/finance.py",
            "app/models/field_transaction.py",
            "app/models/canteen.py",
            "app/models/hr.py",
        }
    ]

    summary_rows = [
        ["Total Float di model", str(len(fields))],
        ["Money / rupiah", str(by_category["money"])],
        ["Quantity / stok / porsi", str(by_category["quantity"])],
        ["Ratio / persen", str(by_category["ratio"])],
        ["Perlu review manual", str(by_category["review"])],
        ["P0 kandidat migrasi uang", str(by_priority["P0"])],
        ["P1 kandidat migrasi qty/ratio", str(by_priority["P1"])],
    ]

    file_rows = [[path, str(count)] for path, count in by_file.most_common()]
    stage_rows = [
        [
            stage,
            str(by_stage[stage]),
            {
                "P0A - uang finance/accounting": "Ubah ke db.Numeric(18, 2), lalu rekonsiliasi jurnal, invoice, payment, AP/AR, cash/bank.",
                "P0B - uang operasional/domain lain": "Ubah ke db.Numeric(18, 2) setelah P0A stabil; cek biaya, HPP, aset, payroll, warung.",
                "P1A - kuantitas/stok/porsi": "Ubah ke db.Numeric(18, 4); cek stok, resep, porsi, procurement, konversi unit.",
                "P1B - rasio/persen": "Ubah ke db.Numeric(8, 4); tetapkan skala persen 0-100 atau 0-1 sebelum migrasi.",
                "P2 - review manual": "Klasifikasikan manual sebelum dibuat migration.",
            }[stage],
        ]
        for stage in [
            "P0A - uang finance/accounting",
            "P0B - uang operasional/domain lain",
            "P1A - kuantitas/stok/porsi",
            "P1B - rasio/persen",
            "P2 - review manual",
        ]
    ]
    high_risk_rows = [
        [
            field.priority,
            f"{field.relative_path}:{field.line}",
            field.model,
            field.field,
            field.category,
            field.recommended_type,
            migration_stage(field),
        ]
        for field in high_risk_fields
    ]
    all_rows = [
        [
            field.priority,
            f"{field.relative_path}:{field.line}",
            field.model,
            field.field,
            field.category,
            field.recommended_type,
            migration_stage(field),
        ]
        for field in fields
    ]

    return "\n\n".join(
        [
            "# Audit Float ke Numeric ERP Idha Boga",
            "Laporan ini dibuat dari parsing AST `app/models/*.py`. Tidak ada perubahan schema atau migration.",
            "## Ringkasan",
            _table(["Metrik", "Nilai"], summary_rows),
            "## Sebaran Per File",
            _table(["File", "Jumlah Float"], file_rows),
            "## Gelombang Migrasi Bertahap",
            _table(["Gelombang", "Jumlah Field", "Catatan"], stage_rows),
            "## Kandidat P0",
            (
                "Prioritas pertama adalah field uang pada modul accounting, finance, field transaction, canteen, dan HR. "
                "Field ini paling dekat dengan invoice, payment, jurnal, kas, hutang/piutang, salary, dan closing."
            ),
            _table(["Priority", "Lokasi", "Model", "Field", "Kategori", "Rekomendasi", "Gelombang"], high_risk_rows),
            "## Rekomendasi Migrasi",
            "- Jangan edit migration lama yang sudah pernah dipakai. Buat migration koreksi baru.",
            "- Buat migration per gelombang, bukan satu migration raksasa. Setiap gelombang wajib punya snapshot nilai sebelum/sesudah dan laporan selisih.",
            "- Konversi P0 lebih dulu ke `db.Numeric(18, 2)`, lalu rekonsiliasi invoice, payment, jurnal, kas, payable, receivable, dan payroll.",
            "- Konversi quantity ke `db.Numeric(18, 4)` setelah alur uang stabil, terutama stok, porsi, recipe, dan procurement.",
            "- Konversi ratio/persentase ke `db.Numeric(8, 4)` dengan normalisasi jelas: simpan 30.0000 untuk 30 persen bila sistem saat ini memakai skala 0-100.",
            "- Ubah kalkulasi service kritis agar memakai `Decimal`, bukan `float`, sebelum/bersamaan dengan migration.",
            "- Tambahkan regression test untuk pembulatan, partial payment, outstanding nol, debit-kredit balance, dan stock balance.",
            "## Semua Field Float",
            _table(["Priority", "Lokasi", "Model", "Field", "Kategori", "Rekomendasi", "Gelombang"], all_rows),
            "",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models-dir", type=Path, default=DEFAULT_MODELS_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    fields = collect_float_fields(args.models_dir)
    report = render_report(fields)
    args.output.write_text(report, encoding="utf-8")
    print(f"Float field audit written: {args.output}")
    print(f"Total Float fields: {len(fields)}")


if __name__ == "__main__":
    main()
