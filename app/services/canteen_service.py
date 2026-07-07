from app.extensions import db
from app.models.canteen import (
    CanteenSale,
    CanteenSaleItem,
    WorkerDebt,
    DebtPayment,
    CanteenExternalReceivable,
    CanteenExternalReceivablePayment,
)
from app.models.finance import BankAccount, CashBankTransaction
from app.services.atomic_transaction_service import atomic_business_action

PAYMENT_METHODS = ["CASH", "QRIS", "TRANSFER", "DEBT"]
PAID_PAYMENT_METHODS = ["CASH", "QRIS", "TRANSFER"]
BUYER_TYPES = ["REGISTERED_WORKER", "GENERAL_BUYER", "EXTERNAL_COMPANY_WORKER", "GUEST"]
EXTERNAL_DEBT_BUYER_TYPES = ["EXTERNAL_COMPANY_WORKER", "GUEST", "GENERAL_BUYER"]


def _clean(value):
    text = str(value or "").strip()
    return text or None


def _normalize_choice(value, allowed, default_value):
    clean = str(value or "").strip().upper()
    return clean if clean in allowed else default_value


def _require_active_bank_account(branch_id, bank_account_id):
    if not bank_account_id:
        return None

    try:
        bank_account_id = int(bank_account_id)
    except (TypeError, ValueError):
        return None

    return BankAccount.query.filter_by(
        id=bank_account_id,
        branch_id=branch_id,
        is_active=True,
    ).first()


def _create_warung_cash_bank_transaction(sale, created_by):
    """Catat ledger kas/bank warung untuk transaksi lunas dan pembayaran piutang."""
    if not sale:
        return None

    payment_method = _normalize_choice(getattr(sale, "payment_method", None), PAYMENT_METHODS, "CASH")

    if payment_method not in PAID_PAYMENT_METHODS:
        return None

    account_type = "CASH" if payment_method == "CASH" else "BANK"
    bank_account_id = getattr(sale, "cash_bank_account_id", None) if account_type == "BANK" else None
    label = "Kas" if account_type == "CASH" else payment_method

    existing = CashBankTransaction.query.filter_by(
        reference_type="CANTEEN_SALE",
        reference_id=sale.id,
    ).first()

    if existing:
        return existing

    transaction = CashBankTransaction(
        branch_id=sale.branch_id,
        transaction_date=sale.sale_date,
        account_type=account_type,
        bank_account_id=bank_account_id,
        transaction_type="IN",
        amount=float(sale.total_amount or 0),
        description=f"Penjualan warung {payment_method} - Sale #{sale.id} masuk ke {label}.",
        reference_type="CANTEEN_SALE",
        reference_id=sale.id,
        created_by=created_by,
    )
    db.session.add(transaction)
    return transaction


def _create_external_receivable_payment_cash_bank_transaction(payment, created_by):
    if not payment:
        return None

    payment_method = _normalize_choice(getattr(payment, "payment_method", None), PAYMENT_METHODS, "CASH")

    if payment_method not in PAID_PAYMENT_METHODS:
        return None

    existing = CashBankTransaction.query.filter_by(
        reference_type="CANTEEN_EXTERNAL_RECEIVABLE_PAYMENT",
        reference_id=payment.id,
    ).first()

    if existing:
        return existing

    account_type = "CASH" if payment_method == "CASH" else "BANK"
    bank_account_id = getattr(payment, "cash_bank_account_id", None) if account_type == "BANK" else None

    transaction = CashBankTransaction(
        branch_id=payment.external_receivable.branch_id,
        transaction_date=payment.payment_date,
        account_type=account_type,
        bank_account_id=bank_account_id,
        transaction_type="IN",
        amount=float(payment.amount or 0),
        description=f"Pembayaran piutang warung eksternal #{payment.external_receivable.id} via {payment_method}.",
        reference_type="CANTEEN_EXTERNAL_RECEIVABLE_PAYMENT",
        reference_id=payment.id,
        created_by=created_by,
    )
    db.session.add(transaction)
    return transaction


