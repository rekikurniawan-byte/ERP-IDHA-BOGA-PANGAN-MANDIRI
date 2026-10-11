import logging
from datetime import date

from app.utils.clock import today_wib

from sqlalchemy import inspect

from app.extensions import db
from app.models.accounting import Account, Journal, JournalDetail
from app.models.finance import (
    AdvanceSettlement,
    AdvanceTransaction,
    BankAccount,
    CashBankTransaction,
    Invoice,
    SupplierBill,
)
from app.models.master import Client, Mandor, Supplier
from app.services.accounting_service import generate_journal_number
from app.services.audit_log_service import record_audit_log
from app.services.field_transaction_service import (
    create_system_linked_field_transaction,
    find_field_transaction_linked_source,
)
from app.utils.terms import T
from app.utils.terms import L
from app.utils.money import money

logger = logging.getLogger(__name__)


ADVANCE_REFERENCE_TYPE = "ADVANCE_TRANSACTION"
ADVANCE_SETTLEMENT_REFERENCE_TYPE = "ADVANCE_SETTLEMENT"


def _run_in_transaction(action):
    try:
        result = action()
        db.session.commit()
        return result
    except Exception:
        db.session.rollback()
        raise


CLIENT_DP_RECEIVED = "CLIENT_DP_RECEIVED"
SUPPLIER_ADVANCE_PAID = "SUPPLIER_ADVANCE_PAID"
MANDOR_OPERATIONAL_ADVANCE = "MANDOR_OPERATIONAL_ADVANCE"
MANDOR_SECURITY_DEPOSIT = "MANDOR_SECURITY_DEPOSIT"

# Setiap jenis punya akunnya sendiri. Sebelumnya semua jenis memakai 1008 Uang
# Muka / DP, yang di COA berjenis ASET -- jadi DP yang DITERIMA dari client
# (seharusnya kewajiban) dan uang muka yang DIBAYAR ke supplier saling menutupi
# di satu akun. Uang yang diterima sekarang dicatat di akun kewajiban.
ADVANCE_TYPES = {
    CLIENT_DP_RECEIVED: {
        "label": L("DP {client} Diterima"),
        "party_type": "CLIENT",
        "cash_direction": "IN",
        "journal_direction": "CREDIT_ADVANCE",
        "account_code": "2008",
        "account_label": "2008 Uang Muka Pelanggan",
        "description": L("Uang muka/DP diterima dari {client_lower} sebelum invoice final."),
    },
    SUPPLIER_ADVANCE_PAID: {
        "label": "Uang Muka Supplier Dibayar",
        "party_type": "SUPPLIER",
        "cash_direction": "OUT",
        "journal_direction": "DEBIT_ADVANCE",
        "account_code": "1008",
        "account_label": "1008 Uang Muka / DP",
        "description": "Uang muka dibayar ke supplier sebelum tagihan final.",
    },
    MANDOR_OPERATIONAL_ADVANCE: {
        "label": L("Panjar Operasional {sub_client}"),
        "party_type": "MANDOR",
        "cash_direction": "OUT",
        "journal_direction": "DEBIT_ADVANCE",
        "account_code": "1008",
        "account_label": "1008 Uang Muka / DP",
        "description": L("Panjar operasional ke {sub_client_lower} atau PIC-nya. Bukan payroll."),
    },
    MANDOR_SECURITY_DEPOSIT: {
        "label": L("Deposit Jaminan {sub_client}"),
        "party_type": "MANDOR",
        "cash_direction": "IN",
        "journal_direction": "CREDIT_ADVANCE",
        "account_code": "2007",
        # Nama akun COA sengaja baku, tidak ikut istilah cabang: buku besar
        # harus bernama sama di semua cabang dan laporan.
        "account_label": "2007 Deposit Jaminan Pelanggan",
        "description": L(
            "Jaminan dari {sub_client_lower} yang ditagih langsung. Ditahan selama kerja sama, "
            "tidak dipotong ke tiap invoice: dipakai menutup hutang kalau {sub_client_lower} "
            "macet, atau dikembalikan kalau kerja sama selesai dan lunas."
        ),
    },
}

# Memotong deposit dan mengembalikannya adalah keputusan OWNER.
DEPOSIT_TO_INVOICE = "DEPOSIT_TO_INVOICE"
DEPOSIT_REFUND = "DEPOSIT_REFUND"
# Uang muka pesanan pelanggan umum dikembalikan (pesanan ditolak/dibatalkan
# setelah dibayar). Keputusan owner 2026-09-27: hanya OWNER.
CLIENT_DP_REFUND = "CLIENT_DP_REFUND"
OWNER_ONLY_SETTLEMENT_TYPES = {DEPOSIT_TO_INVOICE, DEPOSIT_REFUND, CLIENT_DP_REFUND}
# Pengembalian = uang benar-benar keluar dari kas/bank.
REFUND_SETTLEMENT_TYPES = {DEPOSIT_REFUND, CLIENT_DP_REFUND}

