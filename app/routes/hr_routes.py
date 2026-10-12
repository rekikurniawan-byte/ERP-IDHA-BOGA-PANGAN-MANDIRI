import logging
from calendar import monthrange
from datetime import date
from collections import Counter

from app.utils.clock import today_wib

from flask import Blueprint, flash, redirect, render_template, request, url_for
# LOGIN_REQUIRED_IMPORT
from flask_login import current_user

from app.extensions import db, limiter
from app.models.master import Employee, EmployeeSkill
from app.models.hr import Payroll, PayrollDetail, EmployeeSalaryHistory
from app.models.accounting import Journal, Account
from app.models.finance import BankAccount
from app.services.hr_service import (
    create_employee_record,
    generate_payroll,
    payroll_total,
    toggle_employee_status,
    update_employee_record,
    update_payroll_detail_record,
)
from app.services.accounting_service import (
    create_payroll_journal_for_payroll,
    create_payroll_payment_journal_for_payroll,
)
from app.utils.decorators import role_required
from app.services.workforce_service import active_contract_for
from app.services.global_filter_service import resolve_date_filter, build_filter_bar_context, date_in_range
from app.services.atomic_transaction_service import AtomicTransactionError, atomic_business_action

logger = logging.getLogger(__name__)


# SDM2A_HR_ROUTES


def _payroll_period_label(payroll):
    return f"{int(payroll.period_month or 0):02d}-{payroll.period_year}"


def _payroll_accounting_journal(payroll):
    return Journal.query.filter_by(reference_type="PAYROLL", reference_id=payroll.id).first()


def _payroll_payment_journal(payroll):
    return Journal.query.filter_by(reference_type="PAYROLL_PAYMENT", reference_id=payroll.id).first()


def _payroll_journal_state(payroll):
    status = str(payroll.status or "").upper()
    journal = _payroll_accounting_journal(payroll)

    if status == "DRAFT":
        return {
            "label": "Belum Waktunya",
            "class": "muted",
            "icon": "bi-pencil-square",
            "helper": "Masih konsep; dijurnal setelah dikunci.",
            "journal": journal,
        }

    if status == "FINAL" and not journal:
        return {
            "label": "Belum Dijurnal",
            "class": "warning",
            "icon": "bi-exclamation-triangle",
            "helper": "Sudah dikunci, tekan Catat Hutang Gaji.",
            "journal": journal,
        }

    if status in ["POSTED", "PAID"] and journal:
        return {
            "label": "Sudah Dijurnal",
            "class": "success",
            "icon": "bi-check2-circle",
            "helper": f"Sudah masuk jurnal {journal.journal_number}.",
            "journal": journal,
        }

    if status in ["FINAL", "POSTED", "PAID"]:
        return {
            "label": "Belum Dijurnal",
            "class": "danger",
            "icon": "bi-x-octagon",
            "helper": "Status sudah lanjut, tetapi jurnal gajinya tidak ditemukan.",
            "journal": journal,
        }

    return {
        "label": "Cek Status",
        "class": "muted",
        "icon": "bi-question-circle",
        "helper": "Status penggajian tidak dikenali.",
        "journal": journal,
    }


def _payroll_payment_state(payroll):
    status = str(payroll.status or "").upper()
    journal = _payroll_payment_journal(payroll)

    if status == "PAID" and journal:
        return {
            "label": "Sudah Dibayar",
            "class": "success",
            "icon": "bi-cash-stack",
            "helper": f"Pembayaran tercatat pada jurnal {journal.journal_number}.",
            "journal": journal,
        }

    if status == "PAID" and not journal:
        return {
            "label": "Cek Pembayaran",
            "class": "danger",
            "icon": "bi-x-octagon",
            "helper": "Tercatat dibayar, tetapi jurnal pembayarannya tidak ditemukan.",
            "journal": journal,
        }

    if status == "POSTED":
        return {
            "label": "Belum Dibayar",
            "class": "warning",
            "icon": "bi-hourglass-split",
            "helper": "Hutang gaji sudah dicatat, tinggal proses pembayaran.",
            "journal": journal,
        }

    return {
        "label": "Menunggu",
        "class": "muted",
        "icon": "bi-clock",
        "helper": "Bisa dibayar setelah hutang gaji dicatat.",
        "journal": journal,
    }


