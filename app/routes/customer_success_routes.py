from __future__ import annotations

from datetime import date

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.models.master import Client, ClientPic, Mandor, User
from app.services.customer_complaint_attachment_service import (
    ALLOWED_COMPLAINT_ATTACHMENT_TYPES,
    COMPLAINT_EVIDENCE_TYPE,
    CustomerComplaintAttachmentError,
    attach_customer_complaint_evidence,
    list_customer_complaint_evidence,
)
from app.services.customer_complaint_service import (
    COMPLAINT_CATEGORIES,
    COMPLAINT_STATUSES,
    CustomerComplaintError,
    get_customer_complaint,
    list_customer_complaints,
    submit_customer_complaint,
    transition_customer_complaint,
)
from app.services.customer_contract_document_service import (
    ALLOWED_CONTRACT_ATTACHMENT_TYPES,
    CONTRACT_DOCUMENT_TYPE,
    CustomerContractDocumentError,
    attach_customer_contract_document,
    list_customer_contract_documents,
)
from app.services.contract_lifecycle_service import run_contract_sweep_now
from app.services.customer_contract_service import (
    CONTRACT_STATUS_ACTIVE,
    CONTRACT_STATUS_DRAFT,
    CustomerContractError,
    activate_customer_contract,
    create_customer_contract,
    get_customer_contract,
    list_customer_contracts,
    renew_customer_contract,
)
from app.services.digital_attachment_service import AttachmentValidationError
from app.services.user_management_service import ROLE_CUSTOMER_SUCCESS
from app.utils.decorators import role_required


customer_success_bp = Blueprint("customer_success", __name__, url_prefix="/customer-success")
CUSTOMER_SUCCESS_ROLES = ("ADMIN", ROLE_CUSTOMER_SUCCESS)


@customer_success_bp.route("/")
@role_required(*CUSTOMER_SUCCESS_ROLES)
def index():
    return redirect(url_for("customer_success.contracts"))


@customer_success_bp.route("/contracts", methods=["GET", "POST"])
@role_required(*CUSTOMER_SUCCESS_ROLES)
def contracts():
    if request.method == "POST":
        try:
            create_customer_contract(
                branch_id=current_user.branch_id,
                client_id=_int_or_none(request.form.get("client_id")),
                client_pic_id=_int_or_none(request.form.get("client_pic_id")),
                title=request.form.get("title"),
                start_date=_date_or_none(request.form.get("start_date")),
                end_date=_date_or_none(request.form.get("end_date")),
                payment_terms=request.form.get("payment_terms"),
                credit_limit=request.form.get("credit_limit") or 0,
                notes=request.form.get("notes"),
                created_by=current_user.id,
                status=request.form.get("status") or CONTRACT_STATUS_DRAFT,
            )
            flash("Kontrak customer berhasil dibuat.", "success")
            return redirect(url_for("customer_success.contracts"))
        except CustomerContractError as error:
            flash(str(error), "danger")

    status_filter = request.args.get("status") or "ALL"
    data = {
        "contracts": list_customer_contracts(current_user.branch_id, status=status_filter),
        "status_filter": status_filter,
        "clients": _active_clients(),
        "client_pics": _active_client_pics(),
        "status_options": ["ALL", CONTRACT_STATUS_DRAFT, CONTRACT_STATUS_ACTIVE, "EXPIRED", "TERMINATED", "SUPERSEDED"],
    }
    return render_template("customer_success/contracts.html", data=data)


@customer_success_bp.route("/contracts/<int:contract_id>")
@role_required(*CUSTOMER_SUCCESS_ROLES)
def contract_detail(contract_id):
    contract = get_customer_contract(contract_id, branch_id=current_user.branch_id)
    if not contract:
        flash("Kontrak customer tidak ditemukan.", "warning")
        return redirect(url_for("customer_success.contracts"))
    from app.services.pricing_service import quote_price

    data = {
        "contract": contract,
        "documents": list_customer_contract_documents(contract_id=contract.id, branch_id=current_user.branch_id),
        "attachment_types": sorted(ALLOWED_CONTRACT_ATTACHMENT_TYPES),
        "price_quote": quote_price(current_user.branch_id, contract.client_id),
    }
    return render_template("customer_success/contract_detail.html", data=data)


