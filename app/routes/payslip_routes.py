"""Slip gaji & kwitansi tanda terima gaji (menu SDM → Penggajian).

payslip_bp        : halaman internal ADMIN/OWNER (cetak, kirim WhatsApp, kwitansi).
payslip_public_bp : /slip/<token> untuk karyawan tanpa akun, dibuka dengan PIN.
"""
from __future__ import annotations

import logging

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from flask_login import current_user

from app.extensions import limiter
from app.models.hr import Payroll, PayrollDetail
from app.services.atomic_transaction_service import atomic_business_action
from app.services.payslip_service import (
    build_payslip,
    build_receipt,
    detail_by_token,
    ensure_slip_token,
    pin_matches,
    period_label,
    record_manual_receipt,
    sign_receipt,
    slip_pin,
    whatsapp_url,
)
from app.services.workforce_service import WorkforceError
from app.utils.clock import now_wib
from app.utils.decorators import role_required

logger = logging.getLogger(__name__)

payslip_bp = Blueprint("payslip", __name__, url_prefix="/hr/slip")
payslip_public_bp = Blueprint("payslip_public", __name__, url_prefix="/slip")

HR_ROLES = ("ADMIN", "HR")


def _detail_or_404(detail_id: int) -> PayrollDetail:
    detail = PayrollDetail.query.get_or_404(detail_id)
    if detail.payroll.branch_id != current_user.branch_id:
        abort(404)
    return detail


def _payroll_or_404(payroll_id: int) -> Payroll:
    return Payroll.query.filter_by(id=payroll_id, branch_id=current_user.branch_id).first_or_404()


def _sorted_details(payroll: Payroll) -> list:
    return sorted(payroll.details, key=lambda detail: (detail.employee.full_name if detail.employee else ""))


def _atomic(action: str, description: str, fn, reference_id=None):
    try:
        with atomic_business_action(
            module="HR",
            action=action,
            description=description,
            reference_type="payroll_details",
            reference_id=reference_id,
            user_id=current_user.id,
            branch_id=current_user.branch_id,
        ) as tx:
            result = fn(tx)
        return True, result
    except WorkforceError as error:
        flash(str(error), "warning")
    except Exception as error:
        logger.exception("Aksi slip/kwitansi %s gagal", action)
        flash(f"Gagal menyimpan: {error}", "danger")
    return False, None


# ---------------------------------------------------------------- slip gaji


@payslip_bp.route("/<int:detail_id>")
@role_required(*HR_ROLES)
def print_slip(detail_id):
    detail = _detail_or_404(detail_id)
    return render_template(
        "hr/payslip_print.html",
        slips=[build_payslip(detail)],
        title=f"Slip Gaji {detail.employee.full_name} {period_label(detail.payroll)}",
        back_url=url_for("hr.payroll_detail", payroll_id=detail.payroll_id),
        printed_at=now_wib(),
    )


@payslip_bp.route("/penggajian/<int:payroll_id>")
@role_required(*HR_ROLES)
def print_all(payroll_id):
    payroll = _payroll_or_404(payroll_id)
    return render_template(
        "hr/payslip_print.html",
        slips=[build_payslip(detail) for detail in _sorted_details(payroll)],
        title=f"Slip Gaji {period_label(payroll)}",
        back_url=url_for("hr.payroll_detail", payroll_id=payroll.id),
        printed_at=now_wib(),
    )


@payslip_bp.route("/<int:detail_id>/whatsapp", methods=["POST"])
@role_required(*HR_ROLES)
def send_whatsapp(detail_id):
    detail = _detail_or_404(detail_id)
    if not slip_pin(detail.employee):
        flash("NIK dan No. HP karyawan kosong, slip tidak bisa dikunci PIN. Lengkapi data karyawan dulu.", "warning")
        return redirect(url_for("hr.payroll_detail", payroll_id=detail.payroll_id))
    ok, token = _atomic("PAYSLIP_SHARE", f"Buat link slip {detail.employee.full_name}", lambda tx: ensure_slip_token(detail), detail.id)
    if not ok:
        return redirect(url_for("hr.payroll_detail", payroll_id=detail.payroll_id))
    target = whatsapp_url(detail.employee, url_for("payslip_public.view", token=token, _external=True), detail.payroll)
    if not target:
        flash("No. HP karyawan belum diisi.", "warning")
        return redirect(url_for("hr.payroll_detail", payroll_id=detail.payroll_id))
    return redirect(target)


