from datetime import date, datetime
from types import SimpleNamespace

from app.services.billing_input_source_service import INPUT_SOURCE_MANUAL_BACKFILL


class _JournalQuery:
    def __init__(self, journals):
        self.journals = journals
        self.filters = {}

    def filter_by(self, **kwargs):
        query = _JournalQuery(self.journals)
        query.filters = kwargs
        return query

    def first(self):
        for journal in self.journals:
            if all(getattr(journal, key, None) == value for key, value in self.filters.items()):
                return journal
        return None


class _ListQuery:
    def __init__(self, rows):
        self.rows = rows
        self.filters = {}

    def filter_by(self, **kwargs):
        query = _ListQuery(self.rows)
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


def _detail(account_code, account_name, debit, credit):
    return SimpleNamespace(
        id=1,
        journal_id=1,
        account=SimpleNamespace(account_code=account_code, account_name=account_name),
        debit=debit,
        credit=credit,
    )


def test_invoice_billing_trace_shows_manual_backfill_to_paid_flow(monkeypatch):
    import app.services.billing_trace_service as svc

    invoice = SimpleNamespace(
        id=456,
        branch_id=1,
        invoice_number="INV-MB-001",
        source_type="MANUAL_BILLING_RECAP",
        source_order_id=123,
        input_source=INPUT_SOURCE_MANUAL_BACKFILL,
        total_amount=3396000,
        paid_amount=3396000,
        remaining_amount=0,
        status="PAID",
    )
    batch = SimpleNamespace(
        id=123,
        branch_id=1,
        invoice_id=456,
        batch_number="MBR-001",
        input_source=INPUT_SOURCE_MANUAL_BACKFILL,
        status="PAID",
        locked_at=datetime(2026, 7, 6, 9, 0),
    )
    payment = SimpleNamespace(
        id=77,
        branch_id=1,
        invoice_id=456,
        payment_number="PAY-001",
        payment_date=date(2026, 7, 6),
        amount=3396000,
    )
    cash_bank = SimpleNamespace(
        id=88,
        reference_type="PAYMENT",
        reference_id=77,
        transaction_date=date(2026, 7, 6),
        account_type="CASH",
        amount=3396000,
    )

    monkeypatch.setattr(svc, "ManualBillingBatch", SimpleNamespace(query=_ListQuery([batch])))
    monkeypatch.setattr(svc, "Payment", SimpleNamespace(query=_ListQuery([payment]), payment_date=_Column(), id=_Column()))
    monkeypatch.setattr(svc, "CashBankTransaction", SimpleNamespace(query=_ListQuery([cash_bank])))
    monkeypatch.setattr(
        svc,
        "Journal",
        SimpleNamespace(query=_JournalQuery([
            _journal(10, "INVOICE", 456, "JRN-INV-001"),
            _journal(11, "PAYMENT", 77, "JRN-PAY-001"),
        ])),
    )
    monkeypatch.setattr(svc, "Account", SimpleNamespace(id=_Column()))
    monkeypatch.setattr(
        svc,
        "JournalDetail",
        SimpleNamespace(account_id=_Column(), journal_id=_Column(), id=_Column(), query=_ListQuery([
            _detail("1004", "Piutang Usaha", 3396000, 0),
            _detail("4002", "Pendapatan Catering Harian", 0, 3396000),
        ])),
    )

    trace = svc.build_invoice_billing_trace_context(invoice)

    assert trace["overall_status"] == "Lengkap"
    assert trace["batch"].batch_number == "MBR-001"
    assert trace["invoice_journal"]["journal"].journal_number == "JRN-INV-001"
    assert len(trace["payments"]) == 1
    assert trace["payments"][0]["journal"]["journal"].journal_number == "JRN-PAY-001"
    assert trace["payments"][0]["cash_bank"]["transaction"].id == 88
    assert [step["name"] for step in trace["steps"]] == [
        "Sumber Data",
        "Lock Rekap",
        "Invoice / Piutang",
        "Pembayaran",
        "Jurnal Invoice",
        "Jurnal Pembayaran",
        "Buku Kas/Bank",
    ]


def test_invoice_billing_trace_warns_when_payment_journal_or_ledger_missing(monkeypatch):
    import app.services.billing_trace_service as svc

    invoice = SimpleNamespace(
        id=456,
        branch_id=1,
        invoice_number="INV-MB-001",
        source_type="MANUAL_BILLING_RECAP",
        source_order_id=123,
        input_source=INPUT_SOURCE_MANUAL_BACKFILL,
        total_amount=3396000,
        paid_amount=1000000,
        remaining_amount=2396000,
        status="PARTIAL",
    )
    batch = SimpleNamespace(
        id=123,
        branch_id=1,
        invoice_id=456,
        batch_number="MBR-001",
        input_source=INPUT_SOURCE_MANUAL_BACKFILL,
        status="PARTIALLY_PAID",
        locked_at=datetime(2026, 7, 6, 9, 0),
    )
    payment = SimpleNamespace(
        id=77,
        branch_id=1,
        invoice_id=456,
        payment_number="PAY-001",
        payment_date=date(2026, 7, 6),
        amount=1000000,
    )

    monkeypatch.setattr(svc, "ManualBillingBatch", SimpleNamespace(query=_ListQuery([batch])))
    monkeypatch.setattr(svc, "Payment", SimpleNamespace(query=_ListQuery([payment]), payment_date=_Column(), id=_Column()))
    monkeypatch.setattr(svc, "CashBankTransaction", SimpleNamespace(query=_ListQuery([])))
    monkeypatch.setattr(svc, "Journal", SimpleNamespace(query=_JournalQuery([_journal(10, "INVOICE", 456, "JRN-INV-001")])) )
    monkeypatch.setattr(svc, "Account", SimpleNamespace(id=_Column()))
    monkeypatch.setattr(
        svc,
        "JournalDetail",
        SimpleNamespace(account_id=_Column(), journal_id=_Column(), id=_Column(), query=_ListQuery([
            _detail("1004", "Piutang Usaha", 3396000, 0),
            _detail("4002", "Pendapatan Catering Harian", 0, 3396000),
        ])),
    )

    trace = svc.build_invoice_billing_trace_context(invoice)

    assert trace["overall_status"] == "Belum Lengkap"
    payment_steps = {step["name"]: step["status"] for step in trace["steps"]}
    assert payment_steps["Pembayaran"] == "Partial"
    assert payment_steps["Jurnal Pembayaran"] == "Belum lengkap"
    assert payment_steps["Buku Kas/Bank"] == "Belum lengkap"


def test_manual_billing_batch_trace_without_invoice_stops_before_invoice(monkeypatch):
    import app.services.billing_trace_service as svc

    batch = SimpleNamespace(
        id=123,
        branch_id=1,
        invoice_id=None,
        batch_number="MBR-001",
        input_source=INPUT_SOURCE_MANUAL_BACKFILL,
        status="LOCKED",
        locked_at=datetime(2026, 7, 6, 9, 0),
    )

    monkeypatch.setattr(svc, "Invoice", SimpleNamespace(query=_ListQuery([])))

    trace = svc.build_manual_billing_batch_trace_context(batch)

    assert trace["has_batch"] is True
    assert trace["has_invoice"] is False
    assert trace["overall_status"] == "Belum Lengkap"
    assert [step["name"] for step in trace["steps"]] == [
        "Rekap Dibuat",
        "Lock Rekap",
        "Invoice / Piutang",
    ]