SETTLEMENT_TYPES = {
    "CLIENT_INVOICE": {
        "advance_type": CLIENT_DP_RECEIVED,
        "reference_type": "INVOICE",
        "description": L("Pemakaian DP {client_lower} untuk mengurangi piutang invoice."),
    },
    DEPOSIT_TO_INVOICE: {
        "advance_type": MANDOR_SECURITY_DEPOSIT,
        "reference_type": "INVOICE",
        "description": L("Deposit jaminan dipotong untuk menutup hutang invoice {sub_client_lower} itu sendiri."),
    },
    CLIENT_DP_REFUND: {
        "advance_type": CLIENT_DP_RECEIVED,
        "reference_type": "DP_REFUND",
        "description": L("Uang muka {client_lower} dikembalikan karena pesanannya ditolak atau dibatalkan."),
    },
    DEPOSIT_REFUND: {
        "advance_type": MANDOR_SECURITY_DEPOSIT,
        "reference_type": "DEPOSIT_REFUND",
        "description": L("Deposit jaminan dikembalikan ke {sub_client_lower} setelah kerja sama selesai dan lunas."),
    },
    "SUPPLIER_BILL": {
        "advance_type": SUPPLIER_ADVANCE_PAID,
        "reference_type": "SUPPLIER_BILL",
        "description": "Pemakaian uang muka supplier untuk mengurangi hutang supplier.",
    },
    "MANDOR_EXPENSE_PROOF": {
        "advance_type": MANDOR_OPERATIONAL_ADVANCE,
        "reference_type": "MANDOR_EXPENSE_PROOF",
        "description": L("Pertanggungjawaban panjar {sub_client_lower}. Jurnal final menunggu PRODUCTION expense mapping."),
    },
}

# Kunci = kode akun yang diposting. Kode dan nama mengikuti COA di database
# (keputusan owner 2026-09-25). Versi sebelumnya memposting Gas ke 5006 (Beban
# Air), Perawatan ke 5007 (Beban Gas LPG), dan BBM ke 5011 (Beban Perawatan
# Kendaraan). Transport dan BBM digabung karena COA menggabungnya di 5003.
MANDOR_EXPENSE_PROOF_ACCOUNT_CHOICES = {
    "5002": {
        "label": "Operasional Dapur",
        "account_label": "5002 Beban Operasional Dapur",
        "description": "Pertanggungjawaban panjar untuk kebutuhan operasional dapur.",
    },
    "5003": {
        "label": "Transport / BBM",
        "account_label": "5003 Beban Transport / BBM",
        "description": "Pertanggungjawaban panjar untuk ongkos jalan, kirim, logistik, atau bahan bakar.",
    },
    "5005": {
        "label": "Listrik",
        "account_label": "5005 Beban Listrik",
        "description": "Pertanggungjawaban panjar untuk listrik lokasi kerja.",
    },
    "5006": {
        "label": "Air",
        "account_label": "5006 Beban Air",
        "description": "Pertanggungjawaban panjar untuk air bersih lokasi kerja.",
    },
    "5007": {
        "label": "Gas / LPG",
        "account_label": "5007 Beban Gas LPG",
        "description": "Pertanggungjawaban panjar untuk gas atau LPG.",
    },
    "5008": {
        "label": "Administrasi Site",
        "account_label": "5008 Beban Administrasi / Bunga",
        "description": "Pertanggungjawaban panjar untuk pembelian operasional umum/site.",
    },
    "5009": {
        "label": "Perawatan / Lain-lain",
        "account_label": "5009 Beban Lain-Lain",
        "description": "Pertanggungjawaban panjar untuk perbaikan kecil dan pengeluaran lain di luar kategori ini.",
    },
    "5010": {
        "label": "Kemasan",
        "account_label": "5010 Beban Kemasan",
        "description": "Pertanggungjawaban panjar untuk box, plastik, atau perlengkapan packing.",
    },
    "5011": {
        "label": "Perawatan Kendaraan",
        "account_label": "5011 Beban Perawatan Kendaraan",
        "description": "Pertanggungjawaban panjar untuk servis dan perbaikan kendaraan operasional.",
    },
}


def _money(value):
    try:
        return f"Rp {float(value or 0):,.0f}".replace(",", ".")
    except Exception:
        logger.exception("Suppressed unexpected exception in app/services/advance_service.py:131")
        return "Rp 0"


def _normalize(value):
    return str(value or "").strip().upper()


def is_advance_schema_ready():
    """Avoid crashing local runtime when migration has not been applied yet."""
    try:
        inspector = inspect(db.engine)
        return inspector.has_table("advance_transactions") and inspector.has_table("advance_settlements")
    except Exception:
        logger.exception("Suppressed unexpected exception in app/services/advance_service.py:144")
        return False


def get_account_by_code(code):
    return Account.query.filter_by(account_code=code, is_active=True).first()