def _payroll_lifecycle_steps(payroll):
    status_order = ["DRAFT", "FINAL", "POSTED", "PAID"]
    descriptions = {
        "DRAFT": "Cek potongan & karyawan keluar, sesuaikan bonus.",
        "FINAL": "Nominal dikunci, siap dicatat ke keuangan.",
        "POSTED": "Beban & hutang gaji sudah dijurnal.",
        "PAID": "Gaji dibayar dari kas/bank.",
    }
    labels = {"DRAFT": "1. Konsep", "FINAL": "2. Terkunci", "POSTED": "3. Hutang Dicatat", "PAID": "4. Dibayar"}
    status = str(payroll.status or "DRAFT").upper()
    current_index = status_order.index(status) if status in status_order else 0

    steps = []
    for index, key in enumerate(status_order):
        if index < current_index:
            state_class = "is-complete"
        elif index == current_index:
            state_class = "is-active"
        else:
            state_class = "is-pending"
        steps.append({
            "key": key,
            "label": labels[key],
            "description": descriptions[key],
            "class": state_class,
        })
    return steps


def _payroll_receipts(payroll):
    from app.models.workforce import PayrollReceipt

    return {row.payroll_detail_id: row for row in PayrollReceipt.query.filter_by(payroll_id=payroll.id).all()}


def _payroll_exit_employee_ids(payroll):
    from app.models.workforce import EmployeeExit

    detail_ids = [detail.id for detail in payroll.details]
    if not detail_ids:
        return set()
    return {row.employee_id for row in EmployeeExit.query.filter(EmployeeExit.payroll_detail_id.in_(detail_ids)).all()}


def _employee_or_404(employee_id):
    """Karyawan cabang pengguna saja; cabang lain = 404."""
    return Employee.query.filter_by(id=employee_id, branch_id=current_user.branch_id).first_or_404()


def _payroll_or_404(payroll_id):
    return Payroll.query.filter_by(id=payroll_id, branch_id=current_user.branch_id).first_or_404()


def _employee_salary_employee_ids():
    return {
        row.employee_id
        for row in EmployeeSalaryHistory.query
        .join(Employee, Employee.id == EmployeeSalaryHistory.employee_id)
        .filter(Employee.branch_id == current_user.branch_id)
        .with_entities(EmployeeSalaryHistory.employee_id)
        .distinct()
        .all()
    }


def _employee_summary(employees=None):
    employees = list(employees if employees is not None else Employee.query.filter_by(branch_id=current_user.branch_id).order_by(Employee.full_name.asc()).all())
    salary_employee_ids = _employee_salary_employee_ids()
    active = [employee for employee in employees if str(employee.status or "").upper() == "ACTIVE"]
    inactive = [employee for employee in employees if str(employee.status or "").upper() == "INACTIVE"]
    without_phone = [employee for employee in employees if not employee.phone]
    without_salary = [
        employee for employee in active
        if employee.id not in salary_employee_ids and employee.employee_type != "CADANGAN"
    ]

    return {
        "total": len(employees),
        "active": len(active),
        "inactive": len(inactive),
        "without_phone": len(without_phone),
        "without_salary": len(without_salary),
    }


def _payroll_rows(payrolls):
    rows = []
    for payroll in payrolls:
        rows.append({
            "payroll": payroll,
            "period": _payroll_period_label(payroll),
            "total": payroll_total(payroll),
            "journal_state": _payroll_journal_state(payroll),
            "payment_state": _payroll_payment_state(payroll),
        })
    return rows


hr_bp = Blueprint("hr", __name__, url_prefix="/hr")


@hr_bp.route("/")
@role_required("ADMIN", "HR")
def index():
    """Dashboard SDM lama dilebur ke Ringkasan SDM (keputusan 2026-10-11): satu pintu."""
    return redirect(url_for("workforce.index"))


