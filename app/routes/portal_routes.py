from uuid import uuid4

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user

from app.models.master import User
from app.models.system import PortalOrderDraft, PortalUserMapping
from app.services.portal_access_service import (
    build_portal_access_scope,
    build_portal_customer_directory,
    build_portal_location_directory,
    build_portal_mandor_directory,
    build_portal_ownership_analysis,
    build_portal_profile,
    build_portal_status_shell,
)
from app.services.portal_closing_visibility_service import build_portal_closing_visibility
from app.services.portal_command_center_service import build_portal_command_center
from app.services.portal_debt_visibility_service import build_portal_worker_debt_read_model
from app.services.portal_financial_visibility_service import (
    build_portal_invoice_read_model,
    build_portal_payment_history_read_model,
)
from app.services.portal_order_draft_service import (
    build_portal_order_draft_review_queue,
    build_portal_order_status_context,
    build_portal_draft_order_context,
    confirm_portal_order_draft,
    create_portal_order_draft,
    list_pending_portal_order_drafts,
    reject_portal_order_draft,
)
from app.services.portal_mobile_read_model_service import (
    build_portal_mobile_debt_cards,
    build_portal_mobile_invoice_cards,
    build_portal_mobile_mandor_cards,
    build_portal_mobile_worker_cards,
)
from app.services.portal_experience_service import (
    build_portal_complaint_model,
    build_portal_contract_model,
    submit_portal_customer_complaint,
)
from app.services.portal_integrated_foundation_service import (
    build_portal_approval_model,
    build_portal_calendar_model,
    build_portal_document_model,
    build_portal_notification_model,
    build_portal_return_model,
    build_portal_subscription_model,
    get_portal_owned_document,
)
from app.services.portal_payment_instruction_service import build_portal_payment_instruction
from app.services.portal_payment_proof_service import (
    PortalPaymentProofError,
    upload_portal_order_draft_payment_proof,
    upload_portal_payment_proof,
)
from app.services.customer_complaint_attachment_service import (
    CustomerComplaintAttachmentError,
    attach_customer_complaint_evidence,
)
from app.services.customer_complaint_service import get_customer_complaint
from app.services.digital_attachment_service import (
    AttachmentValidationError,
    get_attachment_file_path,
    is_inline_view_safe,
)
from app.services.portal_customer_registration_service import register_portal_customer
from app.services.notification_service import (
    can_user_access_notification,
    get_notification_or_none,
    mark_notification_dismissed,
    mark_notification_read,
)
from app.services.user_management_service import (
    ROLE_PORTAL_CLIENT,
    ROLE_PORTAL_CUSTOMER,
    ROLE_PORTAL_SUBCLIENT,
    list_active_branches,
)
from app.utils.decorators import role_required
from app.utils.terms import T


portal_bp = Blueprint("portal", __name__, url_prefix="/portal")
PORTAL_READONLY_ROLES = (
    "ADMIN",
    ROLE_PORTAL_CLIENT,
    ROLE_PORTAL_SUBCLIENT,
    ROLE_PORTAL_CUSTOMER,
)
PORTAL_INTERNAL_ROLES = ("ADMIN",)

PORTAL_ROLE_DASHBOARD_ENDPOINTS = {
    ROLE_PORTAL_CUSTOMER: "portal.customer_dashboard",
    ROLE_PORTAL_SUBCLIENT: "portal.mandor_dashboard",
    # CLIENT and PT are one role now and it gets the PT home: the company
    # view over every sub client under the contract. The narrower
    # client_dashboard page still exists and still renders.
    ROLE_PORTAL_CLIENT: "portal.pt_dashboard",
}


@portal_bp.before_request
def require_portal_feature_flag():
    if not current_app.config.get("PORTAL_ENABLED", False):
        abort(404)


@portal_bp.route("/login")
def login_entry():
    return redirect(url_for("auth.login"))


@portal_bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        try:
            user = register_portal_customer(request.form)
        except ValueError as exc:
            flash(str(exc), "danger")
            data = _customer_register_page_data()
            data["form"] = request.form
            return render_template("portal/register.html", data=data), 400

        flash("Akun pelanggan berhasil dibuat. Silakan masuk untuk mulai memesan.", "success")
        current_app.logger.info("Registrasi pelanggan portal berhasil untuk user_id=%s", user.id)
        return redirect(url_for("auth.login"))

    return render_template("portal/register.html", data=_customer_register_page_data())


def _customer_register_page_data():
    branches = list_active_branches()
    data = {
        "title": "Daftar Pelanggan",
        "description": "Buat akun pelanggan umum untuk memesan catering.",
        "branches": branches,
        "form": {},
        "login_url": url_for("auth.login"),
    }
    return data


@portal_bp.route("")
@portal_bp.route("/")
@role_required(*PORTAL_READONLY_ROLES)
def index():
    return redirect(url_for("portal.my_dashboard"))


