from datetime import date
from types import SimpleNamespace

import pytest

from app.services.billing_input_source_service import INPUT_SOURCE_MANUAL_BACKFILL
from app.services import manual_backfill_billing_service
from app.services.manual_backfill_billing_service import (
    MANUAL_BACKFILL_ITEM_CATERING,
    MANUAL_BACKFILL_ITEM_WARUNG,
    MANUAL_BACKFILL_SOURCE_CATERING,
    MANUAL_BACKFILL_SOURCE_WARUNG,
    ManualBackfillBillingError,
    build_catering_backfill_rows,
    build_warung_backfill_rows,
    build_manual_backfill_duplicate_guard_context,
    build_manual_backfill_print_context,
    build_manual_backfill_register_summary,
    collect_manual_backfill_duplicate_conflicts,
    create_invoice_from_manual_backfill_batch,
    create_invoice_from_manual_backfill_batch_record,
    create_manual_backfill_batch,
    create_manual_backfill_batch_record,
    summarize_backfill_rows,
    validate_manual_backfill_batch_before_invoice,
    validate_manual_backfill_invoice_consistency,
)


class _FakeSession:
    def __init__(self):
        self.added = []
        self.deleted = []
        self.committed = False

    def add(self, obj):
        self.added.append(obj)

    def delete(self, obj):
        self.deleted.append(obj)

    def commit(self):
        self.committed = True

    def flush(self):
        # Simulate database id assignment for persisted objects.
        for obj in self.added:
            if obj.__class__.__name__ == "ManualBillingBatch" and not getattr(obj, "id", None):
                obj.id = 123
            if obj.__class__.__name__ in {"Invoice", "FakeInvoice"} and not getattr(obj, "id", None):
                obj.id = 456


class _FakeTransactionSession:
    def __init__(self, *, fail_commit=False):
        self.commit_count = 0
        self.rollback_count = 0
        self.fail_commit = fail_commit

    def commit(self):
        self.commit_count += 1
        if self.fail_commit:
            raise RuntimeError("commit failed")

    def rollback(self):
        self.rollback_count += 1


class _FakeDb:
    def __init__(self, session):
        self.session = session


class _FakeQuery:
    def __init__(self, first_result):
        self.first_result = first_result

    def filter_by(self, **kwargs):
        return self

    def first(self):
        return self.first_result


def test_build_catering_backfill_rows_matches_book_format():
    rows = build_catering_backfill_rows(
        ["2026-06-19", ""],
        ["7", ""],
        ["7", ""],
        ["15000", ""],
        ["Pak Yatno", ""],
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["item_type"] == MANUAL_BACKFILL_ITEM_CATERING
    assert row["source_type"] == MANUAL_BACKFILL_SOURCE_CATERING
    assert row["qty"] == 14
    assert row["unit_price"] == 15000
    assert row["subtotal"] == 210000
    assert "Siang 7" in row["description"]
    assert "Sore 7" in row["description"]


def test_create_manual_backfill_batch_record_commits_once(monkeypatch):
    session = _FakeTransactionSession()
    monkeypatch.setattr(manual_backfill_billing_service, "db", _FakeDb(session))
    batch = SimpleNamespace(id=12, batch_number="MBR-1")
    calls = {}

    def fake_create_manual_backfill_batch(**kwargs):
        calls.update(kwargs)
        return batch

    monkeypatch.setattr(
        manual_backfill_billing_service,
        "create_manual_backfill_batch",
        fake_create_manual_backfill_batch,
    )

    result = create_manual_backfill_batch_record(
        branch_id=1,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        created_by=9,
    )

    assert result is batch
    assert calls["commit"] is False
    assert session.commit_count == 1
    assert session.rollback_count == 0


def test_manual_backfill_record_wrapper_rolls_back_when_commit_fails(monkeypatch):
    session = _FakeTransactionSession(fail_commit=True)
    monkeypatch.setattr(manual_backfill_billing_service, "db", _FakeDb(session))
    monkeypatch.setattr(
        manual_backfill_billing_service,
        "create_manual_backfill_batch",
        lambda **kwargs: SimpleNamespace(id=12),
    )

    with pytest.raises(RuntimeError, match="commit failed"):
        create_manual_backfill_batch_record(
            branch_id=1,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            created_by=9,
        )

    assert session.commit_count == 1
    assert session.rollback_count == 1


def test_create_invoice_from_manual_backfill_batch_record_rolls_back_mid_process_failure(monkeypatch):
    session = _FakeTransactionSession()
    monkeypatch.setattr(manual_backfill_billing_service, "db", _FakeDb(session))
    monkeypatch.setattr(
        manual_backfill_billing_service,
        "create_invoice_from_manual_backfill_batch",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("journal failed")),
    )

    with pytest.raises(RuntimeError, match="journal failed"):
        create_invoice_from_manual_backfill_batch_record(
            batch_id=12,
            branch_id=1,
            created_by=7,
        )

    assert session.commit_count == 0
    assert session.rollback_count == 1



