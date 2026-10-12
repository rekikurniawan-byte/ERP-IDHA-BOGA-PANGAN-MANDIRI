"""Karyawan keluar: resign (pemberitahuan 30 hari), habis kontrak, mangkir, diberhentikan.

Penyelesaian akhir dibayar lewat penggajian periode tanggal keluar:
upah sampai hari kerja terakhir + kompensasi PKWT (PP 35/2021) - denda/ganti rugi,
dengan potongan maks 50% upah; sisanya tetap piutang karyawan.
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timedelta
from decimal import ROUND_DOWN, Decimal

from app.extensions import db
from app.models.master import Employee
from app.models.workforce import (
    CASE_DEEMED_RESIGNED,
    CONTRACT_PKWT,
    EXIT_ABSCONDED,
    EXIT_APPROVED,
    EXIT_CANCELLED,
    EXIT_CONTRACT_END,
    EXIT_DISMISSED,
    EXIT_DONE,
    EXIT_RESIGN,
    EXIT_SUBMITTED,
    EmployeeAbsenceCase,
    EmployeeExit,
    EmploymentContract,
)
from app.services.workforce_service import (
    WorkforceError,
    active_contract_for,
    contract_last_day,
    hr_settings,
    latest_signed_contract,
    money,
)
from app.utils.clock import today_wib

EXIT_TYPE_LABELS = {
    EXIT_RESIGN: "Mengundurkan diri",
    EXIT_CONTRACT_END: "Kontrak habis",
    EXIT_ABSCONDED: "Mangkir (dikualifikasikan mengundurkan diri)",
    EXIT_DISMISSED: "Diberhentikan perusahaan",
}
EXIT_STATUS_LABELS = {
    EXIT_SUBMITTED: "Diajukan",
    EXIT_APPROVED: "Disetujui, menunggu penggajian",
    EXIT_DONE: "Selesai dibayar",
    EXIT_CANCELLED: "Batal",
}
EXIT_REASONS = {
    "UPAH": "Upah/penghasilan",
    "KELUARGA": "Urusan keluarga",
    "PULANG_KAMPUNG": "Pulang kampung",
    "PEKERJAAN_LAIN": "Dapat pekerjaan lain",
    "KESEHATAN": "Kesehatan",
    "BEBAN_KERJA": "Lingkungan/beban kerja",
    "KONTRAK_HABIS": "Kontrak habis",
    "MANGKIR": "Mangkir",
    "PELANGGARAN": "Pelanggaran aturan",
    "LAINNYA": "Lainnya",
}
OPEN_EXIT_STATUSES = (EXIT_SUBMITTED, EXIT_APPROVED)


def get_exit(exit_id: int, branch_id: int) -> EmployeeExit:
    row = EmployeeExit.query.filter_by(id=exit_id, branch_id=branch_id).first()
    if not row:
        raise WorkforceError("Data keluar tidak ditemukan.")
    return row


def end_compensation(contract: EmploymentContract | None, last_work_date: date) -> Decimal:
    """Kompensasi PKWT: masa kerja (bulan) / 12 x upah sebulan, minimal 1 bulan kerja."""
    if not contract or contract.contract_type != CONTRACT_PKWT or last_work_date < contract.start_date:
        return Decimal("0")
    months = Decimal((last_work_date - contract.start_date).days + 1) / Decimal("30.4375")
    if months < 1:
        return Decimal("0")
    return money(money(contract.monthly_salary) * months / Decimal(12))


def remaining_contract_wages(contract: EmploymentContract | None, effective_date: date) -> Decimal:
    """Pasal 62 UU 13/2003: upah sampai batas waktu berakhirnya PKWT."""
    if not contract or contract.contract_type != CONTRACT_PKWT or not contract.end_date:
        return Decimal("0")
    remaining_days = (contract.end_date - effective_date).days
    if remaining_days <= 0:
        return Decimal("0")
    return money(money(contract.monthly_salary) * Decimal(remaining_days) / Decimal(30))


def exit_month_wage(contract: EmploymentContract | None, monthly: Decimal, last_work_date: date) -> Decimal:
    days_in_month = monthrange(last_work_date.year, last_work_date.month)[1]
    start = date(last_work_date.year, last_work_date.month, 1)
    if contract and contract.start_date > start:
        start = contract.start_date
    days = max(0, (last_work_date - start).days + 1)
    return money(monthly * Decimal(days) / Decimal(days_in_month))


def settlement_preview(row: EmployeeExit) -> dict:
    from app.services.employee_charge_service import outstanding_for
    from app.services.hr_service import get_latest_salary

    contract = row.contract
    settings = hr_settings(row.branch_id)
    monthly = money(contract.monthly_salary) if contract else money(get_latest_salary(row.employee_id, row.last_work_date))
    wage = exit_month_wage(contract, monthly, row.last_work_date)
    compensation = end_compensation(contract, row.last_work_date)
    employer_damages = Decimal("0")
    employee_damages = Decimal("0")
    if row.exit_type == EXIT_DISMISSED:
        employer_damages = remaining_contract_wages(contract, row.effective_date)
    elif row.exit_type in (EXIT_RESIGN, EXIT_ABSCONDED):
        employee_damages = remaining_contract_wages(contract, row.effective_date)
    short_notice_fine = Decimal("0")
    if row.exit_type == EXIT_RESIGN and row.short_notice_days > 0 and contract:
        short_notice_fine = money(contract.fine_short_notice)
    outstanding = outstanding_for(row.employee_id)
    new_charges = employee_damages + short_notice_fine if row.status == EXIT_SUBMITTED else Decimal("0")
    total_charges = outstanding + new_charges
    gross = wage + compensation + employer_damages
    percent = contract.max_deduction_percent if contract else settings["max_deduction_percent"]
    max_deduct = (gross * Decimal(percent) / Decimal(100)).quantize(Decimal("1"), rounding=ROUND_DOWN)
    deduct_now = min(total_charges, max_deduct)
    return {
        "monthly": monthly,
        "wage": wage,
        "compensation": compensation,
        "employer_damages": employer_damages,
        "employee_damages": employee_damages,
        "short_notice_fine": short_notice_fine,
        "outstanding": outstanding,
        "total_charges": total_charges,
        "gross": gross,
        "percent": percent,
        "max_deduct": max_deduct,
        "deduct_now": deduct_now,
        "receivable_after": total_charges - deduct_now,
        "net": gross - deduct_now,
    }


def create_exit(
    employee: Employee,
    *,
    exit_type: str,
    reason_code: str,
    notice_date: date,
    effective_date: date,
    user_id: int,
    reason_notes: str | None = None,
    handover_notes: str | None = None,
    last_work_date: date | None = None,
    absence_case_id: int | None = None,
) -> EmployeeExit:
    exit_type = str(exit_type or "").upper()
    if exit_type not in EXIT_TYPE_LABELS:
        raise WorkforceError("Jenis keluar tidak dikenal.")
    reason_code = str(reason_code or "").upper()
    if reason_code not in EXIT_REASONS:
        raise WorkforceError("Alasan keluar wajib dipilih.")
    if employee.status != "ACTIVE":
        raise WorkforceError("Karyawan sudah nonaktif.")
    if effective_date < notice_date:
        raise WorkforceError("Tanggal keluar tidak boleh sebelum tanggal pengajuan.")
    existing = EmployeeExit.query.filter(
        EmployeeExit.employee_id == employee.id,
        EmployeeExit.status.in_(OPEN_EXIT_STATUSES),
    ).first()
    if existing:
        raise WorkforceError("Karyawan ini sudah punya proses keluar yang berjalan.")

    contract = active_contract_for(employee.id, min(notice_date, effective_date)) or latest_signed_contract(employee.id)
    if exit_type == EXIT_CONTRACT_END:
        last_day = contract_last_day(contract) if contract else None
        if not contract or contract.contract_type != CONTRACT_PKWT or not last_day:
            raise WorkforceError("Kontrak habis hanya untuk PKWT yang punya tanggal selesai.")
        if effective_date != last_day:
            raise WorkforceError(f"Tanggal keluar kontrak habis harus {last_day:%d-%m-%Y} (tanggal selesai kontrak).")
    short_notice = 0
    if exit_type == EXIT_RESIGN:
        notice_days = contract.notice_days if contract else hr_settings(employee.branch_id)["notice_days"]
        short_notice = max(0, notice_days - (effective_date - notice_date).days)

    row = EmployeeExit(
        branch_id=employee.branch_id,
        employee_id=employee.id,
        contract_id=contract.id if contract else None,
        absence_case_id=absence_case_id,
        exit_type=exit_type,
        reason_code=reason_code,
        reason_notes=(reason_notes or "").strip() or None,
        notice_date=notice_date,
        effective_date=effective_date,
        last_work_date=last_work_date or effective_date,
        short_notice_days=short_notice,
        handover_notes=(handover_notes or "").strip() or None,
        status=EXIT_SUBMITTED,
        created_by=user_id,
    )
    db.session.add(row)
    db.session.flush()
    return row


def approve_exit(row: EmployeeExit, user, *, handover_done: bool) -> list:
    """Setujui keluar: kunci tanggal, akhiri kontrak, buat denda/ganti rugi."""
    from app.services.employee_charge_service import approve_charge, create_charge
    from app.services.workforce_attendance_service import can_approve_leave

    if not can_approve_leave(user):
        raise WorkforceError("Hanya ADMIN/OWNER yang boleh menyetujui karyawan keluar.")
    if row.status != EXIT_SUBMITTED:
        raise WorkforceError("Pengajuan ini sudah diproses.")
    if row.exit_type != EXIT_ABSCONDED and not handover_done:
        raise WorkforceError("Pastikan serah terima pekerjaan/barang sudah selesai sebelum disetujui.")

    preview = settlement_preview(row)
    contract = row.contract
    charges = []
    if preview["employee_damages"] > 0:
        charges.append(create_charge(
            employee=row.employee,
            charge_type="GANTI_RUGI",
            amount=preview["employee_damages"],
            clause=f"Kontrak {contract.contract_number}: ganti rugi sisa kontrak (Pasal 62 UU 13/2003)",
            description=f"Berhenti {row.effective_date:%d-%m-%Y} sebelum kontrak selesai {contract.end_date:%d-%m-%Y}.",
            created_by=user.id,
            source_type="EXIT",
            source_id=row.id,
            contract=contract,
        ))
    if preview["short_notice_fine"] > 0:
        charges.append(create_charge(
            employee=row.employee,
            charge_type="DENDA",
            amount=preview["short_notice_fine"],
            clause=f"Kontrak {contract.contract_number}: pemberitahuan resign {contract.notice_days} hari",
            description=f"Resign kurang {row.short_notice_days} hari dari masa pemberitahuan.",
            created_by=user.id,
            source_type="EXIT",
            source_id=row.id,
            contract=contract,
        ))
    if str(getattr(user, "role", "")).upper() == "OWNER":
        for charge in charges:
            approve_charge(charge, user)

    row.status = EXIT_APPROVED
    row.handover_done = bool(handover_done)
    row.approved_by = user.id
    row.approved_at = datetime.utcnow()
    row.end_compensation = preview["compensation"] + preview["employer_damages"]

    employee = row.employee
    employee.exit_date = row.effective_date
    employee.exit_reason = row.reason_code
    if contract:
        contract.ended_at = row.effective_date if not contract.end_date else min(contract.end_date, row.effective_date)
        contract.end_reason = row.exit_type
        contract.end_compensation_amount = preview["compensation"]
    return charges


def cancel_exit(row: EmployeeExit) -> EmployeeExit:
    if row.status != EXIT_SUBMITTED:
        raise WorkforceError("Hanya pengajuan yang belum disetujui yang bisa dibatalkan.")
    row.status = EXIT_CANCELLED
    return row


def exit_for_absconding(case: EmployeeAbsenceCase, user) -> EmployeeExit:
    """Mangkir >= 5 hari kerja + 2 panggilan tertulis -> dikualifikasikan mengundurkan diri."""
    from app.services.employee_charge_service import approve_charge, create_charge
    from app.services.workforce_attendance_service import absent_days, deemed_resign_ready

    if str(getattr(user, "role", "")).upper() != "OWNER":
        raise WorkforceError("Hanya OWNER yang memutuskan karyawan dikualifikasikan mengundurkan diri.")
    ready, message = deemed_resign_ready(case)
    if not ready:
        raise WorkforceError(message)
    today = today_wib()
    row = create_exit(
        case.employee,
        exit_type=EXIT_ABSCONDED,
        reason_code="MANGKIR",
        notice_date=today,
        effective_date=today,
        last_work_date=case.start_date - timedelta(days=1),
        user_id=user.id,
        reason_notes=f"Mangkir sejak {case.start_date:%d-%m-%Y}; panggilan {case.summons_1_number} dan {case.summons_2_number}.",
        absence_case_id=case.id,
    )
    charges = approve_exit(row, user, handover_done=False)
    contract = row.contract
    if contract:
        days = absent_days(case)
        fine = money(contract.fine_absent_per_day) * days + money(contract.fine_leave_site)
        if fine > 0:
            charge = create_charge(
                employee=case.employee,
                charge_type="DENDA",
                amount=fine,
                clause=f"Kontrak {contract.contract_number}: denda mangkir & keluar lokasi tanpa izin",
                description=f"Mangkir {days} hari sejak {case.start_date:%d-%m-%Y} sampai dikualifikasikan mengundurkan diri.",
                created_by=user.id,
                source_type="ABSENCE_CASE",
                source_id=case.id,
                contract=contract,
            )
            approve_charge(charge, user)
            charges.append(charge)
    case.status = CASE_DEEMED_RESIGNED
    case.closed_at = datetime.utcnow()
    return row


def exits_waiting_payroll(branch_id: int, period_end: date) -> list[EmployeeExit]:
    return (
        EmployeeExit.query
        .filter(
            EmployeeExit.branch_id == branch_id,
            EmployeeExit.status == EXIT_APPROVED,
            EmployeeExit.effective_date <= period_end,
        )
        .order_by(EmployeeExit.effective_date.asc())
        .all()
    )