def resolve_cash_account_code(account_type, bank_account_id=None):
    """Akun kas/bank yang benar untuk transaksi ini.

    Dulu BANK selalu 1002 (Bank 1), apa pun rekening yang dipilih, jadi uang
    yang masuk ke Bank 2 terjurnal ke Bank 1. Sekarang memakai COA milik
    rekening itu lewat resolver yang sama dengan transaksi lapangan, dan baru
    jatuh ke 1002 kalau rekening belum dipetakan.
    """
    from app.services.field_transaction_policy_service import resolve_cash_bank_coa_code

    account_type = _normalize(account_type)
    if account_type == "CASH":
        return "1001"
    if account_type == "BANK":
        bank_account = db.session.get(BankAccount, bank_account_id) if bank_account_id else None
        return resolve_cash_bank_coa_code(
            payment_method="TRANSFER", bank_account=bank_account, fallback_bank_code="1002"
        )
    raise Exception("Akun kas/bank harus CASH atau BANK.")


def _advance_account(advance_type):
    rule = ADVANCE_TYPES.get(_normalize(advance_type)) or {}
    code = rule.get("account_code")
    account = get_account_by_code(code) if code else None
    if not account:
        raise Exception(f"Akun {rule.get('account_label') or code or '-'} belum tersedia atau tidak aktif.")
    return account


def _require_owner(user_id, action_label):
    from app.models.master import User
    from app.utils.roles import effective_role

    user = db.session.get(User, user_id) if user_id else None
    if user is None or effective_role(user.role) != "OWNER":
        raise Exception(f"{action_label} hanya boleh dilakukan OWNER.")


def generate_advance_number(advance_date):
    prefix = f"ADV-{advance_date.strftime('%Y%m%d')}"
    counter = AdvanceTransaction.query.filter(
        AdvanceTransaction.advance_number.like(f"{prefix}-%")
    ).count() + 1
    while True:
        number = f"{prefix}-{counter:03d}"
        if not AdvanceTransaction.query.filter_by(advance_number=number).first():
            return number
        counter += 1


def generate_settlement_number(settlement_date):
    prefix = f"ADVS-{settlement_date.strftime('%Y%m%d')}"
    counter = AdvanceSettlement.query.filter(
        AdvanceSettlement.settlement_number.like(f"{prefix}-%")
    ).count() + 1
    while True:
        number = f"{prefix}-{counter:03d}"
        if not AdvanceSettlement.query.filter_by(settlement_number=number).first():
            return number
        counter += 1


def get_advance_type_choices():
    return [
        {"value": key, **value}
        for key, value in ADVANCE_TYPES.items()
    ]


def get_mandor_expense_proof_choices():
    return [
        {"value": key, **value}
        for key, value in sorted(MANDOR_EXPENSE_PROOF_ACCOUNT_CHOICES.items())
    ]


def get_advance_status_summary(branch_id):
    if not is_advance_schema_ready():
        return {"total": 0, "open": 0, "settled": 0, "remaining": 0}

    rows = AdvanceTransaction.query.filter_by(branch_id=branch_id).all()
    return {
        "total": len(rows),
        "open": len([row for row in rows if _normalize(row.status) in {"OPEN", "PARTIAL"}]),
        "settled": len([row for row in rows if _normalize(row.status) == "SETTLED"]),
        "remaining": sum(money(row.remaining_amount or 0) for row in rows if _normalize(row.status) in {"OPEN", "PARTIAL"}),
    }


def get_party_label(advance):
    if not advance:
        return "-"
    if advance.party_type == "CLIENT":
        return advance.client.name if advance.client else f"{T.client} ID {advance.client_id or '-'}"
    if advance.party_type == "SUPPLIER":
        return advance.supplier.supplier_name if advance.supplier else f"Supplier ID {advance.supplier_id or '-'}"
    if advance.party_type == "MANDOR":
        return advance.mandor.name if advance.mandor else f"{T.sub_client} ID {advance.mandor_id or '-'}"
    return "-"


def validate_party(branch_id, advance_type, client_id=None, supplier_id=None, mandor_id=None):
    rule = ADVANCE_TYPES.get(advance_type)
    if not rule:
        raise Exception("Tipe uang muka tidak dikenali.")

    expected_party_type = rule["party_type"]

    if expected_party_type == "CLIENT":
        if not client_id:
            raise Exception(f"DP {T.client_lower} wajib memilih {T.client_lower}.")
        party = Client.query.filter_by(id=client_id, is_active=True).first()
        if not party:
            raise Exception(f"{T.client} tidak valid atau tidak aktif.")
        return "CLIENT", party.id, None, None

    if expected_party_type == "SUPPLIER":
        if not supplier_id:
            raise Exception("Uang muka supplier wajib memilih supplier.")
        party = Supplier.query.filter_by(id=supplier_id, branch_id=branch_id, is_active=True).first()
        if not party:
            raise Exception("Supplier tidak valid atau tidak aktif.")
        return "SUPPLIER", None, party.id, None

    if expected_party_type == "MANDOR":
        if not mandor_id:
            raise Exception(f"Panjar {T.sub_client_lower} wajib memilih {T.sub_client_lower}/PIC lapangan.")
        party = Mandor.query.filter_by(id=mandor_id, branch_id=branch_id, is_active=True).first()
        if not party:
            raise Exception(f"{T.sub_client} tidak valid atau tidak aktif.")
        return "MANDOR", None, None, party.id

    raise Exception("Party type advance belum dikenali.")


