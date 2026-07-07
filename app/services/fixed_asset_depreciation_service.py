from __future__ import annotations

from calendar import monthrange
from datetime import date
from typing import Any

from sqlalchemy import inspect

from app.extensions import db
from app.models.accounting import (
    Account,
    FixedAsset,
    FixedAssetDepreciation,
    FixedAssetDepreciationConfig,
    Journal,
    JournalDetail,
)
from app.services.accounting_service import generate_journal_number
from app.services.audit_log_service import record_audit_log


FIXED_ASSET_DEPRECIATION_REFERENCE_TYPE = "FIXED_ASSET_DEPRECIATION"
DEPRECIATION_METHOD_STRAIGHT_LINE = "STRAIGHT_LINE"
DEPRECIATION_STATUS_CONFIGURED = "CONFIGURED"
DEPRECIATION_STATUS_ACTIVE = "ACTIVE"
DEPRECIATION_STATUS_PAUSED = "PAUSED"
DEPRECIATION_STATUS_POSTED = "POSTED"

DEPRECIATION_STATUS_OPTIONS = [
    DEPRECIATION_STATUS_CONFIGURED,
    DEPRECIATION_STATUS_ACTIVE,
    DEPRECIATION_STATUS_PAUSED,
]

ACCUMULATED_ACCOUNT_OPTIONS = [
    {"code": "2101", "label": "2101 - Akumulasi Penyusutan Peralatan"},
    {"code": "2102", "label": "2102 - Akumulasi Penyusutan Kendaraan"},
    {"code": "2103", "label": "2103 - Akumulasi Penyusutan Bangunan"},
]

ASSET_CATEGORY_ACCUMULATED_ACCOUNT = {
    "KITCHEN_EQUIPMENT": "2101",
    "OFFICE_EQUIPMENT": "2101",
    "OTHER": "2101",
    "VEHICLE": "2102",
    "BUILDING": "2103",
}


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
        return "Rp 0"


def is_depreciation_schema_ready() -> bool:
    try:
        inspector = inspect(db.engine)
        return inspector.has_table("fixed_asset_depreciation_configs") and inspector.has_table("fixed_asset_depreciations")
    except Exception:
        return False


def get_account_by_code(code: str) -> Account | None:
    return Account.query.filter_by(account_code=str(code or "").strip(), is_active=True).first()


def get_accumulated_account_options() -> list[dict[str, Any]]:
    rows = []
    for option in ACCUMULATED_ACCOUNT_OPTIONS:
        account = get_account_by_code(option["code"])
        rows.append({
            "code": option["code"],
            "label": f"{option['code']} - {account.account_name if account else option['label'].split(' - ', 1)[-1]}",
            "is_ready": bool(account),
        })
    return rows


def resolve_default_accumulated_account_code(asset_category: str) -> str:
    return ASSET_CATEGORY_ACCUMULATED_ACCOUNT.get(str(asset_category or "OTHER").upper(), "2101")


def is_asset_depreciation_configured(asset: FixedAsset) -> bool:
    if not asset:
        return False
    config = getattr(asset, "depreciation_config", None)
    return bool(config and config.status in [DEPRECIATION_STATUS_CONFIGURED, DEPRECIATION_STATUS_ACTIVE])


def calculate_monthly_depreciation(asset: FixedAsset, config: FixedAssetDepreciationConfig) -> float:
    if not asset or not config:
        return 0.0
    depreciable_base = max(float(asset.purchase_value or 0) - float(config.residual_value or 0), 0)
    useful_life_months = int(config.useful_life_months or 0)
    if depreciable_base <= 0 or useful_life_months <= 0:
        return 0.0
    return round(depreciable_base / useful_life_months, 2)


def calculate_posted_depreciation_total(asset_id: int) -> float:
    total = db.session.query(db.func.coalesce(db.func.sum(FixedAssetDepreciation.amount), 0)).filter(
        FixedAssetDepreciation.fixed_asset_id == asset_id,
        FixedAssetDepreciation.status == DEPRECIATION_STATUS_POSTED,
    ).scalar()
    return float(total or 0)


def get_asset_depreciation_rows(branch_id: int, status: str = "ALL") -> list[dict[str, Any]]:
    assets = FixedAsset.query.filter_by(branch_id=branch_id).order_by(FixedAsset.asset_code.asc()).all()
    rows = []
    for asset in assets:
        config = getattr(asset, "depreciation_config", None)
        posted_total = calculate_posted_depreciation_total(asset.id) if config else float(asset.accumulated_depreciation or 0)
        monthly_amount = calculate_monthly_depreciation(asset, config) if config else 0.0
        row_status = "NOT_CONFIGURED"
        if config:
            row_status = config.status
        if status != "ALL" and row_status != status:
            continue
        rows.append({
            "asset": asset,
            "config": config,
            "status": row_status,
            "monthly_amount": monthly_amount,
            "posted_total": posted_total,
            "book_value": max(float(asset.purchase_value or 0) - posted_total, 0),
            "entries_count": len(getattr(asset, "depreciation_entries", []) or []),
        })
    return rows