@customer_success_bp.route("/contracts/<int:contract_id>/activate", methods=["POST"])
@role_required(*CUSTOMER_SUCCESS_ROLES)
def activate_contract(contract_id):
    try:
        activate_customer_contract(contract_id, branch_id=current_user.branch_id, updated_by=current_user.id)
        flash("Kontrak customer berhasil diaktifkan.", "success")
    except CustomerContractError as error:
        flash(str(error), "danger")
    return redirect(url_for("customer_success.contract_detail", contract_id=contract_id))


@customer_success_bp.route("/contracts/<int:contract_id>/renew", methods=["POST"])
@role_required(*CUSTOMER_SUCCESS_ROLES)
def renew_contract(contract_id):
    try:
        renewed = renew_customer_contract(
            contract_id,
            branch_id=current_user.branch_id,
            start_date=_date_or_none(request.form.get("start_date")),
            end_date=_date_or_none(request.form.get("end_date")),
            payment_terms=request.form.get("payment_terms"),
            credit_limit=request.form.get("credit_limit") or None,
            notes=request.form.get("notes"),
            created_by=current_user.id,
        )
        run_contract_sweep_now(current_user.branch_id, actor_id=current_user.id)
        flash("Kontrak customer berhasil diperpanjang.", "success")
        return redirect(url_for("customer_success.contract_detail", contract_id=renewed.id))
    except CustomerContractError as error:
        flash(str(error), "danger")
    return redirect(url_for("customer_success.contract_detail", contract_id=contract_id))


@customer_success_bp.route("/contracts/<int:contract_id>/documents", methods=["POST"])
@role_required(*CUSTOMER_SUCCESS_ROLES)
def upload_contract_document(contract_id):
    try:
        attach_customer_contract_document(
            contract_id=contract_id,
            branch_id=current_user.branch_id,
            file_storage=request.files.get("document_file"),
            uploaded_by=current_user.id,
            attachment_type=request.form.get("attachment_type") or CONTRACT_DOCUMENT_TYPE,
            notes=request.form.get("notes"),
        )
        flash("Dokumen kontrak berhasil diarsipkan.", "success")
    except (CustomerContractDocumentError, AttachmentValidationError) as error:
        flash(str(error), "danger")
    return redirect(url_for("customer_success.contract_detail", contract_id=contract_id))


@customer_success_bp.route("/contracts/check", methods=["POST"])
@role_required("ADMIN")
def check_contracts_now():
    """Sapuan kontrak berjalan otomatis tiap hari; tombol ini untuk memeriksa sekarang juga."""
    result = run_contract_sweep_now(current_user.branch_id, actor_id=current_user.id)
    flash(
        f"Kontrak diperiksa: {result['expired']} baru berakhir, {result['reminders']} hampir habis, "
        f"{result['lapsed']} sudah berakhir dan belum diperpanjang.",
        "success",
    )
    return redirect(url_for("customer_success.contracts"))