@hr_bp.route("/employees")
@role_required("ADMIN", "HR")
def employees():
    from app.services.workforce_service import active_contract_for, contract_last_day

    status_filter = (request.args.get("status") or "ACTIVE").upper().strip()
    type_filter = (request.args.get("jenis") or "").upper().strip()
    search = (request.args.get("q") or "").strip()

    all_rows = Employee.query.filter_by(branch_id=current_user.branch_id).order_by(Employee.full_name.asc()).all()
    rows = list(all_rows)
    if status_filter in ["ACTIVE", "INACTIVE"]:
        rows = [employee for employee in rows if str(employee.status or "").upper() == status_filter]
    if type_filter in ["KARYAWAN", "CADANGAN"]:
        rows = [employee for employee in rows if employee.employee_type == type_filter]
    if search:
        needle = search.lower()
        rows = [employee for employee in rows if needle in (employee.full_name or "").lower() or needle in (employee.nik or "")]

    today = today_wib()
    contract_rows = []
    for employee in rows:
        contract = active_contract_for(employee.id, today)
        last_day = contract_last_day(contract) if contract else None
        contract_rows.append({
            "employee": employee,
            "contract": contract,
            "last_day": last_day,
            "days_left": (last_day - today).days if last_day else None,
        })

    return render_template(
        "hr/employees.html",
        rows=contract_rows,
        employee_summary=_employee_summary(all_rows),
        status_filter=status_filter,
        type_filter=type_filter,
        search=search,
    )


def _employee_profile_form():
    return {
        field: request.form.get(field)
        for field in ("nik", "address", "position", "employee_type", "emergency_contact_name", "emergency_contact_phone", "ptkp_status", "npwp")
    }


@hr_bp.route("/employees/create", methods=["GET", "POST"])
@role_required("ADMIN", "HR")
def create_employee():
    if request.method == "POST":
        full_name = (request.form.get("full_name") or "").strip()
        phone = (request.form.get("phone") or "").strip()
        join_date_raw = request.form.get("join_date")
        salary_raw = request.form.get("salary_amount") or "0"
        skills_raw = request.form.get("skills") or ""

        if not full_name:
            flash("Nama karyawan wajib diisi.", "danger")
            return redirect(url_for("hr.create_employee"))

        join_date = None
        if join_date_raw:
            join_date = date.fromisoformat(join_date_raw)

        employee = create_employee_record(
            branch_id=current_user.branch_id,
            full_name=full_name,
            phone=phone or None,
            join_date=join_date,
            salary_amount=salary_raw,
            skills_raw=skills_raw,
            profile=_employee_profile_form(),
        )
        if employee.employee_type == "KARYAWAN":
            flash("Karyawan ditambahkan. Langkah berikut: buat kontrak kerjanya.", "success")
        else:
            flash("Tenaga cadangan ditambahkan.", "success")
        return redirect(url_for("workforce.employee_detail", employee_id=employee.id))

    return render_template("hr/employee_form.html", employee=None)


@hr_bp.route("/employees/<int:employee_id>/edit", methods=["GET", "POST"])
@role_required("ADMIN", "HR")
def edit_employee(employee_id):
    employee = _employee_or_404(employee_id)

    if request.method == "POST":
        full_name = (request.form.get("full_name") or "").strip()
        phone = (request.form.get("phone") or "").strip()
        join_date_raw = request.form.get("join_date")
        status = request.form.get("status") or "ACTIVE"
        salary_raw = request.form.get("salary_amount")
        salary_effective_raw = request.form.get("salary_effective_date")
        skills_raw = request.form.get("skills") or ""

        if not full_name:
            flash("Nama karyawan wajib diisi.", "danger")
            return redirect(url_for("hr.edit_employee", employee_id=employee.id))

        if join_date_raw:
            join_date = date.fromisoformat(join_date_raw)
        else:
            join_date = None

        salary_effective_date = date.fromisoformat(salary_effective_raw) if salary_effective_raw else None
        contract = active_contract_for(employee.id)
        if contract:
            # Gaji karyawan berkontrak hanya berubah lewat kontrak/adendum baru.
            salary_raw = None
            if status == "INACTIVE" and employee.status == "ACTIVE":
                flash("Karyawan masih terikat kontrak. Nonaktifkan lewat Karyawan Keluar supaya hak dan potongannya dihitung.", "warning")
                return redirect(url_for("workforce.exit_create", employee_id=employee.id))
        update_employee_record(
            employee,
            full_name=full_name,
            phone=phone,
            join_date=join_date,
            status=status,
            salary_amount=salary_raw,
            salary_effective_date=salary_effective_date,
            skills_raw=skills_raw,
            profile=_employee_profile_form(),
        )
        flash("Data karyawan diperbarui.", "success")
        return redirect(url_for("workforce.employee_detail", employee_id=employee.id))

    latest_salary = (
        EmployeeSalaryHistory.query
        .filter_by(employee_id=employee.id)
        .order_by(EmployeeSalaryHistory.effective_date.desc(), EmployeeSalaryHistory.id.desc())
        .first()
    )

    skill_text = ", ".join(skill.skill_name for skill in employee.skills)

    return render_template(
        "hr/employee_form.html",
        employee=employee,
        latest_salary=latest_salary,
        skill_text=skill_text,
        contract=active_contract_for(employee.id),
    )


