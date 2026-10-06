import logging
from app.extensions import db
from app.models.finance import BankAccount, CashBankTransaction, Invoice, SupplierBill

logger = logging.getLogger(__name__)


CUSTOMER_PAYMENT_REFERENCE_TYPE = "PAYMENT"


def _commit_or_rollback():
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise


def _money(value):
    try:
        return f"Rp {float(value or 0):,.0f}".replace(",", ".")
    except Exception:
        logger.exception("Suppressed unexpected exception in app/services/cash_bank_service.py:19")
        return "Rp 0"


def create_customer_payment_cash_bank_transaction(payment, created_by, commit=False):
    """Create one cash/bank ledger entry for a customer invoice payment.

    This function is intentionally idempotent by payment reference, so a retry
    does not create duplicate ledger rows for the same payment.
    """
    if not payment:
        return False, "Payment tidak ditemukan.", None

    existing_transaction = CashBankTransaction.query.filter_by(
        reference_type=CUSTOMER_PAYMENT_REFERENCE_TYPE,
        reference_id=payment.id,
    ).first()

    if existing_transaction:
        return False, "Ledger kas/bank untuk payment ini sudah ada.", existing_transaction

    method = str(payment.payment_method or "").upper()
    amount = float(payment.amount or 0)

    if amount <= 0:
        raise Exception(f"Nominal payment {payment.payment_number} tidak valid untuk ledger kas/bank.")

    bank_account_id = None
    account_type = None

    if method == "CASH":
        account_type = "CASH"
    elif method == "TRANSFER":
        account_type = "BANK"

        if not payment.bank_account_id:
            raise Exception("Pembayaran transfer wajib memilih rekening bank penerima.")

        bank_account = BankAccount.query.filter_by(
            id=payment.bank_account_id,
            branch_id=payment.branch_id,
            is_active=True,
        ).first()

        if not bank_account:
            raise Exception("Rekening bank penerima tidak valid atau tidak aktif.")

        bank_account_id = bank_account.id
    else:
        raise Exception(f"Metode pembayaran {method} belum dikenali untuk ledger kas/bank.")

    invoice = Invoice.query.get(payment.invoice_id)
    invoice_number = invoice.invoice_number if invoice else f"Invoice ID {payment.invoice_id}"

    description = (
        f"Pembayaran customer {payment.payment_number} untuk {invoice_number} "
        f"masuk {account_type} sebesar {_money(amount)}"
    )

    if payment.reference_number:
        description += f". Ref: {payment.reference_number}"

    transaction = CashBankTransaction(
        branch_id=payment.branch_id,
        transaction_date=payment.payment_date,
        account_type=account_type,
        bank_account_id=bank_account_id,
        transaction_type="IN",
        amount=amount,
        description=description,
        reference_type=CUSTOMER_PAYMENT_REFERENCE_TYPE,
        reference_id=payment.id,
        created_by=created_by,
    )

    db.session.add(transaction)

    if commit:
        _commit_or_rollback()

    return True, "Ledger kas/bank payment berhasil dibuat.", transaction


PROCUREMENT_REFERENCE_TYPE = "PROCUREMENT"


