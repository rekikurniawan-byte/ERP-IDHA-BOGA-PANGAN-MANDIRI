"""Tindakan atas akun kredit: setel, deposit, ubah status, hapus buku, penyapu.

credit_control_service hanya MENILAI. Modul ini yang MENGUBAH data, dan
setiap perubahan meninggalkan jejak: credit_status_events untuk perpindahan
status, jurnal otomatis untuk setiap uang yang bergerak, audit log untuk
perubahan syarat kredit.

Siapa boleh apa (keputusan owner 2026-09-25):
- menyetel kredit, menurunkan/menaikkan status, melepas sementara,
  memotong dan mengembalikan deposit, hapus buku: hanya OWNER;
- menerima deposit: ADMIN atau OWNER -- itu uang masuk biasa.

Alur lengkapnya di BLUEPRINT_V2_KONTROL_KREDIT.md.
"""
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import sqlalchemy as sa

from app.extensions import db
from app.models.accounting import Journal, JournalDetail
from app.models.credit import (
    BILLING_CASH,
    BILLING_DIRECT,
    BILLING_VIA_CLIENT,
    CREDIT_STATUS_ORDER,
    PARTY_CLIENT,
    PARTY_MANDOR,
    STATUS_ACTIVE,
    STATUS_BLOCKED,
    STATUS_HOLD,
    STATUS_WATCH,
    STATUS_WRITE_OFF,
    CreditAccount,
    CreditStatusEvent,
)
from app.models.finance import AdvanceSettlement, AdvanceTransaction, Invoice, InvoiceCollectionLog, Payment
from app.models.master import BranchSetting, Mandor
from app.services.credit_control_service import (
    STATUS_LABELS,
    ZERO,
    _money,
    _rupiah,
    evaluate_party,
    get_credit_account,
    get_or_create_credit_account,
    get_thresholds,
    suggest_credit_limit,
)
from app.utils.roles import effective_role
from app.utils.terms import T
from app.utils.terms import L


class CreditActionError(ValueError):
    """Tindakan kredit ditolak; pesannya aman ditampilkan ke pengguna."""


OWNER = "OWNER"
BILLING_MODES = (BILLING_VIA_CLIENT, BILLING_DIRECT, BILLING_CASH)
BILLING_MODE_LABELS = {
    BILLING_VIA_CLIENT: L("Ditagih lewat {client_lower}-nya"),
    BILLING_DIRECT: L("Ditagih langsung ke {sub_client_lower} (kredit)"),
    BILLING_CASH: "Bayar di muka",
}
# Status yang boleh disetel OWNER lewat tombol. HAPUS BUKU tidak ada di sini:
# itu hanya lewat confirm_write_off, karena ikut memindahkan jurnal.
MANUAL_STATUSES = (STATUS_ACTIVE, STATUS_WATCH, STATUS_HOLD, STATUS_BLOCKED)
# Identitas yang pemiliknya berstatus ini tidak boleh dapat kredit langsung lagi.
BLACKLIST_STATUSES = (STATUS_BLOCKED, STATUS_WRITE_OFF)

SETTLED_INVOICE_STATUSES = ("CANCELLED", "CANCELED", "PAID", "CLOSED")
WRITE_OFF_REFERENCE_TYPE = "CREDIT_WRITE_OFF"
WRITE_OFF_ACCOUNT_CODE = "5013"
RECEIVABLE_ACCOUNT_CODE = "1004"
LAST_SWEEP_KEY = "credit.last_sweep_date"
# Kunci advisory lock Postgres untuk penyapu: (konstanta, branch_id).
SWEEP_LOCK_KEY = 7201
NOTIFY_ROLES = ("OWNER", "ADMIN")
STATUS_PRIORITY = {
    STATUS_WATCH: "INFO",
    STATUS_HOLD: "WARNING",
    STATUS_BLOCKED: "CRITICAL",
    STATUS_WRITE_OFF: "CRITICAL",
}


# --- utilitas -----------------------------------------------------------------

def _rank(status):
    return CREDIT_STATUS_ORDER.index(status) if status in CREDIT_STATUS_ORDER else 0


def _require_owner(actor):
    if actor is None or effective_role(getattr(actor, "role", None)) != OWNER:
        raise CreditActionError("Hanya OWNER yang boleh melakukan ini.")


def _require_internal(actor):
    if actor is None or effective_role(getattr(actor, "role", None)) not in (OWNER, "ADMIN"):
        raise CreditActionError("Hanya OWNER atau ADMIN yang boleh melakukan ini.")


def parse_money(value):
    """Uang dari form: "1.500.000", "Rp 1.500.000", "1500000", "1.500.000,50"."""
    text = str(value or "").replace("Rp", "").replace(" ", "").strip()
    if not text:
        return ZERO
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    else:
        text = text.replace(".", "")
    try:
        amount = Decimal(text)
    except InvalidOperation:
        raise CreditActionError(f"Nominal tidak valid: {value}")
    if amount < 0:
        raise CreditActionError("Nominal tidak boleh minus.")
    return amount


