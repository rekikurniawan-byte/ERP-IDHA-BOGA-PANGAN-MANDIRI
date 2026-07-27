from types import SimpleNamespace

from tools.audit_financial_invariants import (
    audit_invoice_payment_integrity,
    audit_journal_balances,
    audit_manual_backfill_duplicates,
    audit_stock_movements,
    audit_supplier_bill_payment_integrity,
    render_report,
)


def test_audit_journal_balances_flags_unbalanced_journal():
    journal = SimpleNamespace(
        id=1,
        journal_number="JRN-1",
        details=[
            SimpleNamespace(debit=100, credit=0),
            SimpleNamespace(debit=0, credit=90),
        ],
    )

    result = audit_journal_balances([journal])

    assert result.checked_count == 1
    assert len(result.violations) == 1
    assert result.violations[0].severity == "CRITICAL"
    assert result.violations[0].expected == "100.00"
    assert result.violations[0].actual == "90.00"


def test_audit_invoice_payment_integrity_checks_outstanding_and_payment_sum():
    invoice = SimpleNamespace(
        id=10,
        invoice_number="INV-1",
        total_amount=1000,
        paid_amount=400,
        remaining_amount=700,
        status="DRAFT",
    )
    payments = [
        SimpleNamespace(invoice_id=10, amount=200),
        SimpleNamespace(invoice_id=10, amount=100),
    ]

    result = audit_invoice_payment_integrity([invoice], payments)

    messages = [violation.message for violation in result.violations]
    assert "Outstanding invoice tidak sama dengan total - paid." in messages
    assert "Total payment rows tidak sama dengan paid_amount invoice." in messages


def test_audit_supplier_bill_payment_integrity_flags_overpayment():
    bill = SimpleNamespace(
        id=20,
        bill_number="AP-1",
        total_amount=500,
        paid_amount=600,
        remaining_amount=0,
        status="OPEN",
    )

    result = audit_supplier_bill_payment_integrity([bill], [SimpleNamespace(supplier_bill_id=20, amount=600)])

    assert any("melebihi total" in violation.message for violation in result.violations)


def test_audit_stock_movements_flags_unknown_type_and_negative_qty():
    movements = [
        SimpleNamespace(branch_id=1, item_id=2, movement_type="IN", qty=5),
        SimpleNamespace(branch_id=1, item_id=2, movement_type="MYSTERY", qty=-1),
    ]

    result = audit_stock_movements(movements)

    assert result.checked_count == 2
    assert any("qty negatif" in violation.message for violation in result.violations)
    assert any("Movement type belum dikenali" in violation.message for violation in result.violations)


def test_audit_stock_movements_uses_opening_balance_cutover_date():
    openings = [
        SimpleNamespace(branch_id=1, item_id=2, opening_date="2026-01-10", qty=10),
    ]
    movements = [
        SimpleNamespace(branch_id=1, item_id=2, movement_date="2026-01-01", movement_type="OUT", qty=99),
        SimpleNamespace(branch_id=1, item_id=2, movement_date="2026-01-11", movement_type="OUT", qty=3),
    ]

    result = audit_stock_movements(
        movements,
        expected_balances={(1, 2): 7},
        opening_balances=openings,
    )

    assert result.violations == ()
    assert "stock_opening_balances" in result.notes[0]


def test_audit_manual_backfill_duplicates_flags_business_key_and_invoice_source_duplicates():
    batches = [
        SimpleNamespace(id=1, batch_number="MB-1", branch_id=1, period_start="2026-01-01", period_end="2026-01-31", bill_to_type="CLIENT_EXISTING", client_id=3, mandor_id=None, bill_to_name_snapshot="PT A", total_amount=100, input_source="MANUAL_BACKFILL", status="DRAFT"),
        SimpleNamespace(id=2, batch_number="MB-2", branch_id=1, period_start="2026-01-01", period_end="2026-01-31", bill_to_type="CLIENT_EXISTING", client_id=3, mandor_id=None, bill_to_name_snapshot="PT A", total_amount=100, input_source="MANUAL_BACKFILL", status="LOCKED"),
    ]
    invoices = [
        SimpleNamespace(id=10, invoice_number="INV-1", source_type="MANUAL_BILLING_RECAP", source_order_id=1, status="DRAFT"),
        SimpleNamespace(id=11, invoice_number="INV-2", source_type="MANUAL_BILLING_RECAP", source_order_id=1, status="DRAFT"),
    ]

    result = audit_manual_backfill_duplicates(batches, invoices)

    assert len(result.violations) == 2
    assert any("batch manual backfill dobel" in violation.message for violation in result.violations)
    assert any("source yang sama" in violation.message for violation in result.violations)


def test_render_report_includes_database_error_when_unavailable():
    report = render_report([], db_error="OperationalError: connection refused")

    assert "Audit database belum bisa dijalankan" in report
    assert "connection refused" in report


def test_render_report_includes_database_skipped_status():
    report = render_report([], db_skipped=True)

    assert "Audit database belum dijalankan" in report
    assert "--from-db" in report