def create_procurement_cash_bank_transaction(procurement, created_by, account_type="CASH", bank_account_id=None, commit=False):
    """Create one cash/bank OUT ledger entry for a cash procurement/purchase.

    Supplier tetap remains optional. This helper only records money out for
    procurements marked CASH; CREDIT procurements are handled later by AP.
    It is idempotent by procurement reference to avoid duplicate ledger rows.
    """
    if not procurement:
        return False, "Data pembelian tidak ditemukan.", None

    if str(procurement.purchase_type or "").upper() != "CASH":
        return False, "Pembelian hutang tidak membuat ledger kas/bank keluar langsung.", None

    existing_transaction = CashBankTransaction.query.filter_by(
        reference_type=PROCUREMENT_REFERENCE_TYPE,
        reference_id=procurement.id,
    ).first()

    if existing_transaction:
        return False, "Ledger kas/bank untuk pembelian ini sudah ada.", existing_transaction

    amount = float(procurement.total_amount or 0)

    if amount <= 0:
        raise Exception(f"Total pembelian {procurement.procurement_number} tidak valid untuk ledger kas/bank.")

    account_type = str(account_type or "CASH").upper()
    resolved_bank_account_id = None

    if account_type == "CASH":
        resolved_bank_account_id = None
    elif account_type == "BANK":
        if not bank_account_id:
            raise Exception("Pembelian tunai dari bank wajib memilih rekening bank keluar.")

        bank_account = BankAccount.query.filter_by(
            id=bank_account_id,
            branch_id=procurement.branch_id,
            is_active=True,
        ).first()

        if not bank_account:
            raise Exception("Rekening bank keluar tidak valid atau tidak aktif.")

        resolved_bank_account_id = bank_account.id
    else:
        raise Exception("Sumber pembayaran pembelian tunai harus CASH atau BANK.")

    purchase_place = procurement.purchase_place or procurement.supplier_name or "Pembelian sendiri"
    destination = "Kas" if account_type == "CASH" else "Bank"

    description = (
        f"Pembelian tunai {procurement.procurement_number} di {purchase_place} "
        f"keluar dari {destination} sebesar {_money(amount)}"
    )

    transaction = CashBankTransaction(
        branch_id=procurement.branch_id,
        transaction_date=procurement.procurement_date,
        account_type=account_type,
        bank_account_id=resolved_bank_account_id,
        transaction_type="OUT",
        amount=amount,
        description=description,
        reference_type=PROCUREMENT_REFERENCE_TYPE,
        reference_id=procurement.id,
        created_by=created_by,
    )

    db.session.add(transaction)

    if commit:
        _commit_or_rollback()

    return True, "Ledger kas/bank pembelian tunai berhasil dibuat.", transaction


SUPPLIER_PAYMENT_REFERENCE_TYPE = "SUPPLIER_PAYMENT"


def create_supplier_payment_cash_bank_transaction(supplier_payment, created_by, commit=False):
    """Create one cash/bank OUT ledger entry for a supplier payment."""
    if not supplier_payment:
        return False, "Pembayaran supplier tidak ditemukan.", None

    existing_transaction = CashBankTransaction.query.filter_by(
        reference_type=SUPPLIER_PAYMENT_REFERENCE_TYPE,
        reference_id=supplier_payment.id,
    ).first()

    if existing_transaction:
        return False, "Ledger kas/bank untuk pembayaran supplier ini sudah ada.", existing_transaction

    method = str(supplier_payment.payment_method or "").upper()
    amount = float(supplier_payment.amount or 0)

    if amount <= 0:
        raise Exception(f"Nominal pembayaran supplier {supplier_payment.payment_number} tidak valid untuk ledger kas/bank.")

    account_type = None
    bank_account_id = None

    if method == "CASH":
        account_type = "CASH"
    elif method == "TRANSFER":
        account_type = "BANK"

        if not supplier_payment.bank_account_id:
            raise Exception("Pembayaran supplier transfer wajib memilih rekening bank keluar.")

        bank_account = BankAccount.query.filter_by(
            id=supplier_payment.bank_account_id,
            branch_id=supplier_payment.branch_id,
            is_active=True,
        ).first()

        if not bank_account:
            raise Exception("Rekening bank keluar tidak valid atau tidak aktif.")

        bank_account_id = bank_account.id
    else:
        raise Exception(f"Metode pembayaran supplier {method} belum dikenali untuk ledger kas/bank.")

    bill = SupplierBill.query.get(supplier_payment.supplier_bill_id)
    bill_number = bill.bill_number if bill else f"Supplier Bill ID {supplier_payment.supplier_bill_id}"
    supplier_name = bill.supplier_name if bill else "Supplier"
    source_label = "Kas" if account_type == "CASH" else "Bank"

    description = (
        f"Pembayaran hutang supplier {supplier_payment.payment_number} untuk {bill_number} "
        f"({supplier_name}) keluar dari {source_label} sebesar {_money(amount)}"
    )

    if supplier_payment.reference_number:
        description += f". Ref: {supplier_payment.reference_number}"

    transaction = CashBankTransaction(
        branch_id=supplier_payment.branch_id,
        transaction_date=supplier_payment.payment_date,
        account_type=account_type,
        bank_account_id=bank_account_id,
        transaction_type="OUT",
        amount=amount,
        description=description,
        reference_type=SUPPLIER_PAYMENT_REFERENCE_TYPE,
        reference_id=supplier_payment.id,
        created_by=created_by,
    )

    db.session.add(transaction)

    if commit:
        _commit_or_rollback()

    return True, "Ledger kas/bank pembayaran supplier berhasil dibuat.", transaction