def create_canteen_sale(
    branch_id,
    sale_date,
    sale_type=None,
    worker_id=None,
    item_rows=None,
    notes=None,
    created_by=None,
    payment_method=None,
    buyer_type=None,
    buyer_name=None,
    buyer_company=None,
    buyer_phone=None,
    payment_reference=None,
    cash_bank_account_id=None,
):
    item_rows = item_rows or []
    payment_method = _normalize_choice(payment_method or sale_type, PAYMENT_METHODS, "CASH")
    buyer_type = _normalize_choice(buyer_type, BUYER_TYPES, "GENERAL_BUYER")
    sale_type = "DEBT" if payment_method == "DEBT" else "CASH"

    if payment_method in ["QRIS", "TRANSFER"]:
        bank = _require_active_bank_account(branch_id, cash_bank_account_id)
        if not bank:
            return False, "Transaksi QRIS/transfer wajib memilih rekening bank aktif.", None
        cash_bank_account_id = bank.id
    else:
        cash_bank_account_id = None

    if payment_method == "DEBT" and buyer_type == "REGISTERED_WORKER" and not worker_id:
        return False, "Hutang pekerja internal wajib memilih pekerja.", None

    if payment_method == "DEBT" and buyer_type in EXTERNAL_DEBT_BUYER_TYPES and not _clean(buyer_name):
        return False, "Hutang buyer eksternal wajib mengisi nama pembeli.", None

    valid_items = []
    total_amount = 0

    for row in item_rows:
        item_id = row.get("item_id")
        qty = int(row.get("qty") or 0)
        price = float(row.get("price") or 0)

        if not item_id or qty <= 0:
            continue

        subtotal = qty * price

        valid_items.append({
            "item_id": int(item_id),
            "qty": qty,
            "price": price,
            "subtotal": subtotal,
        })

        total_amount += subtotal

    if not valid_items:
        return False, "Minimal satu barang warung harus diisi.", None

    if total_amount <= 0:
        return False, "Total transaksi harus lebih dari 0.", None

    is_external_debt = payment_method == "DEBT" and buyer_type in EXTERNAL_DEBT_BUYER_TYPES

    sale = CanteenSale(
        branch_id=branch_id,
        sale_date=sale_date,
        sale_type=sale_type,
        payment_method=payment_method,
        buyer_type=buyer_type,
        buyer_name=_clean(buyer_name),
        buyer_company=_clean(buyer_company),
        buyer_phone=_clean(buyer_phone),
        payment_reference=_clean(payment_reference),
        cash_bank_account_id=cash_bank_account_id,
        is_external_debt=is_external_debt,
        total_amount=total_amount,
        notes=notes,
        created_by=created_by,
    )

    with atomic_business_action(
        module="CANTEEN",
        action="CANTEEN_SALE_CREATE",
        description="Create transaksi warung + hutang/piutang/jurnal/ledger secara atomic.",
        reference_type="canteen_sales",
        user_id=created_by,
        branch_id=branch_id,
        metadata={"payment_method": payment_method, "buyer_type": buyer_type, "item_count": len(valid_items), "total_amount": total_amount},
    ):
        db.session.add(sale)
        db.session.flush()

        for row in valid_items:
            sale_item = CanteenSaleItem(
                sale_id=sale.id,
                item_id=row["item_id"],
                qty=row["qty"],
                price=row["price"],
                subtotal=row["subtotal"],
            )
            db.session.add(sale_item)

        if payment_method == "DEBT" and buyer_type == "REGISTERED_WORKER":
            worker_debt = WorkerDebt(
                branch_id=branch_id,
                worker_id=int(worker_id),
                sale_id=sale.id,
                debt_amount=total_amount,
                status="UNPAID",
            )
            db.session.add(worker_debt)
            db.session.flush()

            from app.services.accounting_service import create_warung_debt_accrual_journal
            create_warung_debt_accrual_journal(
                worker_debt=worker_debt,
                created_by=created_by,
                commit=False,
            )
        elif payment_method == "DEBT" and is_external_debt:
            receivable = CanteenExternalReceivable(
                branch_id=branch_id,
                sale_id=sale.id,
                buyer_name=_clean(buyer_name) or "Pembeli Eksternal",
                buyer_company=_clean(buyer_company),
                buyer_phone=_clean(buyer_phone),
                receivable_amount=total_amount,
                paid_amount=0,
                remaining_amount=total_amount,
                status="UNPAID",
                notes=notes,
                created_by=created_by,
            )
            db.session.add(receivable)
            db.session.flush()

            from app.services.accounting_service import create_warung_external_debt_accrual_journal
            create_warung_external_debt_accrual_journal(
                external_receivable=receivable,
                created_by=created_by,
                commit=False,
            )
        elif payment_method in PAID_PAYMENT_METHODS:
            from app.services.accounting_service import create_warung_direct_sale_journal
            create_warung_direct_sale_journal(
                sale=sale,
                created_by=created_by,
                commit=False,
            )
            _create_warung_cash_bank_transaction(sale=sale, created_by=created_by)

    return True, "Transaksi warung berhasil disimpan.", sale


