from __future__ import annotations

from datetime import date
from typing import Any, Optional

from sqlalchemy import or_

from app.extensions import db
from app.models.accounting import Account, FixedAsset, FixedAssetPurchase, Journal, JournalDetail
from app.models.finance import BankAccount, CashBankTransaction
from app.services.accounting_service import generate_journal_number, get_active_account_by_code
from app.services.audit_log_service import record_audit_log
from app.services.cash_bank_service import calculate_account_balance, get_account_label, normalize_cash_bank_account


FIXED_ASSET_PURCHASE_REFERENCE_TYPE = "FIXED_ASSET_PURCHASE"

ASSET_ACCOUNT_OPTIONS = [
    {"code": "1101", "label": "1101 - Peralatan Dapur"},
    {"code": "1102", "label": "1102 - Kendaraan Operasional"},
    {"code": "1103", "label": "1103 - Bangunan / Dapur"},
]

ASSET_CATEGORY_OPTIONS = ["KITCHEN_EQUIPMENT", "VEHICLE", "OFFICE_EQUIPMENT", "BUILDING", "OTHER"]
ASSET_STATUS_ACTIVE = "ACTIVE"


def _money(value: Any) -> str:
    try:
        return f"Rp {float(value or 0):,.0f}".replace(",", ".")
    except Exception:
        return "Rp 0"


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


def generate_fixed_asset_purchase_number(purchase_date: date) -> str:
    prefix = f"FAP-{purchase_date.strftime('%Y%m%d')}"
    counter = FixedAssetPurchase.query.filter(
        FixedAssetPurchase.purchase_number.like(f"{prefix}-%")
    ).count() + 1

    while True:
        purchase_number = f"{prefix}-{counter:03d}"
        if not FixedAssetPurchase.query.filter_by(purchase_number=purchase_number).first():
            return purchase_number
        counter += 1



def generate_fixed_asset_code() -> str:
    latest = FixedAsset.query.order_by(FixedAsset.id.desc()).first()
    next_number = (latest.id + 1) if latest else 1
    while True:
        asset_code = f"AST-{next_number:04d}"
        if not FixedAsset.query.filter_by(asset_code=asset_code).first():
            return asset_code
        next_number += 1

def get_asset_account_options() -> list[dict[str, str]]:
    rows = []
    for option in ASSET_ACCOUNT_OPTIONS:
        account = Account.query.filter_by(account_code=option["code"], is_active=True).first()
        rows.append({
            "code": option["code"],
            "label": f"{option['code']} - {account.account_name if account else option['label'].split(' - ', 1)[-1]}",
            "is_ready": bool(account),
        })
    return rows


def get_fixed_asset_purchase_detail(purchase_id: int, branch_id: int) -> Optional[FixedAssetPurchase]:
    return FixedAssetPurchase.query.filter_by(id=purchase_id, branch_id=branch_id).first()


def list_fixed_asset_purchases(branch_id: int, q: str = "", payment_method: str = "ALL") -> list[FixedAssetPurchase]:
    query = FixedAssetPurchase.query.filter_by(branch_id=branch_id)

    q = (q or "").strip()
    if q:
        like = f"%{q}%"
        query = query.outerjoin(FixedAsset, FixedAsset.id == FixedAssetPurchase.fixed_asset_id).filter(
            or_(
                FixedAssetPurchase.purchase_number.ilike(like),
                FixedAssetPurchase.vendor_name.ilike(like),
                FixedAsset.asset_code.ilike(like),
                FixedAsset.asset_name.ilike(like),
                FixedAsset.asset_category.ilike(like),
            )
        )

    payment_method = str(payment_method or "ALL").upper()
    if payment_method in ["CASH", "BANK"]:
        query = query.filter(FixedAssetPurchase.payment_method == payment_method)

    return query.order_by(FixedAssetPurchase.purchase_date.desc(), FixedAssetPurchase.id.desc()).all()