# === PRODUCTION_CASH_BANK_CONTROL ===
OPENING_BALANCE_REFERENCE_TYPE = "OPENING_BALANCE"
CASH_BANK_TRANSFER_REFERENCE_TYPE = "CASH_BANK_TRANSFER"
CASH_BANK_ADJUSTMENT_REFERENCE_TYPE = "CASH_BANK_ADJUSTMENT"

# Jenis penyesuaian saldo dan akun lawannya (keputusan owner 2026-09-28, poin 8-9).
# Kas/bank sendiri memakai akun yang sama dengan jurnal lain: 1001 Kas, 1002 Bank.
ADJUSTMENT_CATEGORIES = {
    "SELISIH": {"label": "Selisih hitung kas/bank", "INCREASE": "4004", "DECREASE": "5009", "bank_only": False},
    "BIAYA_BANK": {"label": "Biaya administrasi bank", "DECREASE": "5008", "bank_only": True},
    "BUNGA_BANK": {"label": "Bunga / jasa giro bank", "INCREASE": "4004", "bank_only": True},
    "KODE_UNIK": {"label": "Kode unik transfer pelanggan", "INCREASE": "4004", "bank_only": False, "system_only": True},
}
# Selisih di atas batas ini hanya boleh dicatat OWNER.
SELISIH_OWNER_LIMIT = 100000


def cash_bank_coa_code(account_type, bank_account_id=None):
    """1001 untuk kas; untuk bank: akun COA milik rekening itu (1002 bila belum dipetakan)."""
    if str(account_type or "").upper() == "CASH":
        return "1001"
    from app.services.advance_service import resolve_cash_account_code

    return resolve_cash_account_code("BANK", bank_account_id)


def post_cash_bank_journal(*, journal_date, reference_type, reference_id, description, debit_code, credit_code, amount, created_by):
    """Jurnal dua baris untuk transaksi kas/bank. Gagal kalau akun tidak ada. Tidak commit."""
    from app.models.accounting import Journal, JournalDetail
    from app.services.accounting_service import generate_journal_number, get_active_account_by_code

    debit_account = get_active_account_by_code(debit_code)
    credit_account = get_active_account_by_code(credit_code)
    missing = [code for code, account in ((debit_code, debit_account), (credit_code, credit_account)) if account is None]
    if missing:
        raise Exception(f"Akun {', '.join(missing)} belum ada atau tidak aktif di COA.")
    journal = Journal(
        journal_number=generate_journal_number(journal_date),
        journal_date=journal_date,
        reference_type=reference_type,
        reference_id=reference_id,
        description=description,
        created_by=created_by,
    )
    db.session.add(journal)
    db.session.flush()
    db.session.add(JournalDetail(journal_id=journal.id, account_id=debit_account.id, debit=amount, credit=0))
    db.session.add(JournalDetail(journal_id=journal.id, account_id=credit_account.id, debit=0, credit=amount))
    db.session.flush()
    return journal


