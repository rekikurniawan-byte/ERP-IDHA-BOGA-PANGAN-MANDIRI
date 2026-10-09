"""Satu sumber aturan kontrak: jam lock, libur, mode tagih, tempo, dan siklus.

Fondasi untuk:
- Pembatasan order & sesi portal (Fase 1 & Fase 3)
- Pesanan otomatis harian 18.00 (Fase 5)
- Invoice otomatis 06.00 & siklus tagihan (Fase 6)
- Kontrol kredit syariah & ta'zir (Fase 7)
- Pembuatan surat kontrak otomatis (Fase 9)

Semua fungsi di sini adalah fungsi murni / query baca-saja yang ringan.
Tidak melakukan commit, rollback, atau modifikasi data.
"""
from __future__ import annotations

import calendar
from datetime import date, datetime, time, timedelta
from typing import Optional

from app.extensions import db
from app.models.contract import (
    BILLING_CYCLE_BIWEEKLY,
    BILLING_CYCLE_MONTHLY,
    BILLING_CYCLE_WEEKLY,
    ContractHoliday,
    CustomerContract,
)
from app.models.credit import (
    BILLING_CASH,
    BILLING_DIRECT,
    BILLING_VIA_CLIENT,
    PARTY_MANDOR,
    CreditAccount,
)
from app.models.master import Mandor
from app.utils.clock import today_wib


DEFAULT_LUNCH_LOCK_TIME = time(10, 0)
DEFAULT_DINNER_LOCK_TIME = time(15, 0)
FALLBACK_PORTAL_CUTOFF_TIMES = {
    "LUNCH": DEFAULT_LUNCH_LOCK_TIME,
    "DINNER": DEFAULT_DINNER_LOCK_TIME,
}


def active_contract_for(
    client_id: int | None,
    on_date: date | None = None,
    *,
    branch_id: int | None = None,
) -> Optional[CustomerContract]:
    """Kontrak berstatus ACTIVE milik client yang mencakup tanggal on_date."""
    if not client_id:
        return None
    target_date = on_date or today_wib()

    query = CustomerContract.query.filter(
        CustomerContract.client_id == client_id,
        CustomerContract.status == "ACTIVE",
        CustomerContract.start_date <= target_date,
        CustomerContract.end_date >= target_date,
    )
    if branch_id:
        query = query.filter(CustomerContract.branch_id == branch_id)

    return query.order_by(CustomerContract.end_date.desc(), CustomerContract.id.desc()).first()


def lock_time_for(
    client_id: int | None,
    meal_type: str,
    on_date: date | None = None,
    *,
    branch_id: int | None = None,
) -> time:
    """Jam lock pesanan dari kontrak aktif; tanpa kontrak memakai cutoff bawaan."""
    meal_key = str(meal_type or "").upper()
    contract = active_contract_for(client_id, on_date, branch_id=branch_id)
    if contract:
        if meal_key == "LUNCH":
            return contract.lunch_lock_time or DEFAULT_LUNCH_LOCK_TIME
        if meal_key == "DINNER":
            return contract.dinner_lock_time or DEFAULT_DINNER_LOCK_TIME

    return FALLBACK_PORTAL_CUTOFF_TIMES.get(
        meal_key,
        DEFAULT_LUNCH_LOCK_TIME if meal_key == "LUNCH" else DEFAULT_DINNER_LOCK_TIME,
    )


def is_contract_holiday(
    client_id: int | None,
    on_date: date | None = None,
    *,
    branch_id: int | None = None,
) -> bool:
    """Periksa apakah on_date adalah hari libur rutin atau tanggal libur khusus kontrak."""
    target_date = on_date or today_wib()
    contract = active_contract_for(client_id, target_date, branch_id=branch_id)
    if not contract:
        return False

    # 1. Hari libur rutin mingguan (ISO 1..7, e.g. "7" = Minggu, "6,7" = Sabtu & Minggu)
    iso_day = str(target_date.isoweekday())
    raw_weekly = str(contract.weekly_holidays or "")
    weekly_days = {part.strip() for part in raw_weekly.split(",") if part.strip()}
    if iso_day in weekly_days:
        return True

    # 2. Tanggal libur khusus per kontrak
    has_specific = (
        ContractHoliday.query.filter_by(
            contract_id=contract.id,
            holiday_date=target_date,
        ).first()
        is not None
    )
    return has_specific


