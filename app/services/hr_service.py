from datetime import date
from calendar import monthrange

from app.extensions import db
from app.models.master import Employee, EmployeeSkill
from app.models.hr import Payroll, PayrollDetail, EmployeeSalaryHistory


# SDM2A_HR_SERVICE


def get_latest_salary(employee_id, target_date=None):
    target_date = target_date or date.today()

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

        db.session.add(PayrollDetail(
            payroll_id=payroll.id,
            employee_id=employee.id,
            base_salary=monthly_salary,
            bonus=0,
            deduction=prorata_deduction,
            final_salary=prorated_salary,
        ))

    return True, "Payroll berhasil dibuat.", payroll


def recalculate_payroll_detail(detail):
    detail.final_salary = float(detail.base_salary or 0) + float(detail.bonus or 0) - float(detail.deduction or 0)

    if detail.final_salary < 0:
        detail.final_salary = 0

    return detail


def payroll_total(payroll):
    return sum(float(detail.final_salary or 0) for detail in payroll.details)
