from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.accounting import Account, Journal, JournalDetail
from app.models.contract import CustomerContract
from app.models.finance import AdvanceTransaction, BankAccount, CashBankAdjustment, CashBankTransaction, Payment
from app.models.system import DigitalAttachment, Notification, PortalOrderDraft, PortalPaymentProofClaim
from app.services.portal_order_draft_service import (
    confirm_portal_order_draft,
    draft_total_amount,
)
from app.services.portal_payment_approval_service import (
    PaymentApprovalError,
    approve_draft_payment,
    build_draft_payment_review,
    reject_draft_payment,
)
from app.services.portal_payment_proof_service import (
    PAYMENT_PROOF_PENDING_TYPE,
    upload_portal_order_draft_payment_proof,
)
from tests.test_payment_unique_code import _setup_customer_portal
from tests.test_portal_payment_proof_service import PDF_BYTES, _file_storage
from tests.test_prepaid_orders import _ensure_accounts, _setup


@pytest.fixture
def ctx(app):
    app.config["WTF_CSRF_ENABLED"] = False
    with app.app_context():
        from app.extensions import db
        try:
            yield db
        finally:
            db.session.rollback()


TODAY = date.today()


def _setup_bank(db, s):
    bank_account = BankAccount(
        branch_id=s.branch.id,
        bank_name="BCA",
        account_number=f"1234567890-{uuid4().hex[:6]}",
        account_name="PT Idha Boga Mandiri",
        coa_account_code="1002",
        is_active=True,
    )
    db.session.add(bank_account)
    db.session.commit()
    return bank_account


def _create_draft(s, qty=12, meal="LUNCH", unique_code=None, order_date=None):
    draft = PortalOrderDraft(
        user_id=s.portal_customer.id,
        branch_id=s.branch.id,
        client_id=s.client.id,
        mandor_id=s.mandor.id,
        delivery_location_id=s.location.id,
        order_date=order_date or (TODAY + timedelta(days=2)),
        meal_type=meal,
        portion_qty=qty,
        price_per_portion=Decimal("25000"),
        price_source="STANDAR",
        delivery_fee=Decimal("15000"),
        payment_unique_code=unique_code,
        idempotency_key=uuid4().hex,
        status="PENDING_ADMIN_CONFIRMATION",
    )
    db.session.add(draft)
    db.session.commit()
    return draft  # total = 12 * 25000 + 15000 = 315000


def _upload_proof(s, draft, claimed_amount=None, sender_name="Pengirim Uji", transfer_reference=None):
    res = upload_portal_order_draft_payment_proof(
        s.portal_customer,
        draft_id=draft.id,
        file_storage=_file_storage(filename=f"proof_{uuid4().hex[:6]}.pdf", payload=PDF_BYTES + uuid4().bytes),
        notes="Transfer dari portal",
        claimed_amount=claimed_amount,
        sender_name=sender_name,
        transfer_reference=transfer_reference,
        commit=True,
    )
    return db.session.get(DigitalAttachment, res["attachment_id"])


