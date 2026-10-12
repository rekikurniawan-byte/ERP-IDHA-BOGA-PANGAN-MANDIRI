"""Laporan tenaga kerja: rekap apel, sering izin/mangkir, alasan keluar, denda & ganti rugi."""
from __future__ import annotations

from collections import Counter
from datetime import date
from decimal import Decimal

from app.models.hr import EmployeeAttendance
from app.models.master import Employee
from app.models.workforce import (
    CHARGE_ACTIVE,
    CHARGE_PAID,
    EXIT_CANCELLED,
    EmployeeAbsenceCase,
    EmployeeCharge,
    EmployeeExit,
    EmployeeLeave,
)
from app.services.employee_charge_service import charge_remaining
from app.services.employee_exit_service import EXIT_REASONS, EXIT_TYPE_LABELS
from app.services.workforce_service import money


def workforce_report(branch_id: int, start: date, end: date) -> dict:
    attendance = (
        EmployeeAttendance.query
        .filter(
            EmployeeAttendance.branch_id == branch_id,
            EmployeeAttendance.attendance_date >= start,
            EmployeeAttendance.attendance_date <= end,
        )
        .all()
    )
    per_employee: dict[int, Counter] = {}
    for row in attendance:
        per_employee.setdefault(row.employee_id, Counter())[row.status] += 1
    employees = {e.id: e for e in Employee.query.filter_by(branch_id=branch_id).all()}
    recap = []
    for employee_id, counts in per_employee.items():
        employee = employees.get(employee_id)
        if not employee:
            continue
        total = sum(counts.values())
        recap.append({
            "employee": employee,
            "counts": counts,
            "total": total,
            "attendance_rate": round(counts.get("HADIR", 0) * 100 / total) if total else 0,
            "absence": counts.get("ALPA", 0),
        })
    recap.sort(key=lambda row: (-row["absence"], -(row["total"] - row["counts"].get("HADIR", 0)), row["employee"].full_name))

    leaves = (
        EmployeeLeave.query
        .filter(EmployeeLeave.branch_id == branch_id, EmployeeLeave.start_date >= start, EmployeeLeave.start_date <= end)
        .all()
    )
    leave_counts = Counter(leave.employee_id for leave in leaves)
    late_returns = Counter(
        leave.employee_id for leave in leaves
        if leave.actual_return_date and leave.actual_return_date > leave.expected_return_date
    )
    cases = (
        EmployeeAbsenceCase.query
        .filter(EmployeeAbsenceCase.branch_id == branch_id, EmployeeAbsenceCase.start_date >= start, EmployeeAbsenceCase.start_date <= end)
        .all()
    )
    case_counts = Counter(case.employee_id for case in cases)
    watch_ids = set(leave_counts) | set(case_counts)
    watchlist = sorted(
        (
            {
                "employee": employees[employee_id],
                "leaves": leave_counts.get(employee_id, 0),
                "late_returns": late_returns.get(employee_id, 0),
                "cases": case_counts.get(employee_id, 0),
            }
            for employee_id in watch_ids if employee_id in employees
        ),
        key=lambda row: (-row["cases"], -row["late_returns"], -row["leaves"]),
    )

    exits = (
        EmployeeExit.query
        .filter(
            EmployeeExit.branch_id == branch_id,
            EmployeeExit.effective_date >= start,
            EmployeeExit.effective_date <= end,
            EmployeeExit.status != EXIT_CANCELLED,
        )
        .all()
    )
    reasons = Counter(row.reason_code for row in exits)
    exit_types = Counter(row.exit_type for row in exits)

    charges = EmployeeCharge.query.filter(
        EmployeeCharge.branch_id == branch_id,
        EmployeeCharge.status.in_((CHARGE_ACTIVE, CHARGE_PAID)),
    ).all()
    charge_summary = {
        "approved": sum((money(c.amount) for c in charges), Decimal("0")),
        "deducted": sum((money(c.deducted_amount) for c in charges), Decimal("0")),
        "outstanding": sum((charge_remaining(c) for c in charges if c.status == CHARGE_ACTIVE), Decimal("0")),
    }

    return {
        "start": start,
        "end": end,
        "recap": recap,
        "watchlist": watchlist,
        "exits": exits,
        "exit_reasons": [(EXIT_REASONS.get(code, code), count) for code, count in reasons.most_common()],
        "exit_types": [(EXIT_TYPE_LABELS.get(code, code), count) for code, count in exit_types.most_common()],
        "charges": charge_summary,
        "case_count": len(cases),
        "leave_count": len(leaves),
    }