def get_debt_paid_amount(worker_debt):
    return sum(payment.amount for payment in worker_debt.payments)


def get_debt_remaining_amount(worker_debt):
    paid_amount = get_debt_paid_amount(worker_debt)
    remaining = worker_debt.debt_amount - paid_amount

    if remaining < 0:
        return 0

    return remaining


def pay_worker_debt(worker_debt, payment_date, amount, notes, created_by, payment_method="CASH", cash_bank_account_id=None, payment_reference=None):
    from app.extensions import db
    from app.models.canteen import WorkerDebt

    amount = float(amount or 0)
    payment_method = _normalize_choice(payment_method, PAID_PAYMENT_METHODS, "CASH")

    if amount <= 0:
        return False, "Jumlah pembayaran harus lebih dari 0."

    # Lock the debt row to prevent concurrent overpayment (SELECT FOR UPDATE)
    locked_debt = WorkerDebt.query.with_for_update().get(worker_debt.id)
    if not locked_debt:
        return False, "Data hutang tidak ditemukan."

    remaining = get_debt_remaining_amount(locked_debt)

    if remaining <= 0:
        return False, "Hutang ini sudah lunas."

    if amount > remaining:
        return False, "Pembayaran melebihi sisa hutang."

    if payment_method in ["QRIS", "TRANSFER"]:
        bank = _require_active_bank_account(worker_debt.branch_id, cash_bank_account_id)
        if not bank:
            return False, "Pembayaran QRIS/transfer wajib memilih rekening bank aktif."
        cash_bank_account_id = bank.id
    else:
        cash_bank_account_id = None

    payment = DebtPayment(
        worker_debt_id=worker_debt.id,
        payment_date=payment_date,
        amount=amount,
        payment_method=payment_method,
        cash_bank_account_id=cash_bank_account_id,
        payment_reference=_clean(payment_reference),
        notes=notes,
        created_by=created_by,
    )

    with atomic_business_action(
        module="CANTEEN",
        action="CANTEEN_WORKER_DEBT_PAY",
        description=f"Bayar hutang warung pekerja #{worker_debt.id} secara atomic.",
        reference_type="worker_debts",
        reference_id=worker_debt.id,
        user_id=created_by,
        branch_id=worker_debt.branch_id,
        metadata={"worker_debt_id": worker_debt.id, "amount": amount, "payment_method": payment_method},
    ):
        db.session.add(payment)
        db.session.flush()

        from app.services.accounting_service import create_warung_debt_payment_journal
        create_warung_debt_payment_journal(
            debt_payment=payment,
            created_by=created_by,
            commit=False,
        )

        existing_ledger = CashBankTransaction.query.filter_by(
            reference_type="CANTEEN_WORKER_DEBT_PAYMENT",
            reference_id=payment.id,
        ).first()
        if not existing_ledger:
            db.session.add(CashBankTransaction(
                branch_id=worker_debt.branch_id,
                transaction_date=payment.payment_date,
                account_type="CASH" if payment_method == "CASH" else "BANK",
                bank_account_id=cash_bank_account_id if payment_method != "CASH" else None,
                transaction_type="IN",
                amount=amount,
                description=f"Pembayaran hutang warung pekerja #{worker_debt.id} via {payment_method}.",
                reference_type="CANTEEN_WORKER_DEBT_PAYMENT",
                reference_id=payment.id,
                created_by=created_by,
            ))

        new_remaining = remaining - amount

        if new_remaining <= 0:
            worker_debt.status = "PAID"
        elif amount > 0:
            worker_debt.status = "PARTIAL"
        else:
            worker_debt.status = "UNPAID"

    return True, "Pembayaran hutang berhasil disimpan."


