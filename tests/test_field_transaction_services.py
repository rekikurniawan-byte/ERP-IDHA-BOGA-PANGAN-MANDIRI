import os
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://localhost/test_db")
os.environ.setdefault("APP_ENV", "testing")

from app.services.field_transaction_monitoring_service import build_field_transaction_monitoring
from app.services.field_transaction_posting_service import (
    FieldTransactionPostingError,
    _ensure_field_transaction_can_post,
)
from app.services.field_transaction_service import (
    FieldTransactionValidationError,
    attach_existing_digital_attachment_to_field_transaction,
    create_field_transaction,
    update_field_transaction_draft,
    update_field_transaction_review_status,
    verify_field_transaction_attachment,
)
from app.services.field_transaction_settlement_service import (
    record_manual_payable_payment,
    record_manual_receivable_payment,
)
from app.services.field_transaction_policy_service import (
    FieldTransactionPolicyError,
    list_field_transaction_event_choices,
    resolve_event_account_map,
    resolve_policy_defaults,
    validate_field_transaction_event_payload,
)
from app.services.business_logic_guard_service import decimal_money
from app.services.field_transaction_bridge_service import (
    FieldTransactionBridgeError,
    _ensure_not_already_posted_or_bridged,
)
from app.routes.field_transaction_routes import _parse_date, _resolve_document_link_target


def test_resolve_policy_defaults_for_direct_income_event():
    defaults = resolve_policy_defaults("CATERING_DAILY_CASH_SALE")

    assert defaults["transaction_direction"] == "IN"
    assert defaults["payment_status"] == "PAID"
    assert defaults["review_status"] == "WAITING_CLASSIFICATION"
    assert defaults["evidence_status"] == "PENDING"
    assert defaults["supports_auto_post"] is True


def test_validate_field_transaction_event_payload_requires_bank_for_transfer():
    with pytest.raises(FieldTransactionPolicyError) as exc:
        validate_field_transaction_event_payload(
            event_type="SITE_OPERATION_EXPENSE",
            transaction_direction="OUT",
            amount=150000,
            payment_status="PAID",
            payment_method="TRANSFER",
            bank_account_id=None,
            counterparty_id=None,
            party_snapshot_name="Vendor Site",
        )

    assert "wajib memilih rekening bank" in str(exc.value)


def test_decimal_money_accepts_indonesia_thousand_separator():
    assert decimal_money("1.000.000") == Decimal("1000000.00")


def test_list_field_transaction_event_choices_ui_ready_only_hides_partial_events():
    rows = list_field_transaction_event_choices(ui_ready_only=True)
    values = {row["value"] for row in rows}

    assert "MANUAL_RECEIVABLE_PAYMENT" not in values
    assert "VENDOR_PAYABLE_PAYMENT" not in values
    assert "MANDOR_ADVANCE_SETTLEMENT" not in values
    assert "OWNER_CASH_INJECTION" in values


def test_resolve_event_account_map_uses_bank_account_mapping():
    mapped_bank = SimpleNamespace(coa_account_code="1003")

    result = resolve_event_account_map(
        event_type="OTHER_OPERATING_INCOME",
        payment_method="TRANSFER",
        bank_account=mapped_bank,
    )

    assert result["debit_account_code"] == "1003"
    assert result["credit_account_code"] == "4004"


class _FakeQueryResult:
    def __init__(self, rows):
        self.rows = rows

    def order_by(self, *args, **kwargs):
        return self

    def all(self):
        return list(self.rows)


class _FakeQueryManager:
    def __init__(self, rows):
        self.rows = rows

    def filter_by(self, **kwargs):
        branch_id = kwargs.get("branch_id")
        filtered = [row for row in self.rows if getattr(row, "branch_id", None) == branch_id]
        return _FakeQueryResult(filtered)


class _FakeColumn:
    def desc(self):
        return self

    def __eq__(self, other):
        return self

    def in_(self, other):
        return self


