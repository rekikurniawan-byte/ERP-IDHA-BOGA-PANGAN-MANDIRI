import os
from datetime import date
from types import SimpleNamespace

os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://localhost/test_db")
os.environ.setdefault("APP_ENV", "testing")

from app.services import advance_service as target


class _FakeSession:
    def add(self, obj):
        return None

    def flush(self):
        return None

    def commit(self):
        return None


class _FakeAdvanceSettlement:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
        self.id = kwargs.get("id", 501)
        self.journal_id = kwargs.get("journal_id")


class _FakeJournal:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
        self.id = kwargs.get("id", 601)


def test_create_advance_settlement_creates_field_trace_for_linked_mandor_advance(monkeypatch):
    trace_calls = []

    monkeypatch.setattr(target, "is_advance_schema_ready", lambda: True)
    monkeypatch.setattr(
        target,
        "resolve_settlement_reference",
        lambda branch_id, settlement_type, reference_id: (
            {
                "advance_type": target.MANDOR_OPERATIONAL_ADVANCE,
                "reference_type": "MANDOR_EXPENSE_PROOF",
            },
            None,
        ),
    )
    monkeypatch.setattr(target, "get_account_by_code", lambda code: SimpleNamespace(id=100, account_code=code))
    monkeypatch.setattr(target, "generate_settlement_number", lambda settlement_date: "ADVS-TEST-001")
    monkeypatch.setattr(target, "generate_journal_number", lambda journal_date: "JRN-TEST-001")
    monkeypatch.setattr(
        target,
        "find_field_transaction_linked_source",
        lambda *args, **kwargs: SimpleNamespace(
            field_transaction=SimpleNamespace(id=31, branch_id=1, evidence_status="VERIFIED")
        ),
    )
    monkeypatch.setattr(
        target,
        "create_system_linked_field_transaction",
        lambda **kwargs: trace_calls.append(kwargs) or (True, "ok", SimpleNamespace(notes="trace note")),
    )
    monkeypatch.setattr(target, "record_audit_log", lambda **kwargs: None)
    monkeypatch.setattr(target, "AdvanceSettlement", _FakeAdvanceSettlement)
    monkeypatch.setattr(target, "Journal", _FakeJournal)
    monkeypatch.setattr(target, "JournalDetail", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(target, "db", SimpleNamespace(session=_FakeSession()))

    advance = SimpleNamespace(
        id=41,
        branch_id=1,
        advance_type=target.MANDOR_OPERATIONAL_ADVANCE,
        status="OPEN",
        remaining_amount=150000,
        amount=150000,
        settled_amount=0,
        advance_date=date(2026, 7, 1),
        advance_number="ADV-TEST-001",
    )

    ok, message, settlement = target.create_advance_settlement(
        advance,
        settlement_date=date(2026, 7, 3),
        settlement_type="MANDOR_EXPENSE_PROOF",
        amount=150000,
        created_by=7,
        reference_id=None,
        expense_account_code="5008",
        notes="expense proof lengkap",
        commit=True,
    )

    assert ok is True
    assert "berhasil dibuat" in message
    assert settlement.settlement_number == "ADVS-TEST-001"
    assert settlement.journal_id == 601
    assert advance.status == "SETTLED"
    assert advance.remaining_amount == 0
    assert trace_calls[0]["business_event_type"] == "MANDOR_ADVANCE_SETTLEMENT"
    assert trace_calls[0]["payment_status"] == "PAID"
    assert settlement.notes.startswith("[5008 Biaya Administrasi]")


def test_create_advance_settlement_skips_field_trace_for_non_mandor_advance(monkeypatch):
    trace_calls = []

    invoice = SimpleNamespace(
        remaining_amount=200000,
        total_amount=200000,
        paid_amount=0,
        status="OPEN",
        invoice_number="INV-TEST-001",
    )

    monkeypatch.setattr(target, "is_advance_schema_ready", lambda: True)
    monkeypatch.setattr(
        target,
        "resolve_settlement_reference",
        lambda branch_id, settlement_type, reference_id: (
            {
                "advance_type": target.CLIENT_DP_RECEIVED,
                "reference_type": "INVOICE",
            },
            invoice,
        ),
    )
    monkeypatch.setattr(target, "get_account_by_code", lambda code: SimpleNamespace(id=100, account_code=code))
    monkeypatch.setattr(target, "generate_settlement_number", lambda settlement_date: "ADVS-TEST-002")
    monkeypatch.setattr(target, "generate_journal_number", lambda journal_date: "JRN-TEST-001")
    monkeypatch.setattr(
        target,
        "find_field_transaction_linked_source",
        lambda *args, **kwargs: SimpleNamespace(
            field_transaction=SimpleNamespace(id=32, branch_id=1, evidence_status="VERIFIED")
        ),
    )
    monkeypatch.setattr(
        target,
        "create_system_linked_field_transaction",
        lambda **kwargs: trace_calls.append(kwargs) or (True, "ok", SimpleNamespace(notes="trace note")),
    )
    monkeypatch.setattr(target, "record_audit_log", lambda **kwargs: None)
    monkeypatch.setattr(target, "AdvanceSettlement", _FakeAdvanceSettlement)
    monkeypatch.setattr(target, "Journal", _FakeJournal)
    monkeypatch.setattr(target, "JournalDetail", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(target, "db", SimpleNamespace(session=_FakeSession()))

    advance = SimpleNamespace(
        id=42,
        branch_id=1,
        advance_type=target.CLIENT_DP_RECEIVED,
        status="OPEN",
        remaining_amount=200000,
        amount=200000,
        settled_amount=0,
        advance_date=date(2026, 7, 1),
        advance_number="ADV-TEST-002",
    )

    ok, message, settlement = target.create_advance_settlement(
        advance,
        settlement_date=date(2026, 7, 3),
        settlement_type="CLIENT_INVOICE",
        amount=100000,
        created_by=7,
        reference_id=77,
        notes="pakai DP client",
        commit=True,
    )

    assert ok is True
    assert "berhasil dibuat" in message
    assert settlement.journal_id == 601
    assert advance.status == "PARTIAL"
    assert advance.remaining_amount == 100000
    assert invoice.status == "PARTIAL"
    assert trace_calls == []
