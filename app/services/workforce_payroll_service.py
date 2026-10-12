"""Penghubung modul Tenaga Kerja dengan penggajian.

- Hari tidak bekerja dipotong sesuai aturan yang tertulis di kontrak masing-masing
  (status apel yang dipotong + pembagi upah harian; diatur owner di Aturan Gaji & Potongan).
- Karyawan keluar dibayar sampai hari kerja terakhir + kompensasi PKWT.
- Denda/ganti rugi dipotong maks 50% upah periode (PP 36/2021).
- Saat penggajian dijurnal, potongan resmi mengurangi piutang dan proses keluar selesai.
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date
from decimal import Decimal

from app.models.hr import EmployeeAttendance, Payroll, PayrollDetail
from app.models.workforce import CONTRACT_ACTIVE, CONTRACT_ENDED, EXIT_APPROVED, EXIT_DONE, EmployeeExit
from app.services.employee_charge_service import (
    allocate_detail_deductions,
    apply_posted_payroll_deductions,
    recalculate_detail,
)
from app.services.employee_exit_service import exits_waiting_payroll
from app.services.workforce_service import WorkforceError, hr_settings, money
from app.extensions import db


def period_bounds(payroll: Payroll) -> tuple[date, date]:
    last_day = monthrange(payroll.period_year, payroll.period_month)[1]
    return date(payroll.period_year, payroll.period_month, 1), date(payroll.period_year, payroll.period_month, last_day)


def pay_rules(employee_id: int, branch_id: int, on_date: date) -> dict:
    """Aturan potong hari dari kontrak karyawan; tanpa kontrak = aturan cabang saat ini."""
    from app.services.workforce_service import active_contract_for, latest_signed_contract, parse_statuses

    contract = active_contract_for(employee_id, on_date) or latest_signed_contract(employee_id)
    if contract:
        return {"statuses": parse_statuses(contract.unpaid_statuses), "divisor": contract.daily_wage_divisor or "KALENDER", "contract": contract}
    settings = hr_settings(branch_id)
    return {"statuses": settings["unpaid_statuses"], "divisor": settings["daily_wage_divisor"], "contract": None}


def divisor_days(divisor: str, days_in_month: int) -> int:
    return days_in_month if divisor in (None, "", "KALENDER") else int(divisor)


ANNUAL_LEAVE_DAYS = 12  # UU 13/2003 Ps. 79 ayat 2c: 12 hari kerja setelah 12 bulan bekerja terus-menerus.


def _add_years(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year + years)
    except ValueError:  # 29 Februari
        return value.replace(year=value.year + years, day=28)


def annual_leave_cycle(join_date: date | None, on_date: date) -> tuple[date, date] | None:
    """Tahun cuti yang sedang berjalan pada tanggal itu; None bila belum 12 bulan bekerja."""
    if not join_date:
        return None
    first = _add_years(join_date, 1)
    if on_date < first:
        return None
    years = 0
    while _add_years(first, years + 1) <= on_date:
        years += 1
    start = _add_years(first, years)
    return start, _add_years(first, years + 1)


def paid_annual_leave_dates(employee, start: date, end: date) -> set:
    """Tanggal cuti di rentang yang masih dalam jatah cuti tahunan (dibayar)."""
    from app.models.master import Employee

    if isinstance(employee, int):
        employee = db.session.get(Employee, employee)
    paid = set()
    if not employee or not employee.join_date:
        return paid
    cycle = annual_leave_cycle(employee.join_date, end)
    first_cycle = annual_leave_cycle(employee.join_date, start) or cycle
    if not cycle:
        return paid
    window_start = first_cycle[0] if first_cycle else cycle[0]
    rows = (
        EmployeeAttendance.query
        .filter(
            EmployeeAttendance.employee_id == employee.id,
            EmployeeAttendance.status == "CUTI",
            EmployeeAttendance.attendance_date >= window_start,
            EmployeeAttendance.attendance_date <= end,
        )
        .order_by(EmployeeAttendance.attendance_date.asc())
        .all()
    )
    used: dict = {}
    for row in rows:
        row_cycle = annual_leave_cycle(employee.join_date, row.attendance_date)
        if not row_cycle:
            continue
        used[row_cycle] = used.get(row_cycle, 0) + 1
        if used[row_cycle] <= ANNUAL_LEAVE_DAYS and row.attendance_date >= start:
            paid.add(row.attendance_date)
    return paid


def annual_leave_status(employee, on_date: date) -> dict:
    cycle = annual_leave_cycle(employee.join_date, on_date)
    if not cycle:
        eligible_from = _add_years(employee.join_date, 1) if employee.join_date else None
        return {"eligible": False, "eligible_from": eligible_from, "used": 0, "remaining": 0}
    used = EmployeeAttendance.query.filter(
        EmployeeAttendance.employee_id == employee.id,
        EmployeeAttendance.status == "CUTI",
        EmployeeAttendance.attendance_date >= cycle[0],
        EmployeeAttendance.attendance_date < cycle[1],
    ).count()
    return {"eligible": True, "cycle": cycle, "used": used, "remaining": max(0, ANNUAL_LEAVE_DAYS - used)}


def unpaid_days_by_status(employee_id: int, start: date, end: date, statuses) -> dict:
    """Jumlah hari tidak dibayar per status apel di rentang tanggal.

    Sesuai UU (tidak bisa dimatikan): sakit dengan surat dokter dan cuti dalam jatah
    cuti tahunan 12 hari tetap dibayar, jadi tidak dihitung di sini.
    """
    counts = {code: 0 for code in statuses}
    if end < start or not statuses:
        return counts
    rows = EmployeeAttendance.query.filter(
        EmployeeAttendance.employee_id == employee_id,
        EmployeeAttendance.status.in_(tuple(statuses)),
        EmployeeAttendance.attendance_date >= start,
        EmployeeAttendance.attendance_date <= end,
    ).all()
    paid_leave = paid_annual_leave_dates(employee_id, start, end) if "CUTI" in statuses else set()
    for row in rows:
        if row.status == "SAKIT" and row.medical_note:
            continue
        if row.status == "CUTI" and row.attendance_date in paid_leave:
            continue
        counts[row.status] = counts.get(row.status, 0) + 1
    return counts


def unpaid_absence_days(employee_id: int, start: date, end: date, statuses=("ALPA",)) -> int:
    return sum(unpaid_days_by_status(employee_id, start, end, statuses).values())


def absence_deduction(monthly, days: int, days_divisor: int) -> Decimal:
    if days <= 0 or days_divisor <= 0:
        return Decimal("0")
    return money(money(monthly) * Decimal(days) / Decimal(days_divisor))


def _apply_exit_line(payroll: Payroll, detail: PayrollDetail, row: EmployeeExit) -> None:
    from app.services.hr_service import get_latest_salary

    period_start, period_end = period_bounds(payroll)
    days_in_month = (period_end - period_start).days + 1
    contract = row.contract
    monthly = money(contract.monthly_salary) if contract else money(get_latest_salary(row.employee_id, row.last_work_date))
    start = period_start
    join_date = row.employee.join_date
    if join_date and join_date > start:
        start = join_date
    end = min(period_end, row.last_work_date)
    counted = max(0, (end - start).days + 1) if end >= start else 0
    rules = pay_rules(row.employee_id, payroll.branch_id, end)
    unpaid = unpaid_absence_days(row.employee_id, start, end, rules["statuses"])
    earned = money(monthly * Decimal(counted) / Decimal(days_in_month))
    earned = max(Decimal("0"), earned - absence_deduction(monthly, unpaid, divisor_days(rules["divisor"], days_in_month)))
    detail.base_salary = monthly
    detail.deduction = max(Decimal("0"), monthly - earned)
    detail.unpaid_absence_days = unpaid
    detail.exit_compensation = money(row.end_compensation)
    row.payroll_detail_id = detail.id


def sync_payroll_workforce(payroll: Payroll) -> dict:
    """Masukkan karyawan keluar dan potongan denda/ganti rugi ke penggajian konsep."""
    if payroll.status != "DRAFT":
        raise WorkforceError("Hanya penggajian konsep yang bisa dihitung ulang.")
    _, period_end = period_bounds(payroll)
    details = {detail.employee_id: detail for detail in payroll.details}
    exits = 0
    for row in exits_waiting_payroll(payroll.branch_id, period_end):
        if row.payroll_detail_id and row.payroll_detail_id not in {d.id for d in details.values()}:
            continue  # sudah masuk penggajian lain yang masih konsep
        detail = details.get(row.employee_id)
        if not detail:
            detail = PayrollDetail(payroll_id=payroll.id, employee_id=row.employee_id, bonus=0)
            db.session.add(detail)
            db.session.flush()
            details[row.employee_id] = detail
        _apply_exit_line(payroll, detail, row)
        exits += 1
    percent = hr_settings(payroll.branch_id)["max_deduction_percent"]
    deducted = Decimal("0")
    from app.services.tax_pph21_service import compute_payroll_detail_pph21
    for detail in details.values():
        compute_payroll_detail_pph21(detail, payroll)
        recalculate_detail(detail)
        deducted += allocate_detail_deductions(detail, percent)
    db.session.flush()
    return {"exits": exits, "deducted": deducted}


def finalize_payroll_workforce(payroll: Payroll) -> Decimal:
    """Dipanggil bersama jurnal penggajian: kurangi piutang, selesaikan proses keluar."""
    total = apply_posted_payroll_deductions(payroll)
    detail_ids = [detail.id for detail in payroll.details]
    if detail_ids:
        rows = EmployeeExit.query.filter(
            EmployeeExit.payroll_detail_id.in_(detail_ids),
            EmployeeExit.status == EXIT_APPROVED,
        ).all()
        for row in rows:
            row.status = EXIT_DONE
            row.employee.status = "INACTIVE"
            if row.contract and row.contract.status == CONTRACT_ACTIVE:
                row.contract.status = CONTRACT_ENDED
    return total


def payroll_charge_total(payroll: Payroll) -> Decimal:
    return sum((money(detail.charge_deduction) for detail in payroll.details), Decimal("0"))
