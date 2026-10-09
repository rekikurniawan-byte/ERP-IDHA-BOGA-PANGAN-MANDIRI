"""Pajak (Fase 8): laporan masa, setor pajak, pengaturan pajak, potongan pajak pelanggan.

Route tipis; semua aturan (peran, validasi, jurnal) ada di tax_service.
"""
from app.extensions import db
from app.routes.finance_routes import *  # noqa: F401,F403
from app.utils.roles import role_in


def _tax_period():
    from app.utils.clock import today_wib

    today = today_wib()
    try:
        year = int(request.args.get("year") or today.year)
        month = int(request.args.get("month") or today.month)
    except ValueError:
        year, month = today.year, today.month
    if not 1 <= month <= 12 or not 2000 <= year <= 2100:
        year, month = today.year, today.month
    return year, month


@finance_bp.route("/tax")
@role_required("OWNER", "ADMIN")
def tax_report():
    from app.models.finance import BankAccount
    from app.services.tax_service import (
        TAX_PAYMENT_LABELS,
        WITHHOLDING_LABELS,
        build_tax_month,
    )
    from app.utils.clock import today_wib

    year, month = _tax_period()
    return render_template(
        "finance/tax.html",
        report=build_tax_month(current_user.branch_id, year, month),
        payment_labels=TAX_PAYMENT_LABELS,
        withholding_labels=WITHHOLDING_LABELS,
        bank_accounts=BankAccount.query.filter_by(branch_id=current_user.branch_id, is_active=True).all(),
        today=today_wib(),
        is_owner=role_in(current_user.role, ("OWNER",)),
    )


@finance_bp.route("/tax/payments", methods=["POST"])
@role_required("OWNER", "ADMIN")
def tax_payment_create():
    from app.services.tax_service import TAX_PAYMENT_LABELS, TaxError, record_tax_payment

    try:
        row = record_tax_payment(current_user.branch_id, request.form, request.files.get("evidence"), current_user)
        flash(f"Setoran {TAX_PAYMENT_LABELS[row.tax_type]} dicatat: kas/bank keluar dan jurnal dibuat.", "success")
    except TaxError as error:
        flash(str(error), "warning")
    return redirect(url_for(
        "finance.tax_report", year=request.form.get("period_year"), month=request.form.get("period_month")
    ))


@finance_bp.route("/tax/settings", methods=["GET", "POST"])
@role_required("OWNER")
def tax_settings():
    from app.services.tax_service import (
        DOCUMENT_TYPES,
        REGIME_LABELS,
        TaxError,
        get_tax_settings,
        list_tax_documents,
        save_tax_settings,
    )

    if request.method == "POST":
        try:
            save_tax_settings(current_user.branch_id, request.form, current_user)
            flash("Pengaturan pajak disimpan.", "success")
            return redirect(url_for("finance.tax_settings"))
        except TaxError as error:
            flash(str(error), "warning")
    return render_template(
        "finance/tax_settings.html",
        settings=get_tax_settings(current_user.branch_id),
        form=request.form if request.method == "POST" else None,
        regime_labels=REGIME_LABELS,
        document_types=DOCUMENT_TYPES,
        documents=list_tax_documents(current_user.branch_id),
    )


@finance_bp.route("/tax/documents", methods=["POST"])
@role_required("OWNER")
def tax_document_upload():
    from app.services.tax_service import TaxError, save_tax_document

    try:
        save_tax_document(current_user.branch_id, request.form, request.files.get("evidence"), current_user)
        flash("Dokumen pajak disimpan.", "success")
    except TaxError as error:
        flash(str(error), "warning")
    return redirect(url_for("finance.tax_settings"))


@finance_bp.route("/invoices/<int:invoice_id>/tax-withholding", methods=["POST"])
@role_required("OWNER", "ADMIN")
def invoice_tax_withholding(invoice_id):
    from app.services.tax_service import TaxError, WITHHOLDING_LABELS, record_withholding

    invoice = db.session.get(Invoice, invoice_id)
    if invoice is None or invoice.branch_id != current_user.branch_id:
        abort(404)
    try:
        row = record_withholding(invoice, request.form, request.files.get("evidence"), current_user)
        flash(f"Potongan {WITHHOLDING_LABELS[row.withholding_type]} dicatat; sisa invoice berkurang dan jurnal dibuat.", "success")
    except TaxError as error:
        flash(str(error), "warning")
    return redirect(url_for("finance.invoice_detail", invoice_id=invoice_id))


@finance_bp.route("/tax/attachments/<int:attachment_id>/view")
@role_required("OWNER", "ADMIN")
def tax_attachment_view(attachment_id):
    from app.services.digital_attachment_service import get_attachment_file_path, is_inline_view_safe
    from app.services.tax_service import tax_attachment_or_none

    attachment = tax_attachment_or_none(attachment_id, current_user.branch_id)
    if attachment is None:
        abort(404)
    response = send_file(
        str(get_attachment_file_path(attachment)),
        as_attachment=not is_inline_view_safe(attachment),
        download_name=attachment.original_filename,
        mimetype=attachment.mime_type or "application/octet-stream",
        max_age=0,
    )
    response.headers["Cache-Control"] = "no-store"
    return response