@portal_bp.route("/dashboard")
@role_required(*PORTAL_INTERNAL_ROLES)
def dashboard():
    portal_roles = [
        ROLE_PORTAL_CLIENT,
        ROLE_PORTAL_SUBCLIENT,
        ROLE_PORTAL_CUSTOMER,
    ]
    user_query = User.query.filter(User.role.in_(portal_roles))
    mapping_query = PortalUserMapping.query.join(User, PortalUserMapping.user_id == User.id)
    draft_query = PortalOrderDraft.query

    if current_user.role != "OWNER":
        user_query = user_query.filter(User.branch_id == current_user.branch_id)
        mapping_query = mapping_query.filter(User.branch_id == current_user.branch_id)
        draft_query = draft_query.filter(PortalOrderDraft.branch_id == current_user.branch_id)

    data = {
        "status_label": "Internal",
        "active_role": current_user.role,
        "branch_id": current_user.branch_id,
        "cards": [
            {
                "title": "User Portal",
                "value": user_query.count(),
                "caption": "Akun portal memakai sistem login yang sama.",
            },
            {
                "title": "Mapping Aktif",
                "value": mapping_query.filter(PortalUserMapping.is_active.is_(True)).count(),
                "caption": f"Penghubung akun ke perusahaan, {T.sub_client_lower}, dan lokasi.",
            },
            {
                "title": "Draft Pending",
                "value": draft_query.filter(PortalOrderDraft.status == "PENDING_ADMIN_CONFIRMATION").count(),
                "caption": "Antrian sebelum diproses admin.",
            },
        ],
        "sources": [
            {
                "area": "Akun portal",
                "erp_source": "Akun dan hak akses",
                "rule": "Semua akun masuk dari halaman login yang sama.",
            },
            {
                "area": f"{T.client}, {T.sub_client_lower}, lokasi",
                "erp_source": "clients, mandors, delivery_locations",
                "rule": f"Perusahaan, {T.sub_client_lower}, dan lokasi tetap dikelola dari Master Data.",
            },
            {
                "area": "Draft order",
                "erp_source": "Pesanan harian",
                "rule": "Pesanan baru menunggu admin sebelum masuk produksi dan pengiriman.",
            },
            {
                "area": "Tagihan dan pembayaran",
                "erp_source": "Finance",
                "rule": "Invoice dan pembayaran mengikuti hak akses akun.",
            },
        ],
    }
    return render_template("portal/dashboard.html", data=data)


@portal_bp.route("/my-dashboard")
@role_required(*PORTAL_READONLY_ROLES)
def my_dashboard():
    role_endpoint = PORTAL_ROLE_DASHBOARD_ENDPOINTS.get(current_user.role)
    if role_endpoint:
        return redirect(url_for(role_endpoint))

    data = {
        "status_label": "Role portal",
        "active_role": current_user.role,
        "branch_id": current_user.branch_id,
        "scope": build_portal_access_scope(current_user),
        "orders": build_portal_order_status_context(current_user),
        "invoices": build_portal_invoice_read_model(current_user, limit=5),
        "payments": build_portal_payment_history_read_model(current_user, limit=5),
        "debts": build_portal_worker_debt_read_model(current_user, limit=5),
        "closing": build_portal_closing_visibility(
            current_user,
            year=request.args.get("year"),
            month=request.args.get("month"),
        ),
    }
    return render_template("portal/my_dashboard.html", data=data)


def _role_dashboard_data(persona, *, include_center=False):
    data = {
        "persona": persona,
        "active_role": current_user.role,
        "branch_id": current_user.branch_id,
        "scope": build_portal_access_scope(current_user),
        "orders": build_portal_order_status_context(current_user),
        "invoices": build_portal_invoice_read_model(current_user, limit=5),
        "payments": build_portal_payment_history_read_model(current_user, limit=5),
        "debts": build_portal_worker_debt_read_model(current_user, limit=5),
        "closing": build_portal_closing_visibility(
            current_user,
            year=request.args.get("year"),
            month=request.args.get("month"),
        ),
    }
    if include_center:
        data["center"] = build_portal_command_center(current_user)
    return data


def _portal_feature_data(persona, feature):
    data = _role_dashboard_data(persona)
    data["feature"] = feature
    return data


def _portal_feature_response(persona, feature):
    return render_template("portal/feature_shell.html", data=_portal_feature_data(persona, feature))


def _customer_persona():
    return {
        "eyebrow": "Portal Pelanggan Umum",
        "title": "Beranda Pelanggan",
        "description": "Ringkasan akses pelanggan umum. Order dan pembayaran aktual tetap mengikuti workflow data utama.",
        "scope_label": "Akses pribadi",
        "primary_note": f"Prepayment tetap wajib. Pelanggan umum belum membuka piutang/hutang {T.worker_lower}.",
    }


def _mandor_persona():
    return {
        "eyebrow": f"Portal {T.sub_client}",
        "title": f"Beranda {T.sub_client}",
        "description": f"Ringkasan {T.sub_client_lower} berdasarkan akses ke {T.sub_client_lower} dan lokasi .",
        "scope_label": f"Akses {T.sub_client_lower}",
        "primary_note": f"{T.sub_client} hanya melihat order, invoice, hutang {T.worker_lower}, dan pembayaran miliknya.",
    }


