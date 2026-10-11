"""Kontrol kredit syariah (Fase 7): ta'zir, ta'widh, kelonggaran, Dana Sosial.

Prinsip (fatwa DSN-MUI No. 17/2000 dan No. 43/2004, keputusan owner 2026-10-06
dan 2026-10-09):
- Tidak ada denda persen/harian yang menjadi pendapatan PT.
- Ta'zir: nominal TETAP per kejadian dari kontrak, hanya DIUSULKAN sistem saat
  janji bayar meleset atau status sudah BLOKIR; OWNER yang memutuskan.
  Ditagih terpisah, dijurnal Dr 1004 / Cr 2009 Dana Sosial (kewajiban).
- Ta'widh: ganti biaya penagihan RIIL dengan bukti, diputuskan OWNER,
  ditagih terpisah, Dr 1004 / Cr 4004 (penggantian biaya, bukan untung).
- Kelonggaran (QS 2:280) untuk yang benar-benar tidak mampu: utang lama
  ditangguhkan tanpa ta'zir, pesanan baru wajib bayar di muka.
- Penyaluran Dana Sosial hanya dicatat OWNER, dengan bukti:
  Dr 2009 / Cr Kas/Bank + buku kas/bank keluar.

Semua tindakan OWNER commit lewat _in_transaction (satu transaksi per tindakan).
Fungsi penyapu tidak commit; penyapu yang commit.
"""
from datetime import date, datetime, timedelta

from app.extensions import db
from app.utils.clock import today_wib
from app.models.credit import (
    BILLING_CASH,
    CHARGE_DECLINED,
    CHARGE_IMPOSED,
    CHARGE_PROPOSED,
    CHARGE_TAWIDH,
    CHARGE_TAZIR,
    PARTY_CLIENT,
    PARTY_MANDOR,
    STATUS_BLOCKED,
    STATUS_WRITE_OFF,
    TRIGGER_BLOCKED,
    TRIGGER_BROKEN_PROMISE,
    TRIGGER_MANUAL,
    CreditAccount,
    CreditCharge,
    CreditStatusEvent,
    SocialFundDisbursement,
)
from app.models.finance import Invoice, InvoiceItem
from app.models.master import Client, Mandor
from app.services.credit_account_service import (
    CreditActionError,
    _clean,
    _in_transaction,
    _parse_date,
    _require_owner,
    _int_or_none,
    party_name,
    parse_money,
)
from app.services.credit_control_service import ZERO, _money, _rupiah

CHARGE_LABELS = {CHARGE_TAZIR: "Ta'zir (Dana Sosial)", CHARGE_TAWIDH: "Ta'widh (biaya penagihan riil)"}
CHARGE_STATUS_LABELS = {
    CHARGE_PROPOSED: "Menunggu Owner",
    CHARGE_IMPOSED: "Dikenakan",
    CHARGE_DECLINED: "Tidak dikenakan",
}
TRIGGER_LABELS = {
    TRIGGER_BROKEN_PROMISE: "Janji bayar meleset",
    TRIGGER_BLOCKED: "Status Blokir",
    TRIGGER_MANUAL: "Dicatat Owner",
}
# Janji meleset yang lebih tua dari ini tidak diusulkan lagi: saat fitur ini
# pertama jalan, riwayat lama tidak boleh membanjiri Owner dengan usulan.
PROMISE_LOOKBACK_DAYS = 30
SOCIAL_FUND_REFERENCE = "SOCIAL_FUND_DISBURSEMENT"
CREDIT_ATTACHMENT_MODULE = "CREDIT"


# --- penerima notifikasi --------------------------------------------------------

def portal_users_for_party(party_type, party_id):
    """Akun portal aktif milik pihak yang ditagih (sub client atau client)."""
    from app.models.master import User
    from app.models.system import PortalUserMapping

    query = PortalUserMapping.query.filter(PortalUserMapping.is_active.is_(True))
    if party_type == PARTY_MANDOR:
        query = query.filter(PortalUserMapping.mandor_id == party_id)
    else:
        query = query.filter(PortalUserMapping.client_id == party_id, PortalUserMapping.mandor_id.is_(None))
    user_ids = {row.user_id for row in query.all()}
    if not user_ids:
        return []
    return User.query.filter(User.id.in_(user_ids), User.is_active.is_(True)).all()


