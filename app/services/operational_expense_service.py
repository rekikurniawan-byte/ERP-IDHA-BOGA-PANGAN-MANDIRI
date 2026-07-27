import logging
from datetime import date

from sqlalchemy import inspect

from app.extensions import db
from app.models.accounting import Account, Journal, JournalDetail
from app.models.finance import BankAccount, CashBankTransaction, OperationalExpense
from app.models.master import Supplier
from app.services.accounting_service import generate_journal_number
from app.services.audit_log_service import record_audit_log

logger = logging.getLogger(__name__)


OPERATIONAL_EXPENSE_REFERENCE_TYPE = "OPERATIONAL_EXPENSE"


def _run_in_transaction(action):
    try:
        result = action()
        db.session.commit()
        return result
    except Exception:
        db.session.rollback()
        raise


ELECTRIC_WATER = "ELECTRIC_WATER"
GAS_LPG = "GAS_LPG"
MAINTENANCE = "MAINTENANCE"
ADMINISTRATION = "ADMINISTRATION"
PACKAGING = "PACKAGING"

OPERATIONAL_EXPENSE_CATEGORIES = {
    ELECTRIC_WATER: {
        "label": "Listrik & Air",
        "account_code": "5005",
        "account_label": "5005 Biaya Listrik & Air",
        "description": "Biaya listrik, air, dan utilitas dapur/catering.",
    },
    GAS_LPG: {
        "label": "Gas / LPG",
        "account_code": "5006",
        "account_label": "5006 Biaya Gas",
        "description": "Biaya gas LPG untuk produksi dapur.",
    },
    MAINTENANCE: {
        "label": "Perawatan",
        "account_code": "5007",
        "account_label": "5007 Biaya Perawatan",
        "description": "Biaya perawatan alat, dapur, dan fasilitas operasional.",
    },
    ADMINISTRATION: {
        "label": "Administrasi",
        "account_code": "5008",
        "account_label": "5008 Biaya Administrasi",
        "description": "Biaya administrasi operasional non-pajak dan non-payroll.",
    },
    PACKAGING: {
        "label": "Kemasan",
        "account_code": "5010",
        "account_label": "5010 Biaya Kemasan",
        "description": "Biaya kemasan, kertas nasi, box, plastik, dan perlengkapan packing.",
    },
}


def _normalize(value):
    return str(value or "").strip().upper()


def _money(value):
    try:
        return f"Rp {float(value or 0):,.0f}".replace(",", ".")
    except Exception:
        logger.exception("Suppressed unexpected exception in app/services/operational_expense_service.py:73")
        return "Rp 0"


def is_operational_expense_schema_ready():
    """Avoid crashing local runtime when migration has not been applied yet."""
    try:
        inspector = inspect(db.engine)
        return inspector.has_table("operational_expenses")
    except Exception:
        logger.exception("Suppressed unexpected exception in app/services/operational_expense_service.py:82")
        return False


def get_operational_expense_category_choices():
    return [
        {"value": key, **value}
        for key, value in OPERATIONAL_EXPENSE_CATEGORIES.items()
    ]


def get_account_by_code(code):
    return Account.query.filter_by(account_code=code, is_active=True).first()


def resolve_cash_account_code(account_type):
    account_type = _normalize(account_type)
    if account_type == "CASH":
        return "1001"
    if account_type == "BANK":
        return "1002"
    raise Exception("Akun kas/bank harus CASH atau BANK.")


def validate_cash_bank(branch_id, payment_method, bank_account_id=None):
    method = _normalize(payment_method)
    if method == "CASH":
        return "CASH", None
    if method == "TRANSFER":
        if not bank_account_id:
            raise Exception("Transaksi transfer wajib memilih rekening bank.")
        try:
            bank_account_id = int(bank_account_id)
        except (TypeError, ValueError):
            raise Exception("Rekening bank tidak valid.")
        bank = BankAccount.query.filter_by(
            id=bank_account_id,
            branch_id=branch_id,
            is_active=True,
        ).first()
        if not bank:
            raise Exception("Rekening bank tidak valid atau tidak aktif.")
        return "BANK", bank.id
    raise Exception("Metode pembayaran harus CASH atau TRANSFER.")


def validate_supplier(branch_id, supplier_id=None):
    if not supplier_id:
        return None
    try:
        supplier_id = int(supplier_id)
    except (TypeError, ValueError):
        raise Exception("Supplier tidak valid.")
    supplier = Supplier.query.filter_by(id=supplier_id, branch_id=branch_id, is_active=True).first()
    if not supplier:
        raise Exception("Supplier tidak ditemukan atau tidak aktif.")
    return supplier.id


def generate_operational_expense_number(expense_date):
    prefix = f"OPEX-{expense_date.strftime('%Y%m%d')}"
    counter = OperationalExpense.query.filter(
        OperationalExpense.expense_number.like(f"{prefix}-%")
    ).count() + 1
    while True:
        number = f"{prefix}-{counter:03d}"
        if not OperationalExpense.query.filter_by(expense_number=number).first():
            return number
        counter += 1


