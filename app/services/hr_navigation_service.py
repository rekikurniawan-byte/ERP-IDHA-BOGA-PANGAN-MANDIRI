"""Peta navigasi SDM: satu sumber untuk 4 menu sidebar dan tab di tiap menu.

Aturan owner (2026-10-11): setiap halaman hanya punya SATU pintu. Sidebar SDM
berisi 4 menu; perpindahan di dalam menu lewat tab, bukan dropdown di header.
1. Ringkasan SDM          : dashboard gabungan (tanpa tab).
2. Karyawan & Kontrak     : Daftar Karyawan · Kontrak Kerja · Karyawan Keluar.
3. Kehadiran & Disiplin   : Apel Harian · Izin · Mangkir · Denda & Ganti Rugi · Laporan.
4. Penggajian             : Daftar Penggajian · Riwayat Pembayaran.
"""
from __future__ import annotations

from typing import Any


def _tab(endpoint: str, label: str, also: tuple = (), count: str | None = None) -> dict:
    return {"endpoint": endpoint, "label": label, "endpoints": [endpoint, *also], "count": count}


HR_SECTIONS: list[dict[str, Any]] = [
    {
        "key": "summary",
        "label": "Ringkasan SDM",
        "icon": "bi-speedometer2",
        "endpoint": "workforce.index",
        "tabs": [_tab("workforce.index", "Ringkasan", ("hr.index",))],
    },
    {
        "key": "people",
        "label": "Karyawan & Kontrak",
        "icon": "bi-people",
        "endpoint": "hr.employees",
        "tabs": [
            _tab("hr.employees", "Daftar Karyawan", ("hr.create_employee", "hr.edit_employee", "workforce.employee_detail")),
            _tab("workforce.contracts", "Kontrak Kerja", (
                "workforce.contract_create", "workforce.contract_detail", "workforce.contract_sign_employee",
            ), count="contracts"),
            _tab("workforce.exits", "Karyawan Keluar", ("workforce.exit_create", "workforce.exit_detail"), count="exits"),
        ],
    },
    {
        "key": "attendance",
        "label": "Kehadiran & Disiplin",
        "icon": "bi-calendar-check",
        "endpoint": "workforce.attendance",
        "tabs": [
            _tab("workforce.attendance", "Apel Harian"),
            _tab("workforce.leaves", "Izin", ("workforce.leave_create",), count="leaves"),
            _tab("workforce.cases", "Mangkir", ("workforce.case_detail",), count="cases"),
            _tab("workforce.charges", "Denda & Ganti Rugi", count="charges"),
            _tab("workforce.reports", "Laporan"),
        ],
    },
    {
        "key": "payroll",
        "label": "Penggajian",
        "icon": "bi-cash-coin",
        "endpoint": "hr.payrolls",
        "tabs": [
            _tab("hr.payrolls", "Daftar Penggajian", ("hr.generate_payroll_route", "hr.payroll_detail", "payslip.receipt_sign")),
            _tab("hr.payroll_payment_history", "Riwayat Pembayaran"),
            _tab("workforce.rules", "Aturan Gaji & Potongan"),
        ],
    },
]


def hr_section_for(endpoint: str | None) -> dict | None:
    for section in HR_SECTIONS:
        if any(endpoint in tab["endpoints"] for tab in section["tabs"]):
            return section
    return None


def hr_sections(endpoint: str | None) -> list[dict]:
    """Untuk sidebar: 4 menu dengan penanda aktif."""
    active = hr_section_for(endpoint)
    return [dict(section, active=section is active) for section in HR_SECTIONS]


def hr_tab_counts(branch_id: int) -> dict:
    """Angka kecil di tab: yang menunggu tindakan."""
    from app.models.workforce import (
        CASE_OPEN_STATUSES,
        CHARGE_PROPOSED,
        CONTRACT_DRAFT,
        CONTRACT_WAITING_EMPLOYER,
        EXIT_SUBMITTED,
        LEAVE_SUBMITTED,
        EmployeeAbsenceCase,
        EmployeeCharge,
        EmployeeExit,
        EmployeeLeave,
        EmploymentContract,
    )

    return {
        "leaves": EmployeeLeave.query.filter_by(branch_id=branch_id, status=LEAVE_SUBMITTED).count(),
        "cases": EmployeeAbsenceCase.query.filter(
            EmployeeAbsenceCase.branch_id == branch_id,
            EmployeeAbsenceCase.status.in_(CASE_OPEN_STATUSES),
        ).count(),
        "charges": EmployeeCharge.query.filter_by(branch_id=branch_id, status=CHARGE_PROPOSED).count(),
        "exits": EmployeeExit.query.filter_by(branch_id=branch_id, status=EXIT_SUBMITTED).count(),
        "contracts": EmploymentContract.query.filter(
            EmploymentContract.branch_id == branch_id,
            EmploymentContract.status.in_((CONTRACT_DRAFT, CONTRACT_WAITING_EMPLOYER)),
        ).count(),
    }