def _pt_persona():
    return {
        "eyebrow": f"Portal {T.client}",
        "title": f"Beranda {T.client}",
        "description": f"Ringkasan {T.client_lower} berdasarkan akses {T.client_lower}.",
        "scope_label": f"Akses {T.client_lower}",
        "primary_note": f"{T.client} melihat {T.sub_client_lower}, lokasi, invoice, pembayaran, dan closing miliknya.",
    }


def _current_portal_persona():
    if current_user.role == ROLE_PORTAL_CLIENT:
        return _pt_persona()
    if current_user.role == ROLE_PORTAL_SUBCLIENT:
        return _mandor_persona()
    if current_user.role == ROLE_PORTAL_CUSTOMER:
        return _customer_persona()
    return {
        "eyebrow": "Portal",
        "title": "Beranda Portal",
        "description": "Ringkasan portal terintegrasi dengan data utama.",
        "scope_label": "Akses portal",
        "primary_note": "Akses mengikuti role dan data yang ditentukan admin.",
    }


@portal_bp.route("/customer")
@role_required(ROLE_PORTAL_CUSTOMER)
def customer_dashboard():
    return render_template(
        "portal/role_dashboard.html",
        data=_role_dashboard_data(_customer_persona(), include_center=True),
    )


@portal_bp.route("/customer/order")
@role_required(ROLE_PORTAL_CUSTOMER)
def customer_order():
    return render_template(
        "portal/draft_order.html",
        data={
            **_role_dashboard_data(_customer_persona()),
            "status_label": "Wajib bayar dulu",
            "context": build_portal_draft_order_context(current_user),
            "idempotency_key": uuid4().hex,
        },
    )


@portal_bp.route("/customer/orders")
@role_required(ROLE_PORTAL_CUSTOMER)
def customer_order_history():
    return render_template(
        "portal/order_status.html",
        data={
            **_role_dashboard_data(_customer_persona()),
            "status_label": "Hanya dilihat",
            "page_title": "Riwayat Pesanan",
            "page_description": "Riwayat pesanan pelanggan.",
            "orders": build_portal_order_status_context(current_user),
        },
    )


@portal_bp.route("/customer/tracking")
@role_required(ROLE_PORTAL_CUSTOMER)
def customer_tracking():
    return render_template(
        "portal/order_status.html",
        data={
            **_role_dashboard_data(_customer_persona()),
            "status_label": "Hanya dilihat",
            "page_title": "Lacak Pesanan",
            "page_description": "Pelacakan memakai status draft dan order internal . Produksi/pengiriman ditampilkan saat relasi tersedia.",
            "orders": build_portal_order_status_context(current_user),
        },
    )


@portal_bp.route("/customer/invoices")
@role_required(ROLE_PORTAL_CUSTOMER)
def customer_invoices():
    flash("Pelanggan umum tidak memakai menu tagihan tempo. Gunakan Bayar / Bukti untuk pembayaran awal.", "info")
    return redirect(url_for("portal.customer_payments"))


@portal_bp.route("/customer/payments")
@role_required(ROLE_PORTAL_CUSTOMER)
def customer_payments():
    return render_template(
        "portal/mobile_payments.html",
        data={
            **_role_dashboard_data(_customer_persona()),
            "page_title": "Bayar / Bukti Pembayaran",
            "page_description": "Pelanggan umum bayar di awal. Bukti pembayaran diperiksa sebelum pesanan diproses admin.",
        },
    )


@portal_bp.route("/customer/complaints", methods=["GET", "POST"])
@role_required(ROLE_PORTAL_CUSTOMER)
def customer_complaints():
    if request.method == "POST":
        complaint, error = submit_portal_customer_complaint(current_user, request.form)
        if error:
            flash(error, "danger")
        else:
            flash(f"Komplain {complaint.complaint_number} berhasil dikirim.", "success")
        return redirect(url_for("portal.customer_complaints"))

    return render_template(
        "portal/complaints.html",
        data={
            **_role_dashboard_data(_customer_persona()),
            "page_title": "Komplain",
            "page_description": "Komplain pelanggan tersambung ke Complaint Management data utama.",
            "complaints": build_portal_complaint_model(current_user),
        },
    )


@portal_bp.route("/customer/complaints/<int:complaint_id>/evidence", methods=["POST"])
@role_required(ROLE_PORTAL_CUSTOMER)
def upload_customer_complaint_evidence(complaint_id):
    complaint = get_customer_complaint(complaint_id, branch_id=current_user.branch_id)
    if not complaint or complaint.submitted_by != current_user.id:
        abort(404)
    try:
        attachment = attach_customer_complaint_evidence(
            complaint_id=complaint_id,
            branch_id=current_user.branch_id,
            file_storage=request.files.get("evidence_file"),
            uploaded_by=current_user.id,
            notes=request.form.get("notes"),
        )
    except (CustomerComplaintAttachmentError, AttachmentValidationError) as exc:
        flash(str(exc), "danger")
    else:
        flash(f"Bukti komplain {attachment.original_filename} berhasil diupload.", "success")
    return redirect(url_for("portal.customer_complaints"))