# 1. Bayar pas (tanpa kode) -> outcome CONFIRMED, 1 AdvanceTransaction = total, draft CONFIRMED, converted_daily_order_id terisi, attachment PAYMENT_PROOF_PAYMENT_CREATED, jurnal seimbang
def test_approve_bayar_pas_tanpa_kode_konfirmasi_dan_jurnal_seimbang(ctx):
    s = _setup(ctx)
    _setup_customer_portal(ctx, s)
    bank = _setup_bank(ctx, s)
    draft = _create_draft(s, qty=12)
    att = _upload_proof(s, draft, claimed_amount="315000", sender_name="Budi", transfer_reference="REF001")

    res = approve_draft_payment(
        s.admin,
        attachment_id=att.id,
        draft_id=draft.id,
        received_amount="315000",
        payment_method="TRANSFER",
        bank_account_id=bank.id,
        payment_date=TODAY,
        reference_number="REF001",
        checked_mutation=True,
        note="Bayar lunas pas",
        idempotency_key=uuid4().hex,
    )

    assert res["outcome"] == "CONFIRMED"
    assert res["prepay"] == Decimal("315000.00")
    assert res["extra"] == Decimal("0.00")
    assert res["remaining"] == Decimal("0.00")

    db.session.refresh(draft)
    assert draft.status == "CONFIRMED"
    assert draft.converted_daily_order_id is not None

    db.session.refresh(att)
    assert att.attachment_type == "PAYMENT_PROOF_PAYMENT_CREATED"
    assert "PAYMENT_CREATED" in att.notes

    # Advance transaction
    adv = AdvanceTransaction.query.filter_by(portal_order_draft_id=draft.id).one()
    assert adv.amount == Decimal("315000.00")
    assert adv.advance_number == res["advance_number"]

    # Jurnal seimbang
    journal = db.session.get(Journal, adv.journal_id)
    assert journal is not None
    details = JournalDetail.query.filter_by(journal_id=journal.id).all()
    tot_debit = sum(Decimal(str(d.debit)) for d in details)
    tot_credit = sum(Decimal(str(d.credit)) for d in details)
    assert tot_debit == tot_credit == Decimal("315000.00")


# 2. Bayar total + kode unik -> advance = total, CashBankAdjustment KODE_UNIK = kode, jurnal Dr bank / Cr 4004 = kode, saldo bank naik sebesar total + kode
def test_approve_bayar_total_plus_kode_unik_adj_tercatat_saldo_naik(ctx):
    s = _setup(ctx)
    _setup_customer_portal(ctx, s)
    bank = _setup_bank(ctx, s)
    draft = _create_draft(s, qty=12, unique_code=237)
    att = _upload_proof(s, draft, claimed_amount="315237", sender_name="Budi", transfer_reference="REF002")

    res = approve_draft_payment(
        s.admin,
        attachment_id=att.id,
        draft_id=draft.id,
        received_amount="315237",
        payment_method="TRANSFER",
        bank_account_id=bank.id,
        payment_date=TODAY,
        reference_number="REF002",
        checked_mutation=True,
        note="",
        idempotency_key=uuid4().hex,
    )

    assert res["outcome"] == "CONFIRMED"
    assert res["prepay"] == Decimal("315000.00")
    assert res["extra"] == Decimal("237.00")
    assert res["remaining"] == Decimal("0.00")

    # CashBankAdjustment KODE_UNIK
    adj = CashBankAdjustment.query.filter_by(adjustment_category="KODE_UNIK", branch_id=s.branch.id).one()
    assert adj.amount == Decimal("237.00")
    assert adj.account_type == "BANK"
    assert adj.bank_account_id == bank.id

    # Jurnal penyesuaian: Dr bank (1002) / Cr 4004
    adj_journal = Journal.query.filter_by(reference_type="CASH_BANK_ADJUSTMENT", reference_id=adj.id).one()
    adj_details = JournalDetail.query.filter_by(journal_id=adj_journal.id).all()
    lines = {
        Account.query.get(d.account_id).account_code: (Decimal(str(d.debit)), Decimal(str(d.credit)))
        for d in adj_details
    }
    assert lines == {"1002": (Decimal("237.00"), Decimal("0.00")), "4004": (Decimal("0.00"), Decimal("237.00"))}

    # Saldo bank naik sebesar total + kode (315000 + 237 = 315237)
    bank_in_txs = CashBankTransaction.query.filter_by(bank_account_id=bank.id, transaction_type="IN").all()
    assert sum(t.amount for t in bank_in_txs) == Decimal("315237.00")