def get_operational_expense_status_summary(branch_id):
    if not is_operational_expense_schema_ready():
        return {
            "count": 0,
            "total": 0,
            "electric_water_total": 0,
            "gas_total": 0,
            "maintenance_total": 0,
            "administration_total": 0,
            "packaging_total": 0,
        }
    rows = OperationalExpense.query.filter_by(branch_id=branch_id).all()
    return {
        "count": len(rows),
        "total": sum(float(row.amount or 0) for row in rows),
        "electric_water_total": sum(float(row.amount or 0) for row in rows if _normalize(row.expense_category) == ELECTRIC_WATER),
        "gas_total": sum(float(row.amount or 0) for row in rows if _normalize(row.expense_category) == GAS_LPG),
        "maintenance_total": sum(float(row.amount or 0) for row in rows if _normalize(row.expense_category) == MAINTENANCE),
        "administration_total": sum(float(row.amount or 0) for row in rows if _normalize(row.expense_category) == ADMINISTRATION),
        "packaging_total": sum(float(row.amount or 0) for row in rows if _normalize(row.expense_category) == PACKAGING),
    }


def get_supplier_label(expense):
    if not expense or not expense.supplier_id:
        return expense.vendor_name or "-"
    return expense.supplier.supplier_name if expense.supplier else f"Supplier ID {expense.supplier_id}"


def create_operational_expense(
    branch_id,
    expense_date,
    expense_category,
    payment_method,
    amount,
    created_by,
    bank_account_id=None,
    supplier_id=None,
    vendor_name=None,
    reference_number=None,
    notes=None,
    commit=False,
):
    if not is_operational_expense_schema_ready():
        raise Exception("Tabel operational_expenses belum tersedia. Jalankan migration PRODUCTION terlebih dahulu.")

    expense_category = _normalize(expense_category)
    rule = OPERATIONAL_EXPENSE_CATEGORIES.get(expense_category)
    if not rule:
        raise Exception("Kategori biaya operasional tidak valid.")

    amount = float(amount or 0)
    if amount <= 0:
        raise Exception("Nominal biaya harus lebih dari 0.")
    if expense_date > date.today():
        raise Exception("Tanggal biaya tidak boleh lebih dari hari ini.")

    account_type, bank_account_id = validate_cash_bank(branch_id, payment_method, bank_account_id)
    supplier_id = validate_supplier(branch_id, supplier_id)

    acc_expense = get_account_by_code(rule["account_code"])
    acc_cash_bank = get_account_by_code(resolve_cash_account_code(account_type))
    missing = []
    if not acc_expense:
        missing.append(rule["account_label"])
    if not acc_cash_bank:
        missing.append(resolve_cash_account_code(account_type))
    if missing:
        raise Exception("Akun wajib belum lengkap: " + ", ".join(missing))

    expense = OperationalExpense(
        branch_id=branch_id,
        expense_number=generate_operational_expense_number(expense_date),
        expense_date=expense_date,
        expense_category=expense_category,
        account_code=rule["account_code"],
        payment_method=_normalize(payment_method),
        account_type=account_type,
        bank_account_id=bank_account_id,
        supplier_id=supplier_id,
        vendor_name=(vendor_name or None),
        amount=amount,
        reference_number=(reference_number or None),
        notes=(notes or None),
        posting_status="POSTED",
        created_by=created_by,
    )
    db.session.add(expense)
    db.session.flush()

    source_label = "Kas" if account_type == "CASH" else "Bank"
    transaction = CashBankTransaction(
        branch_id=branch_id,
        transaction_date=expense_date,
        account_type=account_type,
        bank_account_id=bank_account_id,
        transaction_type="OUT",
        amount=amount,
        description=f"{rule['label']} {expense.expense_number} keluar dari {source_label} sebesar {_money(amount)}",
        reference_type=OPERATIONAL_EXPENSE_REFERENCE_TYPE,
        reference_id=expense.id,
        created_by=created_by,
    )
    db.session.add(transaction)
    db.session.flush()

    journal = Journal(
        journal_number=generate_journal_number(expense_date),
        journal_date=expense_date,
        reference_type=OPERATIONAL_EXPENSE_REFERENCE_TYPE,
        reference_id=expense.id,
        description=f"Jurnal {rule['label']} - {expense.expense_number} ({rule['account_label']})",
        created_by=created_by,
    )
    db.session.add(journal)
    db.session.flush()

    db.session.add(JournalDetail(journal_id=journal.id, account_id=acc_expense.id, debit=amount, credit=0))
    db.session.add(JournalDetail(journal_id=journal.id, account_id=acc_cash_bank.id, debit=0, credit=amount))

    expense.cash_bank_transaction_id = transaction.id
    expense.journal_id = journal.id

    record_audit_log(
        module="FINANCE",
        event_type="OPERATIONAL_EXPENSE_CREATED",
        action="CREATE",
        table_name="operational_expenses",
        record_id=expense.id,
        description=f"Biaya operasional dibuat: {expense.expense_number} ({rule['label']}).",
        metadata={
            "expense_category": expense.expense_category,
            "account_code": expense.account_code,
            "amount": amount,
            "cash_bank_transaction_id": transaction.id,
            "journal_id": journal.id,
            "supplier_id": supplier_id,
        },
        user_id=created_by,
        branch_id=branch_id,
        commit=False,
    )

    if commit:
        db.session.commit()

    return True, f"{rule['label']} berhasil diposting ke {rule['account_label']}.", expense


def create_operational_expense_record(**kwargs):
    kwargs["commit"] = False
    return _run_in_transaction(lambda: create_operational_expense(**kwargs))