def notify_party(account, *, notification_type, title, message, priority, key):
    """Notifikasi ke portal pihak yang ditagih. Tidak commit."""
    from app.services.notification_service import create_or_update_notification

    for user in portal_users_for_party(account.party_type, account.party_id):
        create_or_update_notification(
            branch_id=account.branch_id,
            notification_type=notification_type,
            title=title,
            message=message,
            target_user_id=user.id,
            priority=priority,
            reference_type="CREDIT_ACCOUNT",
            reference_id=account.id,
            generated_key=f"{key}-{user.id}",
            commit=False,
        )


def _notify_internal(account, *, title, message, priority, key, roles=("OWNER", "ADMIN")):
    from app.services.notification_service import create_or_update_notification

    for role in roles:
        create_or_update_notification(
            branch_id=account.branch_id,
            notification_type="CREDIT_CONTROL",
            title=title,
            message=message,
            target_role=role,
            priority=priority,
            reference_type="CREDIT_ACCOUNT",
            reference_id=account.id,
            action_url=f"/credit/accounts/{account.id}",
            generated_key=f"{key}-{role}",
            commit=False,
        )


# --- kontrak & pihak ------------------------------------------------------------

def _party_client_id(account):
    if account.party_type == PARTY_CLIENT:
        return account.party_id
    mandor = db.session.get(Mandor, account.party_id)
    return getattr(mandor, "client_id", None)


def contract_for_account(account, on_date=None):
    from app.services.contract_rules_service import active_contract_for

    client_id = _party_client_id(account)
    if not client_id:
        return None
    return active_contract_for(client_id, on_date, branch_id=account.branch_id)


def tazir_amount_for(account, on_date=None):
    contract = contract_for_account(account, on_date)
    return (_money(getattr(contract, "tazir_amount", 0)), contract)


# --- usulan ta'zir (dipanggil penyapu harian, tidak commit) -----------------------

def _latest_block_event(account):
    return (
        CreditStatusEvent.query.filter_by(credit_account_id=account.id, to_status=STATUS_BLOCKED)
        .order_by(CreditStatusEvent.changed_at.desc(), CreditStatusEvent.id.desc())
        .first()
    )


def _propose(account, *, trigger, trigger_key, amount, reason, contract):
    exists = CreditCharge.query.filter_by(
        credit_account_id=account.id, charge_type=CHARGE_TAZIR, trigger_key=trigger_key
    ).first()
    if exists is not None:
        return None
    charge = CreditCharge(
        branch_id=account.branch_id,
        credit_account_id=account.id,
        charge_type=CHARGE_TAZIR,
        status=CHARGE_PROPOSED,
        trigger=trigger,
        trigger_key=trigger_key,
        amount=amount,
        reason=reason,
        contract_id=getattr(contract, "id", None),
    )
    db.session.add(charge)
    db.session.flush()
    name = party_name(account)
    _notify_internal(
        account,
        title=f"Usulan ta'zir: {name}",
        message=(
            f"{reason} Nominal kontrak {_rupiah(amount)} masuk Dana Sosial bila dikenakan. "
            "Owner memutuskan dikenakan atau tidak."
        ),
        priority="WARNING",
        key=f"tazir-proposal-{charge.id}",
        roles=("OWNER",),
    )
    return charge


