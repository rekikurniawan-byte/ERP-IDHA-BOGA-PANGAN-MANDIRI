from datetime import date

from sqlalchemy import inspect

from app.extensions import db
from app.models.accounting import Account, Journal, JournalDetail
from app.models.delivery import Delivery
from app.models.finance import BankAccount, CashBankTransaction, TransportVehicleExpense
from app.models.master import Driver
from app.services.accounting_service import generate_journal_number
from app.services.audit_log_service import record_audit_log


TRANSPORT_EXPENSE_REFERENCE_TYPE = "TRANSPORT_VEHICLE_EXPENSE"

VEHICLE_FUEL = "VEHICLE_FUEL"
TRANSPORT = "TRANSPORT"

TRANSPORT_EXPENSE_TYPES = {
    VEHICLE_FUEL: {
        "label": "BBM Kendaraan",
        "account_code": "5011",
        "account_label": "5011 Biaya BBM Kendaraan",
        "description": "Biaya BBM kendaraan operasional yang terkait armada/delivery.",
    },
    TRANSPORT: {
        "label": "Biaya Transportasi",
        "account_code": "5003",
        "account_label": "5003 Biaya Transportasi",
        "description": "Biaya transport umum/logistik/non-BBM.",
    },
}


def _normalize(value):
    return str(value or "").strip().upper()


def _money(value):
    try:
        return f"Rp {float(value or 0):,.0f}".replace(",", ".")
    except Exception:
        return "Rp 0"


def is_transport_expense_schema_ready():
    """Avoid crashing local runtime when migration has not been applied yet."""
    try:
        inspector = inspect(db.engine)
        return inspector.has_table("transport_vehicle_expenses")
    except Exception:
        return False