def normalize_cash_bank_account(account_type, bank_account_id=None, branch_id=None):
    """Return normalized account_type, bank_account_id, and stable account_key."""
    account_type = str(account_type or "").strip().upper()

    if account_type not in ["CASH", "BANK"]:
        raise Exception("Jenis akun kas/bank harus CASH atau BANK.")

    if account_type == "CASH":
        return "CASH", None, "CASH"

    if not bank_account_id:
        raise Exception("Akun BANK wajib memilih rekening bank.")

    try:
        bank_account_id = int(bank_account_id)
    except (TypeError, ValueError):
        raise Exception("Rekening bank tidak valid.")

    query = BankAccount.query.filter_by(id=bank_account_id, is_active=True)
    if branch_id is not None:
        query = query.filter_by(branch_id=branch_id)

    bank_account = query.first()
    if not bank_account:
        raise Exception("Rekening bank tidak ditemukan atau tidak aktif.")

    return "BANK", bank_account.id, f"BANK:{bank_account.id}"


def get_account_label(account_type, bank_account=None):
    account_type = str(account_type or "").upper()
    if account_type == "CASH":
        return "Kas Operasional"
    if account_type == "BANK" and bank_account:
        return f"{bank_account.bank_name} - {bank_account.account_name}"
    return "Bank"


def calculate_account_balance(branch_id, account_type, bank_account_id=None):
    account_type, bank_account_id, _ = normalize_cash_bank_account(
        account_type=account_type,
        bank_account_id=bank_account_id,
        branch_id=branch_id,
    )

    query = CashBankTransaction.query.filter_by(
        branch_id=branch_id,
        account_type=account_type,
        bank_account_id=bank_account_id,
    )

    total_in = 0
    total_out = 0

    for transaction in query.all():
        amount = float(transaction.amount or 0)
        transaction_type = str(transaction.transaction_type or "").upper()
        if transaction_type == "IN":
            total_in += amount
        elif transaction_type == "OUT":
            total_out += amount

    return total_in - total_out


def _next_sequence_number(model, field_name, prefix, branch_id=None):
    from datetime import date

    date_part = date.today().strftime("%Y%m%d")
    base = f"{prefix}-{date_part}"
    query = model.query
    if branch_id is not None and hasattr(model, "branch_id"):
        query = query.filter(model.branch_id == branch_id)

    count_today = query.filter(getattr(model, field_name).like(f"{base}-%")).count()
    next_number = count_today + 1

    while True:
        value = f"{base}-{next_number:04d}"
        exists = model.query.filter(getattr(model, field_name) == value).first()
        if not exists:
            return value
        next_number += 1