def parse_int(value, label):
    text = str(value or "").strip()
    if not text:
        return 0
    try:
        number = int(text)
    except ValueError:
        raise CreditActionError(f"{label} harus angka bulat.")
    if number < 0:
        raise CreditActionError(f"{label} tidak boleh minus.")
    return number


def _clean(value):
    return str(value or "").strip() or None


def _mandor_account(mandor):
    return get_credit_account(mandor.branch_id, PARTY_MANDOR, mandor.id)


def _notify(account, title, message, priority, key_suffix):
    from app.services.notification_service import create_or_update_notification

    for role in NOTIFY_ROLES:
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
            generated_key=f"credit-{account.id}-{key_suffix}-{role}",
            metadata={"credit_account_id": account.id, "mutation_scope": "NOTIFICATION_ONLY"},
            commit=False,
        )


def _record_event(account, from_status, to_status, trigger, reason, decision=None, actor_id=None):
    db.session.add(CreditStatusEvent(
        branch_id=account.branch_id,
        credit_account_id=account.id,
        from_status=from_status,
        to_status=to_status,
        trigger=trigger,
        reason=reason,
        exposure_amount=getattr(decision, "exposure", None),
        credit_limit=getattr(decision, "credit_limit", None),
        oldest_days_overdue=getattr(decision, "oldest_days_overdue", None),
        changed_by=actor_id,
        changed_at=datetime.utcnow(),
    ))


def party_name(account):
    if account.party_type == PARTY_MANDOR:
        mandor = db.session.get(Mandor, account.party_id)
        return mandor.name if mandor else f"{T.sub_client} #{account.party_id}"
    from app.models.master import Client

    client = db.session.get(Client, account.party_id)
    return client.name if client else f"{T.client} #{account.party_id}"


def _in_transaction(action):
    """Satu batas transaksi untuk setiap tindakan kredit: semua atau tidak sama sekali.

    Kesalahan dari mesin uang muka (advance_service) berupa Exception biasa
    dengan pesan yang memang untuk pengguna, jadi diteruskan sebagai
    CreditActionError supaya route bisa menampilkannya.
    """
    try:
        result = action()
        db.session.commit()
        return result
    except CreditActionError:
        db.session.rollback()
        raise
    except Exception as error:
        db.session.rollback()
        raise CreditActionError(str(error)) from error


# --- daftar cekal identitas ---------------------------------------------------

def find_blacklisted_identity(id_number, exclude_mandor_id=None):
    """Mandor lain dengan NIK yang sama yang sudah diblokir atau dihapus buku.

    Tanpa ini, mandor yang kabur bisa mendaftar lagi besok sebagai baris
    mandor baru dengan nama sedikit berbeda dan langsung dapat kredit lagi.
    """
    id_number = _clean(id_number)
    if not id_number:
        return []
    query = (
        db.session.query(Mandor, CreditAccount)
        .join(
            CreditAccount,
            sa.and_(
                CreditAccount.party_type == PARTY_MANDOR,
                CreditAccount.party_id == Mandor.id,
            ),
        )
        .filter(Mandor.id_number == id_number, CreditAccount.status.in_(BLACKLIST_STATUSES))
    )
    if exclude_mandor_id:
        query = query.filter(Mandor.id != exclude_mandor_id)
    return query.all()


# --- setel kredit ---------------------------------------------------------------

def save_credit_settings(mandor, form, actor):
    """Simpan syarat kredit dan identitas mandor. Hanya OWNER."""
    _require_owner(actor)

    billing_mode = str(form.get("billing_mode") or "").strip().upper()
    if billing_mode not in BILLING_MODES:
        raise CreditActionError("Mode penagihan tidak valid.")
    if getattr(mandor, "is_direct_unit", False) and billing_mode != BILLING_VIA_CLIENT:
        # Unit order langsung adalah client itu sendiri: tagihannya ke PT,
        # dan remnya limit kontrak client.
        raise CreditActionError(
            f"Unit order langsung ditagih ke client-nya sendiri. Atur kreditnya lewat limit kontrak {T.client_lower}."
        )

    credit_limit = parse_money(form.get("credit_limit"))
    terms_days = parse_int(form.get("payment_terms_days"), "Termin")
    deposit_percent = parse_money(form.get("deposit_percent"))
    if deposit_percent > 100:
        raise CreditActionError("Syarat deposit maksimal 100% dari limit.")

    identity = {
        "id_number": _clean(form.get("id_number")),
        "address": _clean(form.get("address")),
        "guarantor_name": _clean(form.get("guarantor_name")),
        "guarantor_phone": _clean(form.get("guarantor_phone")),
        "guarantor_id_number": _clean(form.get("guarantor_id_number")),
    }

    if billing_mode == BILLING_DIRECT:
        missing = []
        if credit_limit <= 0:
            missing.append("limit kredit")
        if terms_days <= 0:
            missing.append("termin (hari)")
        if not identity["id_number"]:
            missing.append("NIK")
        if not identity["address"]:
            missing.append("alamat")
        if missing:
            raise CreditActionError(
                f"{T.sub_client} yang ditagih langsung wajib punya: " + ", ".join(missing) + "."
            )
        blocked = find_blacklisted_identity(identity["id_number"], exclude_mandor_id=mandor.id)
        if blocked:
            names = ", ".join(
                f"{row_mandor.name} ({STATUS_LABELS.get(row_account.status, row_account.status)})"
                for row_mandor, row_account in blocked
            )
            raise CreditActionError(
                f"NIK ini milik {T.sub_client_lower} yang sudah diblokir/dihapus buku: {names}. "
                "Kredit langsung tidak bisa diberikan."
            )

    def mutate():
        from app.services.audit_log_service import record_audit_log

        account = get_or_create_credit_account(mandor.branch_id, PARTY_MANDOR, mandor.id)
        old = {
            "billing_mode": account.billing_mode,
            "credit_limit": str(account.credit_limit),
            "payment_terms_days": account.payment_terms_days,
            "deposit_percent": str(account.deposit_percent),
        }
        account.billing_mode = billing_mode
        account.credit_limit = credit_limit
        account.payment_terms_days = terms_days
        account.deposit_percent = deposit_percent
        account.notes = _clean(form.get("notes"))
        for key, value in identity.items():
            setattr(mandor, key, value)
        record_audit_log(
            module="CREDIT",
            event_type="CREDIT_SETTINGS_SAVED",
            action="UPDATE",
            table_name="credit_accounts",
            record_id=account.id,
            description=f"Syarat kredit {mandor.name} disetel.",
            old_value=old,
            new_value={
                "billing_mode": billing_mode,
                "credit_limit": str(credit_limit),
                "payment_terms_days": terms_days,
                "deposit_percent": str(deposit_percent),
            },
            user_id=actor.id,
            branch_id=mandor.branch_id,
            commit=False,
        )
        return account

    return _in_transaction(mutate)