def propose_tazir_for_account(account, decision, today):
    """Usulkan ta'zir untuk kejadian baru: janji bayar meleset atau masuk BLOKIR.

    Tidak ada usulan selama kelonggaran, untuk akun bayar di muka / hapus buku,
    atau bila kontraknya tidak mencantumkan nominal ta'zir.
    """
    from app.services.credit_control_service import broken_promises

    if account.billing_mode == BILLING_CASH or account.status == STATUS_WRITE_OFF:
        return []
    if account.grace_active(today) or not decision.enforced:
        return []
    amount, contract = tazir_amount_for(account, today)
    if amount <= ZERO:
        return []

    proposed = []
    since = today - timedelta(days=PROMISE_LOOKBACK_DAYS)
    for invoice_id, promised_for in broken_promises(account.branch_id, account.party_type, account.party_id, today):
        if promised_for < since:
            continue
        invoice = db.session.get(Invoice, invoice_id)
        number = getattr(invoice, "invoice_number", invoice_id)
        charge = _propose(
            account,
            trigger=TRIGGER_BROKEN_PROMISE,
            trigger_key=f"promise-{invoice_id}-{promised_for.isoformat()}",
            amount=amount,
            reason=f"Janji bayar invoice {number} tanggal {promised_for.strftime('%d-%m-%Y')} meleset.",
            contract=contract,
        )
        if charge:
            proposed.append(charge)

    if decision.status == STATUS_BLOCKED:
        event = _latest_block_event(account)
        key = f"blocked-{event.id}" if event else f"blocked-{(account.status_changed_at or datetime.utcnow()):%Y%m%d}"
        charge = _propose(
            account,
            trigger=TRIGGER_BLOCKED,
            trigger_key=key,
            amount=amount,
            reason=f"Status kredit Blokir. {decision.reason}",
            contract=contract,
        )
        if charge:
            proposed.append(charge)
    return proposed


# --- tagihan terpisah ------------------------------------------------------------

def _party_records(account):
    if account.party_type == PARTY_MANDOR:
        mandor = db.session.get(Mandor, account.party_id)
        client = db.session.get(Client, mandor.client_id) if mandor and mandor.client_id else None
        return client, mandor
    return db.session.get(Client, account.party_id), None


def _issue_charge_invoice(charge, account, actor, invoice_date, description):
    """Invoice terpisah untuk ta'zir/ta'widh + jurnalnya. Tidak commit."""
    from app.services.accounting_service import create_invoice_journal_for_invoice
    from app.services.auto_invoice_service import generate_invoice_number
    from app.services.contract_rules_service import due_days_for
    from app.services.invoice_identity_service import build_company_bank_snapshot, invoice_contact_snapshot

    client, mandor = _party_records(account)
    if client is None:
        raise CreditActionError("Data client pihak ini tidak ditemukan.")
    bill_to_type = "MANDOR" if account.party_type == PARTY_MANDOR else "CLIENT"
    contract = contract_for_account(account, invoice_date)
    contact, error = invoice_contact_snapshot(client, mandor, getattr(contract, "client_pic_id", None), bill_to_type)
    if error:
        raise CreditActionError(error)

    amount = _money(charge.amount)
    due_days = due_days_for(client.id, invoice_date, branch_id=account.branch_id)
    invoice = Invoice(
        branch_id=account.branch_id,
        invoice_number=generate_invoice_number(invoice_date),
        invoice_date=invoice_date,
        due_date=invoice_date + timedelta(days=due_days),
        bill_to_type=bill_to_type,
        client_id=client.id,
        mandor_id=getattr(mandor, "id", None),
        **contact,
        **build_company_bank_snapshot(account.branch_id),
        client_name_snapshot=mandor.name if mandor is not None else client.name,
        client_code_snapshot=getattr(client, "client_code", None),
        expected_payment_percent=100,
        total_amount=amount,
        paid_amount=0,
        remaining_amount=amount,
        status="DRAFT",
        notes=description,
        source_type=charge.charge_type,
        created_by=actor.id,
    )
    db.session.add(invoice)
    db.session.flush()
    db.session.add(InvoiceItem(
        invoice_id=invoice.id,
        item_type=charge.charge_type,
        description=description,
        qty=1,
        unit_price=amount,
        subtotal=amount,
        source_type="CREDIT_CHARGE",
        source_id=charge.id,
    ))
    db.session.flush()
    try:
        ok, message, _journal = create_invoice_journal_for_invoice(invoice=invoice, created_by=actor.id, commit=False)
    except Exception as error:  # akun COA kurang / tidak seimbang -> batal semua
        raise CreditActionError(f"Jurnal tagihan gagal dibuat: {error}") from error
    if not ok:
        raise CreditActionError(f"Jurnal tagihan gagal dibuat: {message}")
    return invoice


