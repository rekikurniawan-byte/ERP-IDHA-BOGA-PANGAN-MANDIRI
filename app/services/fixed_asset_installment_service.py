"""PRODUCTION Asset, Vehicle & Installment Foundation service.

Prinsip akuntansi:
- Beli kendaraan/alat besar kredit: Dr Aset Tetap / Cr Hutang Pembiayaan.
- Bayar cicilan: Dr Hutang Pembiayaan + Dr Beban Bunga/Admin / Cr Kas/Bank.
- Pokok cicilan bukan beban langsung; penyusutan tetap lewat depreciation engine.
"""
from __future__ import annotations
import logging

from calendar import monthrange
from datetime import date
from typing import Any, Optional

from sqlalchemy import inspect, or_

from app.extensions import db
from app.models.accounting import (
    Account,
    AssetFinancingContract,
    AssetInstallmentPayment,
    AssetInstallmentSchedule,
    FixedAsset,
    Journal,
    JournalDetail,
)
from app.models.finance import BankAccount, CashBankTransaction
from app.services.accounting_service import generate_journal_number, get_active_account_by_code
from app.services.audit_log_service import record_audit_log
from app.services.cash_bank_service import calculate_account_balance, get_account_label, normalize_cash_bank_account
from app.services.fixed_asset_purchase_service import ASSET_ACCOUNT_OPTIONS, ASSET_CATEGORY_OPTIONS, generate_fixed_asset_code

logger = logging.getLogger(__name__)

ASSET_FINANCING_CONTRACT_REFERENCE_TYPE = "ASSET_FINANCING_CONTRACT"
ASSET_INSTALLMENT_PAYMENT_REFERENCE_TYPE = "ASSET_INSTALLMENT_PAYMENT"

APP_VERSION = "PRODUCTION"
INSTALLMENT_POLICY_VERSION = "PRODUCTION_ASSET_VEHICLE_INSTALLMENT_FOUNDATION_V1"

CONTRACT_STATUS_ACTIVE = "ACTIVE"
CONTRACT_STATUS_PAID = "PAID"
CONTRACT_STATUS_CANCELLED = "CANCELLED"
SCHEDULE_STATUS_UNPAID = "UNPAID"
SCHEDULE_STATUS_PAID = "PAID"
SCHEDULE_STATUS_OVERDUE = "OVERDUE"

LIABILITY_ACCOUNT_OPTIONS = [
    {"code": "2001", "label": "2001 - Hutang Usaha / Pembiayaan"},
    {"code": "2002", "label": "2002 - Hutang Supplier"},
]
EXPENSE_ACCOUNT_OPTIONS = [
    {"code": "5008", "label": "5008 - Biaya Administrasi / Bunga"},
]


def _safe_float(value: Any) -> float:
    try:
        text = str(value or "0").strip()
        if "," in text and "." in text:
            text = text.replace(".", "").replace(",", ".")
        elif "," in text:
            text = text.replace(",", ".")
        return float(text or 0)
    except (TypeError, ValueError):
        return 0.0


def _safe_int(value: Any) -> int:
    try:
        return int(_safe_float(value))
    except (TypeError, ValueError):
        return 0


def _money(value: Any) -> str:
    try:
        return f"Rp {float(value or 0):,.0f}".replace(",", ".")
    except Exception:
        logger.exception("Suppressed unexpected exception in app/services/fixed_asset_installment_service.py:76")
        return "Rp 0"


def _add_months(source_date: date, months: int) -> date:
    month = source_date.month - 1 + months
    year = source_date.year + month // 12
    month = month % 12 + 1
    day = min(source_date.day, monthrange(year, month)[1])
    return date(year, month, day)


def _split_evenly(total: float, count: int) -> list[float]:
    total = round(float(total or 0), 2)
    if count <= 0:
        return []
    base = round(total / count, 2)
    rows = [base for _ in range(count)]
    delta = round(total - sum(rows), 2)
    rows[-1] = round(rows[-1] + delta, 2)
    return rows


def is_installment_schema_ready() -> bool:
    try:
        inspector = inspect(db.engine)
        required = [
            "asset_financing_contracts",
            "asset_installment_schedules",
            "asset_installment_payments",
        ]
        return all(inspector.has_table(name) for name in required)
    except Exception:
        logger.exception("Suppressed unexpected exception in app/services/fixed_asset_installment_service.py:108")
        return False