def test_build_catering_backfill_rows_supports_manual_breakfast_without_realtime_schema_change():
    rows = build_catering_backfill_rows(
        ["2026-06-19"],
        ["7"],
        ["7"],
        ["15000"],
        ["sarapan khusus mandor"],
        ["5"],
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["qty"] == 19
    assert row["subtotal"] == 285000
    assert "Sarapan 5" in row["description"]
    assert "Siang 7" in row["description"]
    assert "Sore 7" in row["description"]


def test_build_catering_backfill_rows_rejects_duplicate_catering_date():
    with pytest.raises(ManualBackfillBillingError, match="Tanggal catering tidak boleh dobel"):
        build_catering_backfill_rows(
            ["2026-06-19", "2026-06-19"],
            ["7", "1"],
            ["7", "0"],
            ["15000", "15000"],
            ["", "penyesuaian dobel"],
        )

def test_build_warung_backfill_rows_matches_book_format():
    rows = build_warung_backfill_rows(
        ["Reza", ""],
        ["468000", ""],
        ["kasbon buku", ""],
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["item_type"] == MANUAL_BACKFILL_ITEM_WARUNG
    assert row["source_type"] == MANUAL_BACKFILL_SOURCE_WARUNG
    assert row["subtotal"] == 468000
    assert row["source_label"] == "Reza"


def test_create_manual_backfill_batch_saves_draft_without_invoice(monkeypatch):
    mandor = SimpleNamespace(id=7, branch_id=1, client_id=99, name="Pak Yatno", is_active=True)
    session = _FakeSession()

    monkeypatch.setattr(
        "app.services.manual_backfill_billing_service.db",
        SimpleNamespace(session=session),
    )
    monkeypatch.setattr(
        "app.services.manual_backfill_billing_service.Mandor",
        SimpleNamespace(query=_FakeQuery(mandor)),
    )
    monkeypatch.setattr(
        "app.services.manual_backfill_billing_service.generate_manual_billing_number",
        lambda period_end: "MBR-20260702-001",
    )
    monkeypatch.setattr(
        "app.services.manual_backfill_billing_service.record_audit_log",
        lambda **kwargs: None,
    )

    catering_rows = build_catering_backfill_rows(["2026-06-19"], ["7"], ["7"], ["15000"])
    warung_rows = build_warung_backfill_rows(["Reza"], ["468000"])
    batch = create_manual_backfill_batch(
        branch_id=1,
        mandor_id=7,
        period_start=date(2026, 6, 19),
        period_end=date(2026, 7, 2),
        catering_rows=catering_rows,
        warung_rows=warung_rows,
        notes="rekap buku Pak Yatno",
        created_by=9,
    )

    assert batch.batch_number == "MBR-20260702-001"
    assert batch.status == "DRAFT"
    assert batch.input_source == INPUT_SOURCE_MANUAL_BACKFILL
    assert batch.total_amount == 678000
    assert batch.invoice_id is None
    batch_items = [obj for obj in session.added if obj.__class__.__name__ == "ManualBillingBatchItem"]
    assert len(batch_items) == 2
    assert all(item.input_source == INPUT_SOURCE_MANUAL_BACKFILL for item in batch_items)
    assert {item.source_type for item in batch_items} == {
        MANUAL_BACKFILL_SOURCE_CATERING,
        MANUAL_BACKFILL_SOURCE_WARUNG,
    }


def test_create_manual_backfill_batch_rejects_empty_rows(monkeypatch):
    mandor = SimpleNamespace(id=7, branch_id=1, client_id=99, name="Pak Yatno", is_active=True)
    monkeypatch.setattr(
        "app.services.manual_backfill_billing_service.Mandor",
        SimpleNamespace(query=_FakeQuery(mandor)),
    )

    with pytest.raises(ManualBackfillBillingError):
        create_manual_backfill_batch(
            branch_id=1,
            mandor_id=7,
            period_start=date(2026, 6, 19),
            period_end=date(2026, 7, 2),
            catering_rows=[],
            warung_rows=[],
            created_by=9,
        )


def test_update_manual_backfill_batch_allows_draft_edit_and_replaces_items(monkeypatch):
    from app.services.manual_backfill_billing_service import update_manual_backfill_batch

    existing_item = SimpleNamespace(id=1, item_type=MANUAL_BACKFILL_ITEM_CATERING)
    batch = SimpleNamespace(
        id=123,
        branch_id=1,
        batch_number="MBR-20260702-001",
        bill_to_type="KELOMPOK",
        bill_to_name_snapshot="Kelompok Lama",
        mandor_id=None,
        client_id=None,
        client_pic_id=None,
        period_start=date(2026, 6, 19),
        period_end=date(2026, 7, 2),
        status="DRAFT",
        input_source=INPUT_SOURCE_MANUAL_BACKFILL,
        invoice_id=None,
        total_amount=210000,
        notes="lama",
        items=[existing_item],
    )
    class FakeManualBillingBatchItem(SimpleNamespace):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)

    session = _FakeSession()
    audit_events = []

    monkeypatch.setattr("app.services.manual_backfill_billing_service.db", SimpleNamespace(session=session))
    monkeypatch.setattr("app.services.manual_backfill_billing_service.ManualBillingBatch", SimpleNamespace(query=_FakeQuery(batch)))
    monkeypatch.setattr("app.services.manual_backfill_billing_service.ManualBillingBatchItem", FakeManualBillingBatchItem)
    monkeypatch.setattr("app.services.manual_backfill_billing_service.record_audit_log", lambda **kwargs: audit_events.append(kwargs))

    catering_rows = build_catering_backfill_rows(["2026-06-20"], ["10"], ["5"], ["16000"], ["revisi porsi"])
    warung_rows = build_warung_backfill_rows(["Reza"], ["500000"], ["revisi kasbon"])
    updated = update_manual_backfill_batch(
        batch_id=123,
        branch_id=1,
        bill_to_type="KELOMPOK",
        bill_to_name_snapshot="Kelompok Pak Yatno Revisi",
        period_start=date(2026, 6, 20),
        period_end=date(2026, 7, 3),
        catering_rows=catering_rows,
        warung_rows=warung_rows,
        notes="sudah dikoreksi",
        updated_by=9,
    )

    assert updated is batch
    assert batch.status == "DRAFT"
    assert batch.bill_to_name_snapshot == "Kelompok Pak Yatno Revisi"
    assert batch.total_amount == 740000
    assert batch.notes == "sudah dikoreksi"
    assert session.deleted == [existing_item]
    new_items = [obj for obj in session.added if obj.__class__.__name__ in {"ManualBillingBatchItem", "FakeManualBillingBatchItem"}]
    assert len(new_items) == 2
    assert {item.item_type for item in new_items} == {MANUAL_BACKFILL_ITEM_CATERING, MANUAL_BACKFILL_ITEM_WARUNG}
    assert audit_events[-1]["event_type"] == "MANUAL_BACKFILL_BATCH_UPDATED"
    assert audit_events[-1]["metadata"]["before_total_amount"] == 210000


def test_update_manual_backfill_batch_rejects_locked_or_invoiced(monkeypatch):
    from app.services.manual_backfill_billing_service import update_manual_backfill_batch

    batch = SimpleNamespace(
        id=123,
        branch_id=1,
        batch_number="MBR-20260702-001",
        status="LOCKED",
        input_source=INPUT_SOURCE_MANUAL_BACKFILL,
        invoice_id=None,
        items=[],
    )
    monkeypatch.setattr("app.services.manual_backfill_billing_service.ManualBillingBatch", SimpleNamespace(query=_FakeQuery(batch)))

    with pytest.raises(ManualBackfillBillingError, match="Draft"):
        update_manual_backfill_batch(
            batch_id=123,
            branch_id=1,
            bill_to_type="KELOMPOK",
            bill_to_name_snapshot="Kelompok Pak Yatno",
            period_start=date(2026, 6, 20),
            period_end=date(2026, 7, 3),
            catering_rows=build_catering_backfill_rows(["2026-06-20"], ["1"], ["0"], ["15000"]),
            updated_by=9,
        )


def test_void_manual_backfill_batch_allows_draft_before_invoice(monkeypatch):
    from app.services.manual_backfill_billing_service import (
        MANUAL_BACKFILL_STATUS_VOID,
        void_manual_backfill_batch,
    )

    batch = SimpleNamespace(
        id=123,
        branch_id=1,
        batch_number="MBR-20260702-001",
        status="DRAFT",
        input_source=INPUT_SOURCE_MANUAL_BACKFILL,
        invoice_id=None,
        notes="catatan awal",
    )
    audit_events = []
    session = _FakeSession()

    monkeypatch.setattr("app.services.manual_backfill_billing_service.db", SimpleNamespace(session=session))
    monkeypatch.setattr("app.services.manual_backfill_billing_service.ManualBillingBatch", SimpleNamespace(query=_FakeQuery(batch)))
    monkeypatch.setattr("app.services.manual_backfill_billing_service.Invoice", SimpleNamespace(query=_FakeQuery(None)))
    monkeypatch.setattr("app.services.manual_backfill_billing_service.record_audit_log", lambda **kwargs: audit_events.append(kwargs))

    voided = void_manual_backfill_batch(
        batch_id=123,
        branch_id=1,
        voided_by=9,
        reason="Salah input dari buku",
        commit=True,
    )

    assert voided is batch
    assert batch.status == MANUAL_BACKFILL_STATUS_VOID
    assert "catatan awal" in batch.notes
    assert "Salah input dari buku" in batch.notes
    assert session.committed is True
    assert audit_events[-1]["event_type"] == "MANUAL_BACKFILL_BATCH_VOIDED"
    assert audit_events[-1]["metadata"]["old_status"] == "DRAFT"
    assert audit_events[-1]["metadata"]["new_status"] == MANUAL_BACKFILL_STATUS_VOID


def test_void_manual_backfill_batch_allows_locked_before_invoice(monkeypatch):
    from app.services.manual_backfill_billing_service import void_manual_backfill_batch

    batch = SimpleNamespace(
        id=123,
        branch_id=1,
        batch_number="MBR-20260702-001",
        status="LOCKED",
        input_source=INPUT_SOURCE_MANUAL_BACKFILL,
        invoice_id=None,
        notes=None,
    )

    monkeypatch.setattr("app.services.manual_backfill_billing_service.db", SimpleNamespace(session=_FakeSession()))
    monkeypatch.setattr("app.services.manual_backfill_billing_service.ManualBillingBatch", SimpleNamespace(query=_FakeQuery(batch)))
    monkeypatch.setattr("app.services.manual_backfill_billing_service.Invoice", SimpleNamespace(query=_FakeQuery(None)))
    monkeypatch.setattr("app.services.manual_backfill_billing_service.record_audit_log", lambda **kwargs: None)

    voided = void_manual_backfill_batch(batch_id=123, branch_id=1, voided_by=9)

    assert voided.status == "VOID"
    assert "sebelum invoice" in voided.notes


def test_void_manual_backfill_batch_rejects_invoiced_recap(monkeypatch):
    from app.services.manual_backfill_billing_service import void_manual_backfill_batch

    batch = SimpleNamespace(
        id=123,
        branch_id=1,
        batch_number="MBR-20260702-001",
        status="LOCKED",
        input_source=INPUT_SOURCE_MANUAL_BACKFILL,
        invoice_id=456,
        notes=None,
    )

    monkeypatch.setattr("app.services.manual_backfill_billing_service.ManualBillingBatch", SimpleNamespace(query=_FakeQuery(batch)))

    with pytest.raises(ManualBackfillBillingError, match="sudah memiliki invoice"):
        void_manual_backfill_batch(batch_id=123, branch_id=1, voided_by=9)


def test_void_manual_backfill_batch_rejects_recap_with_existing_invoice_even_without_invoice_id(monkeypatch):
    from app.services.manual_backfill_billing_service import void_manual_backfill_batch

    existing_invoice = SimpleNamespace(id=456, invoice_number="INV-20260706-001")
    batch = SimpleNamespace(
        id=123,
        branch_id=1,
        batch_number="MBR-20260702-001",
        status="LOCKED",
        input_source=INPUT_SOURCE_MANUAL_BACKFILL,
        invoice_id=None,
        notes=None,
    )

    monkeypatch.setattr("app.services.manual_backfill_billing_service.ManualBillingBatch", SimpleNamespace(query=_FakeQuery(batch)))
    monkeypatch.setattr("app.services.manual_backfill_billing_service.Invoice", SimpleNamespace(query=_FakeQuery(existing_invoice)))

    with pytest.raises(ManualBackfillBillingError, match="sudah punya invoice"):
        void_manual_backfill_batch(batch_id=123, branch_id=1, voided_by=9)


def test_manual_backfill_duplicate_guard_ignores_void_target(monkeypatch):
    queried = {"invoice": False}

    class QueryShouldNotRun:
        def filter_by(self, **kwargs):
            queried["invoice"] = True
            return self
        def all(self):
            return []

    batch = SimpleNamespace(
        id=123,
        branch_id=1,
        batch_number="MBR-20260702-001",
        status="VOID",
        bill_to_type="KELOMPOK",
        bill_to_name_snapshot="Kelompok Pak Yatno",
        mandor_id=None,
        client_id=None,
        period_start=date(2026, 6, 19),
        period_end=date(2026, 7, 2),
        invoice_id=None,
        items=[_manual_item()],
    )

    monkeypatch.setattr("app.services.manual_backfill_billing_service.Invoice", SimpleNamespace(query=QueryShouldNotRun()))

    assert collect_manual_backfill_duplicate_conflicts(batch) == []
    assert queried["invoice"] is False


def _manual_item(**overrides):
    values = {
        "item_type": MANUAL_BACKFILL_ITEM_CATERING,
        "qty": 14,
        "unit_price": 15000,
        "subtotal": 210000,
        "input_source": INPUT_SOURCE_MANUAL_BACKFILL,
        "source_date": date(2026, 6, 19),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_lock_manual_backfill_batch_changes_draft_to_locked(monkeypatch):
    from app.services.manual_backfill_billing_service import (
        MANUAL_BACKFILL_STATUS_LOCKED,
        lock_manual_backfill_batch,
    )

    batch = SimpleNamespace(
        id=123,
        branch_id=1,
        batch_number="MBR-20260702-001",
        period_start=date(2026, 6, 19),
        period_end=date(2026, 7, 2),
        status="DRAFT",
        input_source=INPUT_SOURCE_MANUAL_BACKFILL,
        invoice_id=None,
        total_amount=678000,
        items=[
            _manual_item(subtotal=210000),
            _manual_item(
                item_type=MANUAL_BACKFILL_ITEM_WARUNG,
                qty=1,
                unit_price=468000,
                subtotal=468000,
                source_date=None,
            ),
        ],
    )

    monkeypatch.setattr(
        "app.services.manual_backfill_billing_service.db",
        SimpleNamespace(session=_FakeSession()),
    )
    monkeypatch.setattr(
        "app.services.manual_backfill_billing_service.ManualBillingBatch",
        SimpleNamespace(query=_FakeQuery(batch)),
    )
    monkeypatch.setattr(
        "app.services.manual_backfill_billing_service.record_audit_log",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "app.services.manual_backfill_billing_service.collect_manual_backfill_duplicate_conflicts",
        lambda batch: [],
    )

    locked = lock_manual_backfill_batch(
        batch_id=123,
        branch_id=1,
        locked_by=9,
    )

    assert locked.status == MANUAL_BACKFILL_STATUS_LOCKED
    assert locked.locked_by == 9
    assert locked.locked_at is not None


def test_lock_manual_backfill_batch_rejects_non_draft(monkeypatch):
    from app.services.manual_backfill_billing_service import lock_manual_backfill_batch

    batch = SimpleNamespace(
        id=123,
        branch_id=1,
        batch_number="MBR-20260702-001",
        period_start=date(2026, 6, 19),
        period_end=date(2026, 7, 2),
        status="LOCKED",
        input_source=INPUT_SOURCE_MANUAL_BACKFILL,
        invoice_id=None,
        total_amount=210000,
        items=[_manual_item()],
    )
    monkeypatch.setattr(
        "app.services.manual_backfill_billing_service.ManualBillingBatch",
        SimpleNamespace(query=_FakeQuery(batch)),
    )

    with pytest.raises(ManualBackfillBillingError):
        lock_manual_backfill_batch(batch_id=123, branch_id=1, locked_by=9)


def test_lock_manual_backfill_batch_rejects_total_mismatch(monkeypatch):
    from app.services.manual_backfill_billing_service import lock_manual_backfill_batch

    batch = SimpleNamespace(
        id=123,
        branch_id=1,
        batch_number="MBR-20260702-001",
        period_start=date(2026, 6, 19),
        period_end=date(2026, 7, 2),
        status="DRAFT",
        input_source=INPUT_SOURCE_MANUAL_BACKFILL,
        invoice_id=None,
        total_amount=999999,
        items=[_manual_item()],
    )
    monkeypatch.setattr(
        "app.services.manual_backfill_billing_service.ManualBillingBatch",
        SimpleNamespace(query=_FakeQuery(batch)),
    )

    with pytest.raises(ManualBackfillBillingError):
        lock_manual_backfill_batch(batch_id=123, branch_id=1, locked_by=9)


def test_create_invoice_from_manual_backfill_batch_promotes_locked_batch_to_invoice(monkeypatch):
    from app.services.manual_backfill_billing_service import MANUAL_BACKFILL_STATUS_INVOICED
    from app.services.manual_billing_service import MANUAL_BILLING_INVOICE_SOURCE

    class FakeInvoice(SimpleNamespace):
        query = SimpleNamespace(filter_by=lambda **kwargs: SimpleNamespace(first=lambda: None))

        def __init__(self, **kwargs):
            super().__init__(**kwargs)

    class FakeInvoiceItem(SimpleNamespace):
        query = SimpleNamespace(filter_by=lambda **kwargs: SimpleNamespace(first=lambda: None))

        def __init__(self, **kwargs):
            super().__init__(**kwargs)

    mandor = SimpleNamespace(id=7, branch_id=1, client_id=None, name="Pak Yatno", phone="0812", is_active=True, client=None)
    batch = SimpleNamespace(
        id=123,
        branch_id=1,
        batch_number="MBR-20260702-001",
        period_start=date(2026, 6, 19),
        period_end=date(2026, 7, 2),
        bill_to_type="MANDOR",
        client_id=None,
        mandor_id=7,
        client_pic_id=None,
        mandor=mandor,
        client=None,
        status="LOCKED",
        input_source=INPUT_SOURCE_MANUAL_BACKFILL,
        invoice_id=None,
        total_amount=678000,
        items=[
            _manual_item(
                source_type=MANUAL_BACKFILL_SOURCE_CATERING,
                source_id=12300001,
                description="Catering manual buku 19-06-2026 | Siang 7 | Sore 7 | Total 14 porsi",
                subtotal=210000,
            ),
            _manual_item(
                item_type=MANUAL_BACKFILL_ITEM_WARUNG,
                source_type=MANUAL_BACKFILL_SOURCE_WARUNG,
                source_id=12300002,
                description="Kasbon/hutang warung pekerja Reza",
                qty=1,
                unit_price=468000,
                subtotal=468000,
                source_date=None,
            ),
        ],
    )
    session = _FakeSession()

    monkeypatch.setattr(
        "app.services.manual_backfill_billing_service.db",
        SimpleNamespace(session=session),
    )
    monkeypatch.setattr(
        "app.services.manual_backfill_billing_service.ManualBillingBatch",
        SimpleNamespace(query=_FakeQuery(batch)),
    )
    monkeypatch.setattr(
        "app.services.manual_backfill_billing_service.Mandor",
        SimpleNamespace(query=_FakeQuery(mandor)),
    )
    monkeypatch.setattr("app.services.manual_backfill_billing_service.Invoice", FakeInvoice)
    monkeypatch.setattr("app.services.manual_backfill_billing_service.InvoiceItem", FakeInvoiceItem)
    monkeypatch.setattr(
        "app.services.manual_backfill_billing_service.generate_manual_billing_invoice_number",
        lambda invoice_date: "INV-20260706-001",
    )
    monkeypatch.setattr(
        "app.services.manual_backfill_billing_service.build_company_bank_snapshot",
        lambda branch_id: {
            "company_bank_name_snapshot": "BCA",
            "company_bank_account_number_snapshot": "123",
            "company_bank_account_name_snapshot": "Idha Boga",
        },
    )
    monkeypatch.setattr(
        "app.services.manual_backfill_billing_service.create_invoice_journal_for_invoice",
        lambda invoice, created_by, commit=False: (True, "ok", SimpleNamespace(id=333)),
    )
    monkeypatch.setattr(
        "app.services.manual_backfill_billing_service.record_audit_log",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "app.services.manual_backfill_billing_service.date",
        date,
    )

    promoted_batch, invoice = create_invoice_from_manual_backfill_batch(
        batch_id=123,
        branch_id=1,
        created_by=9,
    )

    assert promoted_batch.status == MANUAL_BACKFILL_STATUS_INVOICED
    assert promoted_batch.invoice_id == 456
    assert invoice.invoice_number == "INV-20260706-001"
    assert invoice.source_type == MANUAL_BILLING_INVOICE_SOURCE
    assert invoice.source_order_id == batch.id
    assert invoice.input_source == INPUT_SOURCE_MANUAL_BACKFILL
    assert invoice.bill_to_type == "MANDOR"
    assert invoice.client_id is None
    assert invoice.client_pic_id is None
    assert invoice.client_name_snapshot == "Pak Yatno"
    assert invoice.total_amount == 678000
    invoice_items = [obj for obj in session.added if obj.__class__.__name__ == "FakeInvoiceItem"]
    assert len(invoice_items) == 2
    assert all(item.input_source == INPUT_SOURCE_MANUAL_BACKFILL for item in invoice_items)


def test_create_invoice_from_manual_backfill_batch_rejects_unlocked_batch(monkeypatch):
    batch = SimpleNamespace(
        id=123,
        branch_id=1,
        batch_number="MBR-20260702-001",
        period_start=date(2026, 6, 19),
        period_end=date(2026, 7, 2),
        status="DRAFT",
        input_source=INPUT_SOURCE_MANUAL_BACKFILL,
        invoice_id=None,
        total_amount=210000,
        items=[_manual_item()],
    )
    monkeypatch.setattr(
        "app.services.manual_backfill_billing_service.ManualBillingBatch",
        SimpleNamespace(query=_FakeQuery(batch)),
    )

    with pytest.raises(ManualBackfillBillingError):
        create_invoice_from_manual_backfill_batch(batch_id=123, branch_id=1, created_by=9)



def test_sync_manual_backfill_batch_status_from_invoice_partial_and_paid(monkeypatch):
    from app.services.manual_backfill_billing_service import (
        MANUAL_BACKFILL_STATUS_INVOICED,
        MANUAL_BACKFILL_STATUS_PAID,
        MANUAL_BACKFILL_STATUS_PARTIALLY_PAID,
        sync_manual_backfill_batch_status_from_invoice,
    )
    from app.services.manual_billing_service import MANUAL_BILLING_INVOICE_SOURCE

    audit_events = []
    batch = SimpleNamespace(
        id=123,
        branch_id=1,
        batch_number="MBR-20260702-001",
        invoice_id=456,
        input_source=INPUT_SOURCE_MANUAL_BACKFILL,
        status=MANUAL_BACKFILL_STATUS_INVOICED,
    )
    invoice = SimpleNamespace(
        id=456,
        branch_id=1,
        invoice_number="INV-20260706-001",
        source_type=MANUAL_BILLING_INVOICE_SOURCE,
        source_order_id=123,
        input_source=INPUT_SOURCE_MANUAL_BACKFILL,
        status="PARTIAL",
        paid_amount=100000,
        remaining_amount=578000,
    )

    monkeypatch.setattr(
        "app.services.manual_backfill_billing_service.ManualBillingBatch",
        SimpleNamespace(query=_FakeQuery(batch)),
    )
    monkeypatch.setattr(
        "app.services.manual_backfill_billing_service.record_audit_log",
        lambda **kwargs: audit_events.append(kwargs),
    )

    synced = sync_manual_backfill_batch_status_from_invoice(invoice, updated_by=9)
    assert synced is batch
    assert batch.status == MANUAL_BACKFILL_STATUS_PARTIALLY_PAID
    assert audit_events[-1]["metadata"]["new_status"] == MANUAL_BACKFILL_STATUS_PARTIALLY_PAID

    invoice.status = "PAID"
    invoice.paid_amount = 678000
    invoice.remaining_amount = 0
    synced = sync_manual_backfill_batch_status_from_invoice(invoice, updated_by=9)
    assert synced is batch
    assert batch.status == MANUAL_BACKFILL_STATUS_PAID
    assert audit_events[-1]["metadata"]["new_status"] == MANUAL_BACKFILL_STATUS_PAID


def test_sync_manual_backfill_batch_status_ignores_realtime_invoice(monkeypatch):
    from app.services.manual_backfill_billing_service import sync_manual_backfill_batch_status_from_invoice
    from app.services.manual_billing_service import MANUAL_BILLING_INVOICE_SOURCE
    from app.services.billing_input_source_service import INPUT_SOURCE_REALTIME

    queried = {"called": False}

    class QueryShouldNotRun:
        def filter_by(self, **kwargs):
            queried["called"] = True
            return self
        def first(self):
            return None

    invoice = SimpleNamespace(
        id=456,
        branch_id=1,
        source_type=MANUAL_BILLING_INVOICE_SOURCE,
        source_order_id=123,
        input_source=INPUT_SOURCE_REALTIME,
        status="PAID",
        paid_amount=678000,
        remaining_amount=0,
    )
    monkeypatch.setattr(
        "app.services.manual_backfill_billing_service.ManualBillingBatch",
        SimpleNamespace(query=QueryShouldNotRun()),
    )

    assert sync_manual_backfill_batch_status_from_invoice(invoice, updated_by=9) is None
    assert queried["called"] is False



def test_manual_backfill_duplicate_guard_detects_realtime_period_invoice_overlap(monkeypatch):
    class _ManyQuery:
        def __init__(self, rows):
            self.rows = rows

        def filter_by(self, **kwargs):
            def matches(obj):
                return all(getattr(obj, key, None) == value for key, value in kwargs.items())
            return _ManyQuery([row for row in self.rows if matches(row)])

        def all(self):
            return self.rows

        def first(self):
            return self.rows[0] if self.rows else None

    conflict_invoice = SimpleNamespace(
        id=456,
        branch_id=1,
        invoice_number="INV-REALTIME-001",
        mandor_id=7,
        period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 30),
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
        items=[
            _manual_item(
                item_type=MANUAL_BACKFILL_ITEM_CATERING,
                source_type=MANUAL_BACKFILL_SOURCE_CATERING,
                source_date=date(2026, 6, 19),
            )
        ],
    )

    monkeypatch.setattr(
        "app.services.manual_backfill_billing_service.Invoice",
        SimpleNamespace(query=_ManyQuery([conflict_invoice])),
    )
    monkeypatch.setattr(
        "app.services.manual_backfill_billing_service.ManualBillingBatch",
        SimpleNamespace(query=_ManyQuery([batch])),
    )

    conflicts = collect_manual_backfill_duplicate_conflicts(batch)

    assert len(conflicts) == 1
    assert conflicts[0]["kind"] == "INVOICE"
    assert conflicts[0]["number"] == "INV-REALTIME-001"
    assert conflicts[0]["input_source"] == "REALTIME"
    assert conflicts[0]["category_label"] == "catering"


def test_manual_backfill_duplicate_guard_allows_different_category_overlap(monkeypatch):
    class _ManyQuery:
        def __init__(self, rows):
            self.rows = rows

        def filter_by(self, **kwargs):
            def matches(obj):
                return all(getattr(obj, key, None) == value for key, value in kwargs.items())
            return _ManyQuery([row for row in self.rows if matches(row)])

        def all(self):
            return self.rows

        def first(self):
            return self.rows[0] if self.rows else None

    conflict_invoice = SimpleNamespace(
        id=456,
        branch_id=1,
        invoice_number="INV-WARUNG-001",
        mandor_id=7,
        period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 30),
        source_type="MANUAL_BILLING_RECAP",
        input_source="REALTIME",
        status="DRAFT",
        items=[SimpleNamespace(item_type="WARUNG_DEBT", source_type="WORKER_DEBT")],
    )
    batch = SimpleNamespace(
        id=123,
        branch_id=1,
        batch_number="MBR-20260702-001",
        mandor_id=7,
        period_start=date(2026, 6, 19),
        period_end=date(2026, 7, 2),
        invoice_id=None,
        items=[
            _manual_item(
                item_type=MANUAL_BACKFILL_ITEM_CATERING,
                source_type=MANUAL_BACKFILL_SOURCE_CATERING,
                source_date=date(2026, 6, 19),
            )
        ],
    )

    monkeypatch.setattr(
        "app.services.manual_backfill_billing_service.Invoice",
        SimpleNamespace(query=_ManyQuery([conflict_invoice])),
    )
    monkeypatch.setattr(
        "app.services.manual_backfill_billing_service.ManualBillingBatch",
        SimpleNamespace(query=_ManyQuery([batch])),
    )

    assert collect_manual_backfill_duplicate_conflicts(batch) == []


