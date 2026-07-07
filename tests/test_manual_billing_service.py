from datetime import date
from types import SimpleNamespace

from app.services.billing_input_source_service import INPUT_SOURCE_REALTIME
from app.services.manual_billing_service import (
    MANUAL_BILLING_INVOICE_SOURCE,
    MANUAL_BILLING_SOURCE_MANUAL_RECEIVABLE,
    collect_manual_billing_candidates,
    create_manual_billing_invoice,
    find_manual_billing_invoice_for_source,
)


class _FakeQueryResult:
    def __init__(self, rows):
        self.rows = rows

    def order_by(self, *args, **kwargs):
        return self

    def all(self):
        return list(self.rows)


class _FakeFilterQuery:
    def __init__(self, rows=None, first_result=None):
        self.rows = rows or []
        self.first_result = first_result

    def filter_by(self, **kwargs):
        return _FakeQueryResult(self.rows)

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def all(self):
        return list(self.rows)

    def first(self):
        return self.first_result

    def count(self):
        return len(self.rows)


class _FakeColumn:
    def asc(self):
        return self

    def desc(self):
        return self


class _FakeModelQuery:
    def __init__(self, rows=None, first_result=None):
        self.rows = rows or []
        self.first_result = first_result

    def filter_by(self, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return _FakeQueryResult(self.rows)

    def first(self):
        return self.first_result

    def all(self):
        return list(self.rows)

    def count(self):
        return len(self.rows)


class _FakeSession:
    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        return None

    def commit(self):
        return None


def test_collect_manual_billing_candidates_includes_manual_receivable_and_worker_debt(monkeypatch):
    field_tx = SimpleNamespace(id=11)
    counterparty = SimpleNamespace(linked_mandor_id=7, name="Mandor Alpha")
    receivable = SimpleNamespace(
        id=101,
        branch_id=1,
        receivable_date=date(2026, 7, 1),
        remaining_amount=150000,
        receivable_number="MREC-1",
        field_transaction=field_tx,
        counterparty=counterparty,
    )
    worker = SimpleNamespace(mandor_id=7, full_name="Budi")
    sale = SimpleNamespace(sale_date=date(2026, 7, 2))
    worker_debt = SimpleNamespace(
        id=202,
        branch_id=1,
        worker=worker,
        sale=sale,
        debt_amount=50000,
    )

    monkeypatch.setattr(
        "app.services.manual_billing_service.ManualReceivable",
        SimpleNamespace(
            query=_FakeModelQuery(rows=[receivable]),
            receivable_date=_FakeColumn(),
            id=_FakeColumn(),
        ),
    )
    monkeypatch.setattr(
        "app.services.manual_billing_service.WorkerDebt",
        SimpleNamespace(
            query=_FakeModelQuery(rows=[worker_debt]),
            id=_FakeColumn(),
        ),
    )
    monkeypatch.setattr(
        "app.services.manual_billing_service.invoice_item_source_exists",
        lambda source_type, source_id: False,
    )
    monkeypatch.setattr(
        "app.services.manual_billing_service.manual_billing_source_exists",
        lambda source_type, source_id: False,
    )
    monkeypatch.setattr(
        "app.services.manual_billing_service.get_debt_remaining_amount",
        lambda debt: debt.debt_amount,
    )
    monkeypatch.setattr(
        "app.services.manual_billing_service.get_debt_paid_amount",
        lambda debt: 0,
    )

    result = collect_manual_billing_candidates(1, 7, date(2026, 7, 1), date(2026, 7, 31))

    assert result["total_amount"] == 200000
    assert len(result["rows"]) == 2
    assert result["manual_receivable_total"] == 150000
    assert result["warung_total"] == 50000


def test_create_manual_billing_invoice_builds_invoice_and_batch(monkeypatch):
    mandor = SimpleNamespace(id=7, branch_id=1, name="Mandor Alpha", client=SimpleNamespace(id=99, name="PT Mandiri", client_code="CL-99", is_active=True))
    client_pic = SimpleNamespace(id=501, name="Sari", position="PIC", phone="08123", email="sari@example.com")
    field_tx = SimpleNamespace(id=11)
    counterparty = SimpleNamespace(linked_mandor_id=7, name="Mandor Alpha")
    receivable = SimpleNamespace(
        id=101,
        branch_id=1,
        receivable_date=date(2026, 7, 1),
        remaining_amount=150000,
        receivable_number="MREC-1",
        field_transaction=field_tx,
        counterparty=counterparty,
    )
    worker = SimpleNamespace(mandor_id=7, full_name="Budi")
    sale = SimpleNamespace(sale_date=date(2026, 7, 2))
    worker_debt = SimpleNamespace(
        id=202,
        branch_id=1,
        worker=worker,
        sale=sale,
        debt_amount=50000,
    )

    session = _FakeSession()
    monkeypatch.setattr(
        "app.services.manual_billing_service.db",
        SimpleNamespace(session=session),
    )
    monkeypatch.setattr(
        "app.services.manual_billing_service.Mandor",
        SimpleNamespace(
            query=SimpleNamespace(filter_by=lambda **kwargs: SimpleNamespace(first=lambda: mandor)),
            id=_FakeColumn(),
        ),
    )
    monkeypatch.setattr(
        "app.services.manual_billing_service.ClientPic",
        SimpleNamespace(
            query=SimpleNamespace(filter_by=lambda **kwargs: SimpleNamespace(order_by=lambda *args, **kwargs: SimpleNamespace(all=lambda: [client_pic]), first=lambda: client_pic)),
        ),
    )
    monkeypatch.setattr(
        "app.services.manual_billing_service.ManualReceivable",
        SimpleNamespace(
            query=_FakeModelQuery(rows=[receivable]),
            receivable_date=_FakeColumn(),
            id=_FakeColumn(),
        ),
    )
    monkeypatch.setattr(
        "app.services.manual_billing_service.WorkerDebt",
        SimpleNamespace(
            query=_FakeModelQuery(rows=[worker_debt]),
            id=_FakeColumn(),
        ),
    )
    monkeypatch.setattr(
        "app.services.manual_billing_service.generate_manual_billing_number",
        lambda period_end: "MBR-20260731-001",
    )
    monkeypatch.setattr(
        "app.services.manual_billing_service.generate_manual_billing_invoice_number",
        lambda invoice_date: "INV-20260704-001",
    )
    monkeypatch.setattr(
        "app.services.manual_billing_service.collect_manual_billing_candidates",
        lambda branch_id, mandor_id, period_start, period_end: {
            "rows": [
                {
                    "date": date(2026, 7, 1),
                    "item_type": "OTHER_RECEIVABLE",
                    "description": "Piutang manual MREC-1",
                    "qty": 1,
                    "unit_price": 150000,
                    "subtotal": 150000,
                    "source_type": "MANUAL_RECEIVABLE",
                    "source_id": 101,
                    "source_label": "MREC-1",
                },
                {
                    "date": date(2026, 7, 2),
                    "item_type": "WARUNG_DEBT",
                    "description": "Hutang warung pekerja Budi",
                    "qty": 1,
                    "unit_price": 50000,
                    "subtotal": 50000,
                    "source_type": "WORKER_DEBT",
                    "source_id": 202,
                    "source_label": "Budi",
                },
            ],
            "blocked_rows": [],
            "total_amount": 200000,
            "manual_receivable_total": 150000,
            "warung_total": 50000,
        },
    )
    monkeypatch.setattr(
        "app.services.manual_billing_service.get_required_client_pic",
        lambda client_id, client_pic_id=None: (client_pic, None),
    )
    monkeypatch.setattr(
        "app.services.manual_billing_service.build_company_bank_snapshot",
        lambda branch_id: {
            "company_bank_name_snapshot": "BCA",
            "company_bank_account_number_snapshot": "123",
            "company_bank_account_name_snapshot": "PT Mandiri",
        },
    )
    monkeypatch.setattr(
        "app.services.manual_billing_service.create_invoice_journal_for_invoice",
        lambda invoice, created_by, commit=False: (True, "ok", SimpleNamespace(id=333)),
    )
    monkeypatch.setattr(
        "app.services.manual_billing_service.record_audit_log",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "app.services.manual_billing_service.date",
        date,
    )

    batch, invoice = create_manual_billing_invoice(
        branch_id=1,
        mandor_id=7,
        period_start=date(2026, 7, 1),
        period_end=date(2026, 7, 31),
        client_pic_id=501,
        created_by=9,
        notes="rekap manual",
    )

    assert batch.batch_number == "MBR-20260731-001"
    assert batch.status == "INVOICED"
    assert invoice.source_type == MANUAL_BILLING_INVOICE_SOURCE
    assert invoice.input_source == INPUT_SOURCE_REALTIME
    assert batch.input_source == INPUT_SOURCE_REALTIME
    assert invoice.total_amount == 200000
    assert invoice.source_order_id is None or invoice.source_order_id == batch.id
    assert len(batch.items) == 2
    assert all(item.input_source == INPUT_SOURCE_REALTIME for item in batch.items)


def test_find_manual_billing_invoice_for_source_returns_linked_invoice(monkeypatch):
    invoice = SimpleNamespace(id=9001, invoice_number="INV-TRACE-001")
    batch = SimpleNamespace(invoice=invoice, invoice_id=invoice.id)
    batch_item = SimpleNamespace(batch=batch)

    monkeypatch.setattr(
        "app.services.manual_billing_service.ManualBillingBatchItem",
        SimpleNamespace(
            query=SimpleNamespace(
                filter_by=lambda **kwargs: SimpleNamespace(first=lambda: batch_item)
            )
        ),
    )

    result = find_manual_billing_invoice_for_source(
        MANUAL_BILLING_SOURCE_MANUAL_RECEIVABLE,
        101,
    )

    assert result is invoice