def configure_asset_depreciation(
    *,
    branch_id: int,
    asset_id: int,
    depreciation_start_date: date,
    useful_life_months: Any,
    residual_value: Any,
    accumulated_account_code: str,
    status: str,
    notes: str | None,
    created_by: int,
    commit: bool = False,
) -> FixedAssetDepreciationConfig:
    asset = FixedAsset.query.filter_by(id=asset_id, branch_id=branch_id).first()
    if not asset:
        raise Exception("Aset tetap tidak ditemukan atau tidak sesuai cabang.")

    if float(asset.purchase_value or 0) <= 0:
        raise Exception("Aset belum memiliki nilai perolehan. Konfigurasi penyusutan tidak bisa dibuat.")

    if not depreciation_start_date:
        raise Exception("Tanggal mulai penyusutan wajib diisi jika penyusutan diaktifkan.")

    useful_life_months = _safe_int(useful_life_months)
    if useful_life_months <= 0:
        raise Exception("Masa manfaat bulan wajib lebih dari 0 jika penyusutan diaktifkan.")

    residual_value = _safe_float(residual_value)
    if residual_value < 0:
        raise Exception("Nilai residu tidak boleh negatif.")
    if residual_value >= float(asset.purchase_value or 0):
        raise Exception("Nilai residu harus lebih kecil dari nilai perolehan aset.")

    accumulated_account_code = str(accumulated_account_code or "").strip()
    if accumulated_account_code not in [item["code"] for item in ACCUMULATED_ACCOUNT_OPTIONS]:
        raise Exception("Akun akumulasi penyusutan tidak valid.")
    if not get_account_by_code(accumulated_account_code):
        raise Exception(f"Akun akumulasi {accumulated_account_code} belum tersedia atau tidak aktif.")
    if not get_account_by_code("5012"):
        raise Exception("Akun 5012 Beban Penyusutan belum tersedia atau tidak aktif.")

    status = str(status or DEPRECIATION_STATUS_CONFIGURED).upper()
    if status not in DEPRECIATION_STATUS_OPTIONS:
        status = DEPRECIATION_STATUS_CONFIGURED

    config = FixedAssetDepreciationConfig.query.filter_by(fixed_asset_id=asset.id).first()
    if not config:
        config = FixedAssetDepreciationConfig(
            branch_id=branch_id,
            fixed_asset_id=asset.id,
            depreciation_start_date=depreciation_start_date,
            useful_life_months=useful_life_months,
            residual_value=residual_value,
            depreciation_method=DEPRECIATION_METHOD_STRAIGHT_LINE,
            accumulated_account_code=accumulated_account_code,
            expense_account_code="5012",
            status=status,
            notes=(notes or None),
            created_by=created_by,
        )
        db.session.add(config)
    else:
        existing_posted = FixedAssetDepreciation.query.filter_by(fixed_asset_id=asset.id).first()
        if existing_posted:
            # Setelah ada jurnal penyusutan, parameter inti tidak boleh diubah diam-diam.
            if (
                config.depreciation_start_date != depreciation_start_date
                or int(config.useful_life_months or 0) != useful_life_months
                or round(float(config.residual_value or 0), 2) != round(residual_value, 2)
                or config.accumulated_account_code != accumulated_account_code
            ):
                raise Exception("Konfigurasi inti tidak boleh diubah setelah ada jurnal penyusutan. Pause aset lalu buat koreksi manual jika diperlukan.")
        config.depreciation_start_date = depreciation_start_date
        config.useful_life_months = useful_life_months
        config.residual_value = residual_value
        config.accumulated_account_code = accumulated_account_code
        config.expense_account_code = "5012"
        config.status = status
        config.notes = notes or None

    if asset.useful_life_years <= 0:
        asset.useful_life_years = max(round(useful_life_months / 12), 1)
    asset.residual_value = residual_value

    record_audit_log(
        module="FIXED_ASSET",
        event_type="FIXED_ASSET_DEPRECIATION_CONFIGURED",
        action="UPDATE",
        table_name="fixed_asset_depreciation_configs",
        record_id=config.id,
        description=f"Konfigurasi penyusutan aset {asset.asset_code} - {asset.asset_name} disimpan.",
        metadata={
            "asset_id": asset.id,
            "asset_code": asset.asset_code,
            "useful_life_months": useful_life_months,
            "residual_value": residual_value,
            "accumulated_account_code": accumulated_account_code,
            "expense_account_code": "5012",
            "status": status,
        },
        user_id=created_by,
        branch_id=branch_id,
        commit=False,
    )

    if commit:
        db.session.commit()
    return config