def test_build_manual_backfill_duplicate_guard_context_exposes_detail_links_and_paid_status(monkeypatch):
    class _ManyQuery:
        def __init__(self, rows):
            self.rows = rows

        def filter_by(self, **kwargs):
            def matches(obj):
                return all(getattr(obj, key, None) == value for key, value in kwargs.items())
            return _ManyQuery([row for row in self.rows if matches(row)])

        def all(self):
            return self.rows

        def first(self):
            return self.rows[0] if self.rows else None

    conflict_invoice = SimpleNamespace(
        id=456,
        branch_id=1,
        invoice_number="INV-REALTIME-PAID",
        mandor_id=7,
        period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 30),
        source_type="PERIOD_INVOICE",
        input_source="REALTIME",
        status="PAID",
        items=[SimpleNamespace(item_type="CATERING", source_type="ORDER_DETAIL")],
    )
    conflict_batch = SimpleNamespace(
        id=789,
        branch_id=1,
        batch_number="MBR-OTHER-001",
        mandor_id=7,
        period_start=date(2026, 6, 15),
        period_end=date(2026, 7, 3),
        status="PAID",
        input_source=INPUT_SOURCE_MANUAL_BACKFILL,
        invoice_id=999,
        invoice=SimpleNamespace(invoice_number="INV-BATCH-001"),
        items=[
            _manual_item(
                item_type=MANUAL_BACKFILL_ITEM_CATERING,
                source_type=MANUAL_BACKFILL_SOURCE_CATERING,
                source_date=date(2026, 6, 20),
            )
        ],
    )
    batch = SimpleNamespace(
        id=123,
        branch_id=1,
        batch_number="MBR-20260702-001",
        mandor_id=7,
        period_start=date(2026, 6, 19),
        period_end=date(2026, 7, 2),
        status="DRAFT",
        invoice_id=None,
        items=[
            _manual_item(
                item_type=MANUAL_BACKFILL_ITEM_CATERING,
                source_type=MANUAL_BACKFILL_SOURCE_CATERING,
                source_date=date(2026, 6, 19),
            )
        ],
    )

    monkeypatch.setattr("app.services.manual_backfill_billing_service.Invoice", SimpleNamespace(query=_ManyQuery([conflict_invoice])))
    monkeypatch.setattr("app.services.manual_backfill_billing_service.ManualBillingBatch", SimpleNamespace(query=_ManyQuery([batch, conflict_batch])))

    context = build_manual_backfill_duplicate_guard_context(batch)

    assert context["has_conflicts"] is True
    assert len(context["conflicts"]) == 2
    invoice_conflict = next(conflict for conflict in context["conflicts"] if conflict["kind"] == "INVOICE")
    batch_conflict = next(conflict for conflict in context["conflicts"] if conflict["kind"] == "REKAP")
    assert invoice_conflict["invoice_id"] == 456
    assert invoice_conflict["status_label"] == "PAID"
    assert batch_conflict["batch_id"] == 789
    assert batch_conflict["invoice_id"] == 999
    assert batch_conflict["linked_invoice_number"] == "INV-BATCH-001"
    assert batch_conflict["status_label"] == "PAID"