@customer_success_bp.route("/complaints", methods=["GET", "POST"])
@role_required(*CUSTOMER_SUCCESS_ROLES)
def complaints():
    if request.method == "POST":
        try:
            complaint = submit_customer_complaint(
                branch_id=current_user.branch_id,
                category=request.form.get("category"),
                title=request.form.get("title"),
                description=request.form.get("description"),
                submitted_by=current_user.id,
                client_id=_int_or_none(request.form.get("client_id")),
                mandor_id=_int_or_none(request.form.get("mandor_id")),
                assigned_to=_int_or_none(request.form.get("assigned_to")),
            )
            flash("Komplain customer berhasil dibuat.", "success")
            return redirect(url_for("customer_success.complaint_detail", complaint_id=complaint.id))
        except CustomerComplaintError as error:
            flash(str(error), "danger")

    status_filter = request.args.get("status") or "ALL"
    data = {
        "complaints": list_customer_complaints(current_user.branch_id, status=status_filter),
        "status_filter": status_filter,
        "status_options": ["ALL", *sorted(COMPLAINT_STATUSES)],
        "category_options": sorted(COMPLAINT_CATEGORIES),
        "clients": _active_clients(),
        "mandors": _branch_mandors(),
        "users": _branch_users(),
    }
    return render_template("customer_success/complaints.html", data=data)


@customer_success_bp.route("/complaints/<int:complaint_id>")
@role_required(*CUSTOMER_SUCCESS_ROLES)
def complaint_detail(complaint_id):
    complaint = get_customer_complaint(complaint_id, branch_id=current_user.branch_id)
    if not complaint:
        flash("Komplain customer tidak ditemukan.", "warning")
        return redirect(url_for("customer_success.complaints"))
    data = {
        "complaint": complaint,
        "evidence": list_customer_complaint_evidence(complaint_id=complaint.id, branch_id=current_user.branch_id),
        "attachment_types": sorted(ALLOWED_COMPLAINT_ATTACHMENT_TYPES),
        "users": _branch_users(),
    }
    return render_template("customer_success/complaint_detail.html", data=data)


@customer_success_bp.route("/complaints/<int:complaint_id>/status", methods=["POST"])
@role_required(*CUSTOMER_SUCCESS_ROLES)
def update_complaint_status(complaint_id):
    try:
        transition_customer_complaint(
            complaint_id,
            branch_id=current_user.branch_id,
            new_status=request.form.get("new_status"),
            updated_by=current_user.id,
            assigned_to=_int_or_none(request.form.get("assigned_to")),
            resolution_note=request.form.get("resolution_note"),
        )
        flash("Status komplain berhasil diperbarui.", "success")
    except CustomerComplaintError as error:
        flash(str(error), "danger")
    return redirect(url_for("customer_success.complaint_detail", complaint_id=complaint_id))


@customer_success_bp.route("/complaints/<int:complaint_id>/evidence", methods=["POST"])
@role_required(*CUSTOMER_SUCCESS_ROLES)
def upload_complaint_evidence(complaint_id):
    try:
        attach_customer_complaint_evidence(
            complaint_id=complaint_id,
            branch_id=current_user.branch_id,
            file_storage=request.files.get("evidence_file"),
            uploaded_by=current_user.id,
            attachment_type=request.form.get("attachment_type") or COMPLAINT_EVIDENCE_TYPE,
            notes=request.form.get("notes"),
        )
        flash("Bukti komplain berhasil diarsipkan.", "success")
    except (CustomerComplaintAttachmentError, AttachmentValidationError) as error:
        flash(str(error), "danger")
    return redirect(url_for("customer_success.complaint_detail", complaint_id=complaint_id))


def _active_clients():
    return Client.query.filter_by(is_active=True).order_by(Client.name.asc()).all()


def _active_client_pics():
    return ClientPic.query.filter_by(is_active=True).order_by(ClientPic.name.asc()).all()


def _branch_mandors():
    return Mandor.query.filter_by(branch_id=current_user.branch_id, is_active=True).order_by(Mandor.name.asc()).all()


def _branch_users():
    return User.query.filter_by(branch_id=current_user.branch_id, is_active=True).order_by(User.full_name.asc()).all()


def _int_or_none(value):
    try:
        number = int(value)
        return number if number > 0 else None
    except (TypeError, ValueError):
        return None


def _date_or_none(value):
    try:
        return date.fromisoformat(str(value or "").strip())
    except ValueError:
        return None