def billing_mode_for(
    mandor_id: int | None,
    on_date: date | None = None,
    *,
    branch_id: int | None = None,
) -> str:
    """Pihak yang ditagih, satu sumber dengan resolve_billing_party (invoice).

    Hanya akun kredit sub client yang menentukan: DIRECT/CASH berarti sub client
    yang ditagih, selain itu VIA_CLIENT. Bawaan kontrak diterapkan ke akun saat
    Owner menyimpan kontrak, bukan dibaca di sini, supaya pesanan otomatis dan
    invoice tidak pernah berbeda pendapat.
    """
    if not mandor_id:
        return BILLING_VIA_CLIENT

    mandor = db.session.get(Mandor, mandor_id)
    target_branch = branch_id or (mandor.branch_id if mandor else None)
    if not target_branch:
        return BILLING_VIA_CLIENT

    from app.services.credit_control_service import resolve_billing_party

    party_type, _party_id, account = resolve_billing_party(target_branch, None, mandor_id)
    if party_type == PARTY_MANDOR and account is not None:
        return account.billing_mode
    return BILLING_VIA_CLIENT


def due_days_for(
    client_id: int | None,
    on_date: date | None = None,
    *,
    branch_id: int | None = None,
) -> int:
    """Jatuh tempo (jumlah hari): due_days kontrak aktif bila ada, else ambang credit.terms_days_direct."""
    contract = active_contract_for(client_id, on_date, branch_id=branch_id)
    if contract and contract.due_days and contract.due_days >= 1:
        return int(contract.due_days)

    if branch_id:
        from app.services.credit_control_service import get_thresholds

        thresholds = get_thresholds(branch_id)
        return int(thresholds.get("credit.terms_days_direct", 7))

    return 7


def next_cycle_cutoff(contract: CustomerContract, after_date: date) -> date:
    """Hitung tanggal potong (cutoff) siklus tagihan berikutnya menurut siklus & anchor.

    Digunakan oleh Fase 6 (Invoice otomatis) untuk menentukan kapan invoice periode
    terbit berikutnya.
    Siklus:
    - WEEKLY: kelipatan 7 hari dari anchor
    - BIWEEKLY: kelipatan 14 hari dari anchor
    - MONTHLY: tanggal anchor di bulan berikutnya, dengan penyesuaian akhir bulan (clipping).
    """
    if not contract:
        raise ValueError("Kontrak wajib disediakan.")
    anchor = getattr(contract, "billing_anchor_date", None) or getattr(contract, "start_date", None)
    if not anchor:
        raise ValueError("Kontrak belum memiliki billing_anchor_date atau start_date.")

    if anchor > after_date:
        return anchor

    cycle = getattr(contract, "billing_cycle", BILLING_CYCLE_BIWEEKLY) or BILLING_CYCLE_BIWEEKLY

    if cycle == BILLING_CYCLE_WEEKLY:
        delta_days = (after_date - anchor).days
        steps = (delta_days // 7) + 1
        return anchor + timedelta(days=steps * 7)

    if cycle == BILLING_CYCLE_BIWEEKLY:
        delta_days = (after_date - anchor).days
        steps = (delta_days // 14) + 1
        return anchor + timedelta(days=steps * 14)

    if cycle == BILLING_CYCLE_MONTHLY:
        anchor_day = anchor.day
        cur_year = after_date.year
        cur_month = after_date.month

        max_in_month = calendar.monthrange(cur_year, cur_month)[1]
        target_day = min(anchor_day, max_in_month)
        candidate = date(cur_year, cur_month, target_day)
        if candidate > after_date:
            return candidate

        # Lanjut ke bulan berikutnya
        if cur_month == 12:
            next_year = cur_year + 1
            next_month = 1
        else:
            next_year = cur_year
            next_month = cur_month + 1

        next_max = calendar.monthrange(next_year, next_month)[1]
        return date(next_year, next_month, min(anchor_day, next_max))

    # Fallback default BIWEEKLY
    delta_days = (after_date - anchor).days
    steps = (delta_days // 14) + 1
    return anchor + timedelta(days=steps * 14)