def test_validate_manual_backfill_batch_before_invoice_rejects_duplicate_conflict(monkeypatch):
    class FakeInvoice(SimpleNamespace):
        query = SimpleNamespace(filter_by=lambda **kwargs: SimpleNamespace(first=lambda: None))

    class FakeInvoiceItem(SimpleNamespace):
        query = SimpleNamespace(filter_by=lambda **kwargs: SimpleNamespace(first=lambda: None))

    batch = SimpleNamespace(
        id=123,
        branch_id=1,
        batch_number="MBR-20260702-001",
        period_start=date(2026, 6, 19),
        period_end=date(2026, 7, 2),
        status="LOCKED",
        input_source=INPUT_SOURCE_MANUAL_BACKFILL,
        invoice_id=None,
        total_amount=210000,
        items=[
            _manual_item(
                source_type=MANUAL_BACKFILL_SOURCE_CATERING,
                source_id=12300001,
                subtotal=210000,
            )
        ],
    )

    monkeypatch.setattr("app.services.manual_backfill_billing_service.Invoice", FakeInvoice)
    monkeypatch.setattr("app.services.manual_backfill_billing_service.InvoiceItem", FakeInvoiceItem)
    monkeypatch.setattr(
        "app.services.manual_backfill_billing_service.collect_manual_backfill_duplicate_conflicts",
        lambda candidate_batch: [
            {
                "kind": "INVOICE",
                "number": "INV-REALTIME-001",
                "period": "19-06-2026 s/d 30-06-2026",
                "category_label": "catering",
            }
        ],
    )

    with pytest.raises(ManualBackfillBillingError, match="berpotensi menagih data dobel"):
        validate_manual_backfill_batch_before_invoice(batch)