# 3. Bayar kurang -> outcome HELD_SHORT, advance = nominal diterima, draft tetap PENDING, notifikasi "Pembayaran kurang" terkirim
def test_approve_bayar_kurang_held_short_draft_pending_notifikasi(ctx):
    s = _setup(ctx)
    _setup_customer_portal(ctx, s)
    bank = _setup_bank(ctx, s)
    draft = _create_draft(s, qty=12, unique_code=150)
    att = _upload_proof(s, draft, claimed_amount="200000", sender_name="Budi", transfer_reference="REF003")

    res = approve_draft_payment(
        s.admin,
        attachment_id=att.id,
        draft_id=draft.id,
        received_amount="200000",
        payment_method="TRANSFER",
        bank_account_id=bank.id,
        payment_date=TODAY,
        reference_number="REF003",
        checked_mutation=True,
        note="Kurang bayar sebagian",
        idempotency_key=uuid4().hex,
    )

    assert res["outcome"] == "HELD_SHORT"
    assert res["prepay"] == Decimal("200000.00")
    assert res["extra"] == Decimal("0.00")
    assert res["remaining"] == Decimal("115000.00")

    db.session.refresh(draft)
    assert draft.status == "PENDING_ADMIN_CONFIRMATION"

    # Notifikasi
    notif = Notification.query.filter_by(generated_key=f"portal-draft-short-{att.id}").first()
    assert notif is not None
    assert notif.title == "Pembayaran kurang"
    assert "Sisa yang harus dibayar" in notif.message


# 4. Bayar lebih dari total + kode -> error, TIDAK ada advance/adjustment/jurnal baru
def test_approve_bayar_lebih_error_tidak_ada_perubahan(ctx):
    s = _setup(ctx)
    _setup_customer_portal(ctx, s)
    bank = _setup_bank(ctx, s)
    draft = _create_draft(s, qty=12, unique_code=100)
    att = _upload_proof(s, draft, claimed_amount="350000", sender_name="Budi")

    adv_count_before = AdvanceTransaction.query.count()
    adj_count_before = CashBankAdjustment.query.count()
    jrn_count_before = Journal.query.count()

    with pytest.raises(PaymentApprovalError, match="lebih besar dari tagihan"):
        approve_draft_payment(
            s.admin,
            attachment_id=att.id,
            draft_id=draft.id,
            received_amount="350000",
            payment_method="TRANSFER",
            bank_account_id=bank.id,
            checked_mutation=True,
            note="Lebih bayar",
            idempotency_key=uuid4().hex,
        )

    assert AdvanceTransaction.query.count() == adv_count_before
    assert CashBankAdjustment.query.count() == adj_count_before
    assert Journal.query.count() == jrn_count_before


# 5. draft_id tidak cocok dengan attachment -> error, tidak ada perubahan
def test_approve_draft_id_tidak_cocok_error(ctx):
    s = _setup(ctx)
    _setup_customer_portal(ctx, s)
    bank = _setup_bank(ctx, s)
    draft1 = _create_draft(s, qty=12)
    draft2 = _create_draft(s, qty=12)
    att1 = _upload_proof(s, draft1, claimed_amount="315000")

    with pytest.raises(PaymentApprovalError, match="bukan milik pesanan"):
        approve_draft_payment(
            s.admin,
            attachment_id=att1.id,
            draft_id=draft2.id,
            received_amount="315000",
            payment_method="TRANSFER",
            bank_account_id=bank.id,
            checked_mutation=True,
            idempotency_key=uuid4().hex,
        )


# 6. checked_mutation=False -> error
def test_approve_checked_mutation_false_error(ctx):
    s = _setup(ctx)
    _setup_customer_portal(ctx, s)
    bank = _setup_bank(ctx, s)
    draft = _create_draft(s, qty=12)
    att = _upload_proof(s, draft, claimed_amount="315000")

    with pytest.raises(PaymentApprovalError, match="Centang dulu"):
        approve_draft_payment(
            s.admin,
            attachment_id=att.id,
            draft_id=draft.id,
            received_amount="315000",
            payment_method="TRANSFER",
            bank_account_id=bank.id,
            checked_mutation=False,
            idempotency_key=uuid4().hex,
        )