def _notify_charge_invoice(account, charge, invoice):
    label = "Tagihan ta'zir" if charge.charge_type == CHARGE_TAZIR else "Tagihan ganti biaya penagihan"
    note = (
        "Seluruhnya disalurkan sebagai Dana Sosial, bukan pendapatan perusahaan."
        if charge.charge_type == CHARGE_TAZIR else "Pengganti biaya penagihan yang benar-benar dikeluarkan."
    )
    notify_party(
        account,
        notification_type="INVOICE_ISSUED",
        title=f"{label} {invoice.invoice_number}",
        message=(
            f"{label} {_rupiah(invoice.total_amount)}, jatuh tempo {invoice.due_date.strftime('%d-%m-%Y')}. "
            f"{charge.reason} {note}"
        ),
        priority="WARNING",
        key=f"credit-charge-invoice-{invoice.id}",
    )


def decide_tazir(charge, form, actor, today=None):
    """OWNER memutuskan usulan ta'zir: dikenakan (tagihan terpisah) atau tidak."""
    _require_owner(actor)
    today = today or today_wib()
    if charge.charge_type != CHARGE_TAZIR or charge.status != CHARGE_PROPOSED:
        raise CreditActionError("Usulan ini sudah diputuskan.")
    decision = str(form.get("decision") or "").strip().upper()
    note = _clean(form.get("note"))
    account = db.session.get(CreditAccount, charge.credit_account_id)

    if decision == "DECLINE":
        if not note or len(note) < 5:
            raise CreditActionError("Tulis alasan singkat kenapa ta'zir tidak dikenakan.")

        def decline():
            charge.status = CHARGE_DECLINED
            charge.decided_by = actor.id
            charge.decided_at = datetime.utcnow()
            charge.decision_note = note
            return charge

        return _in_transaction(decline)

    if decision != "IMPOSE":
        raise CreditActionError("Pilih dikenakan atau tidak dikenakan.")
    if account.grace_active(today):
        raise CreditActionError("Pihak ini sedang dalam masa kelonggaran; ta'zir tidak boleh dikenakan.")
    if _money(charge.amount) <= ZERO:
        raise CreditActionError("Nominal ta'zir kontrak Rp0; tidak ada yang bisa ditagih.")

    def impose():
        description = (
            f"Ta'zir (sanksi keterlambatan, nominal tetap sesuai kontrak) — {charge.reason} "
            "Seluruhnya masuk Dana Sosial dan disalurkan, bukan pendapatan perusahaan."
        )
        invoice = _issue_charge_invoice(charge, account, actor, today, description)
        charge.status = CHARGE_IMPOSED
        charge.invoice_id = invoice.id
        charge.decided_by = actor.id
        charge.decided_at = datetime.utcnow()
        charge.decision_note = note
        _notify_charge_invoice(account, charge, invoice)
        return charge

    return _in_transaction(impose)


