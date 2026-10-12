"""Apel harian, izin keluar lokasi, kasus mangkir, dan kebutuhan orang per sesi.

Semua karyawan tinggal dan bekerja di satu lokasi, jadi tidak ada GPS: admin
mengabsen lewat apel (bawaan Hadir). Status ALPA tanpa izin membuka kasus
mangkir; saat karyawan kembali (Hadir), kasus ditutup dan denda sesuai pasal
kontrak diusulkan ke owner.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from decimal import Decimal

from app.extensions import db
from app.models.hr import EmployeeAttendance
from app.models.master import Employee
from app.models.workforce import (
    ATTENDANCE_STATUSES,
    CASE_DEEMED_RESIGNED,
    CASE_OPEN,
    CASE_OPEN_STATUSES,
    CASE_RETURNED,
    CASE_SUMMONS_1,
    CASE_SUMMONS_2,
    LEAVE_APPROVED,
    LEAVE_REJECTED,
    LEAVE_RETURNED,
    LEAVE_SUBMITTED,
    LEAVE_TYPES,
    EmployeeAbsenceCase,
    EmployeeLeave,
)
from app.services.workforce_service import (
    WorkforceError,
    _safe_url,
    active_contract_for,
    hr_settings,
    latest_signed_contract,
    money,
)
from app.utils.clock import today_wib

ATTENDANCE_LABELS = {
    "HADIR": "Hadir",
    "IZIN": "Izin",
    "SAKIT": "Sakit",
    "CUTI": "Cuti",
    "ALPA": "Tanpa keterangan",
}
LEAVE_TYPE_LABELS = {
    "IZIN_KELUAR": "Izin keluar lokasi",
    "PULANG_KAMPUNG": "Pulang kampung",
    "CUTI": "Cuti",
    "SAKIT": "Sakit",
}
LEAVE_STATUS_LABELS = {
    LEAVE_SUBMITTED: "Menunggu persetujuan",
    LEAVE_APPROVED: "Disetujui",
    LEAVE_REJECTED: "Ditolak",
    LEAVE_RETURNED: "Sudah kembali",
}
CASE_STATUS_LABELS = {
    CASE_OPEN: "Belum ada surat panggilan",
    CASE_SUMMONS_1: "Panggilan 1 terkirim",
    CASE_SUMMONS_2: "Panggilan 2 terkirim",
    CASE_RETURNED: "Sudah kembali",
    CASE_DEEMED_RESIGNED: "Dikualifikasikan mengundurkan diri",
}
LEAVE_TO_ATTENDANCE = {"IZIN_KELUAR": "IZIN", "PULANG_KAMPUNG": "IZIN", "CUTI": "CUTI", "SAKIT": "SAKIT"}
APPROVER_ROLES = ("OWNER", "ADMIN", "HR")


def _role(user) -> str:
    from app.utils.roles import effective_role

    return effective_role(getattr(user, "role", ""))


def can_approve_leave(user) -> bool:
    return _role(user) in ("OWNER", "ADMIN")


def employees_on_roll(branch_id: int, day: date) -> list[Employee]:
    """Karyawan yang wajib diabsen pada hari itu (belum keluar, sudah masuk kerja)."""
    rows = (
        Employee.query
        .filter(Employee.branch_id == branch_id, Employee.status == "ACTIVE")
        .filter(db.or_(Employee.exit_date.is_(None), Employee.exit_date >= day))
        .filter(db.or_(Employee.join_date.is_(None), Employee.join_date <= day))
        .order_by(Employee.employee_type.desc(), Employee.full_name.asc())
        .all()
    )
    return rows


def leave_covering(employee_id: int, day: date) -> EmployeeLeave | None:
    """Izin disetujui yang masih berjalan pada hari itu (belum kembali)."""
    return (
        EmployeeLeave.query
        .filter(
            EmployeeLeave.employee_id == employee_id,
            EmployeeLeave.status == LEAVE_APPROVED,
            EmployeeLeave.start_date <= day,
            EmployeeLeave.actual_return_date.is_(None),
        )
        .order_by(EmployeeLeave.start_date.desc())
        .first()
    )


def open_case_for(employee_id: int) -> EmployeeAbsenceCase | None:
    return (
        EmployeeAbsenceCase.query
        .filter(EmployeeAbsenceCase.employee_id == employee_id, EmployeeAbsenceCase.status.in_(CASE_OPEN_STATUSES))
        .order_by(EmployeeAbsenceCase.start_date.desc())
        .first()
    )


def absent_days(case: EmployeeAbsenceCase, until: date | None = None) -> int:
    """Jumlah hari tanpa keterangan (ALPA di apel) sejak kasus dibuka."""
    end = until or (case.returned_date - timedelta(days=1) if case.returned_date else today_wib())
    return (
        EmployeeAttendance.query
        .filter(
            EmployeeAttendance.employee_id == case.employee_id,
            EmployeeAttendance.status == "ALPA",
            EmployeeAttendance.attendance_date >= case.start_date,
            EmployeeAttendance.attendance_date <= end,
        )
        .count()
    )


def roll_call(branch_id: int, day: date) -> dict:
    employees = employees_on_roll(branch_id, day)
    existing = {
        row.employee_id: row
        for row in EmployeeAttendance.query.filter_by(branch_id=branch_id, attendance_date=day).all()
    }
    rows = []
    for employee in employees:
        record = existing.get(employee.id)
        leave = leave_covering(employee.id, day)
        case = open_case_for(employee.id)
        hint = None
        suggested = "HADIR" if employee.employee_type == "KARYAWAN" else ""
        if case and case.start_date <= day:
            suggested = "ALPA"
            hint = f"Mangkir sejak {case.start_date:%d-%m-%Y}"
        elif leave and day <= leave.expected_return_date:
            suggested = LEAVE_TO_ATTENDANCE.get(leave.leave_type, "IZIN")
            hint = f"{LEAVE_TYPE_LABELS[leave.leave_type]} s/d {leave.expected_return_date:%d-%m-%Y}"
        elif leave:
            suggested = "ALPA"
            hint = f"Seharusnya kembali {leave.expected_return_date:%d-%m-%Y}"
        rows.append({
            "employee": employee,
            "status": record.status if record else suggested,
            "notes": record.notes if record else "",
            "medical_note": bool(record and record.medical_note),
            "recorded": bool(record),
            "hint": hint,
            "is_reserve": employee.employee_type == "CADANGAN",
        })
    counts = {status: 0 for status in ATTENDANCE_STATUSES}
    for row in rows:
        if row["recorded"] and row["status"] in counts:
            counts[row["status"]] += 1
    return {
        "day": day,
        "rows": rows,
        "staff": [r for r in rows if not r["is_reserve"]],
        "reserve": [r for r in rows if r["is_reserve"]],
        "recorded": any(r["recorded"] for r in rows),
        "counts": counts,
    }


def _notify(branch_id, *, key, title, message, endpoint, priority="HIGH", target_role="OWNER", **url_kwargs):
    from app.services.notification_service import create_or_update_notification

    create_or_update_notification(
        branch_id=branch_id,
        notification_type="HR_WORKFORCE",
        title=title,
        message=message,
        target_role=target_role,
        priority=priority,
        action_url=_safe_url(endpoint, **url_kwargs),
        generated_key=key,
        commit=False,
    )


def _propose(employee, *, amount, clause, description, source_type, source_id, created_by, contract=None):
    """Usulkan denda bila nominalnya ada dan karyawan punya kontrak tertulis."""
    from app.services.employee_charge_service import create_charge

    if money(amount) <= 0:
        return None
    contract = contract or latest_signed_contract(employee.id)
    if not contract:
        return None
    return create_charge(
        employee=employee,
        charge_type="DENDA",
        amount=amount,
        clause=clause,
        description=description,
        created_by=created_by,
        source_type=source_type,
        source_id=source_id,
        contract=contract,
    )


def open_absence_case(employee: Employee, day: date, user_id: int, leave: EmployeeLeave | None = None) -> EmployeeAbsenceCase:
    case = EmployeeAbsenceCase(
        branch_id=employee.branch_id,
        employee_id=employee.id,
        contract_id=getattr(active_contract_for(employee.id, day), "id", None),
        leave_id=leave.id if leave else None,
        start_date=day,
        status=CASE_OPEN,
        created_by=user_id,
    )
    db.session.add(case)
    db.session.flush()
    reason = (
        f"tidak kembali dari {LEAVE_TYPE_LABELS[leave.leave_type].lower()} (seharusnya {leave.expected_return_date:%d-%m-%Y})"
        if leave else "tidak ada di lokasi tanpa izin"
    )
    _notify(
        employee.branch_id,
        key=f"hr-case-{case.id}",
        title=f"{employee.full_name} mangkir",
        message=f"{employee.full_name} {reason} sejak {day:%d-%m-%Y}. Siapkan surat panggilan bila belum kembali.",
        endpoint="workforce.case_detail",
        case_id=case.id,
    )
    return case


def return_from_case(case: EmployeeAbsenceCase, day: date, user_id: int) -> list:
    """Karyawan kembali: tutup kasus dan usulkan denda sesuai kontrak."""
    if case.status not in CASE_OPEN_STATUSES:
        raise WorkforceError("Kasus ini sudah ditutup.")
    if day < case.start_date:
        raise WorkforceError("Tanggal kembali tidak boleh sebelum tanggal mulai mangkir.")
    days = absent_days(case, until=day - timedelta(days=1))
    case.status = CASE_RETURNED
    case.returned_date = day
    case.closed_at = datetime.utcnow()
    employee = case.employee
    contract = case.contract or latest_signed_contract(employee.id)
    proposals = []
    if not contract:
        return proposals
    if case.leave_id:
        leave = case.leave
        leave.status = LEAVE_RETURNED
        leave.actual_return_date = day
        proposals.append(_propose(
            employee,
            amount=money(contract.fine_late_return_per_day) * days,
            clause=f"Kontrak {contract.contract_number}: denda terlambat kembali dari izin",
            description=f"Terlambat kembali {days} hari (seharusnya {leave.expected_return_date:%d-%m-%Y}, kembali {day:%d-%m-%Y}).",
            source_type="ABSENCE_CASE",
            source_id=case.id,
            created_by=user_id,
            contract=contract,
        ))
    else:
        proposals.append(_propose(
            employee,
            amount=money(contract.fine_absent_per_day) * days,
            clause=f"Kontrak {contract.contract_number}: denda mangkir per hari",
            description=f"Mangkir {days} hari ({case.start_date:%d-%m-%Y} s/d {day - timedelta(days=1):%d-%m-%Y}).",
            source_type="ABSENCE_CASE",
            source_id=case.id,
            created_by=user_id,
            contract=contract,
        ))
        proposals.append(_propose(
            employee,
            amount=contract.fine_leave_site,
            clause=f"Kontrak {contract.contract_number}: denda keluar lokasi tanpa izin",
            description=f"Meninggalkan lokasi tanpa izin sejak {case.start_date:%d-%m-%Y}.",
            source_type="ABSENCE_CASE",
            source_id=case.id,
            created_by=user_id,
            contract=contract,
        ))
    return [p for p in proposals if p]


def _return_from_leave(leave: EmployeeLeave, day: date, user_id: int):
    leave.status = LEAVE_RETURNED
    leave.actual_return_date = day
    late_days = (day - leave.expected_return_date).days
    if late_days <= 0:
        return None
    contract = latest_signed_contract(leave.employee_id)
    if not contract:
        return None
    return _propose(
        leave.employee,
        amount=money(contract.fine_late_return_per_day) * late_days,
        clause=f"Kontrak {contract.contract_number}: denda terlambat kembali dari izin",
        description=f"Terlambat kembali {late_days} hari (seharusnya {leave.expected_return_date:%d-%m-%Y}, kembali {day:%d-%m-%Y}).",
        source_type="LEAVE",
        source_id=leave.id,
        created_by=user_id,
        contract=contract,
    )


def save_roll_call(branch_id: int, day: date, statuses: dict, notes: dict, user_id: int, medical=None) -> dict:
    if day > today_wib():
        raise WorkforceError("Apel tidak bisa diisi untuk hari yang belum terjadi.")
    if day < today_wib() - timedelta(days=7):
        raise WorkforceError("Apel lebih dari 7 hari lalu tidak bisa diubah.")
    summary = {"saved": 0, "opened": [], "returned": [], "proposals": 0}
    on_roll = {employee.id: employee for employee in employees_on_roll(branch_id, day)}
    for raw_id, raw_status in statuses.items():
        employee = on_roll.get(int(raw_id))
        if not employee:
            continue
        status = str(raw_status or "").upper()
        record = EmployeeAttendance.query.filter_by(employee_id=employee.id, attendance_date=day).first()
        if not status:
            if record and employee.employee_type == "CADANGAN":
                db.session.delete(record)
            continue
        if status not in ATTENDANCE_STATUSES:
            raise WorkforceError(f"Status apel {status} tidak dikenal.")
        note = (notes.get(raw_id) or "").strip() or None
        has_medical = status == "SAKIT" and str(raw_id) in set(map(str, medical or ()))
        if record:
            record.status = status
            record.notes = note
            record.medical_note = has_medical
        else:
            db.session.add(EmployeeAttendance(
                branch_id=branch_id,
                attendance_date=day,
                employee_id=employee.id,
                status=status,
                notes=note,
                medical_note=has_medical,
                created_by=user_id,
            ))
        summary["saved"] += 1
        db.session.flush()

        case = open_case_for(employee.id)
        leave = leave_covering(employee.id, day)
        if status == "ALPA":
            if not case:
                overdue = leave if leave and day > leave.expected_return_date else None
                summary["opened"].append(open_absence_case(employee, day, user_id, leave=overdue))
            continue
        if case and case.start_date == day and case.status == CASE_OPEN:
            # Koreksi apel hari yang sama: kasus belum berjalan, hapus.
            db.session.delete(case)
            continue
        if status == "HADIR":
            if case and case.start_date < day:
                summary["proposals"] += len(return_from_case(case, day, user_id))
                summary["returned"].append(employee)
            elif leave and day > leave.start_date:
                # Hadir di hari berangkat = masih apel pagi sebelum pergi, bukan kembali.
                if _return_from_leave(leave, day, user_id):
                    summary["proposals"] += 1
                summary["returned"].append(employee)
    return summary


def create_leave(employee: Employee, *, leave_type: str, start_date: date, expected_return_date: date, reason: str, user) -> EmployeeLeave:
    leave_type = str(leave_type or "").upper()
    if leave_type not in LEAVE_TYPES:
        raise WorkforceError("Jenis izin tidak dikenal.")
    if employee.status != "ACTIVE":
        raise WorkforceError("Karyawan nonaktif.")
    reason = (reason or "").strip()
    if not reason:
        raise WorkforceError("Alasan izin wajib diisi.")
    if expected_return_date < start_date:
        raise WorkforceError("Tanggal kembali tidak boleh sebelum tanggal berangkat.")
    if start_date < today_wib() - timedelta(days=7):
        raise WorkforceError("Tanggal berangkat terlalu lama di belakang.")
    overlap = EmployeeLeave.query.filter(
        EmployeeLeave.employee_id == employee.id,
        EmployeeLeave.status.in_((LEAVE_SUBMITTED, LEAVE_APPROVED)),
        EmployeeLeave.actual_return_date.is_(None),
        EmployeeLeave.start_date <= expected_return_date,
        EmployeeLeave.expected_return_date >= start_date,
    ).first()
    if overlap:
        raise WorkforceError("Karyawan ini sudah punya izin di tanggal yang sama.")
    leave = EmployeeLeave(
        branch_id=employee.branch_id,
        employee_id=employee.id,
        leave_type=leave_type,
        start_date=start_date,
        expected_return_date=expected_return_date,
        reason=reason,
        status=LEAVE_SUBMITTED,
        created_by=user.id,
    )
    db.session.add(leave)
    db.session.flush()
    if can_approve_leave(user):
        decide_leave(leave, approve=True, user=user, notes="Dicatat dan disetujui langsung.")
    else:
        _notify(
            employee.branch_id,
            key=f"hr-leave-{leave.id}",
            title=f"Izin {employee.full_name} menunggu persetujuan",
            message=(
                f"{LEAVE_TYPE_LABELS[leave_type]} {start_date:%d-%m-%Y} s/d {expected_return_date:%d-%m-%Y}: {reason[:120]}"
            ),
            endpoint="workforce.leaves",
            priority="WARNING",
            target_role="ADMIN",
        )
    return leave


def decide_leave(leave: EmployeeLeave, *, approve: bool, user, notes: str | None = None) -> EmployeeLeave:
    if not can_approve_leave(user):
        raise WorkforceError("Hanya ADMIN/OWNER yang boleh memutuskan izin.")
    if leave.status != LEAVE_SUBMITTED:
        raise WorkforceError("Izin ini sudah diputuskan.")
    leave.status = LEAVE_APPROVED if approve else LEAVE_REJECTED
    leave.decided_by = user.id
    leave.decided_at = datetime.utcnow()
    leave.decision_notes = (notes or "").strip() or None
    return leave


def issue_summons(case: EmployeeAbsenceCase, number: int, day: date | None = None) -> EmployeeAbsenceCase:
    day = day or today_wib()
    if case.status not in CASE_OPEN_STATUSES:
        raise WorkforceError("Kasus ini sudah ditutup.")
    if number == 1:
        if case.summons_1_date:
            raise WorkforceError("Surat panggilan 1 sudah diterbitkan.")
        case.summons_1_date = day
        case.summons_1_number = f"SP-MK/{day.year}/{case.id:04d}-1"
        case.status = CASE_SUMMONS_1
    elif number == 2:
        if not case.summons_1_date:
            raise WorkforceError("Terbitkan surat panggilan 1 dulu.")
        if case.summons_2_date:
            raise WorkforceError("Surat panggilan 2 sudah diterbitkan.")
        if day <= case.summons_1_date:
            raise WorkforceError("Surat panggilan 2 paling cepat sehari setelah panggilan 1.")
        case.summons_2_date = day
        case.summons_2_number = f"SP-MK/{day.year}/{case.id:04d}-2"
        case.status = CASE_SUMMONS_2
    else:
        raise WorkforceError("Surat panggilan hanya 1 atau 2.")
    return case


def deemed_resign_ready(case: EmployeeAbsenceCase) -> tuple[bool, str]:
    settings = hr_settings(case.branch_id)
    days = absent_days(case)
    if case.status != CASE_SUMMONS_2:
        return False, "Butuh 2 kali surat panggilan tertulis."
    if days < settings["deemed_resign_days"]:
        return False, f"Baru {days} hari tanpa keterangan; minimal {settings['deemed_resign_days']} hari kerja berturut-turut."
    return True, f"{days} hari tanpa keterangan dan sudah 2 kali dipanggil."


def staffing_forecast(branch_id: int, day: date | None = None) -> dict:
    """Kebutuhan orang per sesi dari porsi pesanan dibanding karyawan yang tersedia."""
    from app.models.operational import DailyOrder

    day = day or today_wib() + timedelta(days=1)
    settings = hr_settings(branch_id)
    ratio = settings["portions_per_worker"]
    orders = (
        DailyOrder.query
        .filter(DailyOrder.branch_id == branch_id, DailyOrder.order_date == day)
        .filter(~DailyOrder.status.in_(("CANCELLED", "VOID")))
        .all()
    )
    lunch = sum(int(detail.lunch_qty or 0) for order in orders for detail in order.details)
    dinner = sum(int(detail.dinner_qty or 0) for order in orders for detail in order.details)

    staff = [e for e in employees_on_roll(branch_id, day) if e.employee_type == "KARYAWAN"]
    away = []
    available = 0
    for employee in staff:
        leave = leave_covering(employee.id, day)
        case = open_case_for(employee.id)
        if case:
            away.append({"employee": employee, "reason": "Mangkir"})
        elif leave and leave.start_date <= day:
            away.append({"employee": employee, "reason": LEAVE_TYPE_LABELS[leave.leave_type]})
        else:
            available += 1
    sessions = []
    for label, qty in (("Siang", lunch), ("Sore", dinner)):
        needed = math.ceil(qty / ratio) if qty else 0
        sessions.append({"label": label, "portions": qty, "needed": needed, "short": max(0, needed - available)})
    shortage = max((s["short"] for s in sessions), default=0)
    reserves = (
        Employee.query
        .filter_by(branch_id=branch_id, status="ACTIVE", employee_type="CADANGAN")
        .order_by(Employee.full_name.asc())
        .all()
    )
    return {
        "day": day,
        "ratio": ratio,
        "sessions": sessions,
        "available": available,
        "away": away,
        "shortage": shortage,
        "reserves": reserves,
        "has_orders": bool(lunch or dinner),
    }


def leave_overdue_list(branch_id: int, today: date | None = None) -> list[EmployeeLeave]:
    today = today or today_wib()
    return (
        EmployeeLeave.query
        .filter(
            EmployeeLeave.branch_id == branch_id,
            EmployeeLeave.status == LEAVE_APPROVED,
            EmployeeLeave.actual_return_date.is_(None),
            EmployeeLeave.expected_return_date < today,
        )
        .order_by(EmployeeLeave.expected_return_date.asc())
        .all()
    )


def outstanding_fine_estimate(case: EmployeeAbsenceCase) -> Decimal:
    contract = case.contract or latest_signed_contract(case.employee_id)
    if not contract:
        return Decimal("0")
    days = absent_days(case)
    if case.leave_id:
        return money(contract.fine_late_return_per_day) * days
    return money(contract.fine_absent_per_day) * days + money(contract.fine_leave_site)
