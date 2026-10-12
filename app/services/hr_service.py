from datetime import date
from calendar import monthrange

from app.utils.clock import today_wib

from app.extensions import db
from app.models.master import Employee, EmployeeSkill
from app.models.hr import Payroll, PayrollDetail, EmployeeSalaryHistory
from app.services.employee_charge_service import allocate_detail_deductions, recalculate_detail
from app.services.workforce_payroll_service import (
    absence_deduction,
    divisor_days,
    pay_rules,
    sync_payroll_workforce,
    unpaid_absence_days,
)
from app.services.workforce_service import hr_settings


# SDM2A_HR_SERVICE


def get_latest_salary(employee_id, target_date=None):
    target_date = target_date or today_wib()

    salary = (
        EmployeeSalaryHistory.query
        .filter(
            EmployeeSalaryHistory.employee_id == employee_id,
            EmployeeSalaryHistory.effective_date <= target_date,
        )
        .order_by(EmployeeSalaryHistory.effective_date.desc(), EmployeeSalaryHistory.id.desc())
        .first()
    )

    return float(salary.salary_amount or 0) if salary else 0



# SDM4A_PRORATA_GAJI_MASUK_TENGAH_BULAN
def calculate_prorated_monthly_salary(employee, monthly_salary, period_month, period_year):
    """
    Menghitung gaji prorata untuk karyawan yang masuk di tengah bulan.
    Aturan:
    - Kalau join_date kosong atau join_date <= awal bulan, gaji full.
    - Kalau join_date di tengah bulan, gaji dihitung dari join_date sampai akhir bulan.
    - Kalau join_date setelah akhir bulan, gaji 0.
    - Hitungan sementara pakai hari kalender, bukan absensi.
    """
    monthly_salary = float(monthly_salary or 0)

    last_day = monthrange(period_year, period_month)[1]
    period_start = date(period_year, period_month, 1)
    period_end = date(period_year, period_month, last_day)

    join_date = employee.join_date or period_start

    if join_date > period_end:
        return 0, 0, last_day

    counted_start = max(join_date, period_start)
    counted_days = (period_end - counted_start).days + 1

    if counted_days < 0:
        counted_days = 0

    prorated_salary = round(monthly_salary * counted_days / last_day, 0)

    return prorated_salary, counted_days, last_day


def create_or_update_salary(employee, salary_amount, effective_date, notes=None):
    record = EmployeeSalaryHistory(
        employee_id=employee.id,
        effective_date=effective_date,
        salary_amount=float(salary_amount or 0),
        notes=notes,
    )

    db.session.add(record)
    return record


def _commit_or_rollback():
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise


def _skill_names(skills_raw):
    return [item.strip() for item in str(skills_raw or "").split(",") if item.strip()]


def _add_employee_skills(employee_id, skill_names):
    for skill_name in skill_names:
        db.session.add(EmployeeSkill(
            employee_id=employee_id,
            skill_name=skill_name,
        ))


PROFILE_FIELDS = (
    "nik",
    "address",
    "position",
    "emergency_contact_name",
    "emergency_contact_phone",
    "ptkp_status",
    "npwp",
)


def _apply_profile(employee, profile):
    """Data diri untuk kontrak kerja (Modul Tenaga Kerja) dan pajak."""
    if not profile:
        return
    for field in PROFILE_FIELDS:
        if field in profile:
            val = str(profile.get(field) or "").strip() or None
            if field == "ptkp_status" and val:
                val = val.upper()
            setattr(employee, field, val)
    employee_type = str(profile.get("employee_type") or "").upper()
    if employee_type in ("KARYAWAN", "CADANGAN"):
        employee.employee_type = employee_type


def create_employee_record(*, branch_id, full_name, phone, join_date, salary_amount, skills_raw, profile=None):
    employee = Employee(
        branch_id=branch_id,
        full_name=full_name,
        phone=phone or None,
        join_date=join_date,
        status="ACTIVE",
        employee_type="KARYAWAN",
    )
    _apply_profile(employee, profile)

    db.session.add(employee)
    db.session.flush()
    _add_employee_skills(employee.id, _skill_names(skills_raw))

    salary_amount = float(salary_amount or 0)
    if salary_amount > 0:
        create_or_update_salary(
            employee=employee,
            salary_amount=salary_amount,
            effective_date=join_date or today_wib(),
            notes="Gaji awal karyawan",
        )

    _commit_or_rollback()
    return employee