def _create_cash_bank_out_transaction(purchase: FixedAssetPurchase, created_by: int) -> CashBankTransaction:
    existing = CashBankTransaction.query.filter_by(
        reference_type=FIXED_ASSET_PURCHASE_REFERENCE_TYPE,
        reference_id=purchase.id,
    ).first()
    if existing:
        return existing

    bank_account = BankAccount.query.get(purchase.bank_account_id) if purchase.bank_account_id else None
    account_label = get_account_label(purchase.account_type, bank_account)
    description = (
        f"Pembelian aset tetap {purchase.purchase_number} - {purchase.fixed_asset.asset_name} "
        f"keluar dari {account_label} sebesar {_money(purchase.amount)}"
    )
    if purchase.vendor_name:
        description += f". Vendor: {purchase.vendor_name}"
    if purchase.reference_number:
        description += f". Ref: {purchase.reference_number}"

    transaction = CashBankTransaction(
        branch_id=purchase.branch_id,
        transaction_date=purchase.purchase_date,
        account_type=purchase.account_type,
        bank_account_id=purchase.bank_account_id,
        transaction_type="OUT",
        amount=purchase.amount,
        description=description,
        reference_type=FIXED_ASSET_PURCHASE_REFERENCE_TYPE,
        reference_id=purchase.id,
        created_by=created_by,
    )
    db.session.add(transaction)
    db.session.flush()
    purchase.cash_bank_transaction_id = transaction.id
    return transaction


def _create_fixed_asset_purchase_journal(purchase: FixedAssetPurchase, created_by: int) -> Journal:
    existing = Journal.query.filter_by(
        reference_type=FIXED_ASSET_PURCHASE_REFERENCE_TYPE,
        reference_id=purchase.id,
    ).first()
    if existing:
        return existing

    asset_account = get_active_account_by_code(purchase.asset_account_code)
    if not asset_account:
        raise Exception(f"Akun aset {purchase.asset_account_code} belum tersedia atau tidak aktif.")

    if purchase.account_type == "CASH":
        payment_account = get_active_account_by_code("1001")
        payment_account_label = "1001 Kas"
    else:
        # Sistem saat ini masih memakai akun bank utama 1002 untuk jurnal pembayaran bank.
        # Rekening bank detail tetap tercatat di cash_bank_transactions.bank_account_id.
        payment_account = get_active_account_by_code("1002")
        payment_account_label = "1002 Bank 1"

    if not payment_account:
        raise Exception(f"Akun pembayaran {payment_account_label} belum tersedia atau tidak aktif.")

    amount = float(purchase.amount or 0)
    if amount <= 0:
        raise Exception("Nominal pembelian aset tidak valid untuk jurnal.")

    journal = Journal(
        journal_number=generate_journal_number(purchase.purchase_date),
        journal_date=purchase.purchase_date,
        reference_type=FIXED_ASSET_PURCHASE_REFERENCE_TYPE,
        reference_id=purchase.id,
        description=f"Jurnal pembelian aset tetap {purchase.purchase_number} - {purchase.fixed_asset.asset_name}",
        created_by=created_by,
    )
    db.session.add(journal)
    db.session.flush()

    db.session.add(JournalDetail(
        journal_id=journal.id,
        account_id=asset_account.id,
        debit=amount,
        credit=0,
    ))
    db.session.add(JournalDetail(
        journal_id=journal.id,
        account_id=payment_account.id,
        debit=0,
        credit=amount,
    ))

    debit_total = sum(float(detail.debit or 0) for detail in journal.details) + amount
    credit_total = sum(float(detail.credit or 0) for detail in journal.details) + amount
    if round(debit_total, 2) != round(credit_total, 2):
        raise Exception("Jurnal pembelian aset tidak seimbang.")

    purchase.journal_id = journal.id
    return journal