def create_tawidh(account, form, evidence_file, actor, today=None):
    """OWNER membebankan biaya penagihan riil (dengan bukti) sebagai tagihan terpisah."""
    from app.services.digital_attachment_service import AttachmentValidationError, stage_digital_attachment

    _require_owner(actor)
    today = today or today_wib()
    amount = parse_money(form.get("amount"))
    if amount <= ZERO:
        raise CreditActionError("Nominal biaya penagihan harus lebih dari 0.")
    reason = _clean(form.get("reason"))
    if not reason or len(reason) < 10:
        raise CreditActionError("Jelaskan biaya riilnya, mis. 'ongkos ke lokasi menagih 3x, nota terlampir'.")
    if evidence_file is None or not getattr(evidence_file, "filename", None):
        raise CreditActionError("Bukti biaya (foto nota/kuitansi) wajib dilampirkan.")

    def mutate():
        charge = CreditCharge(
            branch_id=account.branch_id,
            credit_account_id=account.id,
            charge_type=CHARGE_TAWIDH,
            status=CHARGE_IMPOSED,
            trigger=TRIGGER_MANUAL,
            trigger_key=f"tawidh-{datetime.utcnow():%Y%m%d%H%M%S%f}",
            amount=amount,
            reason=reason,
            contract_id=getattr(contract_for_account(account, today), "id", None),
            decided_by=actor.id,
            decided_at=datetime.utcnow(),
            created_by=actor.id,
        )
        db.session.add(charge)
        db.session.flush()
        try:
            attachment = stage_digital_attachment(
                file_storage=evidence_file,
                module=CREDIT_ATTACHMENT_MODULE,
                reference_type="CREDIT_CHARGE",
                reference_id=charge.id,
                attachment_type="BUKTI_BIAYA_PENAGIHAN",
                branch_id=account.branch_id,
                uploaded_by=actor.id,
                notes=reason,
            )
        except AttachmentValidationError as error:
            raise CreditActionError(str(error)) from error
        db.session.flush()
        charge.evidence_attachment_id = attachment.id
        description = f"Ta'widh (ganti biaya penagihan riil, bukti terlampir) — {reason}"
        invoice = _issue_charge_invoice(charge, account, actor, today, description)
        charge.invoice_id = invoice.id
        _notify_charge_invoice(account, charge, invoice)
        return charge

    return _in_transaction(mutate)


# --- kelonggaran -----------------------------------------------------------------

def set_grace(account, form, actor, today=None):
    """OWNER mencatat kelonggaran untuk pihak yang benar-benar tidak mampu."""
    from app.services.credit_account_service import _record_event
    from app.services.credit_control_service import evaluate_party

    _require_owner(actor)
    today = today or today_wib()
    until = _parse_date(form.get("grace_until"))
    if until is None or until < today:
        raise CreditActionError("Tanggal akhir kelonggaran wajib diisi dan tidak boleh sebelum hari ini.")
    reason = _clean(form.get("grace_reason"))
    if not reason or len(reason) < 10:
        raise CreditActionError("Alasan kelonggaran wajib jelas, mis. 'proyek berhenti, pembayaran dari owner proyek tertunda'.")
    decision = evaluate_party(account.branch_id, account.party_type, account.party_id, account, today=today)

    def mutate():
        account.grace_until = until
        account.grace_reason = reason
        account.grace_set_by = actor.id
        account.grace_set_at = datetime.utcnow()
        _record_event(
            account, decision.status, decision.status, "GRACE",
            f"Kelonggaran sampai {until.strftime('%d-%m-%Y')}: {reason}", decision, actor.id,
        )
        # Usulan ta'zir yang belum diputuskan gugur: yang tidak mampu tidak dikenai ta'zir.
        for charge in CreditCharge.query.filter_by(
            credit_account_id=account.id, charge_type=CHARGE_TAZIR, status=CHARGE_PROPOSED
        ).all():
            charge.status = CHARGE_DECLINED
            charge.decided_by = actor.id
            charge.decided_at = datetime.utcnow()
            charge.decision_note = "Gugur: pihak diberi kelonggaran (tidak mampu)."
        notify_party(
            account,
            notification_type="CREDIT_STATUS",
            title="Kelonggaran pembayaran",
            message=(
                f"Pembayaran tagihan lama ditangguhkan sampai {until.strftime('%d-%m-%Y')} tanpa ta'zir. "
                "Selama masa ini pesanan baru dibayar di muka."
            ),
            priority="INFO",
            key=f"credit-grace-{account.id}-{until.isoformat()}",
        )
        return account

    return _in_transaction(mutate)