def test_create_manual_backfill_batch_allows_free_kelompok_without_mandor_or_pic(monkeypatch):
    session = _FakeSession()

    monkeypatch.setattr(
        "app.services.manual_backfill_billing_service.db",
        SimpleNamespace(session=session),
    )
    monkeypatch.setattr(
        "app.services.manual_backfill_billing_service.generate_manual_billing_number",
        lambda period_end: "MBR-20260702-002",
    )
    monkeypatch.setattr(
        "app.services.manual_backfill_billing_service.record_audit_log",
        lambda **kwargs: None,
    )

    catering_rows = build_catering_backfill_rows(["2026-06-19"], ["7"], ["7"], ["15000"])
    batch = create_manual_backfill_batch(
        branch_id=1,
        bill_to_type="KELOMPOK",
        bill_to_name_snapshot="Kelompok Pak Yatno",
        bill_to_phone_snapshot="0812",
        bill_to_address_snapshot="Mess proyek",
        bill_to_notes="Tidak ada master mandor",
        period_start=date(2026, 6, 19),
        period_end=date(2026, 7, 2),
        catering_rows=catering_rows,
        created_by=9,
    )

    assert batch.bill_to_type == "KELOMPOK"
    assert batch.bill_to_name_snapshot == "Kelompok Pak Yatno"
    assert batch.bill_to_phone_snapshot == "0812"
    assert batch.bill_to_address_snapshot == "Mess proyek"
    assert batch.bill_to_notes == "Tidak ada master mandor"
    assert batch.mandor_id is None
    assert batch.client_id is None
    assert batch.client_pic_id is None
    assert batch.input_source == INPUT_SOURCE_MANUAL_BACKFILL