# 7. Nominal berbeda tanpa catatan -> error
def test_approve_nominal_berbeda_tanpa_catatan_error(ctx):
    s = _setup(ctx)
    _setup_customer_portal(ctx, s)
    bank = _setup_bank(ctx, s)
    draft = _create_draft(s, qty=12, unique_code=200)
    att = _upload_proof(s, draft, claimed_amount="200000")

    # transfer amount = 315200, outstanding = 315000. Diterima 200000. Note kosong -> error
    with pytest.raises(PaymentApprovalError, match="Tulis catatan alasannya"):
        approve_draft_payment(
            s.admin,
            attachment_id=att.id,
            draft_id=draft.id,
            received_amount="200000",
            payment_method="TRANSFER",
            bank_account_id=bank.id,
            checked_mutation=True,
            note="",
            idempotency_key=uuid4().hex,
        )


# 8. Idempotency key sama dikirim dua kali -> kedua kalinya error, hanya 1 advance
def test_approve_idempotency_key_sama_ditolak(ctx):
    s = _setup(ctx)
    _setup_customer_portal(ctx, s)
    bank = _setup_bank(ctx, s)
    draft = _create_draft(s, qty=12)
    att = _upload_proof(s, draft, claimed_amount="315000")

    key = uuid4().hex
    approve_draft_payment(
        s.admin,
        attachment_id=att.id,
        draft_id=draft.id,
        received_amount="315000",
        payment_method="TRANSFER",
        bank_account_id=bank.id,
        checked_mutation=True,
        idempotency_key=key,
    )

    adv_count = AdvanceTransaction.query.filter_by(portal_order_draft_id=draft.id).count()
    assert adv_count == 1

    # Percobaan kedua dengan key yang sama harus error
    with pytest.raises(PaymentApprovalError):
        approve_draft_payment(
            s.admin,
            attachment_id=att.id,
            draft_id=draft.id,
            received_amount="315000",
            payment_method="TRANSFER",
            bank_account_id=bank.id,
            checked_mutation=True,
            idempotency_key=key,
        )

    assert AdvanceTransaction.query.filter_by(portal_order_draft_id=draft.id).count() == 1


# 9. Gate lain BLOCKED (mis. kontrak berakhir) -> error, SEMUA batal (tidak ada advance, attachment tetap status awal)
def test_approve_gate_lain_blocked_semua_batal(ctx):
    s = _setup(ctx)
    db.session.commit()
    _setup_customer_portal(ctx, s)
    bank = _setup_bank(ctx, s)
    draft = _create_draft(s, qty=12)
    att = _upload_proof(s, draft, claimed_amount="315000")

    # Buat kontrak berakhir (lapsed) untuk client ini
    contract = CustomerContract(
        branch_id=s.branch.id,
        client_id=s.client.id,
        contract_number=f"KTR-{uuid4().hex[:8]}",
        title="Kontrak Kadaluwarsa",
        start_date=TODAY - timedelta(days=200),
        end_date=TODAY - timedelta(days=10),
        payment_terms="NET_30",
        status="EXPIRED",
        credit_limit=Decimal("0"),
        created_by=s.owner.id,
    )
    db.session.add(contract)
    db.session.commit()

    adv_count_before = AdvanceTransaction.query.count()

    with pytest.raises(PaymentApprovalError, match="Perpanjang kontraknya"):
        approve_draft_payment(
            s.admin,
            attachment_id=att.id,
            draft_id=draft.id,
            received_amount="315000",
            payment_method="TRANSFER",
            bank_account_id=bank.id,
            checked_mutation=True,
            idempotency_key=uuid4().hex,
        )

    # Semua batal: tidak ada advance baru, status attachment tetap PENDING
    assert AdvanceTransaction.query.count() == adv_count_before
    db.session.refresh(att)
    assert att.attachment_type == PAYMENT_PROOF_PENDING_TYPE