def default_settings_for(mandor, today=None):
    """Nilai awal form untuk mandor yang belum disetel: termin, usulan limit, deposit %."""
    thresholds = get_thresholds(mandor.branch_id)
    terms = thresholds["credit.terms_days_direct"]
    return {
        "payment_terms_days": terms,
        "deposit_percent": thresholds["credit.deposit_percent"],
        "suggested_limit": suggest_credit_limit(mandor.branch_id, mandor.id, terms, today=today),
    }


# --- deposit ------------------------------------------------------------------

def _open_deposits(mandor):
    from app.services.advance_service import MANDOR_SECURITY_DEPOSIT

    return (
        AdvanceTransaction.query.filter(
            AdvanceTransaction.branch_id == mandor.branch_id,
            AdvanceTransaction.mandor_id == mandor.id,
            AdvanceTransaction.advance_type == MANDOR_SECURITY_DEPOSIT,
            AdvanceTransaction.status.in_(("OPEN", "PARTIAL")),
        )
        .order_by(AdvanceTransaction.advance_date.asc(), AdvanceTransaction.id.asc())
        .all()
    )


def receive_deposit(mandor, form, actor, today=None):
    """Terima deposit jaminan: kas/bank masuk + jurnal Cr 2007, satu transaksi."""
    from app.services.advance_service import MANDOR_SECURITY_DEPOSIT, create_advance_transaction

    _require_internal(actor)
    account = _mandor_account(mandor)
    if account is None or account.billing_mode != BILLING_DIRECT:
        raise CreditActionError(f"Setel {T.sub_client_lower} ini ke 'Ditagih langsung' dulu sebelum menerima deposit.")

    amount = parse_money(form.get("amount"))
    if amount <= 0:
        raise CreditActionError("Nominal deposit harus lebih dari 0.")
    deposit_date = _parse_date(form.get("deposit_date")) or (today or date.today())

    def mutate():
        _, _, advance = create_advance_transaction(
            branch_id=mandor.branch_id,
            advance_date=deposit_date,
            advance_type=MANDOR_SECURITY_DEPOSIT,
            payment_method=form.get("payment_method"),
            amount=amount,
            created_by=actor.id,
            mandor_id=mandor.id,
            bank_account_id=_int_or_none(form.get("bank_account_id")),
            reference_number=_clean(form.get("reference_number")),
            notes=_clean(form.get("notes")),
            commit=False,
        )
        return advance

    return _in_transaction(mutate)


def _require_invoice_journal(invoice):
    """Piutang invoice harus sudah dijurnal sebelum dikredit dari 1004.

    Tanpa ini, memotong deposit atau menghapus buku invoice yang belum
    dijurnal akan membuat 1004 Piutang Usaha minus.
    """
    from app.services.accounting_service import receivable_is_journaled

    if not receivable_is_journaled(invoice):
        raise CreditActionError(
            f"Invoice {invoice.invoice_number} belum dijurnal. Posting jurnal invoice dulu, "
            "baru deposit bisa dipotong atau piutangnya dihapus buku."
        )


def _unpaid_invoices(mandor):
    return (
        Invoice.query.filter(
            Invoice.branch_id == mandor.branch_id,
            Invoice.mandor_id == mandor.id,
            Invoice.status.notin_(SETTLED_INVOICE_STATUSES),
            Invoice.remaining_amount > 0,
        )
        .order_by(Invoice.due_date.asc(), Invoice.id.asc())
        .all()
    )