def end_grace(account, actor, today=None):
    from app.services.credit_account_service import _record_event
    from app.services.credit_control_service import evaluate_party

    _require_owner(actor)
    today = today or today_wib()
    if not account.grace_until:
        raise CreditActionError("Pihak ini tidak sedang dalam kelonggaran.")
    decision = evaluate_party(account.branch_id, account.party_type, account.party_id, account, today=today)

    def mutate():
        _record_event(account, decision.status, decision.status, "GRACE_END", "Kelonggaran diakhiri OWNER.", decision, actor.id)
        account.grace_until = None
        account.grace_reason = None
        account.grace_set_by = actor.id
        account.grace_set_at = datetime.utcnow()
        return account

    return _in_transaction(mutate)


# --- Dana Sosial -----------------------------------------------------------------

def social_fund_summary(branch_id):
    """Terkumpul (ta'zir yang sudah dibayar), disalurkan, saldo siap salur, belum dibayar."""
    from sqlalchemy import func

    tazir = Invoice.query.filter(
        Invoice.branch_id == branch_id,
        Invoice.source_type == CHARGE_TAZIR,
        Invoice.status.notin_(("CANCELLED", "CANCELED")),
    )
    billed = _money(tazir.with_entities(func.coalesce(func.sum(Invoice.total_amount), 0)).scalar())
    collected = _money(tazir.with_entities(func.coalesce(func.sum(Invoice.paid_amount), 0)).scalar())
    unpaid = _money(
        tazir.filter(Invoice.status.notin_(("PAID", "CLOSED")))
        .with_entities(func.coalesce(func.sum(Invoice.remaining_amount), 0)).scalar()
    )
    disbursed = _money(
        db.session.query(func.coalesce(func.sum(SocialFundDisbursement.amount), 0))
        .filter(SocialFundDisbursement.branch_id == branch_id).scalar()
    )
    return {
        "billed": billed,
        "collected": collected,
        "unpaid": unpaid,
        "disbursed": disbursed,
        "available": max(collected - disbursed, ZERO),
    }