def test_create_manual_backfill_batch_allows_client_existing_without_pic(monkeypatch):
    client = SimpleNamespace(id=44, name="PT Contoh Client", phone="0813", address="Palembang", is_active=True)
    session = _FakeSession()

    monkeypatch.setattr(
        "app.services.manual_backfill_billing_service.db",
        SimpleNamespace(session=session),
    )
    monkeypatch.setattr(
        "app.services.manual_backfill_billing_service.Client",
        SimpleNamespace(query=_FakeQuery(client)),
    )
    monkeypatch.setattr(
        "app.services.manual_backfill_billing_service.generate_manual_billing_number",
        lambda period_end: "MBR-20260702-003",
    )
    monkeypatch.setattr(
        "app.services.manual_backfill_billing_service.record_audit_log",
        lambda **kwargs: None,
    )

    warung_rows = build_warung_backfill_rows(["Reza"], ["468000"])
    batch = create_manual_backfill_batch(
        branch_id=1,
        bill_to_type="CLIENT_EXISTING",
        client_id=44,
        period_start=date(2026, 6, 19),
        period_end=date(2026, 7, 2),
        warung_rows=warung_rows,
        created_by=9,
    )

    assert batch.bill_to_type == "CLIENT_EXISTING"
    assert batch.client_id == 44
    assert batch.mandor_id is None
    assert batch.client_pic_id is None
    assert batch.bill_to_name_snapshot == "PT Contoh Client"
    assert batch.bill_to_phone_snapshot == "0813"
    assert batch.bill_to_address_snapshot == "Palembang"