@portal_bp.route("/customer/returns")
@role_required(ROLE_PORTAL_CUSTOMER)
def customer_returns():
    return render_template(
        "portal/returns.html",
        data={
            **_role_dashboard_data(_customer_persona()),
            "page_title": "Retur",
            "page_description": "Retur dibaca dari laporan pelanggan kategori kekurangan, salah menu, rusak, atau pengiriman kurang.",
            "returns": build_portal_return_model(current_user),
        },
    )


@portal_bp.route("/mandor")
@role_required(ROLE_PORTAL_SUBCLIENT)
def mandor_dashboard():
    return render_template(
        "portal/role_dashboard.html",
        data=_role_dashboard_data(_mandor_persona(), include_center=True),
        credit_summaries=_mandor_credit_summaries(),
    )


def _mandor_credit_summaries():
    """Ringkasan kredit untuk mandor dalam akses pengguna ini yang ditagih langsung.

    Mandor yang ditagih lewat PT tidak mendapat kartu: dia tidak punya hutang
    pribadi yang perlu dipantau. Kegagalan di sini tidak boleh menjatuhkan
    dashboard, jadi dicatat di log dan kartunya disembunyikan.
    """
    try:
        from app.models.master import Mandor
        from app.services.credit_account_service import portal_credit_summary
        from app.services.portal_mapping_service import build_portal_external_scope

        scope = build_portal_external_scope(current_user)
        if not scope.allowed or not scope.mandor_ids:
            return []
        summaries = []
        for mandor in Mandor.query.filter(Mandor.id.in_(sorted(scope.mandor_ids))).all():
            summary = portal_credit_summary(mandor)
            if summary:
                summaries.append({"mandor_name": mandor.name, **summary})
        return summaries
    except Exception:
        current_app.logger.exception("Ringkasan kredit portal gagal dimuat.")
        return []


@portal_bp.route("/mandor/order")
@role_required(ROLE_PORTAL_SUBCLIENT)
def mandor_order():
    return render_template(
        "portal/draft_order.html",
        data={
            **_role_dashboard_data(_mandor_persona()),
            "status_label": "Menunggu admin",
            "context": build_portal_draft_order_context(current_user),
            "idempotency_key": uuid4().hex,
        },
        credit_summaries=_mandor_credit_summaries(),
    )


@portal_bp.route("/mandor/workers")
@role_required(ROLE_PORTAL_SUBCLIENT)
def mandor_workers():
    return render_template(
        "portal/mobile_workers.html",
        data={
            **_role_dashboard_data(_mandor_persona()),
            "worker_model": build_portal_mobile_worker_cards(current_user),
        },
    )


@portal_bp.route("/mandor/catering-debts")
@role_required(ROLE_PORTAL_SUBCLIENT)
def mandor_catering_debts():
    return render_template(
        "portal/mobile_invoices.html",
        data={
            **_role_dashboard_data(_mandor_persona()),
            "page_title": "Hutang Catering",
            "page_description": "Sisa tagihan catering dari invoice data utama.",
            "invoice_model": build_portal_mobile_invoice_cards(current_user),
        },
    )


@portal_bp.route("/mandor/canteen-debts")
@role_required(ROLE_PORTAL_SUBCLIENT)
def mandor_canteen_debts():
    return render_template(
        "portal/mobile_debts.html",
        data={
            **_role_dashboard_data(_mandor_persona()),
            "page_title": "Hutang Warung",
            "page_description": f"Hutang {T.worker_lower} dari WorkerDebt data utama.",
            "debt_model": build_portal_mobile_debt_cards(current_user),
        },
    )


@portal_bp.route("/mandor/installments")
@role_required(ROLE_PORTAL_SUBCLIENT)
def mandor_installments():
    return render_template(
        "portal/mobile_debts.html",
        data={
            **_role_dashboard_data(_mandor_persona()),
            "page_title": "Cicilan",
            "page_description": "Cicilan ditampilkan sebagai sisa hutang dan riwayat pembayaran.",
            "debt_model": build_portal_mobile_debt_cards(current_user),
        },
    )


@portal_bp.route("/mandor/invoices")
@role_required(ROLE_PORTAL_SUBCLIENT)
def mandor_invoices():
    return render_template(
        "portal/mobile_invoices.html",
        data={
            **_role_dashboard_data(_mandor_persona()),
            "page_title": "Tagihan",
            "page_description": f"Tagihan {T.sub_client_lower} sesuai akses kepemilikan.",
            "invoice_model": build_portal_mobile_invoice_cards(current_user),
        },
    )


@portal_bp.route("/mandor/payments")
@role_required(ROLE_PORTAL_SUBCLIENT)
def mandor_payments():
    return render_template(
        "portal/mobile_payments.html",
        data={
            **_role_dashboard_data(_mandor_persona()),
            "page_title": "Riwayat Pembayaran",
            "page_description": f"Pembayaran {T.sub_client_lower} dari data payment data utama.",
        },
    )


@portal_bp.route("/mandor/subscriptions")
@role_required(ROLE_PORTAL_SUBCLIENT)
def mandor_subscriptions():
    return render_template(
        "portal/subscriptions.html",
        data={
            **_role_dashboard_data(_mandor_persona()),
            "page_title": "Pesanan Berulang",
            "page_description": "Pola order berulang dibaca dari draft order portal. Tidak membuat order otomatis.",
            "subscriptions": build_portal_subscription_model(current_user),
        },
    )