@hr_bp.route("/employees/<int:employee_id>/toggle", methods=["POST"])
@role_required("ADMIN", "HR")
def toggle_employee(employee_id):
    employee = _employee_or_404(employee_id)
    if employee.status == "ACTIVE" and active_contract_for(employee.id):
        flash("Karyawan masih terikat kontrak. Nonaktifkan lewat Karyawan Keluar supaya hak dan potongannya dihitung.", "warning")
        return redirect(url_for("workforce.exit_create", employee_id=employee.id))
    toggle_employee_status(employee)

    flash("Karyawan diaktifkan kembali." if employee.status == "ACTIVE" else "Karyawan dinonaktifkan.", "success")
    return redirect(url_for("workforce.employee_detail", employee_id=employee.id))


@hr_bp.route("/payrolls")
@role_required("ADMIN", "HR")
def payrolls():
    status_filter = (request.args.get("status") or "").upper().strip()
    period_year_filter = (request.args.get("period_year") or "").strip()
    period_month_filter = (request.args.get("period_month") or "").strip()

    all_rows = (
        Payroll.query
        .filter_by(branch_id=current_user.branch_id)
        .order_by(Payroll.period_year.desc(), Payroll.period_month.desc(), Payroll.id.desc())
        .all()
    )
    rows = list(all_rows)

    if status_filter in ["DRAFT", "FINAL", "POSTED", "PAID"]:
        rows = [payroll for payroll in rows if str(payroll.status or "").upper() == status_filter]

    if period_year_filter.isdigit():
        rows = [payroll for payroll in rows if payroll.period_year == int(period_year_filter)]

    if period_month_filter.isdigit():
        rows = [payroll for payroll in rows if payroll.period_month == int(period_month_filter)]

    lifecycle_counter = Counter(str(payroll.status or "").upper() for payroll in all_rows)
    payroll_summary = {
        "total_rows": len(all_rows),
        "draft": lifecycle_counter.get("DRAFT", 0),
        "final": lifecycle_counter.get("FINAL", 0),
        "posted": lifecycle_counter.get("POSTED", 0),
        "paid": lifecycle_counter.get("PAID", 0),
        "total_salary": sum(payroll_total(payroll) for payroll in all_rows),
        "filtered_salary": sum(payroll_total(payroll) for payroll in rows),
    }

    year_options = sorted({payroll.period_year for payroll in all_rows if payroll.period_year}, reverse=True)

    return render_template(
        "hr/payrolls.html",
        payrolls=rows,
        payroll_rows=_payroll_rows(rows),
        payroll_total=payroll_total,
        payroll_summary=payroll_summary,
        status_filter=status_filter,
        period_year_filter=period_year_filter,
        period_month_filter=period_month_filter,
        year_options=year_options,
    )