def create_cash_bank_transfer(transfer_date, from_account_type, from_bank_account_id, to_account_type, to_bank_account_id, amount, created_by, branch_id, reference_number=None, notes=None, commit=False):
    from app.models.finance import CashBankTransfer

    from_account_type, from_bank_account_id, from_key = normalize_cash_bank_account(
        from_account_type,
        from_bank_account_id,
        branch_id=branch_id,
    )
    to_account_type, to_bank_account_id, to_key = normalize_cash_bank_account(
        to_account_type,
        to_bank_account_id,
        branch_id=branch_id,
    )

    if from_key == to_key:
        raise Exception("Akun asal dan tujuan transfer tidak boleh sama.")

    amount = float(amount or 0)
    if amount <= 0:
        raise Exception("Nominal transfer harus lebih dari 0.")

    current_from_balance = calculate_account_balance(branch_id, from_account_type, from_bank_account_id)
    if amount > current_from_balance:
        raise Exception(f"Saldo akun asal tidak cukup. Saldo tersedia {_money(current_from_balance)}.")

    from_bank = BankAccount.query.get(from_bank_account_id) if from_bank_account_id else None
    to_bank = BankAccount.query.get(to_bank_account_id) if to_bank_account_id else None
    from_label = get_account_label(from_account_type, from_bank)
    to_label = get_account_label(to_account_type, to_bank)

    transfer = CashBankTransfer(
        branch_id=branch_id,
        transfer_number=_next_sequence_number(CashBankTransfer, "transfer_number", "TRF", branch_id=branch_id),
        transfer_date=transfer_date,
        from_account_type=from_account_type,
        from_bank_account_id=from_bank_account_id,
        to_account_type=to_account_type,
        to_bank_account_id=to_bank_account_id,
        amount=amount,
        reference_number=reference_number,
        notes=notes,
        created_by=created_by,
    )
    db.session.add(transfer)
    db.session.flush()

    description_suffix = f" Ref: {reference_number}" if reference_number else ""

    out_transaction = CashBankTransaction(
        branch_id=branch_id,
        transaction_date=transfer_date,
        account_type=from_account_type,
        bank_account_id=from_bank_account_id,
        transaction_type="OUT",
        amount=amount,
        description=f"Transfer keluar dari {from_label} ke {to_label} sebesar {_money(amount)}.{description_suffix}",
        reference_type=CASH_BANK_TRANSFER_REFERENCE_TYPE,
        reference_id=transfer.id,
        transfer_group_id=transfer.id,
        created_by=created_by,
    )
    in_transaction = CashBankTransaction(
        branch_id=branch_id,
        transaction_date=transfer_date,
        account_type=to_account_type,
        bank_account_id=to_bank_account_id,
        transaction_type="IN",
        amount=amount,
        description=f"Transfer masuk ke {to_label} dari {from_label} sebesar {_money(amount)}.{description_suffix}",
        reference_type=CASH_BANK_TRANSFER_REFERENCE_TYPE,
        reference_id=transfer.id,
        transfer_group_id=transfer.id,
        created_by=created_by,
    )
    db.session.add(out_transaction)
    db.session.add(in_transaction)
    db.session.flush()

    # Kas <-> bank dan bank ke bank beda akun COA mengubah posisi di buku
    # besar; dua rekening yang dipetakan ke akun yang sama tidak.
    debit_code = cash_bank_coa_code(to_account_type, to_bank_account_id)
    credit_code = cash_bank_coa_code(from_account_type, from_bank_account_id)
    if debit_code != credit_code:
        post_cash_bank_journal(
            journal_date=transfer_date,
            reference_type=CASH_BANK_TRANSFER_REFERENCE_TYPE,
            reference_id=transfer.id,
            description=f"Pindah dana {transfer.transfer_number}: {from_label} ke {to_label}",
            debit_code=debit_code,
            credit_code=credit_code,
            amount=amount,
            created_by=created_by,
        )

    if commit:
        _commit_or_rollback()

    return transfer, out_transaction, in_transaction


def create_cash_bank_transfer_record(
    *,
    transfer_date,
    from_account_type,
    from_bank_account_id,
    to_account_type,
    to_bank_account_id,
    amount,
    created_by,
    branch_id,
    reference_number=None,
    notes=None,
):
    try:
        transfer, out_transaction, in_transaction = create_cash_bank_transfer(
            transfer_date=transfer_date,
            from_account_type=from_account_type,
            from_bank_account_id=from_bank_account_id,
            to_account_type=to_account_type,
            to_bank_account_id=to_bank_account_id,
            amount=amount,
            created_by=created_by,
            branch_id=branch_id,
            reference_number=reference_number,
            notes=notes,
            commit=False,
        )
    except Exception:
        db.session.rollback()
        raise
    _commit_or_rollback()
    return transfer, out_transaction, in_transaction


