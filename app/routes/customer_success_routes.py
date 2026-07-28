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
from app.services.customer_contract_expiry_notification_service import generate_contract_expiry_notifications
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
from app.services.customer_correction_service import (
    CORRECTION_STATUSES,
    CORRECTION_TYPES,
    EFFECT_NONE,
    EFFECT_PENDING,
    CustomerCorrectionError,
    create_customer_correction,
    get_customer_correction,
    list_customer_corrections,
    submit_customer_correction,
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


@customer_success_bp.route("/returns")
@role_required(*CUSTOMER_SUCCESS_ROLES)
def returns():
    return render_template(
        "customer_success/foundation_shell.html",
        data=_foundation_data(
            title="Return Management",
            description="Fondasi retur/koreksi pengiriman, menu, jumlah, dan kualitas. Efek stok/finance tetap lewat request koreksi dan approval.",
            status="Foundation",
            source="customer_complaints, customer_corrections, daily_orders, deliveries",
            actions=[
                {"label": "Komplain", "url": url_for("customer_success.complaints"), "icon": "bi-chat-square-dots"},
                {"label": "Koreksi", "url": url_for("customer_success.corrections"), "icon": "bi-arrow-repeat"},
            ],
            rules=[
                "Retur tidak langsung mengubah stok, invoice, payment, atau jurnal.",
                "Retur yang berdampak finansial/stok harus masuk koreksi dan approval.",
                "Histori retur memakai komplain/koreksi existing sampai schema khusus disetujui.",
            ],
        ),
    )


@customer_success_bp.route("/approval-engine")
@role_required(*CUSTOMER_SUCCESS_ROLES)
def approval_engine():
    return render_template(
        "customer_success/foundation_shell.html",
        data=_foundation_data(
            title="Approval Engine",
            description="Pintu Customer Success ke maker-checker approval existing.",
            status="Integrated",
            source="approval_requests existing",
            actions=[{"label": "Request Koreksi", "url": url_for("customer_success.corrections"), "icon": "bi-arrow-repeat"}],
            rules=[
                "Approval engine tidak dibuat ulang.",
                "Semua keputusan sensitif tetap melalui ApprovalRequest existing.",
                "Route ini hanya memberi konteks modul customer dan link ke approval center.",
            ],
        ),
    )


@customer_success_bp.route("/notifications")
@role_required(*CUSTOMER_SUCCESS_ROLES)
def notification_center():
    return render_template(
        "customer_success/foundation_shell.html",
        data=_foundation_data(
            title="Notification Center",
            description="Fondasi notifikasi customer, kontrak hampir habis, komplain, dan tindak lanjut.",
            status="Integrated",
            source="notifications existing",
            actions=[{"label": "Kontrak Customer", "url": url_for("customer_success.contracts"), "icon": "bi-file-earmark-text"}],
            rules=[
                "Notifikasi tidak memakai inbox baru.",
                "Reminder kontrak memakai notification_service existing.",
                "Target role/user tetap mengikuti Notification existing.",
            ],
        ),
    )


@customer_success_bp.route("/documents")
@role_required(*CUSTOMER_SUCCESS_ROLES)
def document_management():
    return render_template(
        "customer_success/foundation_shell.html",
        data=_foundation_data(
            title="Document Management",
            description="Pusat dokumen customer yang terhubung ke DigitalAttachment existing.",
            status="Integrated",
            source="digital_attachments existing",
            actions=[
                {"label": "Kontrak", "url": url_for("customer_success.contracts"), "icon": "bi-file-earmark-text"},
                {"label": "Komplain", "url": url_for("customer_success.complaints"), "icon": "bi-chat-square-dots"},
            ],
            rules=[
                "Tidak membuat storage dokumen baru.",
                "Dokumen kontrak/komplain memakai DigitalAttachment existing.",
                "Penghapusan file fisik tetap mengikuti guard attachment existing.",
            ],
        ),
    )


@customer_success_bp.route("/subscriptions")
@role_required(*CUSTOMER_SUCCESS_ROLES)
def subscriptions():
    return render_template(
        "customer_success/foundation_shell.html",
        data=_foundation_data(
            title="Subscription Order",
            description="Fondasi order berulang dari kontrak customer ke order harian ERP.",
            status="Approval required",
            source="customer_contracts -> daily_orders",
            actions=[{"label": "Kontrak Customer", "url": url_for("customer_success.contracts"), "icon": "bi-file-earmark-text"}],
            rules=[
                "Belum membuat jadwal order otomatis agar tidak menggandakan order.",
                "Jika butuh jadwal berulang permanen, schema dan approval user diperlukan.",
                "Eksekusi order tetap harus masuk workflow daily_orders existing.",
            ],
        ),
    )


@customer_success_bp.route("/calendar")
@role_required(*CUSTOMER_SUCCESS_ROLES)
def operational_calendar():
    return render_template(
        "customer_success/foundation_shell.html",
        data=_foundation_data(
            title="Operational Calendar",
            description="Fondasi kalender operasional customer dari kontrak, order, delivery, closing, dan reminder.",
            status="Read-only",
            source="customer_contracts, daily_orders, deliveries, period_closings, notifications",
            actions=[
                {"label": "Kontrak", "url": url_for("customer_success.contracts"), "icon": "bi-file-earmark-text"},
                {"label": "Komplain", "url": url_for("customer_success.complaints"), "icon": "bi-chat-square-dots"},
            ],
            rules=[
                "Kalender tidak membuat jadwal baru.",
                "Kalender membaca tanggal dari modul existing.",
                "Subscription otomatis dipisah sampai business rule disetujui.",
            ],
        ),
    )


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
    data = {
        "contract": contract,
        "documents": list_customer_contract_documents(contract_id=contract.id, branch_id=current_user.branch_id),
        "attachment_types": sorted(ALLOWED_CONTRACT_ATTACHMENT_TYPES),
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


@customer_success_bp.route("/contracts/expiry-notifications", methods=["POST"])
@role_required("ADMIN", "FINANCE")
def generate_contract_expiry_notifications_route():
    result = generate_contract_expiry_notifications(
        branch_id=current_user.branch_id,
        as_of_date=date.today(),
        due_days=_int_or_default(request.form.get("due_days"), 30),
        generated_by=current_user.id,
        commit=True,
    )
    flash(f"Notifikasi kontrak dibuat/diperbarui: {result['created']} baru, {result['updated']} update.", "success")
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


@customer_success_bp.route("/corrections", methods=["GET", "POST"])
@role_required(*CUSTOMER_SUCCESS_ROLES)
def corrections():
    if request.method == "POST":
        try:
            correction = create_customer_correction(
                branch_id=current_user.branch_id,
                correction_type=request.form.get("correction_type"),
                reason=request.form.get("reason"),
                proposed_action=request.form.get("proposed_action"),
                correction_amount=request.form.get("correction_amount") or 0,
                complaint_id=_int_or_none(request.form.get("complaint_id")),
                client_id=_int_or_none(request.form.get("client_id")),
                mandor_id=_int_or_none(request.form.get("mandor_id")),
                stock_effect=request.form.get("stock_effect") or EFFECT_NONE,
                financial_effect=request.form.get("financial_effect") or EFFECT_NONE,
                notes=request.form.get("notes"),
                submitted_by=current_user.id,
            )
            flash("Request koreksi customer berhasil dibuat.", "success")
            return redirect(url_for("customer_success.correction_detail", correction_id=correction.id))
        except CustomerCorrectionError as error:
            flash(str(error), "danger")

    status_filter = request.args.get("status") or "ALL"
    data = {
        "corrections": list_customer_corrections(current_user.branch_id, status=status_filter),
        "status_filter": status_filter,
        "status_options": ["ALL", *sorted(CORRECTION_STATUSES)],
        "type_options": sorted(CORRECTION_TYPES),
        "effect_options": [EFFECT_NONE, EFFECT_PENDING],
        "complaints": list_customer_complaints(current_user.branch_id, status="ALL", limit=100),
        "clients": _active_clients(),
        "mandors": _branch_mandors(),
    }
    return render_template("customer_success/corrections.html", data=data)


@customer_success_bp.route("/corrections/<int:correction_id>")
@role_required(*CUSTOMER_SUCCESS_ROLES)
def correction_detail(correction_id):
    correction = get_customer_correction(correction_id, branch_id=current_user.branch_id)
    if not correction:
        flash("Request koreksi customer tidak ditemukan.", "warning")
        return redirect(url_for("customer_success.corrections"))
    return render_template("customer_success/correction_detail.html", data={"correction": correction})


@customer_success_bp.route("/corrections/<int:correction_id>/submit", methods=["POST"])
@role_required(*CUSTOMER_SUCCESS_ROLES)
def submit_correction(correction_id):
    try:
        submit_customer_correction(correction_id, branch_id=current_user.branch_id, submitted_by=current_user.id)
        flash("Request koreksi customer berhasil diajukan.", "success")
    except CustomerCorrectionError as error:
        flash(str(error), "danger")
    return redirect(url_for("customer_success.correction_detail", correction_id=correction_id))


def _active_clients():
    return Client.query.filter_by(is_active=True).order_by(Client.name.asc()).all()


def _active_client_pics():
    return ClientPic.query.filter_by(is_active=True).order_by(ClientPic.name.asc()).all()


def _branch_mandors():
    return Mandor.query.filter_by(branch_id=current_user.branch_id, is_active=True).order_by(Mandor.name.asc()).all()


def _branch_users():
    return User.query.filter_by(branch_id=current_user.branch_id, is_active=True).order_by(User.full_name.asc()).all()


def _foundation_data(title, description, status, source, actions, rules):
    contracts = list_customer_contracts(current_user.branch_id, status="ALL")
    complaints = list_customer_complaints(current_user.branch_id, status="ALL", limit=500)
    corrections = list_customer_corrections(current_user.branch_id, status="ALL")
    return {
        "title": title,
        "description": description,
        "status": status,
        "source": source,
        "actions": actions,
        "rules": rules,
        "summary": [
            {"label": "Kontrak", "value": len(contracts), "caption": "customer_contracts existing"},
            {"label": "Komplain", "value": len(complaints), "caption": "customer_complaints existing"},
            {"label": "Koreksi", "value": len(corrections), "caption": "customer_corrections existing"},
        ],
    }


def _int_or_none(value):
    try:
        number = int(value)
        return number if number > 0 else None
    except (TypeError, ValueError):
        return None


def _int_or_default(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _date_or_none(value):
    try:
        return date.fromisoformat(str(value or "").strip())
    except ValueError:
        return None