def _apply_deposit(mandor, invoice, amount, actor, settle_date, notes):
    """Potong deposit (tertua dulu) ke satu invoice. Tidak commit."""
    from app.services.advance_service import DEPOSIT_TO_INVOICE, create_advance_settlement

    remaining_to_apply = min(_money(amount), _money(invoice.remaining_amount))
    applied = ZERO
    for advance in _open_deposits(mandor):
        if remaining_to_apply <= 0:
            break
        part = min(_money(advance.remaining_amount), remaining_to_apply)
        if part <= 0:
            continue
        create_advance_settlement(
            advance=advance,
            settlement_date=settle_date,
            settlement_type=DEPOSIT_TO_INVOICE,
            amount=float(part),
            created_by=actor.id,
            reference_id=invoice.id,
            notes=notes,
            commit=False,
        )
        remaining_to_apply -= part
        applied += part
    return applied


def apply_deposit_to_invoice(mandor, form, actor, today=None):
    """OWNER memotong deposit untuk menutup hutang satu invoice mandor ini."""
    _require_owner(actor)
    invoice = Invoice.query.filter_by(
        id=_int_or_none(form.get("invoice_id")), branch_id=mandor.branch_id, mandor_id=mandor.id,
    ).first()
    if invoice is None:
        raise CreditActionError(f"Invoice tidak ditemukan untuk {T.sub_client_lower} ini.")
    _require_invoice_journal(invoice)
    amount = parse_money(form.get("amount")) or _money(invoice.remaining_amount)

    def mutate():
        applied = _apply_deposit(
            mandor, invoice, amount, actor, today or date.today(),
            _clean(form.get("notes")) or "Deposit dipotong oleh OWNER.",
        )
        if applied <= 0:
            raise CreditActionError("Tidak ada deposit yang bisa dipotong.")
        return applied

    return _in_transaction(mutate)


def refund_deposit(mandor, form, actor, today=None):
    """OWNER mengembalikan deposit: Dr 2007, Cr Kas/Bank + kas keluar."""
    from app.services.advance_service import DEPOSIT_REFUND, create_advance_settlement

    _require_owner(actor)
    deposits = _open_deposits(mandor)
    available = sum((_money(row.remaining_amount) for row in deposits), ZERO)
    amount = parse_money(form.get("amount")) or available
    if amount <= 0 or amount > available:
        raise CreditActionError(f"Nominal pengembalian harus antara Rp 1 dan {_rupiah(available)}.")

    def mutate():
        remaining = amount
        for advance in deposits:
            if remaining <= 0:
                break
            part = min(_money(advance.remaining_amount), remaining)
            create_advance_settlement(
                advance=advance,
                settlement_date=today or date.today(),
                settlement_type=DEPOSIT_REFUND,
                amount=float(part),
                created_by=actor.id,
                notes=_clean(form.get("notes")) or f"Deposit dikembalikan ke {T.sub_client_lower}.",
                commit=False,
                payment_method=form.get("payment_method"),
                bank_account_id=_int_or_none(form.get("bank_account_id")),
            )
            remaining -= part
        return amount

    return _in_transaction(mutate)


# --- status -------------------------------------------------------------------

def change_credit_status(account, form, actor, today=None):
    """OWNER menaikkan atau menurunkan status, dengan alasan tertulis.

    Menurunkan status hanya berarti selama angkanya sudah membaik -- gerbang
    selalu memakai status yang lebih ketat. Kalau OWNER memberi kesempatan
    walaupun tunggakan masih tua (misalnya ada komitmen bayar tertulis), dia
    mengisi "lepas sampai": sampai tanggal itu status OWNER yang berlaku.
    """
    _require_owner(actor)
    today = today or date.today()
    to_status = str(form.get("status") or "").strip().upper()
    if to_status not in MANUAL_STATUSES:
        raise CreditActionError("Status tidak valid. Hapus buku dilakukan lewat tombol hapus buku.")
    reason = _clean(form.get("reason"))
    if not reason or len(reason) < 10:
        raise CreditActionError(
            "Alasan wajib diisi dengan jelas, misalnya 'sudah bayar Rp 5.000.000 tgl 20-09' "
            "atau 'komitmen tertulis bayar lunas tgl 30-09'."
        )
    release_until = _parse_date(form.get("release_until"))
    if release_until and release_until < today:
        raise CreditActionError("Tanggal lepas sementara tidak boleh sebelum hari ini.")

    decision = evaluate_party(account.branch_id, account.party_type, account.party_id, account, today=today)

    def mutate():
        from_status = decision.status
        account.status = to_status
        account.status_reason = reason
        account.status_changed_at = datetime.utcnow()
        account.status_changed_by = actor.id
        account.release_until = release_until

        detail = f" Dilepas sampai {release_until.strftime('%d-%m-%Y')}." if release_until else ""
        _record_event(account, from_status, to_status, "MANUAL", reason + detail, decision, actor.id)
        _notify(
            account,
            title=f"Status kredit {party_name(account)}: {STATUS_LABELS[to_status]}",
            message=f"Diubah OWNER dari {STATUS_LABELS.get(from_status, from_status)}. {reason}{detail}",
            priority=STATUS_PRIORITY.get(to_status, "INFO"),
            key_suffix=f"manual-{datetime.utcnow():%Y%m%d%H%M%S}",
        )
        return account

    return _in_transaction(mutate)


