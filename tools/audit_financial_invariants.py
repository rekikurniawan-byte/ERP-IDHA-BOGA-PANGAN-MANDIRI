"""Read-only financial invariant audit for ERP Idha Boga.

This tool does not mutate data. It checks accounting and operational invariants
that should hold before the ERP is treated as a finance source of truth.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DEFAULT_OUTPUT = ROOT / "RINCIAN_AUDIT_REKONSILIASI_ERP_IDHA_BOGA.md"
TOLERANCE = Decimal("0.01")
INACTIVE_STATUSES = {"VOID", "VOIDED", "CANCELLED", "CANCELED", "REJECTED"}


@dataclass(frozen=True)
class InvariantViolation:
    area: str
    key: str
    severity: str
    message: str
    expected: str = ""
    actual: str = ""


@dataclass(frozen=True)
class AuditResult:
    name: str
    checked_count: int
    violations: tuple[InvariantViolation, ...]
    notes: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return not self.violations


def to_decimal(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    text = str(value).strip()
    if not text:
        return Decimal("0")
    try:
        return Decimal(text)
    except InvalidOperation:
        return Decimal(str(float(value or 0)))


def money(value: Any) -> str:
    return str(to_decimal(value).quantize(TOLERANCE))


def almost_equal(left: Any, right: Any, tolerance: Decimal = TOLERANCE) -> bool:
    return abs(to_decimal(left) - to_decimal(right)) <= tolerance


def _value(obj: Any, attr: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(attr, default)
    return getattr(obj, attr, default)


def _is_active_status(status: Any) -> bool:
    return str(status or "").strip().upper() not in INACTIVE_STATUSES


def audit_journal_balances(journals: Iterable[Any]) -> AuditResult:
    violations: list[InvariantViolation] = []
    checked = 0

    for journal in journals:
        checked += 1
        details = list(_value(journal, "details", []) or [])
        journal_id = _value(journal, "id", "-")
        journal_number = _value(journal, "journal_number", f"Journal {journal_id}")

        if not details:
            violations.append(InvariantViolation(
                area="accounting",
                key=str(journal_number),
                severity="HIGH",
                message="Jurnal tidak memiliki detail debit/kredit.",
            ))
            continue

        debit = sum(to_decimal(_value(detail, "debit", 0)) for detail in details)
        credit = sum(to_decimal(_value(detail, "credit", 0)) for detail in details)
        if not almost_equal(debit, credit):
            violations.append(InvariantViolation(
                area="accounting",
                key=str(journal_number),
                severity="CRITICAL",
                message="Total debit dan kredit jurnal tidak seimbang.",
                expected=money(debit),
                actual=money(credit),
            ))

    return AuditResult("Debit = Kredit", checked, tuple(violations))


def audit_invoice_payment_integrity(invoices: Iterable[Any], payments: Iterable[Any]) -> AuditResult:
    payments_by_invoice: dict[Any, list[Any]] = defaultdict(list)
    for payment in payments:
        payments_by_invoice[_value(payment, "invoice_id")].append(payment)

    violations: list[InvariantViolation] = []
    checked = 0

    for invoice in invoices:
        if not _is_active_status(_value(invoice, "status")):
            continue
        checked += 1
        invoice_id = _value(invoice, "id")
        invoice_number = _value(invoice, "invoice_number", f"Invoice {invoice_id}")
        total = to_decimal(_value(invoice, "total_amount", 0))
        paid = to_decimal(_value(invoice, "paid_amount", 0))
        remaining = to_decimal(_value(invoice, "remaining_amount", 0))
        payment_sum = sum(to_decimal(_value(payment, "amount", 0)) for payment in payments_by_invoice.get(invoice_id, []))

        if paid < 0 or remaining < 0 or total < 0:
            violations.append(InvariantViolation("receivables", str(invoice_number), "HIGH", "Invoice memiliki nilai negatif."))
        if paid - total > TOLERANCE:
            violations.append(InvariantViolation(
                "receivables",
                str(invoice_number),
                "CRITICAL",
                "Paid amount melebihi total invoice.",
                expected=money(total),
                actual=money(paid),
            ))
        if not almost_equal(total - paid, remaining):
            violations.append(InvariantViolation(
                "receivables",
                str(invoice_number),
                "CRITICAL",
                "Outstanding invoice tidak sama dengan total - paid.",
                expected=money(total - paid),
                actual=money(remaining),
            ))
        if not almost_equal(payment_sum, paid):
            violations.append(InvariantViolation(
                "receivables",
                str(invoice_number),
                "HIGH",
                "Total payment rows tidak sama dengan paid_amount invoice.",
                expected=money(paid),
                actual=money(payment_sum),
            ))

    return AuditResult("Invoice Payment Outstanding", checked, tuple(violations))


def audit_supplier_bill_payment_integrity(bills: Iterable[Any], payments: Iterable[Any]) -> AuditResult:
    payments_by_bill: dict[Any, list[Any]] = defaultdict(list)
    for payment in payments:
        payments_by_bill[_value(payment, "supplier_bill_id")].append(payment)

    violations: list[InvariantViolation] = []
    checked = 0

    for bill in bills:
        if not _is_active_status(_value(bill, "status")):
            continue
        checked += 1
        bill_id = _value(bill, "id")
        bill_number = _value(bill, "bill_number", f"SupplierBill {bill_id}")
        total = to_decimal(_value(bill, "total_amount", 0))
        paid = to_decimal(_value(bill, "paid_amount", 0))
        remaining = to_decimal(_value(bill, "remaining_amount", 0))
        payment_sum = sum(to_decimal(_value(payment, "amount", 0)) for payment in payments_by_bill.get(bill_id, []))

        if paid - total > TOLERANCE:
            violations.append(InvariantViolation("payables", str(bill_number), "CRITICAL", "Paid amount melebihi total hutang supplier.", money(total), money(paid)))
        if not almost_equal(total - paid, remaining):
            violations.append(InvariantViolation("payables", str(bill_number), "CRITICAL", "Outstanding hutang tidak sama dengan total - paid.", money(total - paid), money(remaining)))
        if not almost_equal(payment_sum, paid):
            violations.append(InvariantViolation("payables", str(bill_number), "HIGH", "Total supplier payment rows tidak sama dengan paid_amount bill.", money(paid), money(payment_sum)))

    return AuditResult("Supplier Bill Payment Outstanding", checked, tuple(violations))


def audit_stock_movements(
    movements: Iterable[Any],
    expected_balances: Mapping[tuple[Any, Any], Any] | None = None,
    opening_balances: Iterable[Any] | None = None,
) -> AuditResult:
    balances: dict[tuple[Any, Any], Decimal] = defaultdict(Decimal)
    opening_dates: dict[tuple[Any, Any], Any] = {}
    violations: list[InvariantViolation] = []
    checked = 0

    for opening in opening_balances or []:
        branch_id = _value(opening, "branch_id")
        item_id = _value(opening, "item_id")
        key = (branch_id, item_id)
        qty = to_decimal(_value(opening, "qty", 0))
        balances[key] += qty
        opening_dates[key] = _value(opening, "opening_date")
        if qty < 0:
            violations.append(InvariantViolation("stock", f"{branch_id}/{item_id}", "HIGH", "Saldo awal stok negatif.", actual=str(qty)))

    for movement in movements:
        checked += 1
        branch_id = _value(movement, "branch_id")
        item_id = _value(movement, "item_id")
        movement_type = str(_value(movement, "movement_type", "") or "").upper()
        qty = to_decimal(_value(movement, "qty", 0))
        key = (branch_id, item_id)
        opening_date = opening_dates.get(key)
        movement_date = _value(movement, "movement_date")

        if opening_date and movement_date and movement_date < opening_date:
            continue

        if qty < 0:
            violations.append(InvariantViolation("stock", f"{branch_id}/{item_id}", "HIGH", "Stock movement memiliki qty negatif.", actual=str(qty)))

        if movement_type in {"IN", "OPENING", "ADJUSTMENT_IN", "RETURN_IN"}:
            balances[key] += qty
        elif movement_type in {"OUT", "DAMAGED", "CONSUMPTION", "ADJUSTMENT_OUT", "RETURN_OUT"}:
            balances[key] -= qty
        else:
            violations.append(InvariantViolation("stock", f"{branch_id}/{item_id}", "MEDIUM", f"Movement type belum dikenali: {movement_type or '-'}"))

    for key, expected in (expected_balances or {}).items():
        actual = balances.get(key, Decimal("0"))
        if not almost_equal(actual, expected, Decimal("0.0001")):
            violations.append(InvariantViolation("stock", f"{key[0]}/{key[1]}", "HIGH", "Saldo stok movement tidak sama dengan expected balance.", str(expected), str(actual)))

    notes = []
    if opening_balances:
        notes.append("Saldo stok dihitung dari stock_opening_balances ditambah movement sejak opening_date.")
    if not expected_balances:
        notes.append("Tanpa expected_balances fisik, audit stok belum bisa membandingkan saldo sistem dengan hasil stock opname resmi.")

    return AuditResult("Stock Movement Balance", checked, tuple(violations), notes=tuple(notes))


def audit_manual_backfill_duplicates(batches: Iterable[Any], invoices: Iterable[Any]) -> AuditResult:
    active_batches: dict[tuple[Any, ...], list[Any]] = defaultdict(list)
    invoice_sources: dict[tuple[Any, Any], list[Any]] = defaultdict(list)
    violations: list[InvariantViolation] = []
    checked = 0

    for batch in batches:
        if not _is_active_status(_value(batch, "status")):
            continue
        if str(_value(batch, "input_source", "") or "").upper() != "MANUAL_BACKFILL":
            continue
        checked += 1
        key = (
            _value(batch, "branch_id"),
            _value(batch, "period_start"),
            _value(batch, "period_end"),
            _value(batch, "bill_to_type"),
            _value(batch, "client_id"),
            _value(batch, "mandor_id"),
            str(_value(batch, "bill_to_name_snapshot", "") or "").strip().lower(),
            money(_value(batch, "total_amount", 0)),
        )
        active_batches[key].append(batch)

    for key, rows in active_batches.items():
        if len(rows) > 1:
            numbers = ", ".join(str(_value(row, "batch_number", _value(row, "id", "-"))) for row in rows)
            violations.append(InvariantViolation("manual_backfill", str(key), "CRITICAL", f"Potensi batch manual backfill dobel: {numbers}"))

    for invoice in invoices:
        if not _is_active_status(_value(invoice, "status")):
            continue
        source_type = _value(invoice, "source_type")
        source_id = _value(invoice, "source_order_id")
        if source_type and source_id:
            invoice_sources[(source_type, source_id)].append(invoice)

    for source_key, rows in invoice_sources.items():
        if len(rows) > 1:
            numbers = ", ".join(str(_value(row, "invoice_number", _value(row, "id", "-"))) for row in rows)
            violations.append(InvariantViolation("invoice_source", str(source_key), "CRITICAL", f"Lebih dari satu invoice aktif untuk source yang sama: {numbers}"))

    return AuditResult("Manual Backfill Duplicate Guard", checked, tuple(violations))


def _table(headers: list[str], rows: list[list[str]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def render_report(results: Iterable[AuditResult], *, db_error: str | None = None, db_skipped: bool = False) -> str:
    results = list(results)
    summary_rows = [
        [
            result.name,
            str(result.checked_count),
            "PASS" if result.passed else "FAIL",
            str(len(result.violations)),
        ]
        for result in results
    ]
    violation_rows = [
        [
            result.name,
            violation.area,
            violation.key,
            violation.severity,
            violation.message,
            violation.expected,
            violation.actual,
        ]
        for result in results
        for violation in result.violations
    ]
    note_rows = [[result.name, note] for result in results for note in result.notes]
    sections = [
        "# Audit Rekonsiliasi Invariant ERP Idha Boga",
        "Laporan ini read-only. Tujuannya membuktikan invariant finansial dan stok, bukan memperbaiki data otomatis.",
    ]
    if db_error:
        sections.extend([
            "## Status Database",
            f"Audit database belum bisa dijalankan: `{db_error}`",
        ])
    elif db_skipped:
        sections.extend([
            "## Status Database",
            "Audit database belum dijalankan. Jalankan ulang dengan `--from-db` saat PostgreSQL/snapshot siap.",
        ])
    sections.extend([
        "## Ringkasan",
        _table(["Audit", "Jumlah Dicek", "Status", "Violations"], summary_rows),
        "## Violations",
        _table(["Audit", "Area", "Key", "Severity", "Masalah", "Expected", "Actual"], violation_rows),
        "## Catatan",
        _table(["Audit", "Catatan"], note_rows),
        "## Invariant Yang Dicek",
        "- Jurnal: total debit harus sama dengan total kredit.",
        "- Invoice: `remaining_amount = total_amount - paid_amount`, `paid_amount <= total_amount`, dan total row payment sama dengan paid amount.",
        "- Hutang supplier: `remaining_amount = total_amount - paid_amount`, `paid_amount <= total_amount`, dan total supplier payment sama dengan paid amount.",
        "- Stok: qty movement tidak negatif dan movement_type harus dikenali. Expected balance bisa dipasok saat data master saldo tersedia.",
        "- Manual backfill: batch aktif dengan business key sama dan invoice aktif dengan source sama dianggap duplikasi kritis.",
        "",
    ])
    return "\n\n".join(sections)


def collect_results_from_database() -> list[AuditResult]:
    from app import create_app
    from app.models.accounting import Journal
    from app.models.finance import Invoice, ManualBillingBatch, Payment, SupplierBill, SupplierPayment
    from app.models.logistics import StockMovement, StockOpeningBalance

    app = create_app()
    with app.app_context():
        journals = Journal.query.all()
        invoices = Invoice.query.all()
        payments = Payment.query.all()
        supplier_bills = SupplierBill.query.all()
        supplier_payments = SupplierPayment.query.all()
        stock_movements = StockMovement.query.all()
        stock_opening_balances = StockOpeningBalance.query.all()
        manual_batches = ManualBillingBatch.query.all()

        return [
            audit_journal_balances(journals),
            audit_invoice_payment_integrity(invoices, payments),
            audit_supplier_bill_payment_integrity(supplier_bills, supplier_payments),
            audit_stock_movements(stock_movements, opening_balances=stock_opening_balances),
            audit_manual_backfill_duplicates(manual_batches, invoices),
        ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--from-db", action="store_true", help="Run against the configured Flask database.")
    args = parser.parse_args()

    db_error = None
    db_skipped = not args.from_db
    if args.from_db:
        try:
            results = collect_results_from_database()
        except Exception as error:
            db_error = f"{type(error).__name__}: {error}"
            results = []
    else:
        results = []

    report = render_report(results, db_error=db_error, db_skipped=db_skipped)
    args.output.write_text(report, encoding="utf-8")
    print(f"Financial invariant audit written: {args.output}")
    if db_error:
        print(f"Database audit unavailable: {db_error}")
    elif db_skipped:
        print("Database audit skipped. Use --from-db when PostgreSQL is ready.")
    else:
        print(f"Audit sections: {len(results)}")
        print(f"Total violations: {sum(len(result.violations) for result in results)}")


if __name__ == "__main__":
    main()