@hr_bp.route("/payrolls/generate", methods=["GET", "POST"])
@role_required("ADMIN", "HR")
def generate_payroll_route():
    if request.method == "POST":
        period_month = int(request.form.get("period_month") or 0)
        period_year = int(request.form.get("period_year") or 0)

        if period_month < 1 or period_month > 12:
            flash("Bulan payroll tidak valid.", "danger")
            return redirect(url_for("hr.generate_payroll_route"))

        if period_year < 2020:
            flash("Tahun payroll tidak valid.", "danger")
            return redirect(url_for("hr.generate_payroll_route"))

        try:
            with atomic_business_action(
                module="HR",
                action="PAYROLL_GENERATE",
                description=f"Generate payroll {period_month:02d}-{period_year} secara atomic.",
                reference_type="payrolls",
                user_id=current_user.id,
                branch_id=current_user.branch_id,
                metadata={"period_month": period_month, "period_year": period_year},
            ):
                ok, message, payroll = generate_payroll(
                    branch_id=current_user.branch_id,
                    period_month=period_month,
                    period_year=period_year,
                    created_by=current_user.id,
                )
                if not ok:
                    raise AtomicTransactionError(message)

            flash(message, "success")
            return redirect(url_for("hr.payroll_detail", payroll_id=payroll.id))
        except AtomicTransactionError as error:
            flash(str(error), "warning")
            return redirect(url_for("hr.payrolls"))
        except Exception as error:
            logger.exception("Suppressed unexpected exception in app/routes/hr_routes.py:474")
            flash(f"Gagal membuat penggajian: {error}", "danger")
            return redirect(url_for("hr.payrolls"))

    today = today_wib()
    active_employees = Employee.query.filter_by(branch_id=current_user.branch_id, status="ACTIVE", employee_type="KARYAWAN").order_by(Employee.full_name.asc()).all()
    salary_employee_ids = _employee_salary_employee_ids()
    generate_summary = {
        "active_employee_count": len(active_employees),
        "without_salary_count": len([employee for employee in active_employees if employee.id not in salary_employee_ids]),
        "period_label": f"{today.month:02d}-{today.year}",
    }
    return render_template("hr/payroll_generate.html", today=today, generate_summary=generate_summary)


@hr_bp.route("/payrolls/<int:payroll_id>")
@role_required("ADMIN", "HR")
def payroll_detail(payroll_id):
    payroll = _payroll_or_404(payroll_id)

    return render_template(
        "hr/payroll_detail.html",
        payroll=payroll,
        payroll_total=payroll_total(payroll),
        detail_count=len(payroll.details),
        lifecycle_steps=_payroll_lifecycle_steps(payroll),
        charge_total=sum(float(detail.charge_deduction or 0) for detail in payroll.details),
        receipts=_payroll_receipts(payroll),
        exit_employee_ids=_payroll_exit_employee_ids(payroll),
        missing_contract=[
            detail.employee for detail in payroll.details
            if detail.employee and detail.employee.employee_type == "KARYAWAN" and not active_contract_for(
                detail.employee_id, date(payroll.period_year, payroll.period_month, monthrange(payroll.period_year, payroll.period_month)[1])
            ) and detail.employee_id not in _payroll_exit_employee_ids(payroll)
        ],
        journal_state=_payroll_journal_state(payroll),
        payment_state=_payroll_payment_state(payroll),
        bank_accounts=BankAccount.query.filter_by(branch_id=payroll.branch_id, is_active=True).order_by(BankAccount.bank_name.asc()).all(),
    )


@hr_bp.route("/payrolls/<int:payroll_id>/details/<int:detail_id>/update", methods=["POST"])
@role_required("ADMIN", "HR")
def update_payroll_detail(payroll_id, detail_id):
    payroll = _payroll_or_404(payroll_id)
    detail = PayrollDetail.query.get_or_404(detail_id)

    if detail.payroll_id != payroll.id:
        flash("Detail payroll tidak sesuai.", "danger")
        return redirect(url_for("hr.payroll_detail", payroll_id=payroll.id))

    if payroll.status != "DRAFT":
        flash("Penggajian yang sudah final/dijurnal tidak bisa diubah.", "warning")
        return redirect(url_for("hr.payroll_detail", payroll_id=payroll.id))

    update_payroll_detail_record(
        detail,
        base_salary=request.form.get("base_salary"),
        bonus=request.form.get("bonus"),
        deduction=request.form.get("deduction"),
    )
    flash("Detail payroll berhasil diperbarui.", "success")
    return redirect(url_for("hr.payroll_detail", payroll_id=payroll.id))