@portal_bp.route("/pt")
@role_required(ROLE_PORTAL_CLIENT)
def pt_dashboard():
    from app.services.portal_mapping_service import build_portal_external_scope
    from app.services.portal_order_draft_service import orderable_location_ids

    return render_template(
        "portal/role_dashboard.html",
        data=_role_dashboard_data(_pt_persona(), include_center=True),
        direct_ordering_enabled=bool(
            orderable_location_ids(current_user, build_portal_external_scope(current_user))
        ),
    )


@portal_bp.route("/pt/order")
@role_required(ROLE_PORTAL_CLIENT)
def pt_order():
    # PT dengan unit order langsung memakai form order yang sama dengan sub
    # client. PT tanpa unit langsung kembali ke berandanya, seperti dulu.
    from app.services.portal_mapping_service import build_portal_external_scope
    from app.services.portal_order_draft_service import orderable_location_ids

    if orderable_location_ids(current_user, build_portal_external_scope(current_user)):
        return redirect(url_for("portal.draft_order"))
    flash(
        f"Portal {T.client} memantau pesanan {T.sub_client_lower}. Untuk memesan sendiri, "
        f"minta admin mengaktifkan Order Langsung dan menambahkan {T.location_lower}.",
        "info",
    )
    return redirect(url_for("portal.pt_dashboard"))


@portal_bp.route("/pt/mandors")
@role_required(ROLE_PORTAL_CLIENT)
def pt_mandors():
    return render_template(
        "portal/mobile_mandors.html",
        data={
            **_role_dashboard_data(_pt_persona()),
            "mandor_model": build_portal_mobile_mandor_cards(current_user),
        },
    )


@portal_bp.route("/pt/invoices")
@role_required(ROLE_PORTAL_CLIENT)
def pt_invoices():
    return render_template(
        "portal/mobile_invoices.html",
        data={
            **_role_dashboard_data(_pt_persona()),
            "page_title": "Seluruh Tagihan",
            "page_description": f"Tagihan {T.client_lower} dari invoice data utama.",
            "invoice_model": build_portal_mobile_invoice_cards(current_user),
        },
    )


@portal_bp.route("/pt/receivables")
@role_required(ROLE_PORTAL_CLIENT)
def pt_receivables():
    return render_template(
        "portal/mobile_invoices.html",
        data={
            **_role_dashboard_data(_pt_persona()),
            "page_title": "Seluruh Piutang",
            "page_description": "Piutang dihitung dari remaining invoice dan payment .",
            "invoice_model": build_portal_mobile_invoice_cards(current_user),
        },
    )


@portal_bp.route("/pt/payments")
@role_required(ROLE_PORTAL_CLIENT)
def pt_payments():
    return render_template(
        "portal/mobile_payments.html",
        data={
            **_role_dashboard_data(_pt_persona()),
            "page_title": f"Riwayat Pembayaran {T.client}",
            "page_description": f"Riwayat pembayaran {T.client_lower} sesuai aksesnya.",
        },
    )


@portal_bp.route("/pt/contracts")
@role_required(ROLE_PORTAL_CLIENT)
def pt_contracts():
    return render_template(
        "portal/contracts.html",
        data={
            **_role_dashboard_data(_pt_persona()),
            "page_title": "Seluruh Kontrak",
            "page_description": f"Kontrak {T.client_lower} dibaca dari Kontrak data utama sesuai akses {T.client_lower}.",
            "contracts": build_portal_contract_model(current_user),
        },
    )


@portal_bp.route("/pt/subscriptions")
@role_required(ROLE_PORTAL_CLIENT)
def pt_subscriptions():
    return render_template(
        "portal/subscriptions.html",
        data={
            **_role_dashboard_data(_pt_persona()),
            "page_title": "Pesanan Berulang",
            "page_description": f"Pola order berulang {T.client_lower} dibaca dari draft order portal. Aktivasi otomatis perlu approval terpisah.",
            "subscriptions": build_portal_subscription_model(current_user),
        },
    )


@portal_bp.route("/invoices/<int:invoice_id>/payment", methods=["GET", "POST"])
@role_required(*PORTAL_READONLY_ROLES)
def invoice_payment_instruction(invoice_id):
    instruction = build_portal_payment_instruction(current_user, invoice_id=invoice_id)

    if request.method == "POST":
        try:
            result = upload_portal_payment_proof(
                current_user,
                invoice_id=invoice_id,
                file_storage=request.files.get("proof_file"),
                notes=request.form.get("notes"),
            )
        except (PortalPaymentProofError, AttachmentValidationError) as exc:
            flash(str(exc), "danger")
        else:
            flash(
                f"Bukti pembayaran invoice {result['invoice_number']} berhasil diupload dan menunggu verifikasi finance.",
                "success",
            )
        return redirect(url_for("portal.invoice_payment_instruction", invoice_id=invoice_id))

    data = {
        **_role_dashboard_data(
            _pt_persona()
            if current_user.role == ROLE_PORTAL_CLIENT
            else _mandor_persona()
            if current_user.role == ROLE_PORTAL_SUBCLIENT
            else _customer_persona()
            if current_user.role == ROLE_PORTAL_CUSTOMER
            else {
                "eyebrow": "Portal",
                "title": "Instruksi Pembayaran",
                "description": "Instruksi pembayaran portal.",
                "scope_label": "Akses portal",
                "primary_note": "Instruksi dibaca dari invoice data utama.",
            }
        ),
        "page_title": "Instruksi Pembayaran",
        "page_description": "Unggah bukti pembayaran dan tunggu pemeriksaan.",
        "instruction": instruction,
    }
    return render_template("portal/payment_instruction.html", data=data)