def confirm_write_off(account, form, actor, today=None):
    """OWNER menghapus buku hutang mandor yang sudah lewat ambang hapus buku.

    Urutannya: deposit dipotong dulu ke invoice tertua, sisanya dijurnal
    Dr 5013 Beban Piutang Tak Tertagih / Cr 1004 Piutang Usaha, invoice
    ditutup (CLOSED, sisa 0), mandor dinonaktifkan, dan NIK-nya otomatis
    masuk daftar cekal. Semuanya satu transaksi: kalau satu langkah gagal,
    tidak ada yang berubah. Kalau kelak ada uang yang kembali, catat sebagai
    pendapatan lain-lain -- invoicenya sudah ditutup.
    """
    from app.services.accounting_service import generate_journal_number
    from app.services.advance_service import get_account_by_code

    _require_owner(actor)
    today = today or date.today()
    if account.party_type != PARTY_MANDOR:
        raise CreditActionError(f"Hapus buku lewat kontrol kredit hanya untuk {T.sub_client_lower}.")
    decision = evaluate_party(account.branch_id, account.party_type, account.party_id, account, today=today)
    if decision.derived_status != STATUS_WRITE_OFF and account.status != STATUS_WRITE_OFF:
        limit_days = get_thresholds(account.branch_id)["credit.write_off_days_overdue"]
        raise CreditActionError(
            f"Hapus buku baru boleh setelah tunggakan tertua {limit_days} hari "
            f"(sekarang {decision.oldest_days_overdue} hari). Sampai saat itu, blokir mandornya "
            "dan potong depositnya ke invoice."
        )
    reason = _clean(form.get("reason"))
    if not reason or len(reason) < 10:
        raise CreditActionError("Alasan hapus buku wajib diisi dengan jelas.")

    mandor = db.session.get(Mandor, account.party_id)
    invoices = _unpaid_invoices(mandor)
    for invoice in invoices:
        _require_invoice_journal(invoice)

    from app.services.accounting_service import SOCIAL_FUND_ACCOUNT_CODE

    acc_expense = get_account_by_code(WRITE_OFF_ACCOUNT_CODE)
    acc_receivable = get_account_by_code(RECEIVABLE_ACCOUNT_CODE)
    if not acc_expense or not acc_receivable:
        raise CreditActionError("Akun 5013 Beban Piutang Tak Tertagih atau 1004 Piutang Usaha belum tersedia.")
    # Ta'zir yang tidak tertagih tidak pernah menjadi pendapatan, jadi menghapusnya
    # mengurangi Dana Sosial yang sudah dicatat, bukan menambah beban.
    acc_social_fund = get_account_by_code(SOCIAL_FUND_ACCOUNT_CODE)
    if any(invoice.source_type == "TAZIR" for invoice in invoices) and not acc_social_fund:
        raise CreditActionError("Akun 2009 Dana Sosial belum tersedia.")

    def mutate():
        written_off = ZERO
        deposit_used = ZERO
        for invoice in invoices:
            deposit_used += _apply_deposit(
                mandor, invoice, invoice.remaining_amount, actor, today,
                f"Deposit dipotong sebelum hapus buku. {reason}",
            )
            db.session.flush()
            remaining = _money(invoice.remaining_amount)
            if remaining <= 0:
                continue
            journal = Journal(
                journal_number=generate_journal_number(today),
                journal_date=today,
                reference_type=WRITE_OFF_REFERENCE_TYPE,
                reference_id=invoice.id,
                description=f"Hapus buku piutang {invoice.invoice_number} - {mandor.name}",
                created_by=actor.id,
            )
            db.session.add(journal)
            db.session.flush()
            debit_account = acc_social_fund if invoice.source_type == "TAZIR" else acc_expense
            db.session.add(JournalDetail(journal_id=journal.id, account_id=debit_account.id, debit=float(remaining), credit=0))
            db.session.add(JournalDetail(journal_id=journal.id, account_id=acc_receivable.id, debit=0, credit=float(remaining)))
            invoice.remaining_amount = 0
            invoice.status = "CLOSED"
            invoice.notes = (
                f"{invoice.notes or ''}\n[HAPUS BUKU {today:%d-%m-%Y}] {_rupiah(remaining)} "
                f"dijurnal {journal.journal_number}. {reason}"
            ).strip()
            written_off += remaining

        from_status = decision.status
        account.status = STATUS_WRITE_OFF
        account.status_reason = reason
        account.status_changed_at = datetime.utcnow()
        account.status_changed_by = actor.id
        account.release_until = None
        mandor.is_active = False
        summary = (
            f"{reason} Deposit dipotong {_rupiah(deposit_used)}, "
            f"dihapus buku {_rupiah(written_off)}."
        )
        _record_event(account, from_status, STATUS_WRITE_OFF, "WRITE_OFF", summary, decision, actor.id)
        _notify(
            account,
            title=f"Hapus buku: {mandor.name}",
            message=summary,
            priority="CRITICAL",
            key_suffix=f"writeoff-{today:%Y%m%d}",
        )
        return {"deposit_used": deposit_used, "written_off": written_off}

    return _in_transaction(mutate)