@hr_bp.route("/payrolls/<int:payroll_id>/sync-workforce", methods=["POST"])
@role_required("ADMIN", "HR")
def sync_payroll_workforce_route(payroll_id):
    """Hitung ulang karyawan keluar + potongan denda/ganti rugi pada penggajian konsep."""
    from app.services.workforce_payroll_service import sync_payroll_workforce
    from app.services.workforce_service import WorkforceError

    payroll = Payroll.query.filter_by(id=payroll_id, branch_id=current_user.branch_id).first_or_404()
    try:
        with atomic_business_action(
            module="HR",
            action="PAYROLL_SYNC_WORKFORCE",
            description=f"Hitung ulang potongan & karyawan keluar payroll {_payroll_period_label(payroll)}.",
            reference_type="payrolls",
            reference_id=payroll.id,
            user_id=current_user.id,
            branch_id=current_user.branch_id,
            metadata={"payroll_id": payroll.id},
        ):
            result = sync_payroll_workforce(payroll)
        deducted = f"{result['deducted']:,.0f}".replace(",", ".")
        flash(f"Dihitung ulang: {result['exits']} karyawan keluar, potongan denda/ganti rugi Rp {deducted}.", "success")
    except WorkforceError as error:
        flash(str(error), "warning")
    except Exception as error:
        logger.exception("Hitung ulang payroll %s gagal", payroll.id)
        flash(f"Gagal menghitung ulang penggajian: {error}", "danger")
    return redirect(url_for("hr.payroll_detail", payroll_id=payroll.id))


@hr_bp.route("/payrolls/<int:payroll_id>/finalize", methods=["POST"])
@role_required("ADMIN", "HR")
def finalize_payroll(payroll_id):
    payroll = _payroll_or_404(payroll_id)

    if payroll.status != "DRAFT":
        flash("Penggajian sudah bukan konsep.", "warning")
        return redirect(url_for("hr.payroll_detail", payroll_id=payroll.id))

    if payroll_total(payroll) <= 0:
        flash("Total payroll masih 0, tidak bisa final.", "danger")
        return redirect(url_for("hr.payroll_detail", payroll_id=payroll.id))

    try:
        with atomic_business_action(
            module="HR",
            action="PAYROLL_FINALIZE",
            description=f"Finalize payroll {_payroll_period_label(payroll)} secara atomic.",
            reference_type="payrolls",
            reference_id=payroll.id,
            user_id=current_user.id,
            branch_id=current_user.branch_id,
            metadata={"payroll_id": payroll.id, "period": _payroll_period_label(payroll)},
        ):
            payroll.status = "FINAL"

        flash("Penggajian dikunci. Langkah berikut: Catat Hutang Gaji.", "success")
    except Exception as error:
        logger.exception("Suppressed unexpected exception in app/routes/hr_routes.py:556")
        flash(f"Gagal memfinalkan penggajian: {error}", "danger")
    return redirect(url_for("hr.payroll_detail", payroll_id=payroll.id))


@hr_bp.route("/payrolls/<int:payroll_id>/post-journal", methods=["POST"])
@limiter.limit("5 per minute", methods=["POST"])
@role_required("ADMIN", "HR")
def post_payroll_journal(payroll_id):
    payroll = _payroll_or_404(payroll_id)

    try:
        with atomic_business_action(
            module="HR",
            action="PAYROLL_POST_JOURNAL",
            description=f"Posting jurnal payroll {_payroll_period_label(payroll)} secara atomic.",
            reference_type="payrolls",
            reference_id=payroll.id,
            user_id=current_user.id,
            branch_id=current_user.branch_id,
            metadata={"payroll_id": payroll.id, "period": _payroll_period_label(payroll)},
        ):
            ok, message, journal = create_payroll_journal_for_payroll(
                payroll=payroll,
                created_by=current_user.id,
                commit=False,
            )
            if not ok:
                raise AtomicTransactionError(message)

        flash(message, "success")
    except AtomicTransactionError as error:
        flash(str(error), "warning")
    except Exception as error:
        logger.exception("Suppressed unexpected exception in app/routes/hr_routes.py:589")
        flash(f"Gagal menjurnal penggajian: {error}", "danger")

    return redirect(url_for("hr.payroll_detail", payroll_id=payroll.id))


@hr_bp.route("/payrolls/<int:payroll_id>/pay", methods=["POST"])
@limiter.limit("5 per minute", methods=["POST"])
@role_required("ADMIN", "HR")
def pay_payroll(payroll_id):
    payroll = _payroll_or_404(payroll_id)
    payment_method = request.form.get("payment_method") or "CASH"

    try:
        with atomic_business_action(
            module="HR",
            action="PAYROLL_PAY",
            description=f"Bayar payroll {_payroll_period_label(payroll)} secara atomic.",
            reference_type="payrolls",
            reference_id=payroll.id,
            user_id=current_user.id,
            branch_id=current_user.branch_id,
            metadata={"payroll_id": payroll.id, "period": _payroll_period_label(payroll), "payment_method": payment_method},
        ):
            ok, message, journal = create_payroll_payment_journal_for_payroll(
                payroll=payroll,
                payment_method=payment_method,
                bank_account_id=request.form.get("bank_account_id") or None,
                created_by=current_user.id,
                commit=False,
            )
            if not ok:
                raise AtomicTransactionError(message)

        flash(message, "success")
    except AtomicTransactionError as error:
        flash(str(error), "warning")
    except Exception as error:
        logger.exception("Suppressed unexpected exception in app/routes/hr_routes.py:625")
        flash(f"Gagal membayar gaji: {error}", "danger")

    return redirect(url_for("hr.payroll_detail", payroll_id=payroll.id))

