"""Acceptance coverage for the locked two-lane billing roadmap.

Scope guarded here:
- REALTIME flow stays separate from MANUAL_BACKFILL.
- Manual book format like Pak Yatno can become a controlled recap total.
- Invoice/piutang payment rules stay safe before production DB UAT.
- Trace can show a complete rekap -> invoice -> payment -> journal -> buku kas/bank chain.
"""
from datetime import date, datetime
from types import SimpleNamespace

import pytest

from app.services.billing_input_source_service import INPUT_SOURCE_MANUAL_BACKFILL
from app.services.business_logic_guard_service import (
    BusinessRuleError,
    assert_date_not_before,
    assert_payment_amount_not_over_remaining,
    resolve_invoice_status_after_payment,
)
from app.services.manual_backfill_billing_service import (
    MANUAL_BACKFILL_ITEM_CATERING,
    MANUAL_BACKFILL_SOURCE_CATERING,
    build_catering_backfill_rows,
    build_warung_backfill_rows,
    collect_manual_backfill_duplicate_conflicts,
    summarize_backfill_rows,
)
from app.services.manual_billing_service import MANUAL_BILLING_INVOICE_SOURCE


class _ManyQuery:
    def __init__(self, rows):
        self.rows = list(rows or [])
        self.filters = {}

    def filter_by(self, **kwargs):
        query = _ManyQuery(self.rows)
        query.filters = kwargs
        return query

    def join(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        rows = self.all()
        return rows[0] if rows else None

    def all(self):
        if not self.filters:
            return list(self.rows)
        return [
            row for row in self.rows
            if all(getattr(row, key, None) == value for key, value in self.filters.items())
        ]


class _Column:
    def __eq__(self, other):
        return True

    def asc(self):
        return self


def _journal(journal_id, reference_type, reference_id, number):
    return SimpleNamespace(
        id=journal_id,
        reference_type=reference_type,
        reference_id=reference_id,
        journal_number=number,
        journal_date=date(2026, 7, 6),
    )


def _journal_detail(journal_id, account_code, account_name, debit, credit):
    return SimpleNamespace(
        id=journal_id,
        journal_id=journal_id,
        account=SimpleNamespace(account_code=account_code, account_name=account_name),
        debit=debit,
        credit=credit,
    )


def test_pak_yatno_book_format_totals_catering_warung_and_grand_total():
    """Manual backfill must match the real book/PDF shape, not cash receipt input."""
    dates = [
        "2026-06-19", "2026-06-20", "2026-06-21", "2026-06-22", "2026-06-23",
        "2026-06-24", "2026-06-25", "2026-06-26", "2026-06-27", "2026-06-28",
        "2026-06-29", "2026-06-30", "2026-07-01", "2026-07-02",
    ]
    lunch = [7, 7, 7, 7, 7, 4, 4, 4, 4, 4, 4, 4, 4, 4]
    dinner = [7, 7, 7, 7, 7, 4, 4, 4, 4, 4, 4, 4, 4, 4]
    prices = [15000] * len(dates)

    catering_rows = build_catering_backfill_rows(dates, lunch, dinner, prices)
    warung_rows = build_warung_backfill_rows(
        ["Reza", "Muji", "Warsep", "Ari", "Pras", "Sutiyono"],
        [468000, 278000, 266000, 116000, 101000, 37000],
    )

    summary = summarize_backfill_rows(catering_rows + warung_rows)

    assert sum(row["qty"] for row in catering_rows) == 142
    assert summary["catering_total"] == 2_130_000
    assert summary["warung_total"] == 1_266_000
    assert summary["total_amount"] == 3_396_000
    assert summary["item_count"] == 20


def test_payment_rules_support_partial_paid_and_reject_overpayment():
    assert resolve_invoice_status_after_payment(3_396_000, 0) == "DRAFT"
    assert resolve_invoice_status_after_payment(3_396_000, 1_000_000) == "PARTIAL"
    assert resolve_invoice_status_after_payment(3_396_000, 3_396_000) == "PAID"

    with pytest.raises(BusinessRuleError, match="tidak boleh lebih dari sisa tagihan"):
        assert_payment_amount_not_over_remaining(3_396_001, 3_396_000)




def test_customer_payment_date_cannot_precede_invoice_date():
    with pytest.raises(BusinessRuleError, match="tidak boleh lebih awal dari tanggal invoice"):
        assert_date_not_before(
            date(2026, 7, 5),
            date(2026, 7, 6),
            label="Tanggal pembayaran",
            reference_label="tanggal invoice",
        )

def test_duplicate_guard_ignores_cancelled_invoice_but_blocks_active_overlap(monkeypatch):
    import app.services.manual_backfill_billing_service as svc

    cancelled_invoice = SimpleNamespace(
        id=400,
        branch_id=1,
        invoice_number="INV-CANCELLED-001",
        mandor_id=7,
        period_start=date(2026, 6, 19),
        period_end=date(2026, 7, 2),
        source_type="PERIOD_INVOICE",
        input_source="REALTIME",
        status="CANCELLED",
        items=[SimpleNamespace(item_type="CATERING", source_type="ORDER_DETAIL")],
    )
    active_invoice = SimpleNamespace(
        id=401,
        branch_id=1,
        invoice_number="INV-AKTIF-001",
        mandor_id=7,
        period_start=date(2026, 6, 19),
        period_end=date(2026, 7, 2),
        source_type="PERIOD_INVOICE",
        input_source="REALTIME",
        status="DRAFT",
        items=[SimpleNamespace(item_type="CATERING", source_type="ORDER_DETAIL")],
    )
    batch = SimpleNamespace(
        id=123,
        branch_id=1,
        batch_number="MBR-20260702-001",
        mandor_id=7,
        period_start=date(2026, 6, 19),
        period_end=date(2026, 7, 2),
        invoice_id=None,
        items=[SimpleNamespace(
            item_type=MANUAL_BACKFILL_ITEM_CATERING,
            source_type=MANUAL_BACKFILL_SOURCE_CATERING,
        )],
    )

    monkeypatch.setattr(svc, "Invoice", SimpleNamespace(query=_ManyQuery([cancelled_invoice])))
    monkeypatch.setattr(svc, "ManualBillingBatch", SimpleNamespace(query=_ManyQuery([batch])))
    assert collect_manual_backfill_duplicate_conflicts(batch) == []

    monkeypatch.setattr(svc, "Invoice", SimpleNamespace(query=_ManyQuery([cancelled_invoice, active_invoice])))
    conflicts = collect_manual_backfill_duplicate_conflicts(batch)
    assert len(conflicts) == 1
    assert conflicts[0]["number"] == "INV-AKTIF-001"
    assert conflicts[0]["category_label"] == "catering"


def test_complete_trace_for_manual_backfill_invoice_payment_journal_and_cash_bank(monkeypatch):
    import app.services.billing_trace_service as trace_svc

    batch = SimpleNamespace(
        id=123,
        branch_id=1,
        batch_number="MBR-20260702-001",
        status="PAID",
        input_source=INPUT_SOURCE_MANUAL_BACKFILL,
        invoice_id=456,
        locked_at=datetime(2026, 7, 6, 9, 0, 0),
    )
    invoice = SimpleNamespace(
        id=456,
        branch_id=1,
        invoice_number="INV-MB-001",
        source_type=MANUAL_BILLING_INVOICE_SOURCE,
        source_order_id=123,
        input_source=INPUT_SOURCE_MANUAL_BACKFILL,
        total_amount=3_396_000,
        paid_amount=3_396_000,
        remaining_amount=0,
        status="PAID",
    )
    payment = SimpleNamespace(
        id=789,
        branch_id=1,
        invoice_id=456,
        payment_number="PAY-20260706-001",
        payment_date=date(2026, 7, 6),
        amount=3_396_000,
    )

    monkeypatch.setattr(trace_svc, "ManualBillingBatch", SimpleNamespace(query=_ManyQuery([batch])))
    monkeypatch.setattr(trace_svc, "Payment", SimpleNamespace(query=_ManyQuery([payment]), payment_date=_Column(), id=_Column()))
    monkeypatch.setattr(trace_svc, "Journal", SimpleNamespace(query=_ManyQuery([
        _journal(1, "INVOICE", 456, "JRN-INV-001"),
        _journal(2, "PAYMENT", 789, "JRN-PAY-001"),
    ])))
    monkeypatch.setattr(trace_svc, "JournalDetail", SimpleNamespace(
        query=_ManyQuery([
            _journal_detail(1, "1101", "Piutang Usaha", 3_396_000, 0),
            _journal_detail(1, "4001", "Pendapatan", 0, 3_396_000),
            _journal_detail(2, "1001", "Kas/Bank", 3_396_000, 0),
            _journal_detail(2, "1101", "Piutang Usaha", 0, 3_396_000),
        ]),
        journal_id=_Column(),
        account_id=_Column(),
        id=_Column(),
    ))
    monkeypatch.setattr(trace_svc, "Account", SimpleNamespace(id=_Column()))
    monkeypatch.setattr(trace_svc, "CashBankTransaction", SimpleNamespace(query=_ManyQuery([
        SimpleNamespace(id=900, reference_type="PAYMENT", reference_id=789)
    ])))

    trace = trace_svc.build_invoice_billing_trace_context(invoice)
    steps = {step["name"]: step["status"] for step in trace["steps"]}

    assert trace["overall_status"] == "Lengkap"
    assert trace["source_label"] == "Input Rekap Manual dari Buku"
    assert steps["Sumber Data"] == "PAID"
    assert steps["Lock Rekap"] == "Locked"
    assert steps["Invoice / Piutang"] == "PAID"
    assert steps["Pembayaran"] == "Paid"
    assert steps["Jurnal Pembayaran"] == "Lengkap"
    assert steps["Buku Kas/Bank"] == "Lengkap"