# --- penyapu harian -------------------------------------------------------------

def sweep_credit_statuses(branch_id, actor_id=None, today=None):
    """Naikkan status akun yang memburuk. Tidak pernah menurunkan.

    Gerbang order tidak bergantung pada ini -- gerbang selalu menghitung
    ulang. Penyapu ada untuk mencatat perpindahan status (tanggal dan angkanya
    dibekukan di credit_status_events) dan memberi tahu OWNER dan ADMIN.
    Tidak commit; pemanggil yang commit.
    """
    from app.services.sharia_credit_service import notify_party, propose_tazir_for_account

    today = today or date.today()
    accounts = CreditAccount.query.filter(
        CreditAccount.branch_id == branch_id,
        CreditAccount.is_active.is_(True),
        CreditAccount.billing_mode != BILLING_CASH,
    ).all()
    # Client kontrak juga tunduk pada aturan kontrak (Fase 7): semuanya didaftarkan
    # supaya tampil di Kontrol Kredit sejak awal, bukan baru setelah statusnya naik.
    for client_id in contract_clients_without_account(branch_id):
        accounts.append(get_or_create_credit_account(branch_id, PARTY_CLIENT, client_id))
    checked = len(accounts)

    escalated = []
    proposals = []
    for account in accounts:
        decision = evaluate_party(branch_id, account.party_type, account.party_id, account, today=today)
        if decision.enforced and _rank(decision.status) > _rank(account.status):
            from_status = account.status
            account.status = decision.status
            account.status_reason = decision.reason
            account.status_changed_at = datetime.utcnow()
            account.status_changed_by = actor_id
            _record_event(account, from_status, decision.status, "SWEEP", decision.reason, decision, actor_id)
            name = party_name(account)
            _notify(
                account,
                title=f"Kredit {name}: {STATUS_LABELS[decision.status]}",
                message=(
                    f"Naik dari {STATUS_LABELS.get(from_status, from_status)}. {decision.reason} "
                    f"Exposure {_rupiah(decision.exposure)} dari limit {_rupiah(decision.credit_limit)}."
                ),
                priority=STATUS_PRIORITY.get(decision.status, "INFO"),
                key_suffix=f"sweep-{decision.status}-{today:%Y%m%d}",
            )
            notify_party(
                account,
                notification_type="CREDIT_STATUS",
                title=f"Status pembayaran: {STATUS_LABELS[decision.status]}",
                message=f"{PARTY_STATUS_MESSAGES.get(decision.status, '')} {decision.reason}".strip(),
                priority=STATUS_PRIORITY.get(decision.status, "INFO"),
                key=f"credit-party-{account.id}-{decision.status}-{today:%Y%m%d}",
            )
            escalated.append({"account_id": account.id, "name": party_name(account), "from": from_status, "to": decision.status})
        proposals.extend(propose_tazir_for_account(account, decision, today))

    return {"checked": checked, "escalated": escalated, "tazir_proposed": len(proposals)}


# Pesan untuk portal pihak yang ditagih: apa akibatnya dan apa yang harus dilakukan.
PARTY_STATUS_MESSAGES = {
    STATUS_WATCH: "Ada tagihan yang lewat jatuh tempo. Mohon segera dibayar agar pesanan tetap lancar.",
    STATUS_HOLD: "Tagihan sudah lama lewat jatuh tempo. Pesanan baru ditahan dan wajib dibayar di muka sampai tunggakan dibayar.",
    STATUS_BLOCKED: "Pesanan baru dihentikan karena tunggakan. Hubungi admin dan lunasi tagihan untuk membuka kembali.",
    STATUS_WRITE_OFF: "Tunggakan sudah sangat lama. Hubungi admin.",
}


def contract_clients_without_account(branch_id):
    from app.models.contract import CustomerContract

    configured = {
        row.party_id for row in CreditAccount.query.filter_by(branch_id=branch_id, party_type=PARTY_CLIENT)
        .with_entities(CreditAccount.party_id).all()
    }
    client_ids = {
        row.client_id for row in CustomerContract.query.filter_by(branch_id=branch_id, status="ACTIVE")
        .with_entities(CustomerContract.client_id).all()
    }
    return sorted(client_ids - configured)


def daily_sweep(branch_id, actor_id=None, today=None):
    """Semua pekerjaan harian satu cabang. Tidak commit.

    Kontrak lebih dulu: kontrak yang habis melepas limit dan termin kontraknya,
    jadi status kredit sesudahnya dihitung dengan aturan yang benar.
    """
    from app.services.contract_lifecycle_service import sweep_contracts

    today = today or date.today()
    contracts = sweep_contracts(branch_id, today, actor_id=actor_id)
    result = sweep_credit_statuses(branch_id, actor_id=actor_id, today=today)
    result["contracts"] = contracts
    return result