def create_cash_bank_adjustment(adjustment_date, account_type, bank_account_id, adjustment_type, amount, reason, created_by, branch_id, notes=None, commit=False, category=None, actor_role=None, allow_system_category=False):
    from app.models.finance import CashBankAdjustment
    from app.utils.roles import effective_role

    account_type, bank_account_id, account_key = normalize_cash_bank_account(
        account_type,
        bank_account_id,
        branch_id=branch_id,
    )

    adjustment_type = str(adjustment_type or "").strip().upper()
    if adjustment_type not in ["INCREASE", "DECREASE"]:
        raise Exception("Tipe penyesuaian harus INCREASE atau DECREASE.")

    category = str(category or "").strip().upper()
    rule = ADJUSTMENT_CATEGORIES.get(category)
    if rule is None:
        raise Exception("Pilih jenis penyesuaian: selisih hitung, biaya administrasi bank, atau bunga bank.")
    if rule.get("system_only") and not allow_system_category:
        raise Exception("Jenis penyesuaian ini hanya dibuat otomatis oleh sistem.")
    if rule["bank_only"] and account_type != "BANK":
        raise Exception(f"{rule['label']} hanya untuk rekening bank.")
    counter_code = rule.get(adjustment_type)
    if counter_code is None:
        direction = "menambah" if adjustment_type == "INCREASE" else "mengurangi"
        raise Exception(f"{rule['label']} tidak bisa {direction} saldo.")

    amount = float(amount or 0)
    if amount <= 0:
        raise Exception("Nominal penyesuaian harus lebih dari 0.")
    if category == "SELISIH" and amount > SELISIH_OWNER_LIMIT and effective_role(actor_role) != "OWNER":
        raise Exception(f"Selisih di atas {_money(SELISIH_OWNER_LIMIT)} hanya bisa dicatat OWNER.")

    if adjustment_type == "DECREASE":
        current_balance = calculate_account_balance(branch_id, account_type, bank_account_id)
        if amount > current_balance:
            raise Exception(f"Saldo tidak cukup untuk dikurangi. Saldo tersedia {_money(current_balance)}.")

    reason = str(reason or "").strip()
    if not reason:
        raise Exception("Alasan penyesuaian saldo wajib diisi.")

    bank_account = BankAccount.query.get(bank_account_id) if bank_account_id else None
    account_label = get_account_label(account_type, bank_account)
    transaction_type = "IN" if adjustment_type == "INCREASE" else "OUT"

    adjustment = CashBankAdjustment(
        branch_id=branch_id,
        adjustment_number=_next_sequence_number(CashBankAdjustment, "adjustment_number", "ADJ", branch_id=branch_id),
        adjustment_date=adjustment_date,
        account_type=account_type,
        bank_account_id=bank_account_id,
        account_key=account_key,
        adjustment_type=adjustment_type,
        adjustment_category=category,
        amount=amount,
        reason=reason,
        notes=notes,
        created_by=created_by,
    )
    db.session.add(adjustment)
    db.session.flush()

    direction_label = "Penambahan" if adjustment_type == "INCREASE" else "Pengurangan"
    transaction = CashBankTransaction(
        branch_id=branch_id,
        transaction_date=adjustment_date,
        account_type=account_type,
        bank_account_id=bank_account_id,
        transaction_type=transaction_type,
        amount=amount,
        description=f"{direction_label} saldo {account_label}: {reason}. Nominal {_money(amount)}",
        reference_type=CASH_BANK_ADJUSTMENT_REFERENCE_TYPE,
        reference_id=adjustment.id,
        created_by=created_by,
    )
    db.session.add(transaction)
    db.session.flush()

    adjustment.ledger_transaction_id = transaction.id

    cash_code = cash_bank_coa_code(account_type, bank_account_id)
    post_cash_bank_journal(
        journal_date=adjustment_date,
        reference_type=CASH_BANK_ADJUSTMENT_REFERENCE_TYPE,
        reference_id=adjustment.id,
        description=f"{rule['label']} {adjustment.adjustment_number} ({account_label}): {reason}",
        debit_code=cash_code if adjustment_type == "INCREASE" else counter_code,
        credit_code=counter_code if adjustment_type == "INCREASE" else cash_code,
        amount=amount,
        created_by=created_by,
    )

    if commit:
        _commit_or_rollback()

    return adjustment, transaction