def test_monitoring_detects_pending_mismatch_and_manual_doc_gap(monkeypatch):
    transaction_pending = SimpleNamespace(
        id=1,
        branch_id=1,
        transaction_number="FTX-1",
        transaction_date=None,
        amount=100000,
        review_status="WAITING_CLASSIFICATION",
        posting_status="NOT_POSTED",
        needs_follow_up=False,
        business_event_type="SITE_OPERATION_EXPENSE",
        links=[],
    )
    transaction_posted_mismatch = SimpleNamespace(
        id=2,
        branch_id=1,
        transaction_number="FTX-2",
        transaction_date=None,
        amount=200000,
        review_status="POSTED",
        posting_status="POSTED",
        needs_follow_up=True,
        business_event_type="OTHER_OPERATING_INCOME",
        links=[],
    )
    transaction_receivable_gap = SimpleNamespace(
        id=3,
        branch_id=1,
        transaction_number="FTX-3",
        transaction_date=None,
        amount=300000,
        review_status="WAITING_CLASSIFICATION",
        posting_status="NOT_POSTED",
        needs_follow_up=True,
        business_event_type="MANUAL_RECEIVABLE_CREATED",
        links=[],
    )
    transaction_bridge_candidate = SimpleNamespace(
        id=4,
        branch_id=1,
        transaction_number="FTX-4",
        transaction_date=None,
        amount=400000,
        review_status="WAITING_CLASSIFICATION",
        posting_status="NOT_POSTED",
        needs_follow_up=False,
        business_event_type="FUEL_EXPENSE",
        links=[],
    )

    receivable_open = SimpleNamespace(
        id=10,
        branch_id=1,
        field_transaction_id=3,
        receivable_number="MREC-1",
        party_name="Mandor A",
        due_date=SimpleNamespace(strftime=lambda fmt: "01-01-2026"),
        remaining_amount=150000,
        status="OPEN",
    )
    payable_open = SimpleNamespace(
        id=20,
        branch_id=1,
        field_transaction_id=4,
        payable_number="MPAY-1",
        party_name="Vendor B",
        due_date=SimpleNamespace(strftime=lambda fmt: "01-01-2026"),
        remaining_amount=175000,
        status="PARTIAL",
    )

    monkeypatch.setattr(
        "app.services.field_transaction_monitoring_service.FieldTransaction",
        SimpleNamespace(
            query=_FakeQueryManager([
                transaction_pending,
                transaction_posted_mismatch,
                transaction_receivable_gap,
                transaction_bridge_candidate,
            ]),
            transaction_date=_FakeColumn(),
            id=_FakeColumn(),
        ),
    )
    monkeypatch.setattr(
        "app.services.field_transaction_monitoring_service.ManualReceivable",
        SimpleNamespace(
            query=_FakeQueryManager([receivable_open]),
            receivable_date=_FakeColumn(),
            id=_FakeColumn(),
        ),
    )
    monkeypatch.setattr(
        "app.services.field_transaction_monitoring_service.ManualPayable",
        SimpleNamespace(
            query=_FakeQueryManager([payable_open]),
            payable_date=_FakeColumn(),
            id=_FakeColumn(),
        ),
    )
    monkeypatch.setattr(
        "app.services.field_transaction_monitoring_service.find_manual_billing_invoice_for_source",
        lambda source_type, source_id: None,
    )

    data = build_field_transaction_monitoring(1)

    assert data["summary"]["pending_review_count"] == 3
    assert data["summary"]["open_receivable_count"] == 1
    assert data["summary"]["open_payable_count"] == 1
    assert data["summary"]["mismatch_count"] == 1
    assert data["summary"]["manual_doc_gap_count"] == 1
    assert data["summary"]["bridge_candidate_count"] == 2


class _FakeFirstQuery:
    def __init__(self, result=None):
        self.result = result

    def filter_by(self, **kwargs):
        return self

    def first(self):
        return self.result