def get_external_receivable_paid_amount(receivable):
    return float(receivable.paid_amount or 0)


def get_external_receivable_remaining_amount(receivable):
    remaining = float(receivable.remaining_amount or 0)
    if remaining < 0:
        return 0
    return remaining


def pay_external_receivable(receivable, payment_date, amount, payment_method, cash_bank_account_id, payment_reference, notes, created_by):
    from app.extensions import db
    from app.models.canteen import CanteenExternalReceivable

    amount = float(amount or 0)
    payment_method = _normalize_choice(payment_method, PAID_PAYMENT_METHODS, "CASH")

    if amount <= 0:
        return False, "Jumlah pembayaran harus lebih dari 0."

    # Lock the receivable row to prevent concurrent overpayment (SELECT FOR UPDATE)
    locked_receivable = CanteenExternalReceivable.query.with_for_update().get(receivable.id)
    if not locked_receivable:
        return False, "Data piutang tidak ditemukan."

    remaining = get_external_receivable_remaining_amount(locked_receivable)

    if remaining <= 0:
        return False, "Piutang eksternal ini sudah lunas."

    if amount > remaining:
        return False, "Pembayaran melebihi sisa piutang eksternal."

    if payment_method in ["QRIS", "TRANSFER"]:
        bank = _require_active_bank_account(receivable.branch_id, cash_bank_account_id)
        if not bank:
            return False, "Pembayaran QRIS/transfer wajib memilih rekening bank aktif."
        cash_bank_account_id = bank.id
    else:
        cash_bank_account_id = None

    payment = CanteenExternalReceivablePayment(
        receivable_id=receivable.id,
        payment_date=payment_date,
        amount=amount,
        payment_method=payment_method,
        cash_bank_account_id=cash_bank_account_id,
        payment_reference=_clean(payment_reference),
        notes=notes,
        created_by=created_by,
    )
    with atomic_business_action(
        module="CANTEEN",
        action="CANTEEN_EXTERNAL_RECEIVABLE_PAY",
        description=f"Bayar piutang warung eksternal #{receivable.id} secara atomic.",
        reference_type="canteen_external_receivables",
        reference_id=receivable.id,
        user_id=created_by,
        branch_id=receivable.branch_id,
        metadata={"receivable_id": receivable.id, "amount": amount, "payment_method": payment_method},
    ):
        db.session.add(payment)
        db.session.flush()

        receivable.paid_amount = float(receivable.paid_amount or 0) + amount
        receivable.remaining_amount = max(float(receivable.receivable_amount or 0) - float(receivable.paid_amount or 0), 0)

        if receivable.remaining_amount <= 0:
            receivable.status = "PAID"
        elif receivable.paid_amount > 0:
            receivable.status = "PARTIAL"
        else:
            receivable.status = "UNPAID"

        from app.services.accounting_service import create_warung_external_receivable_payment_journal
        create_warung_external_receivable_payment_journal(
            external_payment=payment,
            created_by=created_by,
            commit=False,
        )

        _create_external_receivable_payment_cash_bank_transaction(payment=payment, created_by=created_by)

    return True, "Pembayaran piutang warung eksternal berhasil disimpan."