def validate_cash_bank(branch_id, payment_method, bank_account_id=None):
    method = _normalize(payment_method)
    if method == "CASH":
        return "CASH", None
    if method == "TRANSFER":
        if not bank_account_id:
            raise Exception("Transaksi transfer wajib memilih rekening bank.")
        bank = BankAccount.query.filter_by(
            id=bank_account_id,
            branch_id=branch_id,
            is_active=True,
        ).first()
        if not bank:
            raise Exception("Rekening bank tidak valid atau tidak aktif.")
        return "BANK", bank.id
    raise Exception("Metode advance harus CASH atau TRANSFER.")


def create_advance_transaction(
    branch_id,
    advance_date,
    advance_type,
    payment_method,
    amount,
    created_by,
    client_id=None,
    supplier_id=None,
    mandor_id=None,
    bank_account_id=None,
    reference_number=None,
    notes=None,
    commit=False,
):
    if not is_advance_schema_ready():
        raise Exception("Tabel advance belum tersedia. Jalankan migration PRODUCTION terlebih dahulu.")

    advance_type = _normalize(advance_type)
    rule = ADVANCE_TYPES.get(advance_type)
    if not rule:
        raise Exception("Tipe uang muka tidak valid.")

    amount = money(amount or 0)
    if amount <= 0:
        raise Exception("Nominal DP/uang muka harus lebih dari 0.")

    if advance_date > today_wib():
        raise Exception("Tanggal DP/uang muka tidak boleh lebih dari hari ini.")

    party_type, client_id, supplier_id, mandor_id = validate_party(
        branch_id=branch_id,
        advance_type=advance_type,
        client_id=client_id,
        supplier_id=supplier_id,
        mandor_id=mandor_id,
    )
    account_type, bank_account_id = validate_cash_bank(branch_id, payment_method, bank_account_id)

    cash_bank_code = resolve_cash_account_code(account_type, bank_account_id)
    acc_advance = get_account_by_code(rule["account_code"])
    acc_cash_bank = get_account_by_code(cash_bank_code)

    missing = []
    if not acc_advance:
        missing.append(rule["account_label"])
    if not acc_cash_bank:
        missing.append(cash_bank_code)
    if missing:
        raise Exception("Akun wajib belum lengkap: " + ", ".join(missing))

    advance = AdvanceTransaction(
        branch_id=branch_id,
        advance_number=generate_advance_number(advance_date),
        advance_date=advance_date,
        advance_type=advance_type,
        party_type=party_type,
        client_id=client_id,
        supplier_id=supplier_id,
        mandor_id=mandor_id,
        account_type=account_type,
        bank_account_id=bank_account_id,
        payment_method=_normalize(payment_method),
        amount=amount,
        settled_amount=0,
        remaining_amount=amount,
        status="OPEN",
        reference_number=(reference_number or None),
        notes=(notes or None),
        created_by=created_by,
    )
    db.session.add(advance)
    db.session.flush()

    cash_direction = rule["cash_direction"]
    source_label = "Kas" if account_type == "CASH" else "Bank"
    transaction = CashBankTransaction(
        branch_id=branch_id,
        transaction_date=advance_date,
        account_type=account_type,
        bank_account_id=bank_account_id,
        transaction_type=cash_direction,
        amount=amount,
        description=f"{rule['label']} {advance.advance_number} via {source_label} sebesar {_money(amount)}",
        reference_type=ADVANCE_REFERENCE_TYPE,
        reference_id=advance.id,
        created_by=created_by,
    )
    db.session.add(transaction)
    db.session.flush()

    journal = Journal(
        journal_number=generate_journal_number(advance_date),
        journal_date=advance_date,
        reference_type=ADVANCE_REFERENCE_TYPE,
        reference_id=advance.id,
        description=f"Jurnal {rule['label']} - {advance.advance_number}",
        created_by=created_by,
    )
    db.session.add(journal)
    db.session.flush()

    if rule["journal_direction"] == "CREDIT_ADVANCE":
        # Uang diterima (DP client, deposit mandor): Dr Kas/Bank, Cr kewajiban.
        debit_account, credit_account = acc_cash_bank, acc_advance
    else:
        # Uang dibayar (uang muka supplier, panjar mandor): Dr 1008, Cr Kas/Bank.
        debit_account, credit_account = acc_advance, acc_cash_bank

    db.session.add(JournalDetail(journal_id=journal.id, account_id=debit_account.id, debit=amount, credit=0))
    db.session.add(JournalDetail(journal_id=journal.id, account_id=credit_account.id, debit=0, credit=amount))

    advance.cash_bank_transaction_id = transaction.id
    advance.journal_id = journal.id

    record_audit_log(
        module="FINANCE",
        event_type="ADVANCE_CREATED",
        action="CREATE",
        table_name="advance_transactions",
        record_id=advance.id,
        description=f"Advance dibuat: {advance.advance_number} ({rule['label']}).",
        metadata={
            "advance_type": advance.advance_type,
            "party_type": party_type,
            "amount": amount,
            "cash_bank_transaction_id": transaction.id,
            "journal_id": journal.id,
        },
        user_id=created_by,
        branch_id=branch_id,
        commit=False,
    )

    if commit:
        db.session.commit()

    return True, f"{rule['label']} berhasil dibuat secara optional dan traceable.", advance