class _FakeCountQuery:
    def __init__(self, count_value):
        self.count_value = count_value

    def filter_by(self, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return None

    def count(self):
        return self.count_value


class _FakeAtomicContext:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeLookupQuery:
    def __init__(self, results):
        self.results = results
        self.current = None

    def filter_by(self, **kwargs):
        self.current = self.results.get(tuple(sorted(kwargs.items())))
        return self

    def first(self):
        return self.current


class _FakeReviewLog:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _FakeAttachmentLink:
    query = None

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
        self.id = kwargs.get("id", 501)
        self.field_transaction = None
        self.digital_attachment = None


class _FakeManualReceivablePayment:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
        self.id = kwargs.get("id", 701)


class _FakeManualPayablePayment:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
        self.id = kwargs.get("id", 801)


def test_ensure_field_transaction_can_post_rejects_non_ready_status():
    transaction = SimpleNamespace(
        id=11,
        branch_id=1,
        business_event_type="OTHER_OPERATING_INCOME",
        review_status="WAITING_CLASSIFICATION",
        posting_status="NOT_POSTED",
        amount=100000,
        payment_method="CASH",
    )

    with pytest.raises(FieldTransactionPostingError) as exc:
        _ensure_field_transaction_can_post(transaction)

    assert "READY_TO_POST" in str(exc.value)


def test_ensure_field_transaction_can_post_detects_half_posted_state(monkeypatch):
    transaction = SimpleNamespace(
        id=12,
        branch_id=1,
        business_event_type="OTHER_OPERATING_INCOME",
        review_status="POSTED",
        posting_status="POSTED",
        amount=100000,
        payment_method="CASH",
    )

    monkeypatch.setattr(
        "app.services.field_transaction_posting_service.Journal",
        SimpleNamespace(query=_FakeFirstQuery(result=SimpleNamespace(id=1))),
    )
    monkeypatch.setattr(
        "app.services.field_transaction_posting_service.CashBankTransaction",
        SimpleNamespace(query=_FakeFirstQuery(result=None)),
    )

    with pytest.raises(FieldTransactionPostingError) as exc:
        _ensure_field_transaction_can_post(transaction)

    assert "tidak lengkap" in str(exc.value)


def test_bridge_guard_rejects_posted_transaction():
    transaction = SimpleNamespace(
        id=21,
        posting_status="POSTED",
    )

    with pytest.raises(FieldTransactionBridgeError) as exc:
        _ensure_not_already_posted_or_bridged(transaction, "OPERATIONAL_EXPENSE")

    assert "sudah diposting" in str(exc.value)


def test_bridge_guard_rejects_when_financial_trace_exists(monkeypatch):
    transaction = SimpleNamespace(
        id=22,
        posting_status="NOT_POSTED",
    )

    monkeypatch.setattr(
        "app.services.field_transaction_bridge_service.FieldTransactionLink",
        SimpleNamespace(
            query=_FakeCountQuery(count_value=1),
            field_transaction_id=_FakeColumn(),
            link_role=_FakeColumn(),
        ),
    )

    with pytest.raises(FieldTransactionBridgeError) as exc:
        _ensure_not_already_posted_or_bridged(transaction, "TRANSPORT_EXPENSE")

    assert "jejak ledger/journal" in str(exc.value)


def test_attach_existing_digital_attachment_updates_evidence_and_review(monkeypatch):
    added_rows = []
    transaction = SimpleNamespace(
        id=31,
        branch_id=1,
        transaction_number="FTX-20260703-0031",
        review_status="WAITING_EVIDENCE",
        evidence_status="PENDING",
        attachments=[],
    )
    digital_attachment = SimpleNamespace(
        id=88,
        branch_id=1,
        is_deleted=False,
        original_filename="bukti-site.pdf",
    )
    attachment_query = _FakeLookupQuery({
        tuple(sorted({"field_transaction_id": 31, "digital_attachment_id": 88}.items())): None,
    })
    digital_query = _FakeLookupQuery({
        tuple(sorted({"id": 88, "is_deleted": False}.items())): digital_attachment,
    })

    class _FakeSession:
        def add(self, obj):
            added_rows.append(obj)
            if isinstance(obj, _FakeAttachmentLink):
                obj.field_transaction = transaction
                obj.digital_attachment = digital_attachment
                transaction.attachments.append(obj)

        def commit(self):
            return None

    _FakeAttachmentLink.query = attachment_query
    monkeypatch.setattr(
        "app.services.field_transaction_service.DigitalAttachment",
        SimpleNamespace(query=digital_query),
    )
    monkeypatch.setattr(
        "app.services.field_transaction_service.FieldTransactionAttachment",
        _FakeAttachmentLink,
    )
    monkeypatch.setattr(
        "app.services.field_transaction_service.FieldTransactionReviewLog",
        _FakeReviewLog,
    )
    monkeypatch.setattr(
        "app.services.field_transaction_service.atomic_business_action",
        lambda **kwargs: _FakeAtomicContext(),
    )
    monkeypatch.setattr(
        "app.services.field_transaction_service.record_audit_log",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "app.services.field_transaction_service.db",
        SimpleNamespace(session=_FakeSession()),
    )

    ok, message, attachment_link = attach_existing_digital_attachment_to_field_transaction(
        transaction,
        digital_attachment_id=88,
        created_by=7,
        attachment_role="EVIDENCE",
        notes="nota lapangan",
        commit=True,
    )

    assert ok is True
    assert "berhasil ditautkan" in message
    assert attachment_link.status == "ATTACHED"
    assert transaction.evidence_status == "ATTACHED"
    assert transaction.review_status == "WAITING_CLASSIFICATION"


def test_verify_field_transaction_attachment_marks_transaction_verified(monkeypatch):
    added_rows = []
    attachment_link = SimpleNamespace(
        id=901,
        status="ATTACHED",
        verified_at=None,
        verified_by=None,
        notes=None,
        digital_attachment_id=88,
        field_transaction_id=31,
    )
    transaction = SimpleNamespace(
        id=31,
        branch_id=1,
        transaction_number="FTX-20260703-0031",
        review_status="IN_REVIEW",
        evidence_status="ATTACHED",
        attachments=[attachment_link],
    )
    attachment_link.field_transaction = transaction

    class _FakeSession:
        def add(self, obj):
            added_rows.append(obj)

        def commit(self):
            return None

    monkeypatch.setattr(
        "app.services.field_transaction_service.FieldTransactionReviewLog",
        _FakeReviewLog,
    )
    monkeypatch.setattr(
        "app.services.field_transaction_service.atomic_business_action",
        lambda **kwargs: _FakeAtomicContext(),
    )
    monkeypatch.setattr(
        "app.services.field_transaction_service.record_audit_log",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "app.services.field_transaction_service.db",
        SimpleNamespace(session=_FakeSession()),
    )

    ok, message, verified_attachment = verify_field_transaction_attachment(
        attachment_link,
        verified_by=9,
        note="bukti sudah dicek",
        commit=True,
    )

    assert ok is True
    assert "berhasil diverifikasi" in message
    assert verified_attachment.status == "VERIFIED"
    assert verified_attachment.verified_by == 9
    assert verified_attachment.verified_at is not None
    assert transaction.evidence_status == "VERIFIED"


def test_create_field_transaction_rejects_invalid_amount_before_db_access():
    with pytest.raises(FieldTransactionValidationError) as exc:
        create_field_transaction(
            branch_id=1,
            transaction_date=date(2026, 7, 3),
            entry_date=date(2026, 7, 3),
            transaction_direction="IN",
            business_event_type="OTHER_OPERATING_INCOME",
            amount="abc",
            created_by=1,
            field_channel="MANUAL",
        )

    assert "Nominal transaksi lapangan tidak valid" in str(exc.value)


def test_create_field_transaction_rejects_event_not_ready_in_ui():
    with pytest.raises(FieldTransactionValidationError) as exc:
        create_field_transaction(
            branch_id=1,
            transaction_date=date(2026, 7, 3),
            entry_date=date(2026, 7, 3),
            transaction_direction="IN",
            business_event_type="MANUAL_RECEIVABLE_PAYMENT",
            amount="100000",
            created_by=1,
            field_channel="MANUAL",
            party_snapshot_name="Mandor A",
            payment_method="CASH",
        )

    assert "belum dibuka di UI" in str(exc.value)


def test_create_field_transaction_allows_hidden_event_for_system_trace(monkeypatch):
    added_rows = []

    class _FakeSession:
        def add(self, obj):
            added_rows.append(obj)

        def flush(self):
            return None

        def commit(self):
            return None

    monkeypatch.setattr(
        "app.services.field_transaction_service.atomic_business_action",
        lambda **kwargs: _FakeAtomicContext(),
    )
    monkeypatch.setattr(
        "app.services.field_transaction_service.record_audit_log",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "app.services.field_transaction_service.db",
        SimpleNamespace(session=_FakeSession()),
    )
    monkeypatch.setattr(
        "app.services.field_transaction_service.validate_field_transaction_event_payload",
        lambda **kwargs: {"event_type": kwargs["event_type"]},
    )
    monkeypatch.setattr(
        "app.services.field_transaction_service.generate_field_transaction_number",
        lambda transaction_date: "FTX-20260703-0001",
    )

    ok, _, transaction = create_field_transaction(
        branch_id=1,
        transaction_date=date(2026, 7, 3),
        entry_date=date(2026, 7, 3),
        transaction_direction="IN",
        business_event_type="MANUAL_RECEIVABLE_PAYMENT",
        amount="100000",
        created_by=1,
        field_channel="SYSTEM",
        party_snapshot_name="Mandor A",
        payment_method="CASH",
        payment_status="PAID",
        review_status="READY_TO_POST",
        evidence_status="PENDING",
        allow_non_ui_event=True,
        commit=True,
    )

    assert ok is True
    assert transaction.business_event_type == "MANUAL_RECEIVABLE_PAYMENT"
    assert transaction.field_channel == "SYSTEM"


def test_update_field_transaction_draft_updates_core_fields(monkeypatch):
    transaction = SimpleNamespace(
        id=41,
        branch_id=1,
        transaction_number="FTX-20260703-0041",
        review_status="WAITING_CLASSIFICATION",
        posting_status="NOT_POSTED",
        transaction_date=date(2026, 7, 1),
        entry_date=date(2026, 7, 1),
        transaction_direction="IN",
        business_event_type="OTHER_OPERATING_INCOME",
        field_channel="MANUAL",
        counterparty_id=None,
        payment_status="PAID",
        payment_method="CASH",
        bank_account_id=None,
        amount=100000,
        notes="lama",
        branch=SimpleNamespace(id=1),
    )
    added_rows = []

    class _FakeSession:
        def add(self, obj):
            added_rows.append(obj)

        def commit(self):
            return None

    monkeypatch.setattr(
        "app.services.field_transaction_service.atomic_business_action",
        lambda **kwargs: _FakeAtomicContext(),
    )
    monkeypatch.setattr(
        "app.services.field_transaction_service.record_audit_log",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "app.services.field_transaction_service.db",
        SimpleNamespace(session=_FakeSession()),
    )
    monkeypatch.setattr(
        "app.services.field_transaction_service.validate_field_transaction_event_payload",
        lambda **kwargs: {"event_type": kwargs["event_type"]},
    )

    ok, message, updated = update_field_transaction_draft(
        transaction,
        transaction_date=date(2026, 7, 3),
        entry_date=date(2026, 7, 3),
        transaction_direction="IN",
        business_event_type="CATERING_DAILY_CASH_SALE",
        amount="250000",
        updated_by=5,
        field_channel="RECAP_HARIAN",
        counterparty_id=None,
        party_snapshot_name="Mandor Site A",
        party_snapshot_company="Site A",
        party_snapshot_phone="08123",
        site_location="Camp Timur",
        payment_status="PAID",
        payment_method="TRANSFER",
        bank_account_id=None,
        notes="draft diperbarui",
        commit=True,
    )

    assert ok is True
    assert "berhasil diperbarui" in message
    assert updated.business_event_type == "CATERING_DAILY_CASH_SALE"
    assert updated.field_channel == "RECAP_HARIAN"
    assert updated.amount == 250000
    assert updated.party_snapshot_name == "Mandor Site A"
    assert updated.notes == "draft diperbarui"


def test_update_field_transaction_draft_blocks_posted_transaction():
    transaction = SimpleNamespace(
        id=42,
        branch_id=1,
        transaction_number="FTX-20260703-0042",
        review_status="POSTED",
        posting_status="POSTED",
    )

    with pytest.raises(FieldTransactionValidationError) as exc:
        update_field_transaction_draft(
            transaction,
            transaction_date=date(2026, 7, 3),
            entry_date=date(2026, 7, 3),
            transaction_direction="IN",
            business_event_type="OTHER_OPERATING_INCOME",
            amount="100000",
            updated_by=5,
        )

    assert "tidak boleh diedit lagi" in str(exc.value)


def test_update_field_transaction_review_status_blocks_manual_posted_transition():
    transaction = SimpleNamespace(
        id=100,
        branch_id=1,
        transaction_number="FTX-TEST-100",
        review_status="READY_TO_POST",
        posting_status="NOT_POSTED",
    )

    with pytest.raises(FieldTransactionValidationError) as exc:
        update_field_transaction_review_status(
            transaction,
            to_review_status="POSTED",
            acted_by=1,
        )

    assert "hanya boleh dibentuk melalui proses posting resmi" in str(exc.value)


def test_update_field_transaction_review_status_allows_transition_to_in_review(monkeypatch):
    added_rows = []
    transaction = SimpleNamespace(
        id=103,
        branch_id=1,
        transaction_number="FTX-TEST-103",
        review_status="WAITING_CLASSIFICATION",
        posting_status="NOT_POSTED",
        reviewed_at=None,
        reviewed_by=None,
    )

    class _FakeSession:
        def add(self, obj):
            added_rows.append(obj)

        def commit(self):
            return None

    monkeypatch.setattr(
        "app.services.field_transaction_service.atomic_business_action",
        lambda **kwargs: _FakeAtomicContext(),
    )
    monkeypatch.setattr(
        "app.services.field_transaction_service.record_audit_log",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "app.services.field_transaction_service.FieldTransactionReviewLog",
        _FakeReviewLog,
    )
    monkeypatch.setattr(
        "app.services.field_transaction_service.db",
        SimpleNamespace(session=_FakeSession()),
    )

    ok, message, updated = update_field_transaction_review_status(
        transaction,
        to_review_status="IN_REVIEW",
        acted_by=8,
        note="dicek finance",
        commit=True,
    )

    assert ok is True
    assert "berhasil diperbarui" in message
    assert updated.review_status == "IN_REVIEW"
    assert updated.reviewed_by == 8


def test_update_field_transaction_review_status_blocks_invalid_transition_from_void():
    transaction = SimpleNamespace(
        id=101,
        branch_id=1,
        transaction_number="FTX-TEST-101",
        review_status="VOID",
        posting_status="VOIDED",
    )

    with pytest.raises(FieldTransactionValidationError) as exc:
        update_field_transaction_review_status(
            transaction,
            to_review_status="READY_TO_POST",
            acted_by=1,
            note="coba aktifkan lagi",
        )

    assert "sudah di-void" in str(exc.value)


def test_update_field_transaction_review_status_requires_note_for_rejected():
    transaction = SimpleNamespace(
        id=102,
        branch_id=1,
        transaction_number="FTX-TEST-102",
        review_status="IN_REVIEW",
        posting_status="NOT_POSTED",
    )

    with pytest.raises(FieldTransactionValidationError) as exc:
        update_field_transaction_review_status(
            transaction,
            to_review_status="REJECTED",
            acted_by=1,
            note="",
        )

    assert "Catatan wajib diisi" in str(exc.value)


def test_parse_date_rejects_empty_and_invalid_values():
    with pytest.raises(FieldTransactionValidationError):
        _parse_date("", "Tanggal kejadian")

    with pytest.raises(FieldTransactionValidationError):
        _parse_date("2026/07/03", "Tanggal kejadian")


def test_resolve_document_link_target_for_journal(monkeypatch):
    monkeypatch.setattr(
        "app.routes.field_transaction_routes.url_for",
        lambda endpoint, **kwargs: f"/mock/{endpoint}/{kwargs['journal_id']}",
    )
    link = SimpleNamespace(link_role="JOURNAL", reference_type="JOURNAL", reference_id=77)
    transaction = SimpleNamespace(id=31)

    result = _resolve_document_link_target(link, transaction)

    assert result["href"] == "/mock/accounting.journal_detail/77"
    assert result["helper_text"] == "Buka detail jurnal"


def test_resolve_document_link_target_for_manual_receivable_payment(monkeypatch):
    monkeypatch.setattr(
        "app.routes.field_transaction_routes.url_for",
        lambda endpoint, **kwargs: f"/field-transactions/{kwargs['transaction_id']}",
    )
    link = SimpleNamespace(
        link_role="MANUAL_RECEIVABLE_PAYMENT",
        reference_type="MANUAL_RECEIVABLE_PAYMENT",
        reference_id=12,
    )
    transaction = SimpleNamespace(id=31)

    result = _resolve_document_link_target(link, transaction)

    assert result["href"].endswith("/field-transactions/31#manual-receivable-payments")
    assert result["helper_text"] == "Buka riwayat pembayaran piutang"


def test_resolve_document_link_target_for_unknown_reference():
    link = SimpleNamespace(link_role="OTHER", reference_type="UNKNOWN_TYPE", reference_id=99)
    transaction = SimpleNamespace(id=31)

    result = _resolve_document_link_target(link, transaction)

    assert result["href"] is None


def test_record_manual_receivable_payment_creates_accounting_trace(monkeypatch):
    linked_calls = []
    system_trace_calls = []
    receivable = SimpleNamespace(
        id=51,
        branch_id=1,
        field_transaction_id=31,
        receivable_number="MREC-20260703-001",
        receivable_date=date(2026, 7, 1),
        total_amount=300000,
        paid_amount=0,
        remaining_amount=300000,
        status="OPEN",
        party_name="Mandor A",
    )
    field_transaction = SimpleNamespace(
        id=31,
        review_status="WAITING_CLASSIFICATION",
        payment_status="UNPAID",
        needs_follow_up=True,
    )
    receivable.field_transaction = field_transaction

    class _FakeSession:
        def add(self, obj):
            return None

        def flush(self):
            return None

        def commit(self):
            return None

    monkeypatch.setattr(
        "app.services.field_transaction_settlement_service.ManualReceivablePayment",
        _FakeManualReceivablePayment,
    )
    monkeypatch.setattr(
        "app.services.field_transaction_settlement_service.FieldTransactionSettlement",
        _FakeReviewLog,
    )
    monkeypatch.setattr(
        "app.services.field_transaction_settlement_service.FieldTransactionReviewLog",
        _FakeReviewLog,
    )
    monkeypatch.setattr(
        "app.services.field_transaction_settlement_service.atomic_business_action",
        lambda **kwargs: _FakeAtomicContext(),
    )
    monkeypatch.setattr(
        "app.services.field_transaction_settlement_service.record_audit_log",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "app.services.field_transaction_settlement_service.db",
        SimpleNamespace(session=_FakeSession()),
    )
    monkeypatch.setattr(
        "app.services.field_transaction_settlement_service._create_manual_payment_accounting_trace",
        lambda **kwargs: (SimpleNamespace(id=901), SimpleNamespace(id=902)),
    )
    monkeypatch.setattr(
        "app.services.field_transaction_settlement_service.generate_manual_receivable_payment_number",
        lambda payment_date: "MRPAY-TEST-001",
    )
    monkeypatch.setattr(
        "app.services.field_transaction_settlement_service.generate_field_settlement_number",
        lambda payment_date, settlement_type: "FTS-TEST-001",
    )
    monkeypatch.setattr(
        "app.services.field_transaction_settlement_service._ensure_unique_link",
        lambda *args: linked_calls.append(args),
    )
    monkeypatch.setattr(
        "app.services.field_transaction_settlement_service.create_system_linked_field_transaction",
        lambda **kwargs: system_trace_calls.append(kwargs) or (True, "ok", SimpleNamespace(id=9901)),
    )

    ok, message, payment = record_manual_receivable_payment(
        receivable,
        payment_date=date(2026, 7, 3),
        payment_method="CASH",
        amount="100000",
        paid_by=5,
        notes="bayar tahap 1",
        commit=True,
    )

    assert ok is True
    assert "berhasil dicatat" in message
    assert payment.cash_bank_transaction_id == 901
    assert payment.journal_id == 902
    assert receivable.paid_amount == 100000
    assert receivable.remaining_amount == 200000
    assert field_transaction.payment_status == "PARTIAL"
    assert ("LEDGER", "CASH_BANK_TRANSACTION", 901) == linked_calls[1][1:4]
    assert ("JOURNAL", "JOURNAL", 902) == linked_calls[2][1:4]
    assert system_trace_calls[0]["business_event_type"] == "MANUAL_RECEIVABLE_PAYMENT"


def test_record_manual_payable_payment_creates_accounting_trace(monkeypatch):
    linked_calls = []
    system_trace_calls = []
    payable = SimpleNamespace(
        id=61,
        branch_id=1,
        field_transaction_id=41,
        payable_number="MPAY-20260703-001",
        payable_date=date(2026, 7, 1),
        total_amount=250000,
        paid_amount=0,
        remaining_amount=250000,
        status="OPEN",
        party_name="Vendor B",
    )
    field_transaction = SimpleNamespace(
        id=41,
        review_status="WAITING_CLASSIFICATION",
        payment_status="UNPAID",
        needs_follow_up=True,
    )
    payable.field_transaction = field_transaction

    class _FakeSession:
        def add(self, obj):
            return None

        def flush(self):
            return None

        def commit(self):
            return None

    monkeypatch.setattr(
        "app.services.field_transaction_settlement_service.ManualPayablePayment",
        _FakeManualPayablePayment,
    )
    monkeypatch.setattr(
        "app.services.field_transaction_settlement_service.FieldTransactionSettlement",
        _FakeReviewLog,
    )
    monkeypatch.setattr(
        "app.services.field_transaction_settlement_service.FieldTransactionReviewLog",
        _FakeReviewLog,
    )
    monkeypatch.setattr(
        "app.services.field_transaction_settlement_service.atomic_business_action",
        lambda **kwargs: _FakeAtomicContext(),
    )
    monkeypatch.setattr(
        "app.services.field_transaction_settlement_service.record_audit_log",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "app.services.field_transaction_settlement_service.db",
        SimpleNamespace(session=_FakeSession()),
    )
    monkeypatch.setattr(
        "app.services.field_transaction_settlement_service._create_manual_payment_accounting_trace",
        lambda **kwargs: (SimpleNamespace(id=951), SimpleNamespace(id=952)),
    )
    monkeypatch.setattr(
        "app.services.field_transaction_settlement_service.generate_manual_payable_payment_number",
        lambda payment_date: "MPPAY-TEST-001",
    )
    monkeypatch.setattr(
        "app.services.field_transaction_settlement_service.generate_field_settlement_number",
        lambda payment_date, settlement_type: "FTS-TEST-002",
    )
    monkeypatch.setattr(
        "app.services.field_transaction_settlement_service._ensure_unique_link",
        lambda *args: linked_calls.append(args),
    )
    monkeypatch.setattr(
        "app.services.field_transaction_settlement_service.create_system_linked_field_transaction",
        lambda **kwargs: system_trace_calls.append(kwargs) or (True, "ok", SimpleNamespace(id=9902)),
    )

    ok, message, payment = record_manual_payable_payment(
        payable,
        payment_date=date(2026, 7, 3),
        payment_method="CASH",
        amount="150000",
        paid_by=5,
        notes="bayar vendor tahap 1",
        commit=True,
    )

    assert ok is True
    assert "berhasil dicatat" in message
    assert payment.cash_bank_transaction_id == 951
    assert payment.journal_id == 952
    assert payable.paid_amount == 150000
    assert payable.remaining_amount == 100000
    assert field_transaction.payment_status == "PARTIAL"
    assert ("LEDGER", "CASH_BANK_TRANSACTION", 951) == linked_calls[1][1:4]
    assert ("JOURNAL", "JOURNAL", 952) == linked_calls[2][1:4]
    assert system_trace_calls[0]["business_event_type"] == "VENDOR_PAYABLE_PAYMENT"