def test_create_invoice_from_free_perorangan_backfill_uses_snapshot_without_master_party(monkeypatch):
    from app.services.manual_backfill_billing_service import MANUAL_BACKFILL_STATUS_INVOICED
    from app.services.manual_billing_service import MANUAL_BILLING_INVOICE_SOURCE

    class FakeInvoice(SimpleNamespace):
        query = SimpleNamespace(filter_by=lambda **kwargs: SimpleNamespace(first=lambda: None))

        def __init__(self, **kwargs):
            super().__init__(**kwargs)

    class FakeInvoiceItem(SimpleNamespace):
        query = SimpleNamespace(filter_by=lambda **kwargs: SimpleNamespace(first=lambda: None))

        def __init__(self, **kwargs):
            super().__init__(**kwargs)

    batch = SimpleNamespace(
        id=123,
        branch_id=1,
        batch_number="MBR-20260702-004",
        period_start=date(2026, 6, 19),
        period_end=date(2026, 7, 2),
        bill_to_type="PERORANGAN",
        bill_to_name_snapshot="Budi Pribadi",
        bill_to_phone_snapshot="0814",
        bill_to_address_snapshot="Palembang",
        bill_to_notes="Tagihan pribadi dari buku",
        client_id=None,
        mandor_id=None,
        client_pic_id=None,
        mandor=None,
        client=None,
        status="LOCKED",
        input_source=INPUT_SOURCE_MANUAL_BACKFILL,
        invoice_id=None,
        total_amount=210000,
        items=[
            _manual_item(
                source_type=MANUAL_BACKFILL_SOURCE_CATERING,
                source_id=12300001,
                description="Catering manual buku 19-06-2026 | Siang 7 | Sore 7 | Total 14 porsi",
                subtotal=210000,
            ),
        ],
    )
    session = _FakeSession()

    monkeypatch.setattr("app.services.manual_backfill_billing_service.db", SimpleNamespace(session=session))
    monkeypatch.setattr("app.services.manual_backfill_billing_service.ManualBillingBatch", SimpleNamespace(query=_FakeQuery(batch)))
    monkeypatch.setattr("app.services.manual_backfill_billing_service.Invoice", FakeInvoice)
    monkeypatch.setattr("app.services.manual_backfill_billing_service.InvoiceItem", FakeInvoiceItem)
    monkeypatch.setattr(
        "app.services.manual_backfill_billing_service.generate_manual_billing_invoice_number",
        lambda invoice_date: "INV-20260706-002",
    )
    monkeypatch.setattr(
        "app.services.manual_backfill_billing_service.build_company_bank_snapshot",
        lambda branch_id: {
            "company_bank_name_snapshot": "BCA",
            "company_bank_account_number_snapshot": "123",
            "company_bank_account_name_snapshot": "Idha Boga",
        },
    )
    monkeypatch.setattr(
        "app.services.manual_backfill_billing_service.create_invoice_journal_for_invoice",
        lambda invoice, created_by, commit=False: (True, "ok", SimpleNamespace(id=333)),
    )
    monkeypatch.setattr("app.services.manual_backfill_billing_service.record_audit_log", lambda **kwargs: None)
    monkeypatch.setattr("app.services.manual_backfill_billing_service.date", date)

    promoted_batch, invoice = create_invoice_from_manual_backfill_batch(batch_id=123, branch_id=1, created_by=9)

    assert promoted_batch.status == MANUAL_BACKFILL_STATUS_INVOICED
    assert promoted_batch.invoice_id == 456
    assert invoice.source_type == MANUAL_BILLING_INVOICE_SOURCE
    assert invoice.input_source == INPUT_SOURCE_MANUAL_BACKFILL
    assert invoice.bill_to_type == "PERORANGAN"
    assert invoice.client_id is None
    assert invoice.mandor_id is None
    assert invoice.client_pic_id is None
    assert invoice.client_name_snapshot == "Budi Pribadi"
    assert invoice.client_pic_phone_snapshot == "0814"
    assert "Budi Pribadi" in invoice.notes
    assert "Perorangan" in invoice.notes


def test_manual_backfill_duplicate_guard_matches_free_party_name_type_period_branch_and_category(monkeypatch):
    class _ManyQuery:
        def __init__(self, rows):
            self.rows = rows

        def filter_by(self, **kwargs):
            def matches(obj):
                return all(getattr(obj, key, None) == value for key, value in kwargs.items())
            return _ManyQuery([row for row in self.rows if matches(row)])

        def all(self):
            return self.rows

        def first(self):
            return self.rows[0] if self.rows else None

    conflict_invoice = SimpleNamespace(
        id=456,
        branch_id=1,
        invoice_number="INV-KEL-001",
        bill_to_type="KELOMPOK",
        client_name_snapshot="Kelompok Pak Yatno",
        mandor_id=None,
        client_id=None,
        period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 30),
        source_type="PERIOD_INVOICE",
        input_source=INPUT_SOURCE_MANUAL_BACKFILL,
        status="DRAFT",
        items=[SimpleNamespace(item_type="CATERING", source_type="MANUAL_BOOK_CATERING")],
    )
    different_party_invoice = SimpleNamespace(
        id=457,
        branch_id=1,
        invoice_number="INV-KEL-002",
        bill_to_type="KELOMPOK",
        client_name_snapshot="Kelompok Lain",
        mandor_id=None,
        client_id=None,
        period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 30),
        source_type="PERIOD_INVOICE",
        input_source=INPUT_SOURCE_MANUAL_BACKFILL,
        status="DRAFT",
        items=[SimpleNamespace(item_type="CATERING", source_type="MANUAL_BOOK_CATERING")],
    )
    batch = SimpleNamespace(
        id=123,
        branch_id=1,
        batch_number="MBR-20260702-005",
        bill_to_type="KELOMPOK",
        bill_to_name_snapshot="  kelompok   pak yatno ",
        mandor_id=None,
        client_id=None,
        period_start=date(2026, 6, 19),
        period_end=date(2026, 7, 2),
        invoice_id=None,
        items=[_manual_item(item_type=MANUAL_BACKFILL_ITEM_CATERING, source_type=MANUAL_BACKFILL_SOURCE_CATERING)],
    )

    monkeypatch.setattr(
        "app.services.manual_backfill_billing_service.Invoice",
        SimpleNamespace(query=_ManyQuery([conflict_invoice, different_party_invoice])),
    )
    monkeypatch.setattr(
        "app.services.manual_backfill_billing_service.ManualBillingBatch",
        SimpleNamespace(query=_ManyQuery([batch])),
    )

    conflicts = collect_manual_backfill_duplicate_conflicts(batch)

    assert len(conflicts) == 1
    assert conflicts[0]["kind"] == "INVOICE"
    assert conflicts[0]["number"] == "INV-KEL-001"
    assert conflicts[0]["category_label"] == "catering"


def test_build_manual_backfill_register_summary_tracks_active_ready_receivable_paid_and_void():
    batches = [
        SimpleNamespace(status="DRAFT", total_amount=100000, invoice_id=None),
        SimpleNamespace(status="LOCKED", total_amount=200000, invoice_id=None),
        SimpleNamespace(status="INVOICED", total_amount=300000, invoice_id=1),
        SimpleNamespace(status="PARTIALLY_PAID", total_amount=400000, invoice_id=2),
        SimpleNamespace(status="PAID", total_amount=500000, invoice_id=3),
        SimpleNamespace(status="VOID", total_amount=600000, invoice_id=None),
    ]

    summary = build_manual_backfill_register_summary(batches)

    assert summary["total_count"] == 6
    assert summary["total_amount"] == 2100000
    assert summary["active_total_amount"] == 1500000
    assert summary["draft_count"] == 1
    assert summary["locked_count"] == 1
    assert summary["invoice_ready_count"] == 1
    assert summary["receivable_count"] == 2
    assert summary["paid_count"] == 1
    assert summary["void_count"] == 1