def run_daily_sweep_if_due(branch_id, today=None):
    """Jalankan penyapu sekali per hari per cabang. Aman dipanggil berkali-kali.

    Tidak ada penjadwal di aplikasi ini, jadi permintaan pertama pengguna
    internal tiap hari yang menjalankannya. Advisory lock Postgres memastikan
    dua permintaan bersamaan tidak menyapu dua kali; baris
    branch_settings credit.last_sweep_date mencatat hari terakhirnya.
    Mengembalikan hasil sapuan, atau None kalau hari ini sudah disapu.
    """
    from app.utils.clock import today_wib

    return _sweep_once_and_commit(branch_id, today or today_wib())


def _sweep_once_and_commit(branch_id, today):
    if not branch_id:
        return None
    try:
        result = _sweep_if_due_locked(branch_id, today)
        # Commit juga ketika tidak ada yang disapu: itu yang melepas lock.
        db.session.commit()
        return result
    except Exception:
        db.session.rollback()
        raise


def _sweep_if_due_locked(branch_id, today):
    got_lock = db.session.execute(
        sa.text("SELECT pg_try_advisory_xact_lock(:k, :b)"),
        {"k": SWEEP_LOCK_KEY, "b": int(branch_id)},
    ).scalar()
    if not got_lock:
        return None
    setting = BranchSetting.query.filter_by(branch_id=branch_id, setting_key=LAST_SWEEP_KEY).first()
    if setting and setting.setting_value == today.isoformat():
        return None
    result = daily_sweep(branch_id, today=today)
    if setting is None:
        db.session.add(BranchSetting(branch_id=branch_id, setting_key=LAST_SWEEP_KEY, setting_value=today.isoformat()))
    else:
        setting.setting_value = today.isoformat()
    return result


def run_credit_sweep_job(branch_id=None, period_key=None, now=None):
    """Tugas penjadwal 07.30 WIB: penyapu kontrak + kredit satu cabang, sekali sehari.

    Memakai penanda hari yang sama dengan pemicu lewat permintaan pertama, jadi
    keduanya tidak pernah menyapu dua kali di hari yang sama.
    """
    from app.utils.clock import today_wib

    try:
        today = date.fromisoformat(str(period_key)[:10]) if period_key else (now.date() if now else today_wib())
    except ValueError:
        today = now.date() if now else today_wib()
    result = _sweep_once_and_commit(branch_id, today)
    if result is None:
        return {"message": "Sudah diperiksa hari ini."}
    return {
        "checked": result["checked"],
        "escalated": len(result["escalated"]),
        "tazir_proposed": result.get("tazir_proposed", 0),
    }


def run_sweep_now(branch_id, actor_id=None, today=None):
    """Tombol "Periksa Kredit Sekarang": sapu satu cabang dan simpan."""
    return _in_transaction(lambda: daily_sweep(branch_id, actor_id=actor_id, today=today))


def sweep_all_branches(today=None):
    """Untuk penjadwal server (`flask credit-sweep`): sapu semua cabang aktif."""
    from app.models.master import Branch

    return {
        branch.id: run_sweep_now(branch.id, today=today)
        for branch in Branch.query.filter_by(is_active=True).all()
    }


# --- tampilan -------------------------------------------------------------------

def _mode_label(account):
    if account.party_type == PARTY_CLIENT:
        return f"{T.client} kontrak (aturan kredit dari kontrak)"
    return BILLING_MODE_LABELS.get(account.billing_mode, account.billing_mode)


def list_credit_overview(branch_id, today=None):
    """Semua akun kredit cabang ini, paling berisiko di atas."""
    today = today or date.today()
    rows = []
    for account in CreditAccount.query.filter_by(branch_id=branch_id, is_active=True).all():
        decision = evaluate_party(branch_id, account.party_type, account.party_id, account, today=today)
        rows.append({"account": account, "name": party_name(account), "decision": decision,
                     "status_label": STATUS_LABELS.get(decision.status, decision.status),
                     "mode_label": _mode_label(account)})
    rows.sort(key=lambda row: (
        -_rank(row["decision"].status),
        -row["decision"].oldest_days_overdue,
        -row["decision"].exposure,
    ))
    return rows


