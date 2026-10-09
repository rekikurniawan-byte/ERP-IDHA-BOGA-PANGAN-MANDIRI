"""Fase 7: kontrol kredit syariah -- ta'zir, ta'widh, kelonggaran, Dana Sosial.

Keputusan owner yang dikunci di sini (2026-10-06 / 2026-10-09):
- ta'zir nominal tetap dari kontrak, hanya diusulkan; OWNER memutuskan;
- ta'zir ditagih terpisah dan masuk 2009 Dana Sosial, tidak pernah ke pendapatan;
- telat bayar ta'zir tidak menaikkan status kredit (tidak ada denda atas denda);
- kelonggaran: status tidak naik melewati TAHAN, tanpa ta'zir, pesanan baru bayar di muka;
- penyaluran hanya OWNER, hanya dari dana yang sudah diterima, dengan bukti;
- client kontrak ikut tunduk pada tangga kredit.
"""
import io
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from werkzeug.datastructures import FileStorage

from app.extensions import db
from app.models.accounting import Account, Journal, JournalDetail
from app.models.credit import (
    CHARGE_DECLINED,
    CHARGE_IMPOSED,
    CHARGE_PROPOSED,
    CHARGE_TAWIDH,
    CHARGE_TAZIR,
    PARTY_CLIENT,
    STATUS_BLOCKED,
    STATUS_HOLD,
    CreditAccount,
    CreditCharge,
)
from app.models.finance import CashBankTransaction, Invoice, InvoiceCollectionLog, InvoiceItem
from app.models.master import Branch, Client, ClientPic, Mandor, User
from app.models.system import Notification, PortalUserMapping
from app.services.credit_account_service import CreditActionError, sweep_credit_statuses
from app.services.credit_control_service import evaluate_credit, evaluate_party, get_credit_account
from app.services.customer_contract_service import CONTRACT_STATUS_ACTIVE, create_customer_contract
from app.services.portal_mapping_service import ACCESS_DRAFT_ORDER, PRINCIPAL_CLIENT
from app.services.sharia_credit_service import (
    create_tawidh,
    decide_tazir,
    record_disbursement,
    set_grace,
    social_fund_summary,
)

TODAY = date(2026, 10, 20)
TAZIR = Decimal("100000")
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


@pytest.fixture
def ctx(app, monkeypatch, tmp_path):
    with app.app_context():
        monkeypatch.setattr(db.session, "commit", db.session.flush)
        monkeypatch.setitem(app.config, "DIGITAL_ATTACHMENT_UPLOAD_DIR", str(tmp_path))
        try:
            yield db
        finally:
            db.session.rollback()


def _ensure_accounts():
    for code, name, kind in (
        ("1001", "Kas", "ASSET"), ("1004", "Piutang Usaha", "ASSET"),
        ("2009", "Dana Sosial (Ta'zir)", "LIABILITY"), ("4004", "Pendapatan Lain-Lain", "REVENUE"),
        ("4001", "Pendapatan Catering Proyek", "REVENUE"),
    ):
        if not Account.query.filter_by(account_code=code).first():
            db.session.add(Account(account_code=code, account_name=name, account_type=kind, is_active=True))
    db.session.flush()


def _fixtures(tazir=TAZIR):
    _ensure_accounts()
    suffix = uuid4().hex[:6]
    branch = Branch(code=f"F7-{suffix}", name=f"Cabang F7 {suffix}", is_active=True)
    client = Client(name=f"PT Proyek {suffix}", is_active=True)
    db.session.add_all([branch, client])
    db.session.flush()

    def user(role, name):
        row = User(branch_id=branch.id, full_name=name, username=f"{name.lower()}_{suffix}",
                   password_hash="hash", role=role, is_active=True)
        db.session.add(row)
        return row

    owner, admin, client_user = user("OWNER", "Owner"), user("ADMIN", "Admin"), user("PORTAL_CLIENT", "Ptportal")
    mandor = Mandor(branch_id=branch.id, client_id=client.id, name=f"Mandor {suffix}", is_active=True)
    db.session.add_all([mandor, ClientPic(client_id=client.id, name="Bu PIC", phone="0811", is_active=True)])
    db.session.flush()
    db.session.add(PortalUserMapping(user_id=client_user.id, principal_type=PRINCIPAL_CLIENT, client_id=client.id,
                                     access_level=ACCESS_DRAFT_ORDER, is_active=True))
    contract = create_customer_contract(
        branch_id=branch.id, client_id=client.id, title="Kontrak", start_date=date(2026, 9, 1),
        end_date=date(2026, 12, 31), payment_terms="Net 7", status=CONTRACT_STATUS_ACTIVE,
        created_by=owner.id, due_days=7, tazir_amount=tazir,
    )
    db.session.flush()
    return SimpleNamespace(branch=branch, client=client, owner=owner, admin=admin, client_user=client_user,
                           mandor=mandor, contract=contract)