# UX3A_PAYROLL_PAYMENT_HISTORY_ROUTE
@hr_bp.route("/payroll-payment-history")
@role_required("ADMIN", "HR")
def payroll_payment_history():
    payrolls = (
        Payroll.query
        .filter(Payroll.branch_id == current_user.branch_id, Payroll.status == "PAID")
        .order_by(Payroll.period_year.desc(), Payroll.period_month.desc(), Payroll.id.desc())
        .all()
    )

    rows = []
    total_paid = 0

    for payroll in payrolls:
        payment_journal = Journal.query.filter_by(
            reference_type="PAYROLL_PAYMENT",
            reference_id=payroll.id
        ).first()

        payment_date = None
        journal_number = "-"
        payment_method = "-"

        if payment_journal:
            payment_date = payment_journal.journal_date
            journal_number = payment_journal.journal_number

            for detail in payment_journal.details:
                if float(detail.credit or 0) > 0:
                    account = Account.query.filter_by(id=detail.account_id).first()

                    if account:
                        if account.account_code == "1001":
                            payment_method = "CASH"
                        elif account.account_code == "1002":
                            payment_method = "TRANSFER"
                        else:
                            payment_method = account.account_name
                    break

        for detail in payroll.details:
            final_salary = float(detail.final_salary or 0)
            total_paid += final_salary

            rows.append({
                "payroll": payroll,
                "detail": detail,
                "employee": detail.employee,
                "payment_date": payment_date,
                "journal_number": journal_number,
                "payment_method": payment_method,
                "final_salary": final_salary,
            })

    date_filter = resolve_date_filter(request.args, default_preset="this_month")
    method_filter = (request.args.get("method") or "").upper().strip()
    period_year_filter = (request.args.get("period_year") or "").strip()
    period_month_filter = (request.args.get("period_month") or "").strip()

    rows = [row for row in rows if date_in_range(row.get("payment_date"), date_filter)]

    if method_filter in ["CASH", "TRANSFER"]:
        rows = [row for row in rows if str(row["payment_method"] or "").upper() == method_filter]

    if period_year_filter.isdigit():
        rows = [row for row in rows if row["payroll"].period_year == int(period_year_filter)]

    if period_month_filter.isdigit():
        rows = [row for row in rows if row["payroll"].period_month == int(period_month_filter)]

    total_paid = sum(float(row["final_salary"] or 0) for row in rows)
    latest_period = _payroll_period_label(rows[0]["payroll"]) if rows else "-"
    year_options = sorted({payroll.period_year for payroll in payrolls if payroll.period_year}, reverse=True)

    return render_template(
        "hr/payroll_payment_history.html",
        rows=rows,
        total_paid=total_paid,
        history_summary={
            "row_count": len(rows),
            "total_paid": total_paid,
            "latest_period": latest_period,
        },
        method_filter=method_filter,
        period_year_filter=period_year_filter,
        period_month_filter=period_month_filter,
        year_options=year_options,
        filter_bar=build_filter_bar_context(
            state=date_filter,
            action_url=url_for("hr.payroll_payment_history"),
            reset_url=url_for("hr.payroll_payment_history"),
            title="Filter Riwayat Payroll",
            description="Custom tanggal pembayaran dan metode pembayaran gaji.",
            status_name="method",
            status_value=method_filter,
            status_options=[
                {"value": "", "label": "Semua Metode"},
                {"value": "CASH", "label": "CASH"},
                {"value": "TRANSFER", "label": "TRANSFER"},
            ],
            hidden_fields={"period_year": period_year_filter, "period_month": period_month_filter},
        ),
    )