@portal_bp.route("/client")
@role_required(ROLE_PORTAL_CLIENT)
def client_dashboard():
    return render_template(
        "portal/role_dashboard.html",
        data=_role_dashboard_data(
            {
                "eyebrow": f"Portal {T.client}",
                "title": f"Beranda {T.client}",
                "description": f"Ringkasan {T.client_lower}/PIC berdasarkan akses {T.client_lower} atau delegasi .",
                "scope_label": f"Akses {T.client_lower}",
                "primary_note": f"Role ini dipertahankan untuk kompatibilitas data {T.client_lower} .",
            },
            include_center=True,
        ),
    )


@portal_bp.route("/invoices")
@role_required(*PORTAL_READONLY_ROLES)
def invoices():
    if current_user.role == ROLE_PORTAL_CUSTOMER:
        return redirect(url_for("portal.customer_payments"))
    return render_template(
        "portal/invoices.html",
        data={
            **_role_dashboard_data(_current_portal_persona()),
            "status_label": "Read-only",
            "model": build_portal_invoice_read_model(current_user, limit=50),
        },
    )


@portal_bp.route("/payments")
@role_required(*PORTAL_READONLY_ROLES)
def payments():
    if current_user.role == ROLE_PORTAL_CUSTOMER:
        return redirect(url_for("portal.customer_payments"))
    return render_template(
        "portal/payments.html",
        data={
            **_role_dashboard_data(_current_portal_persona()),
            "status_label": "Read-only",
            "model": build_portal_payment_history_read_model(current_user, limit=50),
        },
    )


@portal_bp.route("/debts")
@role_required(*PORTAL_READONLY_ROLES)
def debts():
    if current_user.role == ROLE_PORTAL_CUSTOMER:
        return redirect(url_for("portal.customer_dashboard"))
    return render_template(
        "portal/debts.html",
        data={
            **_role_dashboard_data(_current_portal_persona()),
            "status_label": "Read-only",
            "model": build_portal_worker_debt_read_model(current_user, limit=50),
        },
    )


@portal_bp.route("/closing")
@role_required(*PORTAL_READONLY_ROLES)
def closing():
    if current_user.role == ROLE_PORTAL_CUSTOMER:
        return redirect(url_for("portal.customer_dashboard"))
    return render_template(
        "portal/closing.html",
        data={
            **_role_dashboard_data(_current_portal_persona()),
            "status_label": "Read-only",
            "model": build_portal_closing_visibility(
                current_user,
                year=request.args.get("year"),
                month=request.args.get("month"),
            ),
        },
    )


@portal_bp.route("/notifications")
@role_required(*PORTAL_READONLY_ROLES)
def notifications():
    persona = (
        _pt_persona()
        if current_user.role == ROLE_PORTAL_CLIENT
        else _mandor_persona()
        if current_user.role == ROLE_PORTAL_SUBCLIENT
        else _customer_persona()
    )
    return render_template(
        "portal/notifications.html",
        data={
            **_role_dashboard_data(persona),
            "page_title": "Notifikasi",
            "page_description": "Pusat notifikasi membaca tabel notifications  sesuai target user/role.",
            "notifications": build_portal_notification_model(current_user),
        },
    )


@portal_bp.route("/documents")
@role_required(*PORTAL_READONLY_ROLES)
def documents():
    persona = (
        _pt_persona()
        if current_user.role == ROLE_PORTAL_CLIENT
        else _mandor_persona()
        if current_user.role == ROLE_PORTAL_SUBCLIENT
        else _customer_persona()
    )
    return render_template(
        "portal/documents.html",
        data={
            **_role_dashboard_data(persona),
            "page_title": "Dokumen",
            "page_description": "Arsip dokumen sesuai akun.",
            "documents": build_portal_document_model(current_user),
        },
    )