def _invoice(f, *, days_overdue, amount=Decimal("500000"), source_type="PERIOD_INVOICE", bill_to_type="CLIENT"):
    due = TODAY - timedelta(days=days_overdue)
    invoice = Invoice(
        branch_id=f.branch.id, invoice_number=f"INV-T-{uuid4().hex[:10]}", invoice_date=due - timedelta(days=7),
        due_date=due, bill_to_type=bill_to_type, client_id=f.client.id,
        mandor_id=f.mandor.id if bill_to_type == "MANDOR" else None,
        total_amount=amount, paid_amount=0, remaining_amount=amount, status="DRAFT",
        source_type=source_type, created_by=f.owner.id,
    )
    db.session.add(invoice)
    db.session.flush()
    return invoice


def _promise(f, invoice, promised_for, made_on):
    db.session.add(InvoiceCollectionLog(
        branch_id=f.branch.id, invoice_id=invoice.id, follow_up_date=made_on, channel="WHATSAPP",
        promise_date=promised_for, collection_status="FOLLOW_UP", created_by=f.owner.id,
    ))
    db.session.flush()


def _file(name="bukti.png"):
    return FileStorage(stream=io.BytesIO(PNG), filename=name, content_type="image/png")


def _journal_lines(reference_type, reference_id):
    journal = Journal.query.filter_by(reference_type=reference_type, reference_id=reference_id).one()
    rows = (
        db.session.query(Account.account_code, JournalDetail.debit, JournalDetail.credit)
        .join(Account, Account.id == JournalDetail.account_id)
        .filter(JournalDetail.journal_id == journal.id).all()
    )
    return {code: (Decimal(str(debit)), Decimal(str(credit))) for code, debit, credit in rows}


def _proposal(f):
    _promise(f, _invoice(f, days_overdue=10), TODAY - timedelta(days=3), TODAY - timedelta(days=5))
    sweep_credit_statuses(f.branch.id, today=TODAY)
    return CreditCharge.query.filter_by(branch_id=f.branch.id, charge_type=CHARGE_TAZIR).one()


def test_contract_client_is_enforced_and_charge_or_subclient_invoices_do_not_count(ctx):
    f = _fixtures()
    _invoice(f, days_overdue=10)
    _invoice(f, days_overdue=40, source_type=CHARGE_TAZIR)              # ta'zir lama tidak menua
    _invoice(f, days_overdue=40, bill_to_type="MANDOR")                  # hutang sub client, bukan client

    decision = evaluate_credit(f.branch.id, client_id=f.client.id, today=TODAY)
    assert decision.enforced is True
    assert decision.oldest_days_overdue == 10
    assert decision.outstanding_invoiced == Decimal("500000")
    assert decision.status == STATUS_HOLD

    no_contract = Client(name=f"PT Lepas {uuid4().hex[:6]}", is_active=True)
    db.session.add(no_contract)
    db.session.flush()
    assert evaluate_credit(f.branch.id, client_id=no_contract.id, today=TODAY).enforced is False


