import logging
from datetime import timedelta

from app.extensions import db
from app.models.finance import BankAccount, SupplierBill, SupplierPayment
from app.services.business_logic_guard_service import (
    BusinessRuleError,
    SUPPLIER_PAYMENT_METHODS,
    assert_date_not_before,
    assert_payment_amount_not_over_remaining,
    resolve_supplier_bill_status_after_payment,
    validate_choice,
)

logger = logging.getLogger(__name__)


SUPPLIER_BILL_STATUS_OPEN = "OPEN"
SUPPLIER_BILL_STATUS_PARTIAL = "PARTIAL"
SUPPLIER_BILL_STATUS_PAID = "PAID"


def _money(value):
    try:
        return f"Rp {float(value or 0):,.0f}".replace(",", ".")
    except Exception:
        logger.exception("Suppressed unexpected exception in app/services/accounts_payable_service.py:23")
        return "Rp 0"


def generate_supplier_bill_number(bill_date):
    prefix = f"SB-{bill_date.strftime('%Y%m%d')}"
    counter = SupplierBill.query.filter(SupplierBill.bill_number.like(f"{prefix}-%")).count() + 1

    while True:
        bill_number = f"{prefix}-{counter:03d}"
        existing = SupplierBill.query.filter_by(bill_number=bill_number).first()

        if not existing:
            return bill_number

        counter += 1


def resolve_supplier_bill_due_date(procurement, due_date=None):
    """Resolve due date for a CREDIT procurement supplier bill.

    If user provides a due date, use it. Otherwise use supplier default terms
    when available. For manual/non-fixed supplier purchases, default to the
    procurement date so AP aging can still work without forcing supplier master.
    """
    if due_date:
        return due_date

    bill_date = procurement.procurement_date
    supplier = getattr(procurement, "supplier", None)
    terms_days = int(getattr(supplier, "default_payment_terms_days", 0) or 0)

    if terms_days < 0:
        terms_days = 0

    return bill_date + timedelta(days=terms_days)


def create_supplier_bill_for_procurement(procurement, created_by, due_date=None, commit=False):
    """Create one AP supplier bill for a CREDIT procurement.

    Supplier master remains optional. If procurement has no supplier_id, the
    bill still uses procurement.supplier_name / purchase_place as snapshot.
    The helper is idempotent by procurement_id.
    """
    if not procurement:
        return False, "Data pembelian tidak ditemukan.", None

    purchase_type = str(procurement.purchase_type or "").upper()

    if purchase_type != "CREDIT":
        return False, "Supplier bill hanya dibuat untuk pembelian hutang/CREDIT.", None

    existing_bill = SupplierBill.query.filter_by(
        procurement_id=procurement.id,
    ).first()

    if existing_bill:
        return False, "Supplier bill untuk pembelian ini sudah ada.", existing_bill

    amount = float(procurement.total_amount or 0)

    if amount <= 0:
        raise Exception(f"Total pembelian {procurement.procurement_number} tidak valid untuk hutang supplier.")

    bill_date = procurement.procurement_date
    resolved_due_date = resolve_supplier_bill_due_date(procurement, due_date=due_date)

    if resolved_due_date < bill_date:
        raise Exception("Tanggal jatuh tempo hutang supplier tidak boleh lebih awal dari tanggal pembelian.")

    supplier_name = (
        getattr(getattr(procurement, "supplier", None), "supplier_name", None)
        or procurement.supplier_name
        or procurement.purchase_place
        or "Supplier / toko tidak tetap"
    )

    notes = f"Dibuat otomatis dari pembelian hutang {procurement.procurement_number}."

    if procurement.notes:
        notes += f" Catatan pembelian: {procurement.notes}"

    bill = SupplierBill(
        branch_id=procurement.branch_id,
        bill_number=generate_supplier_bill_number(bill_date),
        supplier_id=procurement.supplier_id,
        procurement_id=procurement.id,
        bill_date=bill_date,
        due_date=resolved_due_date,
        supplier_name=supplier_name,
        total_amount=amount,
        paid_amount=0,
        remaining_amount=amount,
        status=SUPPLIER_BILL_STATUS_OPEN,
        notes=notes,
        created_by=created_by,
    )

    db.session.add(bill)

    if commit:
        db.session.commit()

    return True, f"Supplier bill {bill.bill_number} sebesar {_money(amount)} berhasil dibuat.", bill


