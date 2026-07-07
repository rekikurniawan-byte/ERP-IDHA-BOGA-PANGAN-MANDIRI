from app.extensions import db
from app.models.finance import BankAccount, CashBankTransaction, Invoice, SupplierBill


CUSTOMER_PAYMENT_REFERENCE_TYPE = "PAYMENT"


def _money(value):
    try:
        return f"Rp {float(value or 0):,.0f}".replace(",", ".")
    except Exception:
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
        db.session.commit()

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
        db.session.commit()

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
        db.session.commit()

    return True, "Ledger kas/bank pembayaran supplier berhasil dibuat.", transaction


# === PRODUCTION_CASH_BANK_CONTROL ===
OPENING_BALANCE_REFERENCE_TYPE = "OPENING_BALANCE"
CASH_BANK_TRANSFER_REFERENCE_TYPE = "CASH_BANK_TRANSFER"
CASH_BANK_ADJUSTMENT_REFERENCE_TYPE = "CASH_BANK_ADJUSTMENT"


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


def create_opening_balance(account_type, bank_account_id, opening_date, amount, created_by, branch_id, notes=None, commit=False):
    from app.models.finance import CashBankOpeningBalance

    account_type, bank_account_id, account_key = normalize_cash_bank_account(
        account_type=account_type,
        bank_account_id=bank_account_id,
        branch_id=branch_id,
    )

    amount = float(amount or 0)
    if amount < 0:
        raise Exception("Saldo awal tidak boleh negatif.")

    existing = CashBankOpeningBalance.query.filter_by(
        branch_id=branch_id,
        account_key=account_key,
    ).first()
    if existing:
        raise Exception("Saldo awal untuk akun ini sudah pernah dibuat. Gunakan penyesuaian saldo jika ada koreksi.")

    bank_account = BankAccount.query.get(bank_account_id) if bank_account_id else None
    account_label = get_account_label(account_type, bank_account)

    opening = CashBankOpeningBalance(
        branch_id=branch_id,
        account_type=account_type,
        bank_account_id=bank_account_id,
        account_key=account_key,
        opening_date=opening_date,
        amount=amount,
        notes=notes,
        created_by=created_by,
    )
    db.session.add(opening)
    db.session.flush()

    transaction = CashBankTransaction(
        branch_id=branch_id,
        transaction_date=opening_date,
        account_type=account_type,
        bank_account_id=bank_account_id,
        transaction_type="IN",
        amount=amount,
        description=f"Saldo awal {account_label} sebesar {_money(amount)}",
        reference_type=OPENING_BALANCE_REFERENCE_TYPE,
        reference_id=opening.id,
        created_by=created_by,
    )
    db.session.add(transaction)
    db.session.flush()

    opening.ledger_transaction_id = transaction.id

    if commit:
        db.session.commit()

    return opening, transaction


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

    if commit:
        db.session.commit()

    return transfer, out_transaction, in_transaction


def create_cash_bank_adjustment(adjustment_date, account_type, bank_account_id, adjustment_type, amount, reason, created_by, branch_id, notes=None, commit=False):
    from app.models.finance import CashBankAdjustment

    account_type, bank_account_id, account_key = normalize_cash_bank_account(
        account_type,
        bank_account_id,
        branch_id=branch_id,
    )

    adjustment_type = str(adjustment_type or "").strip().upper()
    if adjustment_type not in ["INCREASE", "DECREASE"]:
        raise Exception("Tipe penyesuaian harus INCREASE atau DECREASE.")

    amount = float(amount or 0)
    if amount <= 0:
        raise Exception("Nominal penyesuaian harus lebih dari 0.")

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

    if commit:
        db.session.commit()

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
        db.session.commit()

    return transaction


def unreconcile_cash_bank_transaction(transaction, commit=False):
    if not transaction:
        raise Exception("Transaksi kas/bank tidak ditemukan.")

    transaction.is_reconciled = False
    transaction.reconciled_at = None
    transaction.reconciled_by = None
    transaction.reconciliation_note = None

    if commit:
        db.session.commit()

    return transaction