def test_sweep_escalates_contract_client_warns_portal_and_proposes_tazir_once(ctx):
    f = _fixtures()
    charge = _proposal(f)

    account = get_credit_account(f.branch.id, PARTY_CLIENT, f.client.id)
    assert account is not None and account.status in (STATUS_HOLD, STATUS_BLOCKED)
    assert charge.status == CHARGE_PROPOSED and charge.amount == TAZIR
    assert charge.trigger_key.startswith("promise-")
    assert Notification.query.filter_by(target_user_id=f.client_user.id, notification_type="CREDIT_STATUS").count() == 1

    sweep_credit_statuses(f.branch.id, today=TODAY)
    assert CreditCharge.query.filter_by(branch_id=f.branch.id, charge_type=CHARGE_TAZIR).count() == 1


def test_no_tazir_proposal_when_contract_amount_is_zero(ctx):
    f = _fixtures(tazir=Decimal("0"))
    _promise(f, _invoice(f, days_overdue=10), TODAY - timedelta(days=3), TODAY - timedelta(days=5))
    sweep_credit_statuses(f.branch.id, today=TODAY)
    assert CreditCharge.query.filter_by(branch_id=f.branch.id).count() == 0


def test_owner_imposes_tazir_into_social_fund_never_revenue(ctx):
    f = _fixtures()
    charge = _proposal(f)

    with pytest.raises(CreditActionError):
        decide_tazir(charge, {"decision": "IMPOSE"}, f.admin, today=TODAY)
    with pytest.raises(CreditActionError, match="alasan"):
        decide_tazir(charge, {"decision": "DECLINE"}, f.owner, today=TODAY)

    decide_tazir(charge, {"decision": "IMPOSE"}, f.owner, today=TODAY)
    assert charge.status == CHARGE_IMPOSED
    invoice = charge.invoice
    assert invoice.source_type == CHARGE_TAZIR and invoice.total_amount == TAZIR
    assert invoice.due_date == TODAY + timedelta(days=7)
    assert InvoiceItem.query.filter_by(invoice_id=invoice.id, item_type=CHARGE_TAZIR).count() == 1

    lines = _journal_lines("INVOICE", invoice.id)
    assert lines["1004"] == (TAZIR, Decimal("0"))
    assert lines["2009"] == (Decimal("0"), TAZIR)
    assert not any(code.startswith("4") for code in lines)
    assert Notification.query.filter_by(target_user_id=f.client_user.id, notification_type="INVOICE_ISSUED").count() == 1

    # Ta'zir yang belum dibayar tidak menaikkan umur tunggakan pihaknya.
    account = get_credit_account(f.branch.id, PARTY_CLIENT, f.client.id)
    later = evaluate_party(f.branch.id, PARTY_CLIENT, f.client.id, account, today=TODAY + timedelta(days=30))
    assert later.outstanding_invoiced == Decimal("500000")


def test_grace_caps_status_and_drops_pending_tazir(ctx):
    f = _fixtures()
    _invoice(f, days_overdue=30)                                        # 30 hari -> BLOKIR
    _promise(f, _invoice(f, days_overdue=10), TODAY - timedelta(days=3), TODAY - timedelta(days=5))
    sweep_credit_statuses(f.branch.id, today=TODAY)
    proposals = CreditCharge.query.filter_by(branch_id=f.branch.id, charge_type=CHARGE_TAZIR).all()
    # Satu kejadian = satu usulan: janji meleset dan masuk Blokir.
    assert sorted(charge.trigger for charge in proposals) == ["BLOCKED", "BROKEN_PROMISE"]
    account = get_credit_account(f.branch.id, PARTY_CLIENT, f.client.id)
    assert evaluate_party(f.branch.id, PARTY_CLIENT, f.client.id, account, today=TODAY).status == STATUS_BLOCKED

    with pytest.raises(CreditActionError):
        set_grace(account, {"grace_until": "2026-10-25", "grace_reason": "Proyek berhenti total"}, f.admin, today=TODAY)
    set_grace(account, {"grace_until": "2026-10-25", "grace_reason": "Proyek berhenti total, dana owner proyek tertahan"},
              f.owner, today=TODAY)

    decision = evaluate_party(f.branch.id, PARTY_CLIENT, f.client.id, account, today=TODAY)
    assert decision.status == STATUS_HOLD                               # pesanan baru bayar di muka
    assert decision.requires_approval is True
    assert all(charge.status == CHARGE_DECLINED for charge in proposals)

    _promise(f, _invoice(f, days_overdue=12), TODAY - timedelta(days=1), TODAY - timedelta(days=2))
    sweep_credit_statuses(f.branch.id, today=TODAY)
    assert CreditCharge.query.filter_by(branch_id=f.branch.id, status=CHARGE_PROPOSED).count() == 0

    after = evaluate_party(f.branch.id, PARTY_CLIENT, f.client.id, account, today=date(2026, 10, 26))
    assert after.status == STATUS_BLOCKED                               # kelonggaran habis -> aturan biasa