# 10. Referensi bank sudah dipakai -> error
def test_approve_referensi_bank_sudah_dipakai_error(ctx):
    s = _setup(ctx)
    _setup_customer_portal(ctx, s)
    bank = _setup_bank(ctx, s)
    draft1 = _create_draft(s, qty=12)
    att1 = _upload_proof(s, draft1, claimed_amount="315000")

    approve_draft_payment(
        s.admin,
        attachment_id=att1.id,
        draft_id=draft1.id,
        received_amount="315000",
        payment_method="TRANSFER",
        bank_account_id=bank.id,
        reference_number="REF-DUPLIKAT-123",
        checked_mutation=True,
        idempotency_key=uuid4().hex,
    )

    # Draft 2 coba pakai referensi yang sama
    draft2 = _create_draft(s, qty=12)
    att2 = _upload_proof(s, draft2, claimed_amount="315000")

    with pytest.raises(PaymentApprovalError, match="sudah pernah digunakan"):
        approve_draft_payment(
            s.admin,
            attachment_id=att2.id,
            draft_id=draft2.id,
            received_amount="315000",
            payment_method="TRANSFER",
            bank_account_id=bank.id,
            reference_number="ref-duplikat-123",
            checked_mutation=True,
            idempotency_key=uuid4().hex,
        )


# 11. Tolak dengan alasan -> attachment REJECTED, draft tetap PENDING, pelanggan dapat notifikasi
def test_reject_draft_payment_sukses_dan_notifikasi(ctx):
    s = _setup(ctx)
    _setup_customer_portal(ctx, s)
    draft = _create_draft(s, qty=12)
    att = _upload_proof(s, draft, claimed_amount="315000")

    res = reject_draft_payment(
        s.admin,
        attachment_id=att.id,
        draft_id=draft.id,
        reason_code="UNREADABLE",
        note="Foto terpotong",
    )

    assert res["rejected"] is True
    db.session.refresh(att)
    assert att.attachment_type == "PAYMENT_PROOF_REJECTED"
    assert "Bukti tidak jelas/terbaca" in att.notes
    assert "Foto terpotong" in att.notes

    db.session.refresh(draft)
    assert draft.status == "PENDING_ADMIN_CONFIRMATION"

    # Notifikasi ke pelanggan
    notif = Notification.query.filter_by(target_user_id=att.uploaded_by).first()
    assert notif is not None
    assert "ditolak" in notif.title.lower() or "ditolak" in notif.message.lower()


# 12. confirm_portal_order_draft default (commit=True) tetap berjalan normal
def test_confirm_portal_order_draft_default_commit_true(ctx):
    s = _setup(ctx)
    _setup_customer_portal(ctx, s)
    draft = _create_draft(s, qty=12)

    # Simulasikan draft lunas lewat prepay
    from app.services.prepaid_order_service import record_draft_prepayment

    record_draft_prepayment(
        draft=draft,
        amount=Decimal("315000"),
        payment_method="CASH",
        created_by=s.admin.id,
    )

    confirmed_draft, ok, err = confirm_portal_order_draft(draft.id, s.admin)
    assert ok is True
    assert err is None
    assert confirmed_draft.status == "CONFIRMED"
    assert confirmed_draft.converted_daily_order_id is not None


# 13. build_draft_payment_review read model
def test_build_draft_payment_review(ctx):
    s = _setup(ctx)
    _setup_customer_portal(ctx, s)
    draft = _create_draft(s, qty=12, unique_code=237)
    att = _upload_proof(s, draft, claimed_amount="315237", sender_name="Budi", transfer_reference="REF-REV-01")

    review = build_draft_payment_review(att)
    assert review["attachment_id"] == att.id
    assert review["draft_id"] == draft.id
    assert review["total"] == Decimal("315000.00")
    assert review["unique_code"] == Decimal("237.00")
    assert review["expected_transfer"] == Decimal("315237.00")
    assert review["claimed_amount"] == Decimal("315237.00")
    assert review["match"] == "EXACT"
    assert review["match_label"] == "Cocok"
    assert review["sender_name"] == "Budi"
    assert review["transfer_reference"] == "REF-REV-01"
    assert review["can_approve"] is True
    assert len(review["blockers"]) == 0