def record_disbursement(branch_id, form, evidence_file, actor):
    """OWNER menyalurkan Dana Sosial: kas/bank keluar + Dr 2009 / Cr kas/bank."""
    from app.models.finance import BankAccount, CashBankTransaction
    from app.services.accounting_service import SOCIAL_FUND_ACCOUNT_CODE
    from app.services.cash_bank_service import (
        calculate_account_balance,
        cash_bank_coa_code,
        get_account_label,
        normalize_cash_bank_account,
        post_cash_bank_journal,
    )
    from app.services.digital_attachment_service import AttachmentValidationError, stage_digital_attachment

    _require_owner(actor)
    disbursed_on = _parse_date(form.get("disbursed_on")) or today_wib()
    recipient = _clean(form.get("recipient"))
    purpose = _clean(form.get("purpose"))
    amount = parse_money(form.get("amount"))
    if not recipient:
        raise CreditActionError("Penerima wajib diisi (mis. 'Masjid Al-Ikhlas Kayuagung').")
    if not purpose or len(purpose) < 5:
        raise CreditActionError("Tujuan penyaluran wajib diisi.")
    if amount <= ZERO:
        raise CreditActionError("Nominal penyaluran harus lebih dari 0.")
    available = social_fund_summary(branch_id)["available"]
    if amount > available:
        raise CreditActionError(
            f"Dana Sosial yang sudah diterima dan belum disalurkan hanya {_rupiah(available)}."
        )
    if evidence_file is None or not getattr(evidence_file, "filename", None):
        raise CreditActionError("Bukti penyaluran (foto kuitansi/serah terima) wajib dilampirkan.")

    def mutate():
        try:
            account_type, bank_account_id, _ = normalize_cash_bank_account(
                form.get("account_type"), _int_or_none(form.get("bank_account_id")), branch_id=branch_id
            )
        except Exception as error:
            raise CreditActionError(str(error)) from error
        balance = calculate_account_balance(branch_id, account_type, bank_account_id)
        if float(amount) > float(balance):
            raise CreditActionError(f"Saldo kas/bank tidak cukup. Saldo tersedia {_rupiah(balance)}.")
        bank_account = db.session.get(BankAccount, bank_account_id) if bank_account_id else None
        label = get_account_label(account_type, bank_account)

        record = SocialFundDisbursement(
            branch_id=branch_id,
            disbursed_on=disbursed_on,
            recipient=recipient,
            purpose=purpose,
            amount=amount,
            account_type=account_type,
            bank_account_id=bank_account_id,
            created_by=actor.id,
        )
        db.session.add(record)
        db.session.flush()

        ledger = CashBankTransaction(
            branch_id=branch_id,
            transaction_date=disbursed_on,
            account_type=account_type,
            bank_account_id=bank_account_id,
            transaction_type="OUT",
            amount=float(amount),
            description=f"Penyaluran Dana Sosial ke {recipient} ({label}): {purpose}",
            reference_type=SOCIAL_FUND_REFERENCE,
            reference_id=record.id,
            created_by=actor.id,
        )
        db.session.add(ledger)
        db.session.flush()
        record.cash_bank_transaction_id = ledger.id
        post_cash_bank_journal(
            journal_date=disbursed_on,
            reference_type=SOCIAL_FUND_REFERENCE,
            reference_id=record.id,
            description=f"Penyaluran Dana Sosial ke {recipient}: {purpose}",
            debit_code=SOCIAL_FUND_ACCOUNT_CODE,
            credit_code=cash_bank_coa_code(account_type, bank_account_id),
            amount=float(amount),
            created_by=actor.id,
        )
        try:
            attachment = stage_digital_attachment(
                file_storage=evidence_file,
                module=CREDIT_ATTACHMENT_MODULE,
                reference_type=SOCIAL_FUND_REFERENCE,
                reference_id=record.id,
                attachment_type="BUKTI_PENYALURAN_DANA_SOSIAL",
                branch_id=branch_id,
                uploaded_by=actor.id,
                notes=f"{recipient}: {purpose}",
            )
        except AttachmentValidationError as error:
            raise CreditActionError(str(error)) from error
        db.session.flush()
        record.evidence_attachment_id = attachment.id
        return record

    return _in_transaction(mutate)


def list_disbursements(branch_id, limit=100):
    return (
        SocialFundDisbursement.query.filter_by(branch_id=branch_id)
        .order_by(SocialFundDisbursement.disbursed_on.desc(), SocialFundDisbursement.id.desc())
        .limit(limit).all()
    )


def list_charges(branch_id, *, status=None, account_id=None, limit=100):
    query = CreditCharge.query.filter_by(branch_id=branch_id)
    if status:
        query = query.filter_by(status=status)
    if account_id:
        query = query.filter_by(credit_account_id=account_id)
    rows = query.order_by(CreditCharge.created_at.desc(), CreditCharge.id.desc()).limit(limit).all()
    return [
        {
            "charge": charge,
            "name": party_name(charge.account),
            "type_label": CHARGE_LABELS.get(charge.charge_type, charge.charge_type),
            "status_label": CHARGE_STATUS_LABELS.get(charge.status, charge.status),
            "trigger_label": TRIGGER_LABELS.get(charge.trigger, charge.trigger),
        }
        for charge in rows
    ]


def pending_tazir_count(branch_id):
    return CreditCharge.query.filter_by(
        branch_id=branch_id, charge_type=CHARGE_TAZIR, status=CHARGE_PROPOSED
    ).count()


def credit_attachment_or_none(attachment_id, branch_id):
    """Lampiran modul kredit (bukti ta'widh / penyaluran) milik cabang ini."""
    from app.models.system import DigitalAttachment

    attachment = db.session.get(DigitalAttachment, attachment_id)
    if attachment is None or attachment.is_deleted or attachment.module != CREDIT_ATTACHMENT_MODULE:
        return None
    if attachment.branch_id not in (None, branch_id):
        return None
    return attachment