def preview_asset_depreciation(asset: FixedAsset, months: int = 12) -> list[dict[str, Any]]:
    config = getattr(asset, "depreciation_config", None)
    if not asset or not config:
        return []
    monthly_amount = calculate_monthly_depreciation(asset, config)
    if monthly_amount <= 0:
        return []
    start_year = config.depreciation_start_date.year
    start_month = config.depreciation_start_date.month
    posted_periods = {
        (row.period_year, row.period_month)
        for row in FixedAssetDepreciation.query.filter_by(fixed_asset_id=asset.id).all()
    }
    rows = []
    posted_total = calculate_posted_depreciation_total(asset.id)
    base_value = float(asset.purchase_value or 0)
    for idx in range(max(int(months or 0), 0)):
        month_index = (start_year * 12 + start_month - 1) + idx
        year = month_index // 12
        month = month_index % 12 + 1
        amount = min(monthly_amount, max(base_value - float(config.residual_value or 0) - posted_total, 0))
        book_value_after = max(base_value - posted_total - amount, float(config.residual_value or 0))
        rows.append({
            "period_year": year,
            "period_month": month,
            "period_label": f"{year}-{month:02d}",
            "amount": amount,
            "book_value_after": book_value_after,
            "is_posted": (year, month) in posted_periods,
        })
        if (year, month) not in posted_periods:
            posted_total += amount
    return rows


def generate_depreciation_number(depreciation_date: date) -> str:
    prefix = f"DEP-{depreciation_date.strftime('%Y%m%d')}"
    counter = FixedAssetDepreciation.query.filter(
        FixedAssetDepreciation.depreciation_number.like(f"{prefix}-%")
    ).count() + 1
    while True:
        number = f"{prefix}-{counter:03d}"
        if not FixedAssetDepreciation.query.filter_by(depreciation_number=number).first():
            return number
        counter += 1


def _period_end_date(year: int, month: int) -> date:
    return date(year, month, monthrange(year, month)[1])


def create_depreciation_journal(entry: FixedAssetDepreciation, created_by: int) -> Journal:
    existing = Journal.query.filter_by(
        reference_type=FIXED_ASSET_DEPRECIATION_REFERENCE_TYPE,
        reference_id=entry.id,
    ).first()
    if existing:
        return existing

    asset = entry.fixed_asset
    config = asset.depreciation_config if asset else None
    if not asset or not config:
        raise Exception("Konfigurasi penyusutan aset tidak ditemukan.")

    expense_account = get_account_by_code(config.expense_account_code)
    accumulated_account = get_account_by_code(config.accumulated_account_code)
    if not expense_account:
        raise Exception(f"Akun beban penyusutan {config.expense_account_code} belum tersedia.")
    if not accumulated_account:
        raise Exception(f"Akun akumulasi penyusutan {config.accumulated_account_code} belum tersedia.")

    amount = float(entry.amount or 0)
    if amount <= 0:
        raise Exception("Nominal penyusutan tidak valid untuk jurnal.")

    journal = Journal(
        journal_number=generate_journal_number(entry.depreciation_date),
        journal_date=entry.depreciation_date,
        reference_type=FIXED_ASSET_DEPRECIATION_REFERENCE_TYPE,
        reference_id=entry.id,
        description=f"Penyusutan aset {asset.asset_code} - {asset.asset_name} periode {entry.period_year}-{entry.period_month:02d}",
        created_by=created_by,
    )
    db.session.add(journal)
    db.session.flush()

    db.session.add(JournalDetail(journal_id=journal.id, account_id=expense_account.id, debit=amount, credit=0))
    db.session.add(JournalDetail(journal_id=journal.id, account_id=accumulated_account.id, debit=0, credit=amount))
    entry.journal_id = journal.id
    return journal