def create_advance_transaction_record(**kwargs):
    kwargs["commit"] = False
    return _run_in_transaction(lambda: create_advance_transaction(**kwargs))


def resolve_settlement_reference(branch_id, settlement_type, reference_id):
    settlement_type = _normalize(settlement_type)
    rule = SETTLEMENT_TYPES.get(settlement_type)
    if not rule:
        raise Exception("Tipe settlement advance tidak valid.")

    if settlement_type in {"CLIENT_INVOICE", DEPOSIT_TO_INVOICE}:
        if not reference_id:
            raise Exception("Pemakaian DP/deposit wajib memilih invoice.")
        invoice = Invoice.query.filter_by(id=reference_id, branch_id=branch_id).first()
        if not invoice:
            raise Exception("Invoice settlement tidak ditemukan.")
        if _normalize(invoice.status) in {"CANCELLED", "CANCELED"}:
            raise Exception("Invoice cancelled tidak boleh dipakai settlement DP.")
        if money(invoice.remaining_amount or 0) <= 0:
            raise Exception("Invoice ini sudah tidak punya sisa piutang.")
        return rule, invoice

    if settlement_type == "SUPPLIER_BILL":
        if not reference_id:
            raise Exception("Settlement uang muka supplier wajib memilih supplier bill.")
        bill = SupplierBill.query.filter_by(id=reference_id, branch_id=branch_id).first()
        if not bill:
            raise Exception("Supplier bill settlement tidak ditemukan.")
        if money(bill.remaining_amount or 0) <= 0:
            raise Exception("Supplier bill ini sudah tidak punya sisa hutang.")
        return rule, bill

    if settlement_type == "MANDOR_EXPENSE_PROOF":
        # PRODUCTION keeps mandor panjar optional and trackable.
        # Expense-account posting is deliberately deferred to PRODUCTION mapping.
        return rule, None

    if settlement_type in REFUND_SETTLEMENT_TYPES:
        return rule, None

    raise Exception("Tipe settlement belum dikenali.")


def invoice_has_journal(invoice_id):
    """Piutang invoice ini sudah dijurnal (Dr 1004) oleh accounting_service?"""
    from app.models.finance import Invoice
    from app.services.accounting_service import receivable_is_journaled

    invoice = db.session.get(Invoice, invoice_id)
    return invoice is not None and receivable_is_journaled(invoice)


def mandor_unpaid_invoice_total(branch_id, mandor_id):
    """Sisa hutang invoice mandor ini. Deposit tidak boleh dikembalikan selama > 0."""
    total = 0.0
    for (remaining,) in Invoice.query.filter(
        Invoice.branch_id == branch_id,
        Invoice.mandor_id == mandor_id,
        Invoice.status.notin_(["CANCELLED", "CANCELED", "PAID", "CLOSED"]),
    ).with_entities(Invoice.remaining_amount).all():
        total += money(remaining or 0)
    return total


def _record_invoice_settlement_log(invoice, settlement, settlement_type, amount, created_by):
    """Log penagihan untuk pelunasan lewat potong DP/deposit, sama seperti pembayaran kas/bank."""
    from app.models.finance import InvoiceCollectionLog

    source = f"deposit jaminan {T.sub_client_lower}" if settlement_type == DEPOSIT_TO_INVOICE else f"uang muka/DP {T.client_lower}"
    paid_off = money(invoice.remaining_amount or 0) <= 0
    amount_label = f"Rp {float(amount or 0):,.0f}".replace(",", ".")
    db.session.add(InvoiceCollectionLog(
        branch_id=getattr(invoice, "branch_id", None) or settlement.branch_id,
        invoice_id=getattr(invoice, "id", None) or settlement.reference_id,
        follow_up_date=settlement.settlement_date,
        channel="SYSTEM",
        contact_person=f"SYSTEM - Potong {source}",
        response_note=(
            f"{settlement.settlement_number}: {amount_label} dipotong dari {source}. "
            + ("Invoice sudah lunas." if paid_off else f"Sisa {invoice.invoice_number}: Rp {float(invoice.remaining_amount or 0):,.0f}.".replace(",", "."))
        ),
        promise_date=None,
        next_action="Invoice sudah lunas. Tidak perlu follow up penagihan." if paid_off else "Follow up pelunasan sisa piutang.",
        collection_status="PAID" if paid_off else "PARTIAL",
        created_by=created_by,
    ))