def supplier_bill_aging_stage(bill, today):
    remaining = float(bill.remaining_amount or 0)

    if remaining <= 0 or str(bill.status or "").upper() == SUPPLIER_BILL_STATUS_PAID:
        return {
            "stage": "PAID",
            "label": "Lunas",
            "badge_class": "status-locked",
            "days_text": "Lunas",
            "days_overdue": 0,
            "days_to_due": 0,
        }

    days_to_due = (bill.due_date - today).days

    if days_to_due < 0:
        return {
            "stage": "OVERDUE",
            "label": "Overdue",
            "badge_class": "status-danger",
            "days_text": f"Lewat {abs(days_to_due)} hari",
            "days_overdue": abs(days_to_due),
            "days_to_due": days_to_due,
        }

    if days_to_due <= 7:
        return {
            "stage": "DUE_SOON",
            "label": "Segera jatuh tempo",
            "badge_class": "status-progress",
            "days_text": f"{days_to_due} hari lagi",
            "days_overdue": 0,
            "days_to_due": days_to_due,
        }

    return {
        "stage": "OPEN",
        "label": "Belum jatuh tempo",
        "badge_class": "status-draft",
        "days_text": f"{days_to_due} hari lagi",
        "days_overdue": 0,
        "days_to_due": days_to_due,
    }


# === PRODUCTION_SUPPLIER_PAYMENT_AP_SERVICE ===
def generate_supplier_payment_number(payment_date):
    prefix = f"SPAY-{payment_date.strftime('%Y%m%d')}"
    counter = SupplierPayment.query.filter(SupplierPayment.payment_number.like(f"{prefix}-%")).count() + 1

    while True:
        payment_number = f"{prefix}-{counter:03d}"
        existing = SupplierPayment.query.filter_by(payment_number=payment_number).first()

        if not existing:
            return payment_number

        counter += 1


def create_supplier_payment_for_bill(
    bill,
    payment_date,
    payment_method,
    amount,
    paid_by,
    bank_account_id=None,
    reference_number=None,
    notes=None,
    commit=False,
):
    """Create one supplier payment for a supplier bill/AP row.

    One supplier payment belongs to one supplier bill. This keeps the first AP
    flow simple and safe while still allowing partial payments through multiple
    payment rows on the same bill.
    """
    if not bill:
        raise Exception("Supplier bill tidak ditemukan.")

    remaining = float(bill.remaining_amount or 0)
    amount = float(amount or 0)

    if remaining <= 0 or str(bill.status or "").upper() == SUPPLIER_BILL_STATUS_PAID:
        raise Exception("Supplier bill ini sudah lunas.")

    try:
        amount = assert_payment_amount_not_over_remaining(amount, remaining, label="Nominal pembayaran hutang supplier")
        assert_date_not_before(payment_date, bill.bill_date, label="Tanggal pembayaran", reference_label="tanggal bill supplier")
        method = validate_choice(payment_method, SUPPLIER_PAYMENT_METHODS, "Metode pembayaran supplier")
    except BusinessRuleError as error:
        raise Exception(str(error))

    resolved_bank_account_id = None

    if method == "TRANSFER":
        if not bank_account_id:
            raise Exception("Pembayaran supplier via transfer wajib memilih rekening bank keluar.")

        bank_account = BankAccount.query.filter_by(
            id=bank_account_id,
            branch_id=bill.branch_id,
            is_active=True,
        ).first()

        if not bank_account:
            raise Exception("Rekening bank keluar tidak valid atau tidak aktif.")

        resolved_bank_account_id = bank_account.id

    payment = SupplierPayment(
        branch_id=bill.branch_id,
        payment_number=generate_supplier_payment_number(payment_date),
        supplier_bill_id=bill.id,
        payment_date=payment_date,
        bank_account_id=resolved_bank_account_id,
        payment_method=method,
        amount=amount,
        reference_number=(reference_number or None),
        notes=(notes or None),
        paid_by=paid_by,
    )

    new_paid = float(bill.paid_amount or 0) + amount
    new_remaining = float(bill.total_amount or 0) - new_paid

    if new_remaining <= 0:
        new_remaining = 0

    bill.status = resolve_supplier_bill_status_after_payment(bill.total_amount, new_paid)
    bill.paid_amount = new_paid
    bill.remaining_amount = new_remaining

    db.session.add(payment)

    if commit:
        db.session.commit()

    return True, f"Pembayaran hutang supplier {payment.payment_number} sebesar {_money(amount)} berhasil dibuat.", payment