def create_fixed_asset_purchase(
    *,
    branch_id: int,
    purchase_date: date,
    asset_mode: str,
    asset_id: Optional[int],
    asset_name: str,
    asset_category: str,
    asset_account_code: str,
    payment_method: str,
    bank_account_id: Optional[int],
    amount: Any,
    useful_life_years: Any,
    residual_value: Any,
    vendor_name: Optional[str],
    reference_number: Optional[str],
    notes: Optional[str],
    created_by: int,
    commit: bool = False,
) -> tuple[FixedAssetPurchase, CashBankTransaction, Journal]:
    if not purchase_date:
        raise Exception("Tanggal pembelian aset wajib diisi.")

    asset_mode = str(asset_mode or "NEW").upper()
    if asset_mode not in ["NEW", "EXISTING"]:
        raise Exception("Mode aset tidak valid.")

    amount = _safe_float(amount)
    if amount <= 0:
        raise Exception("Nominal pembelian aset harus lebih dari 0.")

    useful_life_years = int(_safe_float(useful_life_years))
    residual_value = _safe_float(residual_value)
    if residual_value < 0:
        raise Exception("Nilai residu tidak boleh negatif.")
    if residual_value > amount:
        raise Exception("Nilai residu tidak boleh lebih besar dari nilai pembelian aset.")

    asset_account_code = str(asset_account_code or "").strip()
    if asset_account_code not in [option["code"] for option in ASSET_ACCOUNT_OPTIONS]:
        raise Exception("Akun aset tetap tidak valid.")
    if not get_active_account_by_code(asset_account_code):
        raise Exception(f"Akun aset {asset_account_code} belum tersedia atau tidak aktif.")

    payment_method = str(payment_method or "").upper()
    if payment_method not in ["CASH", "BANK"]:
        raise Exception("Sumber pembayaran aset harus CASH atau BANK.")

    account_type, resolved_bank_account_id, _ = normalize_cash_bank_account(
        payment_method,
        bank_account_id,
        branch_id=branch_id,
    )

    current_balance = calculate_account_balance(branch_id, account_type, resolved_bank_account_id)
    if amount > current_balance:
        raise Exception(f"Saldo kas/bank tidak cukup. Saldo tersedia {_money(current_balance)}.")

    fixed_asset = None
    if asset_mode == "EXISTING":
        if not asset_id:
            raise Exception("Pilih aset existing yang akan dibeli/dikapitalisasi.")
        fixed_asset = FixedAsset.query.filter_by(id=asset_id, branch_id=branch_id).first()
        if not fixed_asset:
            raise Exception("Aset existing tidak ditemukan atau tidak sesuai cabang.")
        if str(fixed_asset.status or "").upper() != ASSET_STATUS_ACTIVE:
            raise Exception("Aset existing harus berstatus ACTIVE.")
        if FixedAssetPurchase.query.filter_by(fixed_asset_id=fixed_asset.id).first():
            raise Exception("Aset ini sudah punya transaksi pembelian aset tetap.")
        # Existing asset hanya boleh dipakai untuk placeholder aset yang belum punya nilai historis.
        if float(fixed_asset.purchase_value or 0) > 0 or float(fixed_asset.accumulated_depreciation or 0) > 0:
            raise Exception("Aset existing sudah punya nilai historis. Gunakan mode Aset Baru agar saldo/jurnal tidak dobel.")
        fixed_asset.purchase_date = purchase_date
        fixed_asset.purchase_value = amount
        fixed_asset.useful_life_years = useful_life_years
        fixed_asset.residual_value = residual_value
        fixed_asset.accumulated_depreciation = 0
        fixed_asset.book_value = amount
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
            purchase_date=purchase_date,
            purchase_value=amount,
            useful_life_years=useful_life_years,
            residual_value=residual_value,
            accumulated_depreciation=0,
            book_value=amount,
            status=ASSET_STATUS_ACTIVE,
            notes=notes,
        )
        db.session.add(fixed_asset)
        db.session.flush()

    purchase = FixedAssetPurchase(
        branch_id=branch_id,
        purchase_number=generate_fixed_asset_purchase_number(purchase_date),
        purchase_date=purchase_date,
        fixed_asset_id=fixed_asset.id,
        asset_account_code=asset_account_code,
        payment_method=payment_method,
        account_type=account_type,
        bank_account_id=resolved_bank_account_id,
        amount=amount,
        vendor_name=(vendor_name or None),
        reference_number=(reference_number or None),
        notes=(notes or None),
        created_by=created_by,
    )
    db.session.add(purchase)
    db.session.flush()

    ledger_transaction = _create_cash_bank_out_transaction(purchase, created_by)
    journal = _create_fixed_asset_purchase_journal(purchase, created_by)

    record_audit_log(
        module="FIXED_ASSET",
        event_type="FIXED_ASSET_PURCHASE_CREATED",
        action="CREATE",
        table_name="fixed_asset_purchases",
        record_id=purchase.id,
        description=f"Pembelian aset tetap dibuat: {purchase.purchase_number} - {fixed_asset.asset_name}.",
        metadata={
            "fixed_asset_id": fixed_asset.id,
            "asset_code": fixed_asset.asset_code,
            "asset_account_code": asset_account_code,
            "payment_method": payment_method,
            "amount": amount,
            "cash_bank_transaction_id": ledger_transaction.id,
            "journal_id": journal.id,
        },
        user_id=created_by,
        branch_id=branch_id,
        commit=False,
    )

    if commit:
        db.session.commit()

    return purchase, ledger_transaction, journal