def update_employee_record(
    employee,
    *,
    full_name,
    phone,
    join_date,
    status,
    salary_amount,
    salary_effective_date,
    skills_raw,
    profile=None,
):
    employee.full_name = full_name
    _apply_profile(employee, profile)
    employee.phone = phone or None
    employee.status = status
    employee.join_date = join_date

    EmployeeSkill.query.filter_by(employee_id=employee.id).delete()
    _add_employee_skills(employee.id, _skill_names(skills_raw))

    if salary_amount not in [None, ""]:
        salary_amount = float(salary_amount or 0)
        if salary_amount > 0:
            create_or_update_salary(
                employee=employee,
                salary_amount=salary_amount,
                effective_date=salary_effective_date or today_wib(),
                notes="Update gaji karyawan",
            )

    _commit_or_rollback()
    return employee


def toggle_employee_status(employee):
    employee.status = "INACTIVE" if employee.status == "ACTIVE" else "ACTIVE"
    _commit_or_rollback()
    return employee


def generate_payroll(branch_id, period_month, period_year, created_by):
    existing = Payroll.query.filter_by(
        branch_id=branch_id,
        period_month=period_month,
        period_year=period_year,
    ).first()

    if existing:
        return False, "Payroll periode tersebut sudah ada.", existing

    employees = (
        Employee.query
        .filter_by(branch_id=branch_id)
        .filter(Employee.status == "ACTIVE")
        # Tenaga cadangan (harian lepas) tidak digaji bulanan.
        .filter(Employee.employee_type != "CADANGAN")
        .order_by(Employee.full_name.asc())
        .all()
    )

    if not employees:
        return False, "Belum ada karyawan aktif.", None

    payroll = Payroll(
        branch_id=branch_id,
        period_month=period_month,
        period_year=period_year,
        status="DRAFT",
        created_by=created_by,
    )

    db.session.add(payroll)
    db.session.flush()

    # SDM3B_EFFECTIVE_SALARY_END_OF_MONTH
    # Gaji yang berlaku di tengah bulan tetap terbaca untuk payroll bulan tersebut.
    last_day = monthrange(period_year, period_month)[1]
    target_date = date(period_year, period_month, last_day)

    for employee in employees:
        monthly_salary = get_latest_salary(employee.id, target_date)
        prorated_salary, counted_days, total_days = calculate_prorated_monthly_salary(
            employee=employee,
            monthly_salary=monthly_salary,
            period_month=period_month,
            period_year=period_year,
        )

        prorata_deduction = max(0, float(monthly_salary or 0) - float(prorated_salary or 0))

        # Hari tidak bekerja dipotong sesuai aturan di kontrak karyawan (Aturan Gaji & Potongan).
        counted_start = max(employee.join_date or date(period_year, period_month, 1), date(period_year, period_month, 1))
        rules = pay_rules(employee.id, branch_id, target_date)
        alpa_days = unpaid_absence_days(employee.id, counted_start, target_date, rules["statuses"])
        alpa_deduction = float(absence_deduction(monthly_salary, alpa_days, divisor_days(rules["divisor"], total_days)))
        alpa_deduction = min(alpa_deduction, float(prorated_salary or 0))

        db.session.add(PayrollDetail(
            payroll_id=payroll.id,
            employee_id=employee.id,
            base_salary=monthly_salary,
            bonus=0,
            deduction=prorata_deduction + alpa_deduction,
            unpaid_absence_days=alpa_days,
            final_salary=max(0, float(prorated_salary or 0) - alpa_deduction),
        ))

    db.session.flush()
    # Karyawan keluar + potongan denda/ganti rugi (maks 50% upah).
    sync_payroll_workforce(payroll)

    return True, "Payroll berhasil dibuat.", payroll


def recalculate_payroll_detail(detail):
    # final = base + bonus + kompensasi keluar - potongan - potongan denda/ganti rugi
    return recalculate_detail(detail)


def update_payroll_detail_record(detail, *, base_salary, bonus, deduction):
    from app.services.tax_pph21_service import compute_payroll_detail_pph21

    detail.base_salary = float(base_salary or 0)
    detail.bonus = float(bonus or 0)
    detail.deduction = float(deduction or 0)
    if detail.payroll and detail.payroll.status == "DRAFT":
        compute_payroll_detail_pph21(detail, detail.payroll)
    recalculate_payroll_detail(detail)
    # Upah berubah -> batas potongan 50% ikut berubah.
    if detail.payroll_id:
        allocate_detail_deductions(detail, hr_settings(detail.payroll.branch_id)["max_deduction_percent"])
    _commit_or_rollback()
    return detail


def payroll_total(payroll):
    return sum(float(detail.final_salary or 0) for detail in payroll.details)
