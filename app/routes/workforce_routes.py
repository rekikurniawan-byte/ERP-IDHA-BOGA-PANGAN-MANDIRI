"""Modul Tenaga Kerja (/sdm): kontrak kerja, apel, izin, mangkir, denda/ganti rugi, keluar, laporan.

Keputusan owner 2026-10-11. Semua mutasi lewat atomic_business_action; service tidak commit.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from flask import Blueprint, abort, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user

from app.extensions import limiter
from app.models.master import Employee
from app.models.workforce import (
    CASE_OPEN_STATUSES,
    CHARGE_ACTIVE,
    CHARGE_PROPOSED,
    CONTRACT_DRAFT,
    EXIT_SUBMITTED,
    LEAVE_APPROVED,
    LEAVE_SUBMITTED,
    EmployeeAbsenceCase,
    EmployeeCharge,
    EmployeeExit,
    EmployeeLeave,
    EmploymentContract,
)
from app.services.atomic_transaction_service import atomic_business_action
from app.services.employee_charge_service import (
    CHARGE_STATUS_LABELS,
    CHARGE_TYPE_LABELS,
    approve_charge,
    cancel_charge,
    charge_remaining,
    create_charge,
    outstanding_for,
)
from app.services.employee_exit_service import (
    EXIT_REASONS,
    EXIT_STATUS_LABELS,
    EXIT_TYPE_LABELS,
    approve_exit,
    cancel_exit,
    create_exit,
    exit_for_absconding,
    get_exit,
    settlement_preview,
)
from app.services.ops_navigation_service import uses_ops_ui
from app.services.workforce_attendance_service import (
    ATTENDANCE_LABELS,
    CASE_STATUS_LABELS,
    LEAVE_STATUS_LABELS,
    LEAVE_TYPE_LABELS,
    absent_days,
    can_approve_leave,
    create_leave,
    decide_leave,
    deemed_resign_ready,
    issue_summons,
    leave_overdue_list,
    outstanding_fine_estimate,
    return_from_case,
    roll_call,
    save_roll_call,
    staffing_forecast,
)
from app.services.workforce_report_service import workforce_report
from app.services.workforce_service import (
    CONTRACT_STATUS_LABELS,
    CONTRACT_TYPE_LABELS,
    EMPLOYEE_TYPE_LABELS,
    ContractInput,
    WorkforceError,
    active_contract_for,
    attachment_data_url,
    cancel_contract,
    contract_alerts,
    contract_body_html,
    contract_document_context,
    contract_last_day,
    create_contract,
    disnaker_due_date,
    get_contract,
    get_employee,
    hr_settings,
    record_disnaker,
    sign_contract_employee,
    sign_contract_employer,
)
from app.utils.clock import today_wib
from app.utils.decorators import role_required

logger = logging.getLogger(__name__)

workforce_bp = Blueprint("workforce", __name__, url_prefix="/sdm")

HR_ROLES = ("ADMIN", "HR")
FIELD_ROLES = ("ADMIN", "HR", "ADMIN_OPERASIONAL")


@workforce_bp.context_processor
def _workforce_labels():
    return {
        "wf_labels": {
            "contract_status": CONTRACT_STATUS_LABELS,
            "contract_type": CONTRACT_TYPE_LABELS,
            "employee_type": EMPLOYEE_TYPE_LABELS,
            "attendance": ATTENDANCE_LABELS,
            "leave_type": LEAVE_TYPE_LABELS,
            "leave_status": LEAVE_STATUS_LABELS,
            "case_status": CASE_STATUS_LABELS,
            "charge_type": CHARGE_TYPE_LABELS,
            "charge_status": CHARGE_STATUS_LABELS,
            "exit_type": EXIT_TYPE_LABELS,
            "exit_status": EXIT_STATUS_LABELS,
            "exit_reason": EXIT_REASONS,
        }
    }


def _branch_id() -> int:
    return current_user.branch_id


def _date(value, default=None):
    try:
        return date.fromisoformat(str(value or "").strip())
    except ValueError:
        return default


def _required_date(name: str, label: str) -> date:
    value = _date(request.form.get(name))
    if not value:
        raise WorkforceError(f"{label} wajib diisi dengan tanggal yang benar.")
    return value


def _decimal(value, default=None):
    raw = str(value or "").strip()
    if raw == "":
        return default
    try:
        return Decimal(raw)
    except InvalidOperation as error:
        raise WorkforceError("Nominal harus berupa angka.") from error


def _next_url(fallback: str) -> str:
    """Kembali ke halaman asal, hanya alamat di dalam aplikasi ini."""
    target = str(request.form.get("next") or "")
    if target.startswith("/") and not target.startswith("//"):
        return target
    return fallback


def _int(value, default=0):
    try:
        return int(str(value or "").strip())
    except ValueError:
        return default


def _run(action: str, description: str, fn, *, reference_type=None, reference_id=None):
    """Jalankan satu aksi bisnis atomik. Mengembalikan (berhasil, hasil)."""
    try:
        with atomic_business_action(
            module="HR",
            action=action,
            description=description,
            reference_type=reference_type,
            reference_id=reference_id,
            user_id=current_user.id,
            branch_id=_branch_id(),
        ) as tx:
            result = fn(tx)
        return True, result
    except WorkforceError as error:
        flash(str(error), "warning")
    except Exception as error:
        logger.exception("Aksi SDM %s gagal", action)
        flash(f"Gagal menyimpan: {error}", "danger")
    return False, None


def _ops_or(desktop_template: str, ops_template: str) -> str:
    return ops_template if uses_ops_ui(current_user) else desktop_template


# ---------------------------------------------------------------- Ringkasan


@workforce_bp.route("/")
@role_required(*HR_ROLES)
def index():
    branch_id = _branch_id()
    alerts = contract_alerts(branch_id)
    pending_leaves = EmployeeLeave.query.filter_by(branch_id=branch_id, status=LEAVE_SUBMITTED).order_by(EmployeeLeave.start_date.asc()).all()
    open_cases = (
        EmployeeAbsenceCase.query
        .filter(EmployeeAbsenceCase.branch_id == branch_id, EmployeeAbsenceCase.status.in_(CASE_OPEN_STATUSES))
        .order_by(EmployeeAbsenceCase.start_date.asc())
        .all()
    )
    proposed = EmployeeCharge.query.filter_by(branch_id=branch_id, status=CHARGE_PROPOSED).order_by(EmployeeCharge.id.asc()).all()
    pending_exits = EmployeeExit.query.filter_by(branch_id=branch_id, status=EXIT_SUBMITTED).all()
    active_charges = EmployeeCharge.query.filter_by(branch_id=branch_id, status=CHARGE_ACTIVE).all()
    from app.services.tax_service import get_tax_settings

    unconfigured_ptkp = [] if not get_tax_settings(branch_id).get("pph21_enabled") else (
        Employee.query.filter(
            Employee.branch_id == branch_id,
            Employee.status == "ACTIVE",
            Employee.employee_type == "KARYAWAN",
            (Employee.ptkp_status.is_(None) | (Employee.ptkp_status == "")),
        )
        .order_by(Employee.full_name.asc())
        .all()
    )
    return render_template(
        "workforce/index.html",
        alerts=alerts,
        pending_leaves=pending_leaves,
        overdue_leaves=leave_overdue_list(branch_id),
        open_cases=[{"case": case, "days": absent_days(case)} for case in open_cases],
        proposed=proposed,
        pending_exits=pending_exits,
        receivable_total=sum((charge_remaining(c) for c in active_charges), Decimal("0")),
        staffing=staffing_forecast(branch_id),
        today_roll=roll_call(branch_id, today_wib()),
        settings=hr_settings(branch_id),
        payroll=_payroll_overview(branch_id),
        approved_exit_ids=[row.employee_id for row in EmployeeExit.query.filter_by(branch_id=branch_id, status="DISETUJUI").all()],
        unconfigured_ptkp=unconfigured_ptkp,
    )


def _payroll_overview(branch_id: int) -> dict:
    """Status penggajian untuk Ringkasan SDM (dulu dashboard SDM terpisah)."""
    from app.models.hr import Payroll
    from app.services.hr_service import payroll_total

    today = today_wib()
    payrolls = (
        Payroll.query.filter_by(branch_id=branch_id)
        .order_by(Payroll.period_year.desc(), Payroll.period_month.desc())
        .limit(12)
        .all()
    )
    current = next((p for p in payrolls if p.period_month == today.month and p.period_year == today.year), None)
    previous = next((p for p in payrolls if p is not current), None)
    return {
        "current": current,
        "current_total": payroll_total(current) if current else Decimal("0"),
        "previous": previous,
        "previous_total": payroll_total(previous) if previous else Decimal("0"),
        "waiting_journal": sum(1 for p in payrolls if p.status == "FINAL"),
        "waiting_payment": sum(1 for p in payrolls if p.status == "POSTED"),
        "period_label": f"{today.month:02d}-{today.year}",
    }


@workforce_bp.route("/karyawan/<int:employee_id>")
@role_required(*HR_ROLES)
def employee_detail(employee_id):
    try:
        employee = get_employee(employee_id, _branch_id())
    except WorkforceError:
        abort(404)
    since = today_wib() - timedelta(days=30)
    from app.models.hr import EmployeeAttendance

    attendance = (
        EmployeeAttendance.query
        .filter(EmployeeAttendance.employee_id == employee.id, EmployeeAttendance.attendance_date >= since)
        .order_by(EmployeeAttendance.attendance_date.desc())
        .all()
    )
    counts = {status: 0 for status in ATTENDANCE_LABELS}
    for row in attendance:
        counts[row.status] = counts.get(row.status, 0) + 1
    return render_template(
        "workforce/employee_detail.html",
        employee=employee,
        contract=active_contract_for(employee.id),
        can_renew=_can_renew(employee),
        contracts=EmploymentContract.query.filter_by(employee_id=employee.id).order_by(EmploymentContract.start_date.desc()).all(),
        attendance=attendance[:31],
        attendance_counts=counts,
        leaves=EmployeeLeave.query.filter_by(employee_id=employee.id).order_by(EmployeeLeave.start_date.desc()).limit(20).all(),
        cases=EmployeeAbsenceCase.query.filter_by(employee_id=employee.id).order_by(EmployeeAbsenceCase.start_date.desc()).all(),
        charges=EmployeeCharge.query.filter_by(employee_id=employee.id).order_by(EmployeeCharge.id.desc()).all(),
        exits=EmployeeExit.query.filter_by(employee_id=employee.id).order_by(EmployeeExit.id.desc()).all(),
        payslips=_employee_payslips(employee.id),
        outstanding=outstanding_for(employee.id),
        annual_leave=_annual_leave(employee),
        charge_remaining=charge_remaining,
    )


def _employee_payslips(employee_id: int) -> list[dict]:
    """6 slip gaji terakhir karyawan untuk profil."""
    from app.models.hr import Payroll, PayrollDetail
    from app.models.workforce import PayrollReceipt

    details = (
        PayrollDetail.query.join(Payroll, Payroll.id == PayrollDetail.payroll_id)
        .filter(PayrollDetail.employee_id == employee_id)
        .order_by(Payroll.period_year.desc(), Payroll.period_month.desc())
        .limit(6)
        .all()
    )
    receipts = {
        row.payroll_detail_id: row
        for row in PayrollReceipt.query.filter(PayrollReceipt.payroll_detail_id.in_([d.id for d in details] or [0])).all()
    }
    return [{"detail": d, "payroll": d.payroll, "receipt": receipts.get(d.id)} for d in details]


def _annual_leave(employee):
    from app.services.workforce_payroll_service import annual_leave_status

    return annual_leave_status(employee, today_wib())


def _can_renew(employee) -> bool:
    """Kontrak baru hanya bila belum ada kontrak berlaku, atau yang berlaku habis <= 30 hari lagi."""
    if employee.status != "ACTIVE" or employee.employee_type != "KARYAWAN":
        return False
    pending = EmploymentContract.query.filter(
        EmploymentContract.employee_id == employee.id,
        EmploymentContract.status.in_(("DRAFT", "MENUNGGU_TTD_PERUSAHAAN")),
    ).first()
    if pending:
        return False
    contract = active_contract_for(employee.id)
    if not contract:
        return True
    last_day = contract_last_day(contract)
    return bool(last_day and (last_day - today_wib()).days <= 30)


# ---------------------------------------------------------------- Kontrak


@workforce_bp.route("/kontrak")
@role_required(*HR_ROLES)
def contracts():
    status = (request.args.get("status") or "").upper()
    query = EmploymentContract.query.filter_by(branch_id=_branch_id())
    if status:
        query = query.filter(EmploymentContract.status == status)
    rows = query.order_by(EmploymentContract.id.desc()).all()
    return render_template(
        "workforce/contracts.html",
        contracts=rows,
        status_filter=status,
        alerts=contract_alerts(_branch_id()),
        contract_last_day=contract_last_day,
        disnaker_due_date=disnaker_due_date,
    )


@workforce_bp.route("/kontrak/baru", methods=["GET", "POST"])
@role_required(*HR_ROLES)
def contract_create():
    branch_id = _branch_id()
    employees = (
        Employee.query
        .filter_by(branch_id=branch_id, status="ACTIVE", employee_type="KARYAWAN")
        .order_by(Employee.full_name.asc())
        .all()
    )
    settings = hr_settings(branch_id)
    if request.method == "POST":
        try:
            employee = get_employee(_int(request.form.get("employee_id")), branch_id)
            data = ContractInput(
                contract_type=request.form.get("contract_type"),
                position=request.form.get("position"),
                start_date=_required_date("start_date", "Tanggal mulai"),
                end_date=_date(request.form.get("end_date")),
                probation_months=_int(request.form.get("probation_months")),
                monthly_salary=_decimal(request.form.get("monthly_salary"), Decimal("0")),
                work_location=request.form.get("work_location"),
                notes=request.form.get("notes"),
                notice_days=_int(request.form.get("notice_days"), settings["notice_days"]),
                fine_absent_per_day=_decimal(request.form.get("fine_absent_per_day")),
                fine_leave_site=_decimal(request.form.get("fine_leave_site")),
                fine_late_return_per_day=_decimal(request.form.get("fine_late_return_per_day")),
                fine_short_notice=_decimal(request.form.get("fine_short_notice")),
            )
        except WorkforceError as error:
            flash(str(error), "warning")
            return render_template("workforce/contract_form.html", employees=employees, settings=settings, form=request.form)
        ok, contract = _run(
            "EMPLOYMENT_CONTRACT_CREATE",
            f"Buat konsep kontrak kerja {employee.full_name}",
            lambda tx: create_contract(employee, data, current_user.id),
            reference_type="employment_contracts",
        )
        if ok:
            flash(f"Konsep kontrak {contract.contract_number} dibuat. Minta karyawan membaca dan menandatangani.", "success")
            return redirect(url_for("workforce.contract_detail", contract_id=contract.id))
        return render_template("workforce/contract_form.html", employees=employees, settings=settings, form=request.form)

    preset = {"employee_id": request.args.get("employee_id", "")}
    return render_template("workforce/contract_form.html", employees=employees, settings=settings, form=preset)


def _contract_or_404(contract_id: int) -> EmploymentContract:
    try:
        return get_contract(contract_id, _branch_id())
    except WorkforceError:
        abort(404)


@workforce_bp.route("/kontrak/<int:contract_id>")
@role_required(*HR_ROLES)
def contract_detail(contract_id):
    contract = _contract_or_404(contract_id)
    return render_template(
        "workforce/contract_detail.html",
        contract=contract,
        body_html=contract_body_html(contract),
        disnaker_due=disnaker_due_date(contract),
        last_day=contract_last_day(contract),
        employee_signature=attachment_data_url(contract.employee_signature_attachment_id),
        employer_signature=attachment_data_url(contract.employer_signature_attachment_id),
        has_ktp=bool(contract.ktp_attachment_id),
        today=today_wib(),
    )


@workforce_bp.route("/kontrak/<int:contract_id>/ktp")
@role_required(*HR_ROLES)
def contract_ktp(contract_id):
    """Foto KTP hanya untuk ADMIN/OWNER, tidak pernah lewat URL publik."""
    from app.services.digital_attachment_service import get_attachment_file_path, get_attachment_or_none

    contract = _contract_or_404(contract_id)
    attachment = get_attachment_or_none(contract.ktp_attachment_id, branch_id=contract.branch_id) if contract.ktp_attachment_id else None
    if not attachment:
        abort(404)
    try:
        path = get_attachment_file_path(attachment)
    except FileNotFoundError:
        abort(404)
    return send_file(path, mimetype=attachment.mime_type, download_name=attachment.original_filename)


@workforce_bp.route("/kontrak/<int:contract_id>/ttd-karyawan", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
@role_required(*HR_ROLES)
def contract_sign_employee(contract_id):
    contract = _contract_or_404(contract_id)
    if request.method == "POST":
        def _sign(tx):
            attachments = sign_contract_employee(
                contract,
                typed_name=request.form.get("typed_name"),
                agreed=request.form.get("agree") == "1",
                signature_data=request.form.get("signature_data"),
                ktp_file=request.files.get("ktp_photo"),
                user_id=current_user.id,
            )
            for attachment in attachments:
                tx.track_attachment(attachment)
            return attachments

        ok, _ = _run(
            "EMPLOYMENT_CONTRACT_SIGN_EMPLOYEE",
            f"TTD karyawan kontrak {contract.contract_number}",
            _sign,
            reference_type="employment_contracts",
            reference_id=contract.id,
        )
        if ok:
            flash("Tanda tangan karyawan tersimpan. Isi kontrak sudah dikunci; tinggal tanda tangan owner.", "success")
            return redirect(url_for("workforce.contract_detail", contract_id=contract.id))
    if contract.status != CONTRACT_DRAFT:
        flash("Kontrak ini sudah ditandatangani karyawan.", "info")
        return redirect(url_for("workforce.contract_detail", contract_id=contract.id))
    return render_template("workforce/contract_sign.html", contract=contract, body_html=contract_body_html(contract))


@workforce_bp.route("/kontrak/<int:contract_id>/ttd-perusahaan", methods=["POST"])
@limiter.limit("10 per minute", methods=["POST"])
@role_required("OWNER")
def contract_sign_employer(contract_id):
    contract = _contract_or_404(contract_id)

    def _sign(tx):
        attachments = sign_contract_employer(contract, signature_data=request.form.get("signature_data"), user=current_user)
        for attachment in attachments:
            tx.track_attachment(attachment)
        return attachments

    ok, _ = _run(
        "EMPLOYMENT_CONTRACT_SIGN_EMPLOYER",
        f"TTD perusahaan kontrak {contract.contract_number}",
        _sign,
        reference_type="employment_contracts",
        reference_id=contract.id,
    )
    if ok:
        message = "Kontrak aktif."
        if contract.contract_type == "PKWT":
            message += f" Catatkan ke Disnaker paling lambat {disnaker_due_date(contract):%d-%m-%Y}."
        flash(message, "success")
    return redirect(url_for("workforce.contract_detail", contract_id=contract.id))


@workforce_bp.route("/kontrak/<int:contract_id>/disnaker", methods=["POST"])
@role_required(*HR_ROLES)
def contract_disnaker(contract_id):
    contract = _contract_or_404(contract_id)
    ok, _ = _run(
        "EMPLOYMENT_CONTRACT_DISNAKER",
        f"Catat pencatatan Disnaker {contract.contract_number}",
        lambda tx: record_disnaker(
            contract,
            registered_at=_date(request.form.get("registered_at"), today_wib()),
            reference=request.form.get("reference"),
        ),
        reference_type="employment_contracts",
        reference_id=contract.id,
    )
    if ok:
        flash("Pencatatan PKWT ke Disnaker tersimpan.", "success")
    return redirect(url_for("workforce.contract_detail", contract_id=contract.id))


@workforce_bp.route("/kontrak/<int:contract_id>/batal", methods=["POST"])
@role_required(*HR_ROLES)
def contract_cancel(contract_id):
    contract = _contract_or_404(contract_id)
    ok, _ = _run(
        "EMPLOYMENT_CONTRACT_CANCEL",
        f"Batalkan konsep kontrak {contract.contract_number}",
        lambda tx: cancel_contract(contract),
        reference_type="employment_contracts",
        reference_id=contract.id,
    )
    if ok:
        flash("Konsep kontrak dibatalkan.", "success")
    return redirect(url_for("workforce.contract_detail", contract_id=contract.id))


@workforce_bp.route("/kontrak/<int:contract_id>/cetak")
@role_required(*HR_ROLES)
def contract_print(contract_id):
    contract = _contract_or_404(contract_id)
    return render_template(
        "workforce/contract_print.html",
        body_html=contract_body_html(contract),
        employee_signature=attachment_data_url(contract.employee_signature_attachment_id),
        employer_signature=attachment_data_url(contract.employer_signature_attachment_id),
        **contract_document_context(contract),
    )


# ---------------------------------------------------------------- Apel & izin


@workforce_bp.route("/apel", methods=["GET", "POST"])
@role_required(*FIELD_ROLES)
def attendance():
    branch_id = _branch_id()
    today = today_wib()
    day = _date(request.values.get("tanggal"), today)
    if request.method == "POST":
        statuses = {
            key.split("_", 1)[1]: value
            for key, value in request.form.items()
            if key.startswith("status_")
        }
        notes = {
            key.split("_", 1)[1]: value
            for key, value in request.form.items()
            if key.startswith("note_")
        }
        medical = [key.split("_", 1)[1] for key in request.form if key.startswith("doctor_")]
        ok, summary = _run(
            "EMPLOYEE_ROLL_CALL",
            f"Simpan apel {day:%d-%m-%Y}",
            lambda tx: save_roll_call(branch_id, day, statuses, notes, current_user.id, medical=medical),
            reference_type="employee_attendance",
        )
        if ok:
            parts = [f"Apel {day:%d-%m-%Y} tersimpan ({summary['saved']} orang)."]
            if summary["opened"]:
                names = ", ".join(case.employee.full_name for case in summary["opened"])
                parts.append(f"Tanpa keterangan, owner sudah diberi tahu: {names}.")
            if summary["returned"]:
                parts.append(f"Kembali bekerja: {', '.join(e.full_name for e in summary['returned'])}.")
            if summary["proposals"]:
                parts.append(f"{summary['proposals']} usulan denda menunggu keputusan owner.")
            flash(" ".join(parts), "success")
        return redirect(url_for("workforce.attendance", tanggal=day.isoformat()))

    return render_template(
        _ops_or("workforce/attendance.html", "ops/apel.html"),
        roll=roll_call(branch_id, day),
        day=day,
        today=today,
        min_day=today - timedelta(days=7),
        staffing=staffing_forecast(branch_id),
        overdue_leaves=leave_overdue_list(branch_id),
    )


@workforce_bp.route("/izin")
@role_required(*HR_ROLES)
def leaves():
    status = (request.args.get("status") or "").upper()
    query = EmployeeLeave.query.filter_by(branch_id=_branch_id())
    if status:
        query = query.filter(EmployeeLeave.status == status)
    return render_template(
        "workforce/leaves.html",
        leaves=query.order_by(EmployeeLeave.start_date.desc()).limit(300).all(),
        status_filter=status,
        today=today_wib(),
        can_decide=can_approve_leave(current_user),
    )


@workforce_bp.route("/izin/baru", methods=["GET", "POST"])
@role_required(*FIELD_ROLES)
def leave_create():
    branch_id = _branch_id()
    employees = Employee.query.filter_by(branch_id=branch_id, status="ACTIVE").order_by(Employee.full_name.asc()).all()
    template = _ops_or("workforce/leave_form.html", "ops/leave_form.html")
    if request.method == "POST":
        try:
            employee = get_employee(_int(request.form.get("employee_id")), branch_id)
            start = _required_date("start_date", "Tanggal berangkat")
            back = _required_date("expected_return_date", "Tanggal kembali")
        except WorkforceError as error:
            flash(str(error), "warning")
            return render_template(template, employees=employees, form=request.form, today=today_wib())
        ok, leave = _run(
            "EMPLOYEE_LEAVE_CREATE",
            f"Catat izin {employee.full_name}",
            lambda tx: create_leave(
                employee,
                leave_type=request.form.get("leave_type"),
                start_date=start,
                expected_return_date=back,
                reason=request.form.get("reason"),
                user=current_user,
            ),
            reference_type="employee_leaves",
        )
        if ok:
            if leave.leave_type == "CUTI":
                from app.services.workforce_payroll_service import annual_leave_status

                quota = annual_leave_status(employee, start)
                days = (back - start).days + 1
                if not quota["eligible"]:
                    flash(f"{employee.full_name} belum 12 bulan bekerja, jadi belum berhak cuti tahunan: {days} hari cuti ini dipotong dari gaji.", "warning")
                elif days > quota["remaining"]:
                    flash(f"Sisa cuti tahunan {employee.full_name} {quota['remaining']} hari; {days - quota['remaining']} hari sisanya dipotong dari gaji.", "warning")
                else:
                    flash(f"Cuti masih dalam jatah tahunan (sisa {quota['remaining']} hari), tetap dibayar.", "info")
            if leave.status == LEAVE_APPROVED:
                flash(f"Izin {employee.full_name} dicatat dan disetujui. Wajib kembali {back:%d-%m-%Y}.", "success")
            else:
                flash(f"Izin {employee.full_name} dicatat dan menunggu persetujuan admin/owner.", "success")
            return redirect(url_for("workforce.attendance") if uses_ops_ui(current_user) else url_for("workforce.leaves"))
        return render_template(template, employees=employees, form=request.form, today=today_wib())
    preset = {"employee_id": request.args.get("employee_id", ""), "start_date": today_wib().isoformat()}
    return render_template(template, employees=employees, form=preset, today=today_wib())


@workforce_bp.route("/izin/<int:leave_id>/putuskan", methods=["POST"])
@role_required(*HR_ROLES)
def leave_decide(leave_id):
    leave = EmployeeLeave.query.filter_by(id=leave_id, branch_id=_branch_id()).first_or_404()
    approve = request.form.get("decision") == "approve"
    ok, _ = _run(
        "EMPLOYEE_LEAVE_DECIDE",
        f"Putuskan izin {leave.employee.full_name}",
        lambda tx: decide_leave(leave, approve=approve, user=current_user, notes=request.form.get("notes")),
        reference_type="employee_leaves",
        reference_id=leave.id,
    )
    if ok:
        flash("Izin disetujui." if approve else "Izin ditolak.", "success")
    return redirect(url_for("workforce.leaves"))


# ---------------------------------------------------------------- Mangkir


@workforce_bp.route("/mangkir")
@role_required(*HR_ROLES)
def cases():
    rows = (
        EmployeeAbsenceCase.query
        .filter_by(branch_id=_branch_id())
        .order_by(EmployeeAbsenceCase.start_date.desc())
        .limit(300)
        .all()
    )
    return render_template(
        "workforce/cases.html",
        cases=[{"case": case, "days": absent_days(case), "open": case.status in CASE_OPEN_STATUSES} for case in rows],
    )


def _case_or_404(case_id: int) -> EmployeeAbsenceCase:
    return EmployeeAbsenceCase.query.filter_by(id=case_id, branch_id=_branch_id()).first_or_404()


@workforce_bp.route("/mangkir/<int:case_id>")
@role_required(*HR_ROLES)
def case_detail(case_id):
    case = _case_or_404(case_id)
    ready, ready_message = deemed_resign_ready(case)
    return render_template(
        "workforce/case_detail.html",
        case=case,
        days=absent_days(case),
        is_open=case.status in CASE_OPEN_STATUSES,
        ready=ready,
        ready_message=ready_message,
        fine_estimate=outstanding_fine_estimate(case),
        settings=hr_settings(case.branch_id),
        today=today_wib(),
    )


@workforce_bp.route("/mangkir/<int:case_id>/panggilan/<int:number>", methods=["POST"])
@role_required(*HR_ROLES)
def case_summons(case_id, number):
    case = _case_or_404(case_id)
    ok, _ = _run(
        "EMPLOYEE_ABSENCE_SUMMONS",
        f"Terbitkan surat panggilan {number} {case.employee.full_name}",
        lambda tx: issue_summons(case, number),
        reference_type="employee_absence_cases",
        reference_id=case.id,
    )
    if ok:
        flash(f"Surat panggilan {number} diterbitkan. Cetak lalu kirim ke alamat/HP karyawan dan simpan buktinya.", "success")
    return redirect(url_for("workforce.case_detail", case_id=case.id))


@workforce_bp.route("/mangkir/<int:case_id>/panggilan/<int:number>/cetak")
@role_required(*HR_ROLES)
def case_summons_print(case_id, number):
    case = _case_or_404(case_id)
    summons_date = case.summons_1_date if number == 1 else case.summons_2_date
    summons_number = case.summons_1_number if number == 1 else case.summons_2_number
    if number not in (1, 2) or not summons_date:
        abort(404)
    settings = hr_settings(case.branch_id)
    return render_template(
        "workforce/summons_print.html",
        case=case,
        number=number,
        summons_date=summons_date,
        summons_number=summons_number,
        report_by=summons_date + timedelta(days=3),
        company=settings["company"],
        settings=settings,
        days=absent_days(case, until=summons_date),
    )


@workforce_bp.route("/mangkir/<int:case_id>/kembali", methods=["POST"])
@role_required(*HR_ROLES)
def case_return(case_id):
    case = _case_or_404(case_id)
    day = _date(request.form.get("returned_date"), today_wib())

    def _return(tx):
        if day <= case.start_date:
            raise WorkforceError("Bila karyawan ada lagi di hari yang sama, ubah apel hari itu menjadi Hadir.")
        return save_roll_call(case.branch_id, day, {str(case.employee_id): "HADIR"}, {}, current_user.id)

    ok, summary = _run(
        "EMPLOYEE_ABSENCE_RETURN",
        f"Tandai {case.employee.full_name} kembali",
        _return,
        reference_type="employee_absence_cases",
        reference_id=case.id,
    )
    if ok:
        flash(f"{case.employee.full_name} dicatat kembali {day:%d-%m-%Y}. Usulan denda menunggu keputusan owner.", "success")
    return redirect(url_for("workforce.case_detail", case_id=case.id))


@workforce_bp.route("/mangkir/<int:case_id>/mengundurkan-diri", methods=["POST"])
@role_required("OWNER")
def case_deem_resigned(case_id):
    case = _case_or_404(case_id)
    ok, row = _run(
        "EMPLOYEE_DEEMED_RESIGNED",
        f"Kualifikasikan {case.employee.full_name} mengundurkan diri",
        lambda tx: exit_for_absconding(case, current_user),
        reference_type="employee_absence_cases",
        reference_id=case.id,
    )
    if ok:
        flash("Karyawan dikualifikasikan mengundurkan diri. Denda/ganti rugi sudah tercatat; penyelesaian ikut penggajian berikutnya.", "success")
        return redirect(url_for("workforce.exit_detail", exit_id=row.id))
    return redirect(url_for("workforce.case_detail", case_id=case.id))


# ---------------------------------------------------------------- Denda & ganti rugi


@workforce_bp.route("/denda", methods=["GET", "POST"])
@role_required(*HR_ROLES)
def charges():
    branch_id = _branch_id()
    if request.method == "POST":
        try:
            employee = get_employee(_int(request.form.get("employee_id")), branch_id)
            amount = _decimal(request.form.get("amount"), Decimal("0"))
        except WorkforceError as error:
            flash(str(error), "warning")
            return redirect(url_for("workforce.charges"))
        ok, _ = _run(
            "EMPLOYEE_CHARGE_CREATE",
            f"Usulkan denda/ganti rugi {employee.full_name}",
            lambda tx: create_charge(
                employee=employee,
                charge_type=request.form.get("charge_type"),
                amount=amount,
                clause=request.form.get("clause"),
                description=request.form.get("description"),
                created_by=current_user.id,
            ),
            reference_type="employee_charges",
        )
        if ok:
            flash("Usulan tersimpan dan menunggu keputusan owner.", "success")
        return redirect(url_for("workforce.charges"))

    status = (request.args.get("status") or "").upper()
    query = EmployeeCharge.query.filter_by(branch_id=branch_id)
    if status:
        query = query.filter(EmployeeCharge.status == status)
    rows = query.order_by(EmployeeCharge.id.desc()).limit(300).all()
    return render_template(
        "workforce/charges.html",
        charges=rows,
        status_filter=status,
        employees=Employee.query.filter_by(branch_id=branch_id).order_by(Employee.full_name.asc()).all(),
        charge_remaining=charge_remaining,
        is_owner=str(current_user.role).upper() == "OWNER",
    )


def _charge_or_404(charge_id: int) -> EmployeeCharge:
    return EmployeeCharge.query.filter_by(id=charge_id, branch_id=_branch_id()).first_or_404()


@workforce_bp.route("/denda/<int:charge_id>/setujui", methods=["POST"])
@role_required("OWNER")
def charge_approve(charge_id):
    charge = _charge_or_404(charge_id)
    ok, _ = _run(
        "EMPLOYEE_CHARGE_APPROVE",
        f"Setujui {CHARGE_TYPE_LABELS[charge.charge_type].lower()} {charge.employee.full_name}",
        lambda tx: approve_charge(charge, current_user, amount=_decimal(request.form.get("amount"))),
        reference_type="employee_charges",
        reference_id=charge.id,
    )
    if ok:
        flash("Disetujui dan dijurnal (Piutang Karyawan / Pendapatan Lain-lain). Dipotong otomatis di penggajian.", "success")
    return redirect(_next_url(url_for("workforce.charges")))


@workforce_bp.route("/denda/<int:charge_id>/batal", methods=["POST"])
@role_required("OWNER")
def charge_cancel(charge_id):
    charge = _charge_or_404(charge_id)
    ok, _ = _run(
        "EMPLOYEE_CHARGE_CANCEL",
        f"Batalkan {CHARGE_TYPE_LABELS[charge.charge_type].lower()} {charge.employee.full_name}",
        lambda tx: cancel_charge(charge, current_user, request.form.get("reason")),
        reference_type="employee_charges",
        reference_id=charge.id,
    )
    if ok:
        flash("Dibatalkan.", "success")
    return redirect(_next_url(url_for("workforce.charges")))


# ---------------------------------------------------------------- Keluar


@workforce_bp.route("/keluar")
@role_required(*HR_ROLES)
def exits():
    rows = EmployeeExit.query.filter_by(branch_id=_branch_id()).order_by(EmployeeExit.id.desc()).limit(300).all()
    return render_template("workforce/exits.html", exits=rows)


@workforce_bp.route("/keluar/baru", methods=["GET", "POST"])
@role_required(*HR_ROLES)
def exit_create():
    branch_id = _branch_id()
    employees = Employee.query.filter_by(branch_id=branch_id, status="ACTIVE").order_by(Employee.full_name.asc()).all()
    settings = hr_settings(branch_id)
    if request.method == "POST":
        try:
            employee = get_employee(_int(request.form.get("employee_id")), branch_id)
            notice = _required_date("notice_date", "Tanggal pengajuan")
            effective = _required_date("effective_date", "Tanggal keluar")
        except WorkforceError as error:
            flash(str(error), "warning")
            return render_template("workforce/exit_form.html", employees=employees, form=request.form, settings=settings, today=today_wib())
        ok, row = _run(
            "EMPLOYEE_EXIT_CREATE",
            f"Ajukan keluar {employee.full_name}",
            lambda tx: create_exit(
                employee,
                exit_type=request.form.get("exit_type"),
                reason_code=request.form.get("reason_code"),
                notice_date=notice,
                effective_date=effective,
                user_id=current_user.id,
                reason_notes=request.form.get("reason_notes"),
                handover_notes=request.form.get("handover_notes"),
            ),
            reference_type="employee_exits",
        )
        if ok:
            flash("Pengajuan keluar tersimpan. Periksa hitungan penyelesaian lalu setujui.", "success")
            return redirect(url_for("workforce.exit_detail", exit_id=row.id))
        return render_template("workforce/exit_form.html", employees=employees, form=request.form, settings=settings, today=today_wib())
    today = today_wib()
    preset = {
        "employee_id": request.args.get("employee_id", ""),
        "notice_date": today.isoformat(),
        "effective_date": (today + timedelta(days=settings["notice_days"])).isoformat(),
    }
    return render_template("workforce/exit_form.html", employees=employees, form=preset, settings=settings, today=today)


def _exit_or_404(exit_id: int) -> EmployeeExit:
    try:
        return get_exit(exit_id, _branch_id())
    except WorkforceError:
        abort(404)


@workforce_bp.route("/keluar/<int:exit_id>")
@role_required(*HR_ROLES)
def exit_detail(exit_id):
    row = _exit_or_404(exit_id)
    charges_rows = EmployeeCharge.query.filter_by(employee_id=row.employee_id).order_by(EmployeeCharge.id.desc()).all()
    return render_template(
        "workforce/exit_detail.html",
        row=row,
        preview=settlement_preview(row),
        charges=charges_rows,
        charge_remaining=charge_remaining,
        is_owner=str(current_user.role).upper() == "OWNER",
    )


@workforce_bp.route("/keluar/<int:exit_id>/setujui", methods=["POST"])
@role_required(*HR_ROLES)
def exit_approve(exit_id):
    row = _exit_or_404(exit_id)
    ok, _ = _run(
        "EMPLOYEE_EXIT_APPROVE",
        f"Setujui keluar {row.employee.full_name}",
        lambda tx: approve_exit(row, current_user, handover_done=request.form.get("handover_done") == "1"),
        reference_type="employee_exits",
        reference_id=row.id,
    )
    if ok:
        flash("Disetujui. Upah terakhir, kompensasi, dan potongan masuk otomatis ke penggajian periode tanggal keluar.", "success")
    return redirect(url_for("workforce.exit_detail", exit_id=row.id))


@workforce_bp.route("/keluar/<int:exit_id>/batal", methods=["POST"])
@role_required(*HR_ROLES)
def exit_cancel(exit_id):
    row = _exit_or_404(exit_id)
    ok, _ = _run(
        "EMPLOYEE_EXIT_CANCEL",
        f"Batalkan pengajuan keluar {row.employee.full_name}",
        lambda tx: cancel_exit(row),
        reference_type="employee_exits",
        reference_id=row.id,
    )
    if ok:
        flash("Pengajuan keluar dibatalkan.", "success")
    return redirect(url_for("workforce.exit_detail", exit_id=row.id))


# ---------------------------------------------------------------- Aturan gaji & potongan


@workforce_bp.route("/aturan", methods=["GET", "POST"])
@role_required(*HR_ROLES)
def rules():
    """Satu tempat untuk semua aturan potongan, denda, dan kontrak. Hanya OWNER yang mengubah."""
    from app.services.workforce_service import DIVISOR_CHOICES, HR_SETTING_DEFAULTS, save_hr_settings

    branch_id = _branch_id()
    is_owner = str(current_user.role).upper() == "OWNER"
    if request.method == "POST":
        if not is_owner:
            flash("Hanya OWNER yang boleh mengubah aturan gaji dan potongan.", "warning")
            return redirect(url_for("workforce.rules"))
        values = {key: request.form.get(key, "") for key in HR_SETTING_DEFAULTS}
        values["hr.unpaid_statuses"] = ",".join(request.form.getlist("unpaid_status"))
        ok, _ = _run("HR_RULES_SAVE", "Simpan aturan gaji & potongan", lambda tx: save_hr_settings(branch_id, values))
        if ok:
            flash("Aturan disimpan. Berlaku untuk kontrak baru; kontrak lama tetap memakai aturan saat ditandatangani.", "success")
        return redirect(url_for("workforce.rules"))
    settings = hr_settings(branch_id)
    contracts = EmploymentContract.query.filter_by(branch_id=branch_id, status="AKTIF").all()
    differs = [c for c in contracts if c.unpaid_statuses != ",".join(settings["unpaid_statuses"]) or c.daily_wage_divisor != settings["daily_wage_divisor"]]
    return render_template(
        "workforce/rules.html",
        settings=settings,
        raw=settings["raw"],
        divisors=DIVISOR_CHOICES,
        is_owner=is_owner,
        old_rule_contracts=differs,
    )


# ---------------------------------------------------------------- Laporan


@workforce_bp.route("/laporan")
@role_required(*HR_ROLES)
def reports():
    today = today_wib()
    start = _date(request.args.get("dari"), today.replace(day=1))
    end = _date(request.args.get("sampai"), today)
    if end < start:
        start, end = end, start
    return render_template("workforce/reports.html", report=workforce_report(_branch_id(), start, end))


# ---------------------------------------------------------------- Bukti Potong 1721-A1


@workforce_bp.route("/karyawan/<int:employee_id>/bukti-potong-1721a1")
@role_required(*HR_ROLES)
def employee_tax_1721_a1(employee_id: int):
    """Cetak Bukti Potong PPh 21 Formulir 1721-A1 tahunan untuk karyawan."""
    from app.services.tax_pph21_service import compute_annual_1721_a1

    try:
        employee = get_employee(employee_id, _branch_id())
    except WorkforceError:
        abort(404)

    today = today_wib()
    try:
        year = int(request.args.get("year", today.year))
    except (ValueError, TypeError):
        year = today.year

    doc = compute_annual_1721_a1(employee, year, _branch_id())
    back_url = url_for("workforce.employee_detail", employee_id=employee.id)

    return render_template(
        "hr/proof_1721_a1.html",
        doc=doc,
        back_url=back_url,
    )