# ---------------------------------------------------------------- kwitansi


@payslip_bp.route("/<int:detail_id>/kwitansi")
@role_required(*HR_ROLES)
def print_receipt(detail_id):
    detail = _detail_or_404(detail_id)
    return render_template(
        "hr/receipt_print.html",
        receipts=[build_receipt(detail)],
        title=f"Kwitansi Gaji {detail.employee.full_name} {period_label(detail.payroll)}",
        back_url=url_for("hr.payroll_detail", payroll_id=detail.payroll_id),
        printed_at=now_wib(),
    )


@payslip_bp.route("/penggajian/<int:payroll_id>/kwitansi")
@role_required(*HR_ROLES)
def print_receipts_all(payroll_id):
    payroll = _payroll_or_404(payroll_id)
    return render_template(
        "hr/receipt_print.html",
        receipts=[build_receipt(detail) for detail in _sorted_details(payroll) if detail.final_salary and detail.final_salary > 0],
        title=f"Kwitansi Gaji {period_label(payroll)}",
        back_url=url_for("hr.payroll_detail", payroll_id=payroll.id),
        printed_at=now_wib(),
    )


@payslip_bp.route("/<int:detail_id>/kwitansi/ttd", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
@role_required(*HR_ROLES)
def receipt_sign(detail_id):
    detail = _detail_or_404(detail_id)
    if request.method == "POST":
        def _sign(tx):
            receipt, attachments = sign_receipt(
                detail,
                typed_name=request.form.get("typed_name"),
                signature_data=request.form.get("signature_data"),
                user=current_user,
            )
            for attachment in attachments:
                tx.track_attachment(attachment)
            return receipt

        ok, receipt = _atomic("PAYROLL_RECEIPT_SIGN", f"TTD terima gaji {detail.employee.full_name}", _sign, detail.id)
        if ok:
            flash(f"Tanda terima gaji {detail.employee.full_name} tersimpan ({receipt.receipt_number}).", "success")
            return redirect(url_for("hr.payroll_detail", payroll_id=detail.payroll_id))
    return render_template("hr/receipt_sign.html", data=build_receipt(detail), slip=build_payslip(detail))


@payslip_bp.route("/<int:detail_id>/kwitansi/manual", methods=["POST"])
@role_required(*HR_ROLES)
def receipt_manual(detail_id):
    detail = _detail_or_404(detail_id)

    def _record(tx):
        receipt, attachments = record_manual_receipt(
            detail, user=current_user, scan_file=request.files.get("scan"), notes=request.form.get("notes"),
        )
        for attachment in attachments:
            tx.track_attachment(attachment)
        return receipt

    ok, receipt = _atomic("PAYROLL_RECEIPT_MANUAL", f"Kwitansi TTD basah {detail.employee.full_name}", _record, detail.id)
    if ok:
        flash(f"Kwitansi kertas {receipt.receipt_number} dicatat sudah ditandatangani.", "success")
    return redirect(url_for("hr.payroll_detail", payroll_id=detail.payroll_id))


# ---------------------------------------------------------------- slip untuk karyawan


@payslip_public_bp.route("/<token>", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def view(token):
    detail = detail_by_token(token)
    if not detail:
        abort(404)
    key = f"slip_ok_{detail.id}"
    error = None
    if request.method == "POST":
        if pin_matches(detail.employee, request.form.get("pin")):
            session[key] = True
            return redirect(url_for("payslip_public.view", token=token))
        error = "PIN salah. Masukkan 4 angka terakhir NIK (atau No. HP bila NIK kosong)."
    if not session.get(key):
        return render_template("hr/payslip_public.html", detail=detail, period=period_label(detail.payroll), error=error, token=token)
    return render_template(
        "hr/payslip_print.html",
        slips=[build_payslip(detail)],
        title=f"Slip Gaji {period_label(detail.payroll)}",
        back_url=None,
        printed_at=now_wib(),
        public=True,
    )