def credit_account_detail(account, today=None):
    """Semua yang dibutuhkan OWNER untuk memutuskan: angka, invoice, janji, jejak."""
    from app.services.advance_service import MANDOR_SECURITY_DEPOSIT

    today = today or date.today()
    decision = evaluate_party(account.branch_id, account.party_type, account.party_id, account, today=today)
    detail = {
        "account": account,
        "name": party_name(account),
        "decision": decision,
        "status_label": STATUS_LABELS.get(decision.status, decision.status),
        "mode_label": _mode_label(account),
        "events": CreditStatusEvent.query.filter_by(credit_account_id=account.id)
        .order_by(CreditStatusEvent.changed_at.desc(), CreditStatusEvent.id.desc()).limit(50).all(),
        "mandor": None,
        "invoices": [],
        "payments": [],
        "promises": [],
        "deposits": [],
        "deposit_settlements": [],
        "manual_statuses": [(status, STATUS_LABELS[status]) for status in MANUAL_STATUSES],
        "can_write_off": decision.derived_status == STATUS_WRITE_OFF or account.status == STATUS_WRITE_OFF,
        "charges": [],
        "grace_active": account.grace_active(today),
        "tazir_amount": ZERO,
    }
    from app.services.sharia_credit_service import list_charges, tazir_amount_for

    detail["charges"] = list_charges(account.branch_id, account_id=account.id, limit=50)
    detail["tazir_amount"], detail["contract"] = tazir_amount_for(account, today)

    invoice_query = Invoice.query.filter(Invoice.branch_id == account.branch_id)
    if account.party_type == PARTY_MANDOR:
        mandor = db.session.get(Mandor, account.party_id)
        detail["mandor"] = mandor
        invoice_query = invoice_query.filter(Invoice.mandor_id == mandor.id)
    else:
        mandor = None
        invoice_query = invoice_query.filter(
            Invoice.client_id == account.party_id,
            sa.or_(Invoice.bill_to_type.is_(None), Invoice.bill_to_type.notlike("MANDOR%")),
        )
    invoices = invoice_query.order_by(Invoice.invoice_date.desc(), Invoice.id.desc()).limit(60).all()
    detail["invoices"] = [
        {
            "invoice": invoice,
            "days_overdue": max((today - invoice.due_date).days, 0) if invoice.due_date else 0,
            "unpaid": invoice.status not in SETTLED_INVOICE_STATUSES and _money(invoice.remaining_amount) > 0,
        }
        for invoice in invoices
    ]
    invoice_ids = [invoice.id for invoice in invoices]
    if invoice_ids:
        from app.services.invoice_payment_history_service import payment_events

        detail["payments"] = payment_events(invoice_ids, limit=60)
        detail["promises"] = (
            InvoiceCollectionLog.query.filter(
                InvoiceCollectionLog.invoice_id.in_(invoice_ids),
                InvoiceCollectionLog.promise_date.isnot(None),
            )
            .order_by(InvoiceCollectionLog.promise_date.desc(), InvoiceCollectionLog.id.desc()).limit(40).all()
        )
    if mandor is None:
        return detail
    deposits = (
        AdvanceTransaction.query.filter(
            AdvanceTransaction.branch_id == account.branch_id,
            AdvanceTransaction.mandor_id == mandor.id,
            AdvanceTransaction.advance_type == MANDOR_SECURITY_DEPOSIT,
        )
        .order_by(AdvanceTransaction.advance_date.desc(), AdvanceTransaction.id.desc()).all()
    )
    detail["deposits"] = deposits
    if deposits:
        detail["deposit_settlements"] = (
            AdvanceSettlement.query.filter(AdvanceSettlement.advance_id.in_([row.id for row in deposits]))
            .order_by(AdvanceSettlement.settlement_date.desc(), AdvanceSettlement.id.desc()).all()
        )
    return detail


def portal_credit_summary(mandor, today=None):
    """Ringkasan kredit untuk mandor sendiri di portal. None kalau tidak berlaku.

    Hanya untuk mandor yang ditagih langsung: mandor yang ditagih lewat PT
    tidak punya hutang pribadi yang perlu dia pantau. Isinya sengaja angka
    yang mendorong bayar -- sisa limit, jatuh tempo terdekat, status -- tanpa
    detail internal seperti alasan atau jejak keputusan OWNER.
    """
    today = today or date.today()
    account = _mandor_account(mandor)
    if account is None or account.billing_mode != BILLING_DIRECT:
        return None
    decision = evaluate_party(account.branch_id, PARTY_MANDOR, mandor.id, account, today=today)
    next_due = (
        Invoice.query.filter(
            Invoice.branch_id == mandor.branch_id,
            Invoice.mandor_id == mandor.id,
            Invoice.status.notin_(SETTLED_INVOICE_STATUSES),
            Invoice.remaining_amount > 0,
        )
        .order_by(Invoice.due_date.asc())
        .first()
    )
    return {
        "status": decision.status,
        "status_label": STATUS_LABELS.get(decision.status, decision.status),
        "credit_limit": decision.credit_limit,
        "used": decision.exposure,
        "available": max(decision.available, ZERO),
        "outstanding": decision.outstanding_invoiced,
        "deposit": decision.deposit_amount,
        "oldest_days_overdue": decision.oldest_days_overdue,
        "next_due_date": next_due.due_date if next_due else None,
        "next_due_amount": _money(next_due.remaining_amount) if next_due else ZERO,
        "can_order": decision.allowed and not decision.requires_approval,
    }


# --- parsing kecil ---------------------------------------------------------------

def _parse_date(value):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        raise CreditActionError(f"Tanggal tidak valid: {value}")


def _int_or_none(value):
    try:
        return int(value) if str(value or "").strip() else None
    except (TypeError, ValueError):
        return None