def test_disbursement_only_from_received_funds_with_evidence_and_journal(ctx):
    f = _fixtures()
    charge = _proposal(f)
    decide_tazir(charge, {"decision": "IMPOSE"}, f.owner, today=TODAY)
    form = {"disbursed_on": TODAY.isoformat(), "recipient": "Masjid Al-Ikhlas", "purpose": "Bantuan musala",
            "amount": "60000", "account_type": "CASH"}

    with pytest.raises(CreditActionError, match="hanya"):
        record_disbursement(f.branch.id, form, _file(), f.owner)        # belum ada yang diterima

    invoice = charge.invoice
    invoice.paid_amount, invoice.remaining_amount, invoice.status = TAZIR, 0, "PAID"
    db.session.add(CashBankTransaction(branch_id=f.branch.id, transaction_date=TODAY, account_type="CASH",
                                       transaction_type="IN", amount=1000000, description="Saldo uji",
                                       created_by=f.owner.id))
    db.session.flush()

    with pytest.raises(CreditActionError):
        record_disbursement(f.branch.id, form, _file(), f.admin)
    with pytest.raises(CreditActionError, match="Bukti"):
        record_disbursement(f.branch.id, form, None, f.owner)

    record = record_disbursement(f.branch.id, form, _file(), f.owner)
    assert record.evidence_attachment_id is not None
    ledger = db.session.get(CashBankTransaction, record.cash_bank_transaction_id)
    assert ledger.transaction_type == "OUT" and Decimal(str(ledger.amount)) == Decimal("60000")
    lines = _journal_lines("SOCIAL_FUND_DISBURSEMENT", record.id)
    assert lines["2009"] == (Decimal("60000"), Decimal("0"))
    assert lines["1001"] == (Decimal("0"), Decimal("60000"))

    summary = social_fund_summary(f.branch.id)
    assert summary["collected"] == TAZIR
    assert summary["disbursed"] == Decimal("60000")
    assert summary["available"] == Decimal("40000")


def test_tawidh_needs_evidence_and_is_billed_separately(ctx):
    f = _fixtures()
    _invoice(f, days_overdue=10)
    sweep_credit_statuses(f.branch.id, today=TODAY)
    account = get_credit_account(f.branch.id, PARTY_CLIENT, f.client.id)
    form = {"amount": "150000", "reason": "Ongkos 3x ke lokasi menagih, nota terlampir"}

    with pytest.raises(CreditActionError, match="Bukti"):
        create_tawidh(account, form, None, f.owner, today=TODAY)
    with pytest.raises(CreditActionError):
        create_tawidh(account, form, _file(), f.admin, today=TODAY)

    charge = create_tawidh(account, form, _file(), f.owner, today=TODAY)
    assert charge.charge_type == CHARGE_TAWIDH and charge.status == CHARGE_IMPOSED
    assert charge.evidence_attachment_id is not None
    assert charge.invoice.source_type == CHARGE_TAWIDH
    lines = _journal_lines("INVOICE", charge.invoice.id)
    assert lines["1004"] == (Decimal("150000"), Decimal("0"))
    assert lines["4004"] == (Decimal("0"), Decimal("150000"))
    assert "2009" not in lines


def test_credit_sweep_runs_from_scheduler_at_0730(ctx):
    from app.services.scheduler_service import get_job

    job = get_job("credit_daily_sweep")
    assert job is not None and job["per_branch"] is True
    assert job["schedule"] == {"type": "daily", "time": "07:30"}