def create_advance_settlement(
    advance,
    settlement_date,
    settlement_type,
    amount,
    created_by,
    reference_id=None,
    expense_account_code=None,
    notes=None,
    commit=False,
    payment_method=None,
    bank_account_id=None,
):
    if not is_advance_schema_ready():
        raise Exception("Tabel advance belum tersedia. Jalankan migration PRODUCTION terlebih dahulu.")
    if not advance:
        raise Exception("Advance tidak ditemukan.")

    settlement_type = _normalize(settlement_type)
    if settlement_type in OWNER_ONLY_SETTLEMENT_TYPES:
        _require_owner(
            created_by,
            "Mengembalikan uang muka pelanggan" if settlement_type == CLIENT_DP_REFUND
            else "Memotong atau mengembalikan deposit jaminan",
        )
    rule, reference_obj = resolve_settlement_reference(advance.branch_id, settlement_type, reference_id)

    if settlement_type == DEPOSIT_TO_INVOICE and getattr(reference_obj, "mandor_id", None) != advance.mandor_id:
        # Deposit mandor A tidak boleh menutup hutang mandor B.
        raise Exception(f"Deposit hanya boleh dipotong ke invoice milik {T.sub_client_lower} yang sama.")
    if settlement_type in {"CLIENT_INVOICE", DEPOSIT_TO_INVOICE} and not invoice_has_journal(getattr(reference_obj, "id", None)):
        # Settlement mengkredit 1004 Piutang Usaha. Kalau piutang invoice ini
        # belum pernah didebit (jurnal invoice belum diposting), 1004 minus.
        raise Exception(
            f"Invoice {reference_obj.invoice_number} belum dijurnal. Posting jurnal invoice dulu."
        )
    if settlement_type == DEPOSIT_REFUND:
        unpaid = mandor_unpaid_invoice_total(advance.branch_id, advance.mandor_id)
        if unpaid > 0:
            raise Exception(
                f"Deposit belum boleh dikembalikan: {T.sub_client_lower} masih punya hutang {_money(unpaid)}. "
                "Lunasi atau potong deposit ke invoice-nya dulu."
            )
    expense_account_code = _normalize(expense_account_code)
    expense_proof_rule = None

    if rule["advance_type"] != _normalize(advance.advance_type):
        raise Exception("Tipe settlement tidak sesuai dengan tipe advance.")

    if _normalize(advance.status) == "SETTLED" or money(advance.remaining_amount or 0) <= 0:
        raise Exception("Advance ini sudah selesai/settled.")

    amount = money(amount or 0)
    if amount <= 0:
        raise Exception("Nominal settlement harus lebih dari 0.")
    if amount > money(advance.remaining_amount or 0):
        raise Exception("Nominal settlement tidak boleh lebih dari sisa advance.")
    if settlement_type in {"CLIENT_INVOICE", DEPOSIT_TO_INVOICE} and amount > money(getattr(reference_obj, "remaining_amount", 0) or 0):
        raise Exception("Nominal settlement tidak boleh lebih dari sisa piutang invoice.")
    if settlement_type == "SUPPLIER_BILL" and amount > money(getattr(reference_obj, "remaining_amount", 0) or 0):
        raise Exception("Nominal settlement tidak boleh lebih dari sisa hutang supplier bill.")
    if settlement_date < advance.advance_date:
        raise Exception("Tanggal settlement tidak boleh lebih awal dari tanggal advance.")
    if settlement_date > today_wib():
        raise Exception("Tanggal settlement tidak boleh lebih dari hari ini.")

    acc_advance = _advance_account(advance.advance_type)
    if settlement_type == "MANDOR_EXPENSE_PROOF":
        expense_proof_rule = MANDOR_EXPENSE_PROOF_ACCOUNT_CHOICES.get(expense_account_code)
        if not expense_proof_rule:
            raise Exception(f"Pilih kategori biaya pertanggungjawaban panjar {T.sub_client_lower} terlebih dahulu.")

    settlement = AdvanceSettlement(
        branch_id=advance.branch_id,
        settlement_number=generate_settlement_number(settlement_date),
        advance_id=advance.id,
        settlement_date=settlement_date,
        settlement_type=settlement_type,
        reference_type=rule["reference_type"],
        reference_id=reference_id,
        amount=amount,
        notes=(notes or None),
        created_by=created_by,
    )
    db.session.add(settlement)
    db.session.flush()

    journal = None

    if settlement_type in {"CLIENT_INVOICE", DEPOSIT_TO_INVOICE}:
        acc_piutang = get_account_by_code("1004")
        if not acc_piutang:
            raise Exception("Akun 1004 Piutang Usaha belum tersedia.")
        source_label = f"deposit jaminan {T.sub_client_lower}" if settlement_type == DEPOSIT_TO_INVOICE else f"DP {T.client_lower}"
        journal = Journal(
            journal_number=generate_journal_number(settlement_date),
            journal_date=settlement_date,
            reference_type=ADVANCE_SETTLEMENT_REFERENCE_TYPE,
            reference_id=settlement.id,
            description=f"Settlement {source_label} {advance.advance_number} ke invoice {getattr(reference_obj, 'invoice_number', reference_id)}",
            created_by=created_by,
        )
        db.session.add(journal)
        db.session.flush()
        # Invoice journal records full receivable; settlement reduces receivable.
        # Dr kewajiban (2008 DP / 2007 deposit), Cr 1004 Piutang Usaha.
        db.session.add(JournalDetail(journal_id=journal.id, account_id=acc_advance.id, debit=amount, credit=0))
        db.session.add(JournalDetail(journal_id=journal.id, account_id=acc_piutang.id, debit=0, credit=amount))

    elif settlement_type in REFUND_SETTLEMENT_TYPES:
        # Uang benar-benar keluar, jadi -- beda dengan settlement lain -- ada
        # mutasi kas/bank sendiri. Dr 2007 Deposit Jaminan / 2008 Uang Muka
        # Pelanggan, Cr Kas/Bank.
        refund_label = (
            f"uang muka {T.client_lower}" if settlement_type == CLIENT_DP_REFUND
            else f"deposit jaminan {T.sub_client_lower}"
        )
        account_type, bank_account_id = validate_cash_bank(advance.branch_id, payment_method, bank_account_id)
        cash_bank_code = resolve_cash_account_code(account_type, bank_account_id)
        acc_cash_bank = get_account_by_code(cash_bank_code)
        if not acc_cash_bank:
            raise Exception(f"Akun kas/bank {cash_bank_code} belum tersedia.")
        refund_transaction = CashBankTransaction(
            branch_id=advance.branch_id,
            transaction_date=settlement_date,
            account_type=account_type,
            bank_account_id=bank_account_id,
            transaction_type="OUT",
            amount=amount,
            description=f"Pengembalian {refund_label} {advance.advance_number} sebesar {_money(amount)}",
            reference_type=ADVANCE_SETTLEMENT_REFERENCE_TYPE,
            reference_id=settlement.id,
            created_by=created_by,
        )
        db.session.add(refund_transaction)
        journal = Journal(
            journal_number=generate_journal_number(settlement_date),
            journal_date=settlement_date,
            reference_type=ADVANCE_SETTLEMENT_REFERENCE_TYPE,
            reference_id=settlement.id,
            description=f"Pengembalian {refund_label} {advance.advance_number}",
            created_by=created_by,
        )
        db.session.add(journal)
        db.session.flush()
        db.session.add(JournalDetail(journal_id=journal.id, account_id=acc_advance.id, debit=amount, credit=0))
        db.session.add(JournalDetail(journal_id=journal.id, account_id=acc_cash_bank.id, debit=0, credit=amount))

    elif settlement_type == "SUPPLIER_BILL":
        acc_ap = get_account_by_code("2002")
        if not acc_ap:
            raise Exception("Akun 2002 Hutang Supplier belum tersedia.")
        journal = Journal(
            journal_number=generate_journal_number(settlement_date),
            journal_date=settlement_date,
            reference_type=ADVANCE_SETTLEMENT_REFERENCE_TYPE,
            reference_id=settlement.id,
            description=f"Settlement uang muka supplier {advance.advance_number} ke bill {getattr(reference_obj, 'bill_number', reference_id)}",
            created_by=created_by,
        )
        db.session.add(journal)
        db.session.flush()
        db.session.add(JournalDetail(journal_id=journal.id, account_id=acc_ap.id, debit=amount, credit=0))
        db.session.add(JournalDetail(journal_id=journal.id, account_id=acc_advance.id, debit=0, credit=amount))

    elif settlement_type == "MANDOR_EXPENSE_PROOF":
        acc_expense = get_account_by_code(expense_account_code)
        if not acc_expense:
            raise Exception(f"Akun biaya {expense_account_code} belum tersedia atau tidak aktif.")
        journal = Journal(
            journal_number=generate_journal_number(settlement_date),
            journal_date=settlement_date,
            reference_type=ADVANCE_SETTLEMENT_REFERENCE_TYPE,
            reference_id=settlement.id,
            description=(
                f"Settlement panjar {T.sub_client_lower} {advance.advance_number} "
                f"ke {expense_proof_rule['account_label']}"
            ),
            created_by=created_by,
        )
        db.session.add(journal)
        db.session.flush()
        db.session.add(JournalDetail(journal_id=journal.id, account_id=acc_expense.id, debit=amount, credit=0))
        db.session.add(JournalDetail(journal_id=journal.id, account_id=acc_advance.id, debit=0, credit=amount))
        note_prefix = f"[{expense_proof_rule['account_label']}]"
        settlement.notes = f"{note_prefix} {notes}".strip() if notes else note_prefix

    if journal:
        settlement.journal_id = journal.id

    # Update operational outstanding without creating a duplicate cash/bank entry.
    # The cash movement happened at advance creation; settlement only applies that advance.
    if settlement_type in {"CLIENT_INVOICE", DEPOSIT_TO_INVOICE} and reference_obj:
        new_paid = money(reference_obj.paid_amount or 0) + amount
        new_remaining_invoice = money(reference_obj.total_amount or 0) - new_paid
        if new_remaining_invoice <= 0:
            new_remaining_invoice = 0
            reference_obj.status = "PAID"
        elif new_paid > 0:
            reference_obj.status = "PARTIAL"
        reference_obj.paid_amount = new_paid
        reference_obj.remaining_amount = new_remaining_invoice
        _record_invoice_settlement_log(reference_obj, settlement, settlement_type, amount, created_by)

    if settlement_type == "SUPPLIER_BILL" and reference_obj:
        new_paid = money(reference_obj.paid_amount or 0) + amount
        new_remaining_bill = money(reference_obj.total_amount or 0) - new_paid
        if new_remaining_bill <= 0:
            new_remaining_bill = 0
            reference_obj.status = "PAID"
        elif new_paid > 0:
            reference_obj.status = "PARTIAL"
        reference_obj.paid_amount = new_paid
        reference_obj.remaining_amount = new_remaining_bill

    new_settled = money(advance.settled_amount or 0) + amount
    new_remaining = money(advance.amount or 0) - new_settled
    if new_remaining <= 0:
        new_remaining = 0
        advance.status = "SETTLED"
    elif new_settled > 0:
        advance.status = "PARTIAL"
    advance.settled_amount = new_settled
    advance.remaining_amount = new_remaining

    field_transaction_link = find_field_transaction_linked_source(
        ADVANCE_REFERENCE_TYPE,
        advance.id,
        branch_id=advance.branch_id,
    )
    parent_field_transaction = getattr(field_transaction_link, "field_transaction", None) if field_transaction_link else None
    if parent_field_transaction and _normalize(advance.advance_type) == MANDOR_OPERATIONAL_ADVANCE:
        _, _, settlement_trace = create_system_linked_field_transaction(
            parent_field_transaction=parent_field_transaction,
            transaction_date=settlement_date,
            business_event_type="MANDOR_ADVANCE_SETTLEMENT",
            amount=amount,
            created_by=created_by,
            payment_status="PAID" if new_remaining <= 0 else "PARTIAL",
            review_status="RECORDED",
            evidence_status=getattr(parent_field_transaction, "evidence_status", None) or "PENDING",
            notes=(notes or None) or f"Jejak otomatis settlement advance {settlement.settlement_number}.",
            source_context={
                "generated_mode": "SYSTEM_LINKED_ADVANCE_SETTLEMENT",
                "source_field_transaction_id": parent_field_transaction.id,
                "advance_id": advance.id,
                "advance_number": advance.advance_number,
                "advance_settlement_id": settlement.id,
                "advance_settlement_number": settlement.settlement_number,
                "settlement_type": settlement_type,
            },
            metadata={
                "advance_id": advance.id,
                "advance_number": advance.advance_number,
                "advance_settlement_id": settlement.id,
                "advance_settlement_number": settlement.settlement_number,
                "settlement_type": settlement_type,
                "journal_id": journal.id if journal else None,
            },
            mark_posted=bool(journal),
            posting_note="Jejak transaksi lapangan turunan diposting otomatis dari settlement advance." if journal else None,
            additional_links=[
                {
                    "link_role": "ADVANCE_TRANSACTION",
                    "reference_type": ADVANCE_REFERENCE_TYPE,
                    "reference_id": advance.id,
                    "notes": f"Sumber advance {advance.advance_number}.",
                },
                {
                    "link_role": "ADVANCE_SETTLEMENT",
                    "reference_type": ADVANCE_SETTLEMENT_REFERENCE_TYPE,
                    "reference_id": settlement.id,
                    "notes": f"Settlement {settlement.settlement_number}.",
                },
                {
                    "link_role": "JOURNAL",
                    "reference_type": "JOURNAL",
                    "reference_id": journal.id if journal else None,
                },
            ],
            needs_follow_up=not bool(journal),
            commit=False,
        )
    record_audit_log(
        module="FINANCE",
        event_type="ADVANCE_SETTLED",
        action="CREATE",
        table_name="advance_settlements",
        record_id=settlement.id,
        description=f"Settlement advance dibuat: {settlement.settlement_number}.",
        metadata={
            "advance_id": advance.id,
            "advance_number": advance.advance_number,
            "settlement_type": settlement_type,
            "amount": amount,
            "journal_id": journal.id if journal else None,
            "expense_account_code": expense_account_code if settlement_type == "MANDOR_EXPENSE_PROOF" else None,
            # Alasan (mis. kenapa uang muka dikembalikan) ditinjau OWNER tiap minggu.
            "reason": (notes or "").strip(),
        },
        user_id=created_by,
        branch_id=advance.branch_id,
        commit=False,
    )

    if commit:
        db.session.commit()

    return True, "Settlement advance berhasil dibuat.", settlement


def create_advance_settlement_record(**kwargs):
    kwargs["commit"] = False
    return _run_in_transaction(lambda: create_advance_settlement(**kwargs))


def get_settlement_reference_options(branch_id, advance):
    if not advance:
        return {"invoices": [], "supplier_bills": []}
    if _normalize(advance.advance_type) == CLIENT_DP_RECEIVED:
        query = Invoice.query.filter(
            Invoice.branch_id == branch_id,
            Invoice.status.notin_(["CANCELLED", "CANCELED"]),
        )
        if advance.client_id:
            query = query.filter(Invoice.client_id == advance.client_id)
        return {"invoices": query.order_by(Invoice.invoice_date.desc(), Invoice.id.desc()).limit(80).all(), "supplier_bills": []}
    if _normalize(advance.advance_type) == SUPPLIER_ADVANCE_PAID:
        query = SupplierBill.query.filter(SupplierBill.branch_id == branch_id)
        if advance.supplier_id:
            query = query.filter(SupplierBill.supplier_id == advance.supplier_id)
        return {"invoices": [], "supplier_bills": query.order_by(SupplierBill.bill_date.desc(), SupplierBill.id.desc()).limit(80).all()}
    return {"invoices": [], "supplier_bills": []}