def create_cash_bank_adjustment_record(
    *,
    adjustment_date,
    account_type,
    bank_account_id,
    adjustment_type,
    amount,
    reason,
    created_by,
    branch_id,
    notes=None,
    category=None,
    actor_role=None,
    allow_system_category=False,
):
    try:
        adjustment, transaction = create_cash_bank_adjustment(
            adjustment_date=adjustment_date,
            account_type=account_type,
            bank_account_id=bank_account_id,
            adjustment_type=adjustment_type,
            amount=amount,
            reason=reason,
            created_by=created_by,
            branch_id=branch_id,
            notes=notes,
            commit=False,
            category=category,
            actor_role=actor_role,
            allow_system_category=allow_system_category,
        )
    except Exception:
        db.session.rollback()
        raise
    _commit_or_rollback()
    return adjustment, transaction


def reconcile_cash_bank_transaction(transaction, reconciled_by, note=None, commit=False):
    from datetime import datetime

    if not transaction:
        raise Exception("Transaksi kas/bank tidak ditemukan.")

    transaction.is_reconciled = True
    transaction.reconciled_at = datetime.now()
    transaction.reconciled_by = reconciled_by
    transaction.reconciliation_note = note

    if commit:
        _commit_or_rollback()

    return transaction


def reconcile_cash_bank_transaction_record(transaction, *, reconciled_by, note=None):
    transaction = reconcile_cash_bank_transaction(
        transaction,
        reconciled_by=reconciled_by,
        note=note,
        commit=False,
    )
    _commit_or_rollback()
    return transaction


def unreconcile_cash_bank_transaction(transaction, commit=False):
    if not transaction:
        raise Exception("Transaksi kas/bank tidak ditemukan.")

    transaction.is_reconciled = False
    transaction.reconciled_at = None
    transaction.reconciled_by = None
    transaction.reconciliation_note = None

    if commit:
        _commit_or_rollback()

    return transaction


def unreconcile_cash_bank_transaction_record(transaction):
    transaction = unreconcile_cash_bank_transaction(transaction, commit=False)
    _commit_or_rollback()
    return transaction


# --- akun COA per rekening bank ----------------------------------------------

def bank_coa_choices():
    """Akun buku besar yang boleh dipetakan ke rekening bank: aset aktif bernama Bank."""
    from app.models.accounting import Account

    return (
        Account.query.filter(
            Account.is_active.is_(True),
            Account.account_type == "ASSET",
            Account.account_name.ilike("bank%"),
        )
        .order_by(Account.account_code.asc())
        .all()
    )


def bank_account_has_activity(bank_account):
    """Rekening sudah punya transaksi/saldo awal: akun COA-nya tidak boleh dipindah lagi.

    Jurnal lama sudah memakai akun lama; memindah akun membuat buku besar dan
    buku kas-bank rekening ini tidak cocok lagi.
    """
    from app.models.finance import CashBankOpeningBalance

    if not bank_account or not getattr(bank_account, "id", None):
        return False
    if CashBankTransaction.query.filter_by(bank_account_id=bank_account.id).first():
        return True
    return CashBankOpeningBalance.query.filter_by(bank_account_id=bank_account.id).first() is not None


def validate_bank_coa_code(bank_account, code):
    """Kode COA yang sah untuk rekening ini, atau Exception dengan pesan jelas."""
    code = str(code or "").strip() or None
    current = str(getattr(bank_account, "coa_account_code", "") or "").strip() or None
    effective_new = code or "1002"
    effective_old = current or "1002"
    if bank_account is not None and effective_new != effective_old and bank_account_has_activity(bank_account):
        raise Exception(
            f"Akun COA rekening ini terkunci di {effective_old} karena sudah ada transaksi. "
            "Untuk memakai akun lain, buat rekening baru."
        )
    if code and code not in {account.account_code for account in bank_coa_choices()}:
        raise Exception(f"Akun {code} bukan akun bank aktif di COA.")
    return code