@portal_bp.route("/documents/<int:attachment_id>/view")
@role_required(*PORTAL_READONLY_ROLES)
def view_document(attachment_id):
    attachment = get_portal_owned_document(current_user, attachment_id)
    if not attachment:
        abort(404)
    if not is_inline_view_safe(attachment):
        abort(403)
    try:
        file_path = get_attachment_file_path(attachment)
    except FileNotFoundError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("portal.documents"))
    response = send_file(
        str(file_path),
        as_attachment=False,
        download_name=attachment.original_filename,
        mimetype=attachment.mime_type or "application/octet-stream",
        max_age=0,
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@portal_bp.route("/documents/<int:attachment_id>/download")
@role_required(*PORTAL_READONLY_ROLES)
def download_document(attachment_id):
    attachment = get_portal_owned_document(current_user, attachment_id)
    if not attachment:
        abort(404)
    try:
        file_path = get_attachment_file_path(attachment)
    except FileNotFoundError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("portal.documents"))
    response = send_file(
        str(file_path),
        as_attachment=True,
        download_name=attachment.original_filename,
        mimetype=attachment.mime_type or "application/octet-stream",
        max_age=0,
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@portal_bp.route("/approvals")
@role_required(*PORTAL_READONLY_ROLES)
def approvals():
    persona = (
        _pt_persona()
        if current_user.role == ROLE_PORTAL_CLIENT
        else _mandor_persona()
        if current_user.role == ROLE_PORTAL_SUBCLIENT
        else _customer_persona()
    )
    return render_template(
        "portal/approvals.html",
        data={
            **_role_dashboard_data(persona),
            "page_title": "Approval",
            "page_description": "Persetujuan portal membaca approval_requests  yang dibuat user ini.",
            "approvals": build_portal_approval_model(current_user),
        },
    )


@portal_bp.route("/notifications/<int:notification_id>/read", methods=["POST"])
@role_required(*PORTAL_READONLY_ROLES)
def read_notification(notification_id):
    notification = get_notification_or_none(notification_id, branch_id=current_user.branch_id)
    if not notification or not can_user_access_notification(notification, current_user):
        abort(404)
    mark_notification_read(notification)
    flash("Notifikasi ditandai sudah dibaca.", "success")
    return redirect(url_for("portal.notifications"))


@portal_bp.route("/notifications/<int:notification_id>/dismiss", methods=["POST"])
@role_required(*PORTAL_READONLY_ROLES)
def dismiss_notification(notification_id):
    notification = get_notification_or_none(notification_id, branch_id=current_user.branch_id)
    if not notification or not can_user_access_notification(notification, current_user):
        abort(404)
    mark_notification_dismissed(notification)
    flash("Notifikasi disembunyikan.", "success")
    return redirect(url_for("portal.notifications"))


@portal_bp.route("/calendar")
@role_required(*PORTAL_READONLY_ROLES)
def calendar():
    persona = (
        _pt_persona()
        if current_user.role == ROLE_PORTAL_CLIENT
        else _mandor_persona()
        if current_user.role == ROLE_PORTAL_SUBCLIENT
        else _customer_persona()
    )
    return render_template(
        "portal/calendar.html",
        data={
            **_role_dashboard_data(persona),
            "page_title": "Kalender Operasional",
            "page_description": "Kalender membaca draft order, tagihan jatuh tempo, kontrak, dan pengiriman data utama.",
            "calendar": build_portal_calendar_model(current_user),
        },
    )


@portal_bp.route("/profile")
@role_required(*PORTAL_READONLY_ROLES)
def profile():
    return render_template(
        "portal/profile.html",
        data={
            **_role_dashboard_data(_current_portal_persona()),
            "profile": build_portal_profile(current_user),
            "page_title": "Profil Portal",
            "page_description": "Akses akun portal terhadap data master.",
        },
    )


@portal_bp.route("/customers")
@role_required(*PORTAL_INTERNAL_ROLES)
def customers():
    data = {
        "status_label": "Hanya dilihat",
        "active_role": current_user.role,
        "branch_id": current_user.branch_id,
        "directory": build_portal_customer_directory(current_user),
    }
    return render_template("portal/customers.html", data=data)


@portal_bp.route("/mandors")
@role_required(*PORTAL_INTERNAL_ROLES)
def mandors():
    data = {
        "status_label": "Hanya dilihat",
        "active_role": current_user.role,
        "branch_id": current_user.branch_id,
        "directory": build_portal_mandor_directory(current_user),
    }
    return render_template("portal/mandors.html", data=data)


@portal_bp.route("/locations")
@role_required(*PORTAL_INTERNAL_ROLES)
def locations():
    data = {
        "status_label": "Hanya dilihat",
        "active_role": current_user.role,
        "branch_id": current_user.branch_id,
        "directory": build_portal_location_directory(current_user),
    }
    return render_template("portal/locations.html", data=data)


@portal_bp.route("/orders/draft", methods=["GET", "POST"])
@role_required(*PORTAL_READONLY_ROLES)
def draft_order():
    if current_user.role == ROLE_PORTAL_CLIENT:
        # Order untuk mandor tetap dibuat mandor itu sendiri; PT hanya memesan
        # untuk unit order langsungnya ("PT X — Langsung"), dan hanya kalau
        # admin sudah mengaktifkannya di Master Client.
        from app.services.portal_mapping_service import build_portal_external_scope
        from app.services.portal_order_draft_service import orderable_location_ids

        if not orderable_location_ids(current_user, build_portal_external_scope(current_user)):
            flash(
                f"Portal {T.client} memantau pesanan {T.sub_client_lower}. Untuk memesan sendiri, "
                f"minta admin mengaktifkan Order Langsung dan menambahkan {T.location_lower}.",
                "info",
            )
            return redirect(url_for("portal.pt_dashboard"))
    if request.method == "POST":
        draft, created, error = create_portal_order_draft(current_user, request.form)
        if error:
            flash(error, "danger")
            context = build_portal_draft_order_context(current_user)
            return render_template(
                "portal/draft_order.html",
                data={
                    **_role_dashboard_data(_current_portal_persona()),
                    "status_label": "Menunggu admin",
                    "context": context,
                    "idempotency_key": request.form.get("idempotency_key") or uuid4().hex,
                },
            ), 400

        if created:
            flash("Draft order portal berhasil dikirim dan menunggu konfirmasi admin.", "success")
        else:
            flash("Draft order yang sama sudah pernah diterima. Tidak dibuat duplikat.", "info")
        return redirect(url_for("portal.draft_order"))

    context = build_portal_draft_order_context(current_user)
    data = {
        **_role_dashboard_data(_current_portal_persona()),
        "status_label": "Menunggu admin",
        "context": context,
        "idempotency_key": uuid4().hex,
    }
    return render_template("portal/draft_order.html", data=data)


@portal_bp.route("/orders/draft/<int:draft_id>/payment-proof", methods=["POST"])
@role_required(*PORTAL_READONLY_ROLES)
def upload_draft_payment_proof(draft_id):
    try:
        result = upload_portal_order_draft_payment_proof(
            current_user,
            draft_id=draft_id,
            file_storage=request.files.get("proof_file"),
            notes=request.form.get("notes"),
        )
    except (PortalPaymentProofError, AttachmentValidationError) as exc:
        flash(str(exc), "danger")
    else:
        flash(f"Bukti pembayaran awal draft #{result['draft_id']} berhasil diunggah dan menunggu finance.", "success")
    return redirect(url_for("portal.order_status"))


@portal_bp.route("/orders/status")
@role_required(*PORTAL_READONLY_ROLES)
def order_status():
    data = {
        **_role_dashboard_data(
            _pt_persona()
            if current_user.role == ROLE_PORTAL_CLIENT
            else _mandor_persona()
            if current_user.role == ROLE_PORTAL_SUBCLIENT
            else _customer_persona()
            if current_user.role == ROLE_PORTAL_CUSTOMER
            else {
                "eyebrow": "Portal",
                "title": "Status Pesanan",
                "description": "Status pesanan portal.",
                "scope_label": "Akses portal",
                "primary_note": "Status dibaca dari data utama.",
            }
        ),
        "status_label": "Hanya dilihat",
        "active_role": current_user.role,
        "branch_id": current_user.branch_id,
        "page_title": "Status Pesanan Portal",
        "page_description": "Status draft dan order internal milik akun portal ini tanpa detail finansial.",
        "orders": build_portal_order_status_context(current_user),
    }
    return render_template("portal/order_status.html", data=data)


@portal_bp.route("/admin/order-drafts")
@role_required("ADMIN")
def admin_order_drafts():
    review_queue = build_portal_order_draft_review_queue(current_user)
    drafts = review_queue["drafts"]
    data = {
        "status_label": "Konfirmasi admin",
        "active_role": current_user.role,
        "branch_id": current_user.branch_id,
        "drafts": drafts,
        "review_rows": review_queue["rows"],
        "sections": review_queue["sections"],
        "summary": review_queue["totals"],
    }
    return render_template("portal/admin_order_drafts.html", data=data)


@portal_bp.route("/admin/order-drafts/<int:draft_id>/confirm", methods=["POST"])
@role_required("ADMIN")
def confirm_order_draft(draft_id):
    draft, converted, error = confirm_portal_order_draft(
        draft_id,
        current_user,
        review_note=request.form.get("review_note"),
    )
    if error:
        flash(error, "warning")
    elif converted:
        flash("Draft order portal berhasil dikonfirmasi ke order harian.", "success")
    else:
        flash("Draft order sudah pernah dikonfirmasi. Tidak dibuat duplikat.", "info")
    return redirect(url_for("portal.admin_order_drafts"))


@portal_bp.route("/admin/order-drafts/<int:draft_id>/reject", methods=["POST"])
@role_required("ADMIN")
def reject_order_draft(draft_id):
    _draft, rejected, error = reject_portal_order_draft(
        draft_id,
        current_user,
        review_note=request.form.get("review_note"),
    )
    if error:
        flash(error, "warning")
    elif rejected:
        flash("Draft order portal ditolak.", "success")
    return redirect(url_for("portal.admin_order_drafts"))


@portal_bp.route("/status")
@role_required(*PORTAL_INTERNAL_ROLES)
def status():
    data = {
        "status_label": "Hanya dilihat",
        "active_role": current_user.role,
        "branch_id": current_user.branch_id,
        "status": build_portal_status_shell(current_user),
    }
    return render_template("portal/status.html", data=data)


@portal_bp.route("/ownership")
@role_required("ADMIN")
def ownership():
    data = {
        "status_label": "Hanya analisis",
        "active_role": current_user.role,
        "branch_id": current_user.branch_id,
        "ownership": build_portal_ownership_analysis(current_user),
    }
    return render_template("portal/ownership.html", data=data)