def get_account_options(options: list[dict[str, str]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for option in options:
        account = Account.query.filter_by(account_code=option["code"], is_active=True).first()
        fallback_label = option["label"].split(" - ", 1)[-1]
        rows.append({
            "code": option["code"],
            "label": f"{option['code']} - {account.account_name if account else fallback_label}",
            "is_ready": bool(account),
        })
    return rows


def get_installment_account_options() -> dict[str, list[dict[str, Any]]]:
    return {
        "asset_accounts": get_account_options(ASSET_ACCOUNT_OPTIONS),
        "liability_accounts": get_account_options(LIABILITY_ACCOUNT_OPTIONS),
        "expense_accounts": get_account_options(EXPENSE_ACCOUNT_OPTIONS),
    }


def generate_contract_number(contract_date: date) -> str:
    prefix = f"AFC-{contract_date.strftime('%Y%m%d')}"
    counter = AssetFinancingContract.query.filter(
        AssetFinancingContract.contract_number.like(f"{prefix}-%")
    ).count() + 1
    while True:
        number = f"{prefix}-{counter:03d}"
        if not AssetFinancingContract.query.filter_by(contract_number=number).first():
            return number
        counter += 1


def generate_installment_payment_number(payment_date: date) -> str:
    prefix = f"AIP-{payment_date.strftime('%Y%m%d')}"
    counter = AssetInstallmentPayment.query.filter(
        AssetInstallmentPayment.payment_number.like(f"{prefix}-%")
    ).count() + 1
    while True:
        number = f"{prefix}-{counter:03d}"
        if not AssetInstallmentPayment.query.filter_by(payment_number=number).first():
            return number
        counter += 1


def _require_account(code: str, label: str) -> Account:
    account = get_active_account_by_code(str(code or "").strip())
    if not account:
        raise Exception(f"Akun {code} {label} belum tersedia atau tidak aktif.")
    return account


def _create_acquisition_journal(contract: AssetFinancingContract, created_by: int) -> Journal:
    existing = Journal.query.filter_by(
        reference_type=ASSET_FINANCING_CONTRACT_REFERENCE_TYPE,
        reference_id=contract.id,
    ).first()
    if existing:
        return existing

    asset_account = _require_account(contract.asset_account_code, "Aset Tetap")
    liability_account = _require_account(contract.liability_account_code, "Hutang Pembiayaan")
    amount = float(contract.principal_amount or 0)
    if amount <= 0:
        raise Exception("Nilai aset/pokok pembiayaan tidak valid untuk jurnal akuisisi.")

    journal = Journal(
        journal_number=generate_journal_number(contract.contract_date),
        journal_date=contract.contract_date,
        reference_type=ASSET_FINANCING_CONTRACT_REFERENCE_TYPE,
        reference_id=contract.id,
        description=f"Jurnal akuisisi aset kredit {contract.contract_number} - {contract.fixed_asset.asset_name}",
        created_by=created_by,
    )
    db.session.add(journal)
    db.session.flush()
    db.session.add(JournalDetail(journal_id=journal.id, account_id=asset_account.id, debit=amount, credit=0))
    db.session.add(JournalDetail(journal_id=journal.id, account_id=liability_account.id, debit=0, credit=amount))

    contract.acquisition_journal_id = journal.id
    return journal


def _create_installment_journal(payment: AssetInstallmentPayment, created_by: int) -> Journal:
    existing = Journal.query.filter_by(
        reference_type=ASSET_INSTALLMENT_PAYMENT_REFERENCE_TYPE,
        reference_id=payment.id,
    ).first()
    if existing:
        return existing
    contract = payment.contract
    liability_account = _require_account(contract.liability_account_code, "Hutang Pembiayaan")
    interest_account = _require_account(contract.interest_expense_account_code, "Beban Bunga")
    admin_account = _require_account(contract.admin_expense_account_code, "Beban Admin")
    if payment.account_type == "CASH":
        credit_account = _require_account("1001", "Kas")
        credit_label = "1001 Kas"
    else:
        from app.services.accounting_service import bank_coa_code

        bank_code = bank_coa_code(getattr(payment, "bank_account_id", None))
        credit_account = _require_account(bank_code, "Bank")
        credit_label = f"{bank_code} Bank"

    amount = round(float(payment.amount or 0), 2)
    if amount <= 0:
        raise Exception("Nominal pembayaran cicilan tidak valid.")

    journal = Journal(
        journal_number=generate_journal_number(payment.payment_date),
        journal_date=payment.payment_date,
        reference_type=ASSET_INSTALLMENT_PAYMENT_REFERENCE_TYPE,
        reference_id=payment.id,
        description=(
            f"Jurnal pembayaran cicilan aset {contract.contract_number} "
            f"jadwal #{payment.schedule.installment_no} via {credit_label}"
        ),
        created_by=created_by,
    )
    db.session.add(journal)
    db.session.flush()
    if float(payment.principal_paid or 0) > 0:
        db.session.add(JournalDetail(journal_id=journal.id, account_id=liability_account.id, debit=payment.principal_paid, credit=0))
    if float(payment.interest_paid or 0) > 0:
        db.session.add(JournalDetail(journal_id=journal.id, account_id=interest_account.id, debit=payment.interest_paid, credit=0))
    if float(payment.admin_paid or 0) > 0:
        db.session.add(JournalDetail(journal_id=journal.id, account_id=admin_account.id, debit=payment.admin_paid, credit=0))
    db.session.add(JournalDetail(journal_id=journal.id, account_id=credit_account.id, debit=0, credit=amount))
    payment.journal_id = journal.id
    return journal


def _create_installment_cash_bank_out(payment: AssetInstallmentPayment, created_by: int) -> CashBankTransaction:
    existing = CashBankTransaction.query.filter_by(
        reference_type=ASSET_INSTALLMENT_PAYMENT_REFERENCE_TYPE,
        reference_id=payment.id,
    ).first()
    if existing:
        return existing
    bank_account = BankAccount.query.get(payment.bank_account_id) if payment.bank_account_id else None
    account_label = get_account_label(payment.account_type, bank_account)
    description = (
        f"Pembayaran cicilan aset {payment.contract.contract_number} jadwal #{payment.schedule.installment_no} "
        f"keluar dari {account_label} sebesar {_money(payment.amount)}. "
        f"Pokok {_money(payment.principal_paid)}, bunga {_money(payment.interest_paid)}, admin {_money(payment.admin_paid)}."
    )
    if payment.reference_number:
        description += f" Ref: {payment.reference_number}."
    transaction = CashBankTransaction(
        branch_id=payment.branch_id,
        transaction_date=payment.payment_date,
        account_type=payment.account_type,
        bank_account_id=payment.bank_account_id,
        transaction_type="OUT",
        amount=payment.amount,
        description=description,
        reference_type=ASSET_INSTALLMENT_PAYMENT_REFERENCE_TYPE,
        reference_id=payment.id,
        created_by=created_by,
    )
    db.session.add(transaction)
    db.session.flush()
    payment.cash_bank_transaction_id = transaction.id
    return transaction


def create_asset_financing_contract(
    *,
    branch_id: int,
    contract_date: date,
    asset_mode: str,
    asset_id: Optional[int],
    asset_name: str,
    asset_category: str,
    asset_account_code: str,
    liability_account_code: str,
    interest_expense_account_code: str,
    admin_expense_account_code: str,
    principal_amount: Any,
    total_interest_amount: Any,
    total_admin_amount: Any,
    installment_count: Any,
    first_due_date: date,
    vendor_name: Optional[str],
    financing_provider: Optional[str],
    notes: Optional[str],
    created_by: int,
    commit: bool = False,
) -> AssetFinancingContract:
    if not is_installment_schema_ready():
        raise Exception("Tabel cicilan aset belum tersedia. Jalankan migration PRODUCTION terlebih dahulu.")
    if not contract_date:
        raise Exception("Tanggal kontrak wajib diisi.")
    if not first_due_date:
        raise Exception("Tanggal jatuh tempo cicilan pertama wajib diisi.")
    if first_due_date < contract_date:
        raise Exception("Jatuh tempo cicilan pertama tidak boleh sebelum tanggal kontrak.")

    principal_amount = _safe_float(principal_amount)
    total_interest_amount = _safe_float(total_interest_amount)
    total_admin_amount = _safe_float(total_admin_amount)
    installment_count = _safe_int(installment_count)
    if principal_amount <= 0:
        raise Exception("Nilai aset/pokok pembiayaan wajib lebih dari 0.")
    if total_interest_amount < 0 or total_admin_amount < 0:
        raise Exception("Bunga/admin tidak boleh negatif.")
    if installment_count <= 0 or installment_count > 120:
        raise Exception("Jumlah cicilan wajib 1 sampai 120.")

    asset_account_code = str(asset_account_code or "").strip()
    liability_account_code = str(liability_account_code or "2001").strip()
    interest_expense_account_code = str(interest_expense_account_code or "5008").strip()
    admin_expense_account_code = str(admin_expense_account_code or "5008").strip()
    if asset_account_code not in [item["code"] for item in ASSET_ACCOUNT_OPTIONS]:
        raise Exception("Akun aset tidak valid.")
    if liability_account_code not in [item["code"] for item in LIABILITY_ACCOUNT_OPTIONS]:
        raise Exception("Akun hutang pembiayaan tidak valid.")
    _require_account(asset_account_code, "Aset Tetap")
    _require_account(liability_account_code, "Hutang Pembiayaan")
    _require_account(interest_expense_account_code, "Beban Bunga")
    _require_account(admin_expense_account_code, "Beban Admin")

    asset_mode = str(asset_mode or "NEW").upper()
    if asset_mode not in ["NEW", "EXISTING"]:
        raise Exception("Mode aset tidak valid.")

    fixed_asset: FixedAsset | None = None
    if asset_mode == "EXISTING":
        if not asset_id:
            raise Exception("Pilih aset existing placeholder yang akan dibiayai.")
        fixed_asset = FixedAsset.query.filter_by(id=asset_id, branch_id=branch_id).first()
        if not fixed_asset:
            raise Exception("Aset existing tidak ditemukan atau tidak sesuai cabang.")
        if str(fixed_asset.status or "").upper() != "ACTIVE":
            raise Exception("Aset existing harus ACTIVE.")
        if float(fixed_asset.purchase_value or 0) > 0 or float(fixed_asset.accumulated_depreciation or 0) > 0:
            raise Exception("Aset existing sudah punya nilai historis. Gunakan aset placeholder bernilai 0.")
        fixed_asset.purchase_date = contract_date
        fixed_asset.purchase_value = principal_amount
        fixed_asset.book_value = principal_amount
        fixed_asset.accumulated_depreciation = 0
        if notes and not fixed_asset.notes:
            fixed_asset.notes = notes
    else:
        asset_name = str(asset_name or "").strip()
        if not asset_name:
            raise Exception("Nama aset baru wajib diisi.")
        asset_category = str(asset_category or "OTHER").upper()
        if asset_category not in ASSET_CATEGORY_OPTIONS:
            asset_category = "OTHER"
        fixed_asset = FixedAsset(
            branch_id=branch_id,
            asset_code=generate_fixed_asset_code(),
            asset_name=asset_name,
            asset_category=asset_category,
            purchase_date=contract_date,
            purchase_value=principal_amount,
            useful_life_years=0,
            residual_value=0,
            accumulated_depreciation=0,
            book_value=principal_amount,
            status="ACTIVE",
            notes=notes,
        )
        db.session.add(fixed_asset)
        db.session.flush()

    contract = AssetFinancingContract(
        branch_id=branch_id,
        contract_number=generate_contract_number(contract_date),
        contract_date=contract_date,
        fixed_asset_id=fixed_asset.id,
        asset_account_code=asset_account_code,
        liability_account_code=liability_account_code,
        interest_expense_account_code=interest_expense_account_code,
        admin_expense_account_code=admin_expense_account_code,
        vendor_name=(vendor_name or None),
        financing_provider=(financing_provider or None),
        principal_amount=principal_amount,
        total_interest_amount=total_interest_amount,
        total_admin_amount=total_admin_amount,
        total_contract_amount=round(principal_amount + total_interest_amount + total_admin_amount, 2),
        installment_count=installment_count,
        installment_frequency="MONTHLY",
        first_due_date=first_due_date,
        status=CONTRACT_STATUS_ACTIVE,
        notes=(notes or None),
        created_by=created_by,
    )
    db.session.add(contract)
    db.session.flush()

    _create_acquisition_journal(contract, created_by)

    principal_rows = _split_evenly(principal_amount, installment_count)
    interest_rows = _split_evenly(total_interest_amount, installment_count)
    admin_rows = _split_evenly(total_admin_amount, installment_count)
    for index in range(installment_count):
        principal = principal_rows[index]
        interest = interest_rows[index]
        admin = admin_rows[index]
        total = round(principal + interest + admin, 2)
        db.session.add(AssetInstallmentSchedule(
            branch_id=branch_id,
            contract_id=contract.id,
            installment_no=index + 1,
            due_date=_add_months(first_due_date, index),
            principal_amount=principal,
            interest_amount=interest,
            admin_amount=admin,
            total_amount=total,
            paid_amount=0,
            remaining_amount=total,
            status=SCHEDULE_STATUS_UNPAID,
        ))

    record_audit_log(
        module="FIXED_ASSET",
        event_type="ASSET_FINANCING_CONTRACT_CREATED",
        action="CREATE",
        table_name="asset_financing_contracts",
        record_id=contract.id,
        description=f"Kontrak cicilan aset dibuat: {contract.contract_number} - {fixed_asset.asset_name}.",
        metadata={
            "app_version": APP_VERSION,
            "policy_version": INSTALLMENT_POLICY_VERSION,
            "fixed_asset_id": fixed_asset.id,
            "asset_code": fixed_asset.asset_code,
            "principal_amount": principal_amount,
            "total_interest_amount": total_interest_amount,
            "total_admin_amount": total_admin_amount,
            "installment_count": installment_count,
            "rule": "principal_is_liability_not_expense",
            "acquisition_journal_id": contract.acquisition_journal_id,
        },
        user_id=created_by,
        branch_id=branch_id,
        commit=False,
    )

    if commit:
        db.session.commit()
    return contract


def list_asset_financing_contracts(branch_id: int, q: str = "", status: str = "ALL") -> list[AssetFinancingContract]:
    if not is_installment_schema_ready():
        return []
    query = AssetFinancingContract.query.filter_by(branch_id=branch_id)
    q = (q or "").strip()
    if q:
        like = f"%{q}%"
        query = query.outerjoin(FixedAsset, FixedAsset.id == AssetFinancingContract.fixed_asset_id).filter(
            or_(
                AssetFinancingContract.contract_number.ilike(like),
                AssetFinancingContract.vendor_name.ilike(like),
                AssetFinancingContract.financing_provider.ilike(like),
                FixedAsset.asset_code.ilike(like),
                FixedAsset.asset_name.ilike(like),
            )
        )
    status = str(status or "ALL").upper()
    if status in [CONTRACT_STATUS_ACTIVE, CONTRACT_STATUS_PAID, CONTRACT_STATUS_CANCELLED]:
        query = query.filter(AssetFinancingContract.status == status)
    return query.order_by(AssetFinancingContract.contract_date.desc(), AssetFinancingContract.id.desc()).all()


def get_contract_detail(contract_id: int, branch_id: int) -> AssetFinancingContract | None:
    if not is_installment_schema_ready():
        return None
    return AssetFinancingContract.query.filter_by(id=contract_id, branch_id=branch_id).first()


def calculate_contract_summary(contract: AssetFinancingContract | None) -> dict[str, float | int]:
    if not contract:
        return {"paid": 0.0, "remaining": 0.0, "schedule_count": 0, "paid_count": 0, "unpaid_count": 0}
    schedules = list(getattr(contract, "schedules", []) or [])
    paid = sum(float(row.paid_amount or 0) for row in schedules)
    remaining = sum(float(row.remaining_amount or 0) for row in schedules)
    return {
        "paid": round(paid, 2),
        "remaining": round(remaining, 2),
        "schedule_count": len(schedules),
        "paid_count": sum(1 for row in schedules if row.status == SCHEDULE_STATUS_PAID),
        "unpaid_count": sum(1 for row in schedules if row.status != SCHEDULE_STATUS_PAID),
    }


def build_installment_summary(contracts: list[AssetFinancingContract]) -> dict[str, float | int]:
    total_contract = sum(float(row.total_contract_amount or 0) for row in contracts)
    active = [row for row in contracts if row.status == CONTRACT_STATUS_ACTIVE]
    remaining = 0.0
    paid = 0.0
    for contract in contracts:
        summary = calculate_contract_summary(contract)
        remaining += float(summary["remaining"] or 0)
        paid += float(summary["paid"] or 0)
    return {
        "count": len(contracts),
        "active_count": len(active),
        "total_contract": round(total_contract, 2),
        "paid": round(paid, 2),
        "remaining": round(remaining, 2),
    }


def pay_installment_schedule(
    *,
    branch_id: int,
    contract_id: int,
    schedule_id: int,
    payment_date: date,
    payment_method: str,
    bank_account_id: Optional[int],
    reference_number: Optional[str],
    notes: Optional[str],
    created_by: int,
    commit: bool = False,
) -> AssetInstallmentPayment:
    if not is_installment_schema_ready():
        raise Exception("Tabel cicilan aset belum tersedia. Jalankan migration PRODUCTION terlebih dahulu.")
    contract = AssetFinancingContract.query.filter_by(id=contract_id, branch_id=branch_id).first()
    if not contract:
        raise Exception("Kontrak cicilan aset tidak ditemukan.")
    if contract.status != CONTRACT_STATUS_ACTIVE:
        raise Exception("Kontrak cicilan tidak aktif.")
    schedule = AssetInstallmentSchedule.query.filter_by(id=schedule_id, contract_id=contract.id, branch_id=branch_id).first()
    if not schedule:
        raise Exception("Jadwal cicilan tidak ditemukan.")
    if schedule.status == SCHEDULE_STATUS_PAID or float(schedule.remaining_amount or 0) <= 0:
        raise Exception("Jadwal cicilan sudah lunas.")
    if not payment_date:
        raise Exception("Tanggal pembayaran wajib diisi.")

    payment_method = str(payment_method or "").upper()
    if payment_method not in ["CASH", "BANK"]:
        raise Exception("Sumber pembayaran cicilan harus CASH atau BANK.")
    account_type, resolved_bank_account_id, _ = normalize_cash_bank_account(
        payment_method,
        bank_account_id,
        branch_id=branch_id,
    )
    amount = round(float(schedule.remaining_amount or 0), 2)
    current_balance = calculate_account_balance(branch_id, account_type, resolved_bank_account_id)
    if amount > current_balance:
        raise Exception(f"Saldo kas/bank tidak cukup. Saldo tersedia {_money(current_balance)}.")

    payment = AssetInstallmentPayment(
        branch_id=branch_id,
        payment_number=generate_installment_payment_number(payment_date),
        contract_id=contract.id,
        schedule_id=schedule.id,
        payment_date=payment_date,
        account_type=account_type,
        bank_account_id=resolved_bank_account_id,
        amount=amount,
        principal_paid=float(schedule.principal_amount or 0),
        interest_paid=float(schedule.interest_amount or 0),
        admin_paid=float(schedule.admin_amount or 0),
        reference_number=(reference_number or None),
        notes=(notes or None),
        created_by=created_by,
    )
    db.session.add(payment)
    db.session.flush()

    schedule.paid_amount = round(float(schedule.paid_amount or 0) + amount, 2)
    schedule.remaining_amount = 0
    schedule.status = SCHEDULE_STATUS_PAID

    ledger = _create_installment_cash_bank_out(payment, created_by)
    journal = _create_installment_journal(payment, created_by)

    if all(row.status == SCHEDULE_STATUS_PAID for row in contract.schedules):
        contract.status = CONTRACT_STATUS_PAID

    record_audit_log(
        module="FIXED_ASSET",
        event_type="ASSET_INSTALLMENT_PAYMENT_CREATED",
        action="CREATE",
        table_name="asset_installment_payments",
        record_id=payment.id,
        description=f"Pembayaran cicilan aset dibuat: {payment.payment_number} untuk {contract.contract_number}.",
        metadata={
            "app_version": APP_VERSION,
            "policy_version": INSTALLMENT_POLICY_VERSION,
            "contract_id": contract.id,
            "schedule_id": schedule.id,
            "principal_paid": payment.principal_paid,
            "interest_paid": payment.interest_paid,
            "admin_paid": payment.admin_paid,
            "amount": amount,
            "cash_bank_transaction_id": ledger.id,
            "journal_id": journal.id,
            "rule": "principal_reduces_liability_interest_admin_are_expense",
        },
        user_id=created_by,
        branch_id=branch_id,
        commit=False,
    )

    if commit:
        db.session.commit()
    return payment