def post_asset_depreciation(
    *,
    branch_id: int,
    asset_id: int,
    period_year: Any,
    period_month: Any,
    created_by: int,
    commit: bool = False,
) -> FixedAssetDepreciation:
    asset = FixedAsset.query.filter_by(id=asset_id, branch_id=branch_id).first()
    if not asset:
        raise Exception("Aset tetap tidak ditemukan atau tidak sesuai cabang.")
    config = getattr(asset, "depreciation_config", None)
    if not config:
        raise Exception("Aset belum dikonfigurasi penyusutannya. Tidak ada jurnal yang dibuat.")
    if config.status == DEPRECIATION_STATUS_PAUSED:
        raise Exception("Penyusutan aset sedang PAUSED. Tidak ada jurnal yang dibuat.")
    if config.status not in [DEPRECIATION_STATUS_CONFIGURED, DEPRECIATION_STATUS_ACTIVE]:
        raise Exception("Status konfigurasi penyusutan tidak valid untuk posting.")

    year = _safe_int(period_year)
    month = _safe_int(period_month)
    if year < 2000 or month < 1 or month > 12:
        raise Exception("Periode penyusutan tidak valid.")

    depreciation_date = _period_end_date(year, month)
    if depreciation_date < config.depreciation_start_date:
        raise Exception("Periode penyusutan lebih awal dari tanggal mulai penyusutan.")

    duplicate = FixedAssetDepreciation.query.filter_by(
        fixed_asset_id=asset.id,
        period_year=year,
        period_month=month,
    ).first()
    if duplicate:
        raise Exception("Jurnal penyusutan periode ini sudah pernah dibuat untuk aset tersebut.")

    monthly_amount = calculate_monthly_depreciation(asset, config)
    if monthly_amount <= 0:
        raise Exception("Nominal penyusutan bulanan tidak valid.")

    posted_total = calculate_posted_depreciation_total(asset.id)
    depreciable_limit = max(float(asset.purchase_value or 0) - float(config.residual_value or 0), 0)
    remaining_depreciable = max(depreciable_limit - posted_total, 0)
    amount = min(monthly_amount, remaining_depreciable)
    if amount <= 0:
        raise Exception("Aset sudah mencapai nilai residu. Tidak ada penyusutan tambahan.")

    accumulated_after = posted_total + amount
    book_value_after = max(float(asset.purchase_value or 0) - accumulated_after, float(config.residual_value or 0))

    entry = FixedAssetDepreciation(
        branch_id=branch_id,
        depreciation_number=generate_depreciation_number(depreciation_date),
        fixed_asset_id=asset.id,
        period_year=year,
        period_month=month,
        depreciation_date=depreciation_date,
        amount=amount,
        accumulated_depreciation_after=accumulated_after,
        book_value_after=book_value_after,
        status=DEPRECIATION_STATUS_POSTED,
        created_by=created_by,
    )
    db.session.add(entry)
    db.session.flush()

    journal = create_depreciation_journal(entry, created_by)
    asset.accumulated_depreciation = accumulated_after
    asset.book_value = book_value_after
    if round(book_value_after, 2) <= round(float(config.residual_value or 0), 2):
        config.status = "FULLY_DEPRECIATED"

    record_audit_log(
        module="FIXED_ASSET",
        event_type="FIXED_ASSET_DEPRECIATION_POSTED",
        action="CREATE",
        table_name="fixed_asset_depreciations",
        record_id=entry.id,
        description=f"Penyusutan aset {asset.asset_code} periode {year}-{month:02d} sebesar {_money(amount)} dibuat.",
        metadata={
            "asset_id": asset.id,
            "asset_code": asset.asset_code,
            "period_year": year,
            "period_month": month,
            "amount": amount,
            "journal_id": journal.id,
            "expense_account_code": config.expense_account_code,
            "accumulated_account_code": config.accumulated_account_code,
        },
        user_id=created_by,
        branch_id=branch_id,
        commit=False,
    )

    if commit:
        db.session.commit()
    return entry


def get_depreciation_summary(branch_id: int) -> dict[str, Any]:
    if not is_depreciation_schema_ready():
        return {
            "asset_count": FixedAsset.query.filter_by(branch_id=branch_id).count(),
            "configured_count": 0,
            "posted_count": 0,
            "posted_total": 0,
        }
    asset_count = FixedAsset.query.filter_by(branch_id=branch_id).count()
    configured_count = FixedAssetDepreciationConfig.query.filter_by(branch_id=branch_id).count()
    posted_count = FixedAssetDepreciation.query.filter_by(branch_id=branch_id).count()
    posted_total = db.session.query(db.func.coalesce(db.func.sum(FixedAssetDepreciation.amount), 0)).filter_by(branch_id=branch_id).scalar()
    return {
        "asset_count": asset_count,
        "configured_count": configured_count,
        "posted_count": posted_count,
        "posted_total": float(posted_total or 0),
    }