def test_build_manual_backfill_print_context_splits_catering_warung_and_payment_summary():
    invoice = SimpleNamespace(
        invoice_number="INV-MBR-001",
        status="PARTIALLY_PAID",
        paid_amount=250000,
        remaining_amount=428000,
    )
    batch = SimpleNamespace(
        id=123,
        batch_number="MBR-20260702-001",
        bill_to_type="KELOMPOK",
        bill_to_name_snapshot="Kelompok Pak Yatno",
        bill_to_phone_snapshot="0812",
        bill_to_address_snapshot="Mess APG",
        bill_to_notes="Input dari buku lama",
        mandor_id=None,
        client_id=None,
        period_start=date(2026, 6, 19),
        period_end=date(2026, 7, 2),
        status="PARTIALLY_PAID",
        total_amount=678000,
        invoice=invoice,
        items=[
            _manual_item(source_date=date(2026, 6, 20), subtotal=210000, source_label="20 Juni"),
            _manual_item(
                item_type=MANUAL_BACKFILL_ITEM_WARUNG,
                qty=1,
                unit_price=468000,
                subtotal=468000,
                description="Kasbon Reza",
                source_date=None,
                source_label="Reza",
            ),
        ],
    )

    context = build_manual_backfill_print_context(batch)

    assert context["bill_to_context"]["name"] == "Kelompok Pak Yatno"
    assert context["status_context"]["label"] == "Dibayar Sebagian"
    assert context["summary"]["item_count"] == 2
    assert context["summary"]["catering_total"] == 210000
    assert context["summary"]["warung_total"] == 468000
    assert context["summary"]["grand_total"] == 678000
    assert len(context["catering_rows"]) == 1
    assert len(context["warung_rows"]) == 1
    assert context["payment_summary"]["invoice_number"] == "INV-MBR-001"
    assert context["payment_summary"]["paid_amount"] == 250000
    assert context["payment_summary"]["remaining_amount"] == 428000



def test_validate_manual_backfill_before_invoice_rejects_future_period():
    batch = SimpleNamespace(
        id=123,
        branch_id=1,
        batch_number="MBR-FUTURE-001",
        period_start=date(2026, 7, 7),
        period_end=date(2026, 7, 8),
        status="LOCKED",
        input_source=INPUT_SOURCE_MANUAL_BACKFILL,
        invoice_id=None,
        total_amount=210000,
        items=[_manual_item(source_date=date(2026, 7, 7), source_id=12300001)],
    )

    with pytest.raises(ManualBackfillBillingError, match="belum selesai"):
        validate_manual_backfill_batch_before_invoice(batch, invoice_date=date(2026, 7, 6))


def test_validate_manual_backfill_before_invoice_rejects_duplicate_catering_dates_in_existing_batch(monkeypatch):
    class FakeInvoice(SimpleNamespace):
        query = SimpleNamespace(filter_by=lambda **kwargs: SimpleNamespace(first=lambda: None))

    class FakeInvoiceItem(SimpleNamespace):
        query = SimpleNamespace(filter_by=lambda **kwargs: SimpleNamespace(first=lambda: None))

    batch = SimpleNamespace(
        id=123,
        branch_id=1,
        batch_number="MBR-DUP-001",
        period_start=date(2026, 6, 19),
        period_end=date(2026, 7, 2),
        bill_to_type="KELOMPOK",
        bill_to_name_snapshot="Kelompok Pak Yatno",
        mandor_id=None,
        client_id=None,
        status="LOCKED",
        input_source=INPUT_SOURCE_MANUAL_BACKFILL,
        invoice_id=None,
        total_amount=420000,
        items=[
            _manual_item(source_date=date(2026, 6, 19), source_id=12300001, subtotal=210000),
            _manual_item(source_date=date(2026, 6, 19), source_id=12300002, subtotal=210000),
        ],
    )

    monkeypatch.setattr("app.services.manual_backfill_billing_service.Invoice", FakeInvoice)
    monkeypatch.setattr("app.services.manual_backfill_billing_service.InvoiceItem", FakeInvoiceItem)
    monkeypatch.setattr(
        "app.services.manual_backfill_billing_service.assert_no_manual_backfill_duplicate_conflicts",
        lambda candidate_batch: None,
    )

    with pytest.raises(ManualBackfillBillingError, match="Tanggal catering baris 2 dobel"):
        validate_manual_backfill_batch_before_invoice(batch, invoice_date=date(2026, 7, 6))


def test_validate_manual_backfill_invoice_consistency_accepts_matching_snapshot_totals():
    batch = SimpleNamespace(
        id=123,
        branch_id=1,
        period_start=date(2026, 6, 19),
        period_end=date(2026, 7, 2),
        total_amount=678000,
        items=[
            _manual_item(source_type=MANUAL_BACKFILL_SOURCE_CATERING, source_id=12300001, subtotal=210000),
            _manual_item(
                item_type=MANUAL_BACKFILL_ITEM_WARUNG,
                source_type=MANUAL_BACKFILL_SOURCE_WARUNG,
                source_id=12300002,
                source_date=None,
                qty=1,
                unit_price=468000,
                subtotal=468000,
            ),
        ],
    )
    invoice = SimpleNamespace(
        id=456,
        branch_id=1,
        source_type="MANUAL_BILLING_RECAP",
        source_order_id=123,
        input_source=INPUT_SOURCE_MANUAL_BACKFILL,
        period_start=date(2026, 6, 19),
        period_end=date(2026, 7, 2),
        client_name_snapshot="Kelompok Pak Yatno",
        total_amount=678000,
        paid_amount=0,
        remaining_amount=678000,
    )
    invoice_items = [
        SimpleNamespace(
            qty=14,
            unit_price=15000,
            subtotal=210000,
            input_source=INPUT_SOURCE_MANUAL_BACKFILL,
            source_type=MANUAL_BACKFILL_SOURCE_CATERING,
            source_id=12300001,
        ),
        SimpleNamespace(
            qty=1,
            unit_price=468000,
            subtotal=468000,
            input_source=INPUT_SOURCE_MANUAL_BACKFILL,
            source_type=MANUAL_BACKFILL_SOURCE_WARUNG,
            source_id=12300002,
        ),
    ]

    result = validate_manual_backfill_invoice_consistency(batch, invoice, invoice_items=invoice_items)

    assert result["invoice_item_count"] == 2
    assert result["invoice_item_total"] == 678000
    assert result["remaining_amount"] == 678000


def test_validate_manual_backfill_invoice_consistency_rejects_total_mismatch():
    batch = SimpleNamespace(
        id=123,
        branch_id=1,
        period_start=date(2026, 6, 19),
        period_end=date(2026, 7, 2),
        total_amount=210000,
        items=[_manual_item(source_type=MANUAL_BACKFILL_SOURCE_CATERING, source_id=12300001, subtotal=210000)],
    )
    invoice = SimpleNamespace(
        id=456,
        branch_id=1,
        source_type="MANUAL_BILLING_RECAP",
        source_order_id=123,
        input_source=INPUT_SOURCE_MANUAL_BACKFILL,
        period_start=date(2026, 6, 19),
        period_end=date(2026, 7, 2),
        client_name_snapshot="Kelompok Pak Yatno",
        total_amount=210000,
        paid_amount=0,
        remaining_amount=210000,
    )
    invoice_items = [
        SimpleNamespace(
            qty=14,
            unit_price=15000,
            subtotal=200000,
            input_source=INPUT_SOURCE_MANUAL_BACKFILL,
            source_type=MANUAL_BACKFILL_SOURCE_CATERING,
            source_id=12300001,
        )
    ]

    with pytest.raises(ManualBackfillBillingError, match="Total rincian invoice"):
        validate_manual_backfill_invoice_consistency(batch, invoice, invoice_items=invoice_items)