def get_transport_expense_type_choices():
    return [
        {"value": key, **value}
        for key, value in TRANSPORT_EXPENSE_TYPES.items()
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


def validate_driver(branch_id, driver_id=None):
    if not driver_id:
        return None
    try:
        driver_id = int(driver_id)
    except (TypeError, ValueError):
        raise Exception("Driver tidak valid.")
    driver = Driver.query.filter_by(id=driver_id, branch_id=branch_id, is_active=True).first()
    if not driver:
        raise Exception("Driver tidak ditemukan atau tidak aktif.")
    return driver.id


def validate_delivery(branch_id, delivery_id=None, driver_id=None):
    if not delivery_id:
        return None
    try:
        delivery_id = int(delivery_id)
    except (TypeError, ValueError):
        raise Exception("Delivery tidak valid.")
    delivery = Delivery.query.filter_by(id=delivery_id, branch_id=branch_id).first()
    if not delivery:
        raise Exception("Delivery tidak ditemukan.")
    if driver_id and delivery.driver_id and int(driver_id) != int(delivery.driver_id):
        raise Exception("Driver yang dipilih tidak sesuai dengan driver pada delivery terkait.")
    return delivery.id


def generate_transport_expense_number(expense_date):
    prefix = f"TVE-{expense_date.strftime('%Y%m%d')}"
    counter = TransportVehicleExpense.query.filter(
        TransportVehicleExpense.expense_number.like(f"{prefix}-%")
    ).count() + 1
    while True:
        number = f"{prefix}-{counter:03d}"
        if not TransportVehicleExpense.query.filter_by(expense_number=number).first():
            return number
        counter += 1


def get_transport_expense_status_summary(branch_id):
    if not is_transport_expense_schema_ready():
        return {"total": 0, "fuel_total": 0, "transport_total": 0, "count": 0}
    rows = TransportVehicleExpense.query.filter_by(branch_id=branch_id).all()
    return {
        "count": len(rows),
        "total": sum(float(row.amount or 0) for row in rows),
        "fuel_total": sum(float(row.amount or 0) for row in rows if _normalize(row.expense_type) == VEHICLE_FUEL),
        "transport_total": sum(float(row.amount or 0) for row in rows if _normalize(row.expense_type) == TRANSPORT),
    }


def get_driver_label(expense):
    if not expense or not expense.driver_id:
        return "-"
    return expense.driver.name if expense.driver else f"Driver ID {expense.driver_id}"


def get_delivery_label(expense):
    if not expense or not expense.delivery_id:
        return "-"
    return expense.delivery.delivery_number if expense.delivery else f"Delivery ID {expense.delivery_id}"


def create_transport_vehicle_expense(
    branch_id,
    expense_date,
    expense_type,
    payment_method,
    amount,
    created_by,
    vehicle_label=None,
    driver_id=None,
    delivery_id=None,
    bank_account_id=None,
    vendor_name=None,
    reference_number=None,
    notes=None,
    commit=False,
):
    if not is_transport_expense_schema_ready():
        raise Exception("Tabel transport_vehicle_expenses belum tersedia. Jalankan migration PRODUCTION terlebih dahulu.")

    expense_type = _normalize(expense_type)
    rule = TRANSPORT_EXPENSE_TYPES.get(expense_type)
    if not rule:
        raise Exception("Tipe biaya transport/BBM tidak valid.")

    amount = float(amount or 0)
    if amount <= 0:
        raise Exception("Nominal biaya harus lebih dari 0.")
    if expense_date > date.today():
        raise Exception("Tanggal biaya tidak boleh lebih dari hari ini.")

    account_type, bank_account_id = validate_cash_bank(branch_id, payment_method, bank_account_id)
    driver_id = validate_driver(branch_id, driver_id)
    delivery_id = validate_delivery(branch_id, delivery_id, driver_id=driver_id)

    # Precision guard: fuel expenses should identify vehicle/driver/delivery whenever possible.
    if expense_type == VEHICLE_FUEL and not (vehicle_label or driver_id or delivery_id):
        raise Exception("Biaya BBM wajib mengisi minimal kendaraan, driver, atau delivery supaya traceable.")

    acc_expense = get_account_by_code(rule["account_code"])
    acc_cash_bank = get_account_by_code(resolve_cash_account_code(account_type))
    missing = []
    if not acc_expense:
        missing.append(rule["account_label"])
    if not acc_cash_bank:
        missing.append(resolve_cash_account_code(account_type))
    if missing:
        raise Exception("Akun wajib belum lengkap: " + ", ".join(missing))

    expense = TransportVehicleExpense(
        branch_id=branch_id,
        expense_number=generate_transport_expense_number(expense_date),
        expense_date=expense_date,
        expense_type=expense_type,
        account_code=rule["account_code"],
        payment_method=_normalize(payment_method),
        account_type=account_type,
        bank_account_id=bank_account_id,
        amount=amount,
        vehicle_label=(vehicle_label or None),
        driver_id=driver_id,
        delivery_id=delivery_id,
        vendor_name=(vendor_name or None),
        reference_number=(reference_number or None),
        notes=(notes or None),
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
        reference_type=TRANSPORT_EXPENSE_REFERENCE_TYPE,
        reference_id=expense.id,
        created_by=created_by,
    )
    db.session.add(transaction)
    db.session.flush()

    journal = Journal(
        journal_number=generate_journal_number(expense_date),
        journal_date=expense_date,
        reference_type=TRANSPORT_EXPENSE_REFERENCE_TYPE,
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
        event_type="TRANSPORT_EXPENSE_CREATED",
        action="CREATE",
        table_name="transport_vehicle_expenses",
        record_id=expense.id,
        description=f"Biaya transport/BBM dibuat: {expense.expense_number} ({rule['label']}).",
        metadata={
            "expense_type": expense.expense_type,
            "account_code": expense.account_code,
            "amount": amount,
            "cash_bank_transaction_id": transaction.id,
            "journal_id": journal.id,
            "driver_id": driver_id,
            "delivery_id": delivery_id,
            "vehicle_label": vehicle_label,
        },
        user_id=created_by,
        branch_id=branch_id,
        commit=False,
    )

    if commit:
        db.session.commit()

    return True, f"{rule['label']} berhasil diposting ke {rule['account_label']}.", expense
