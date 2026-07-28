from uuid import uuid4

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
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
from app.services.portal_debt_visibility_service import build_portal_worker_debt_read_model
from app.services.portal_financial_visibility_service import (
    build_portal_invoice_read_model,
    build_portal_payment_history_read_model,
)
from app.services.portal_order_draft_service import (
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
from app.services.portal_payment_instruction_service import build_portal_payment_instruction
from app.services.portal_payment_proof_service import PortalPaymentProofError, upload_portal_payment_proof
from app.services.digital_attachment_service import AttachmentValidationError
from app.services.user_management_service import (
    ROLE_PORTAL_CLIENT,
    ROLE_PORTAL_CUSTOMER,
    ROLE_PORTAL_DELEGATE,
    ROLE_PORTAL_MANDOR,
    ROLE_PORTAL_PT,
)
from app.utils.decorators import role_required


portal_bp = Blueprint("portal", __name__, url_prefix="/portal")
PORTAL_READONLY_ROLES = (
    "ADMIN",
    ROLE_PORTAL_CLIENT,
    ROLE_PORTAL_PT,
    ROLE_PORTAL_MANDOR,
    ROLE_PORTAL_DELEGATE,
    ROLE_PORTAL_CUSTOMER,
)
PORTAL_INTERNAL_ROLES = ("ADMIN",)

PORTAL_ROLE_DASHBOARD_ENDPOINTS = {
    ROLE_PORTAL_CUSTOMER: "portal.customer_dashboard",
    ROLE_PORTAL_MANDOR: "portal.mandor_dashboard",
    ROLE_PORTAL_PT: "portal.pt_dashboard",
    ROLE_PORTAL_CLIENT: "portal.client_dashboard",
    ROLE_PORTAL_DELEGATE: "portal.delegate_dashboard",
}


@portal_bp.before_request
def require_portal_feature_flag():
    if not current_app.config.get("PORTAL_ENABLED", False):
        abort(404)


@portal_bp.route("/login")
def login_entry():
    return redirect(url_for("auth.login"))


@portal_bp.route("/register")
def register():
    data = {
        "title": "Registrasi Portal",
        "description": "Fondasi permintaan akun eksternal. Pembuatan user tetap dilakukan melalui User Management ERP agar role, branch, dan mapping tidak terpisah.",
        "steps": [
            "Customer, Mandor, atau PT mengirim permintaan akun.",
            "Admin memverifikasi data terhadap master Client/Mandor/Lokasi existing.",
            "Admin membuat user dan mapping portal melalui ERP.",
            "User login memakai autentikasi ERP existing.",
        ],
        "actions": [
            {"label": "Masuk", "url": url_for("auth.login"), "icon": "bi-box-arrow-in-right", "variant": "primary"},
        ],
    }
    return render_template("portal/register.html", data=data)


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
        ROLE_PORTAL_PT,
        ROLE_PORTAL_MANDOR,
        ROLE_PORTAL_DELEGATE,
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
                "caption": "Akun eksternal tetap memakai tabel users existing.",
            },
            {
                "title": "Mapping Aktif",
                "value": mapping_query.filter(PortalUserMapping.is_active.is_(True)).count(),
                "caption": "Penghubung user ke client/mandor/lokasi existing, bukan master baru.",
            },
            {
                "title": "Draft Pending",
                "value": draft_query.filter(PortalOrderDraft.status == "PENDING_ADMIN_CONFIRMATION").count(),
                "caption": "Antrian sebelum dikonfirmasi menjadi order internal existing.",
            },
        ],
        "sources": [
            {
                "area": "Akun portal",
                "erp_source": "users.role",
                "rule": "Tidak ada auth paralel. Login tetap memakai auth ERP.",
            },
            {
                "area": "Client, mandor, lokasi",
                "erp_source": "clients, mandors, delivery_locations",
                "rule": "Portal hanya membaca/mapping ke master existing. Master tetap dikelola di modul Master Data.",
            },
            {
                "area": "Draft order",
                "erp_source": "portal_order_drafts -> daily_orders setelah konfirmasi admin",
                "rule": "Draft belum menyentuh produksi, stok, invoice, payment, atau jurnal.",
            },
            {
                "area": "Invoice dan payment",
                "erp_source": "invoices, payments, receivables",
                "rule": "Portal hanya read-only sesuai ownership. Posting tetap lewat modul Finance.",
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


def _role_dashboard_data(persona):
    return {
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


def _portal_feature_data(persona, feature):
    data = _role_dashboard_data(persona)
    data["feature"] = feature
    return data


def _portal_feature_response(persona, feature):
    return render_template("portal/feature_shell.html", data=_portal_feature_data(persona, feature))


def _customer_persona():
    return {
        "eyebrow": "Portal Pelanggan Umum",
        "title": "Dashboard Pelanggan",
        "description": "Ringkasan akses pelanggan umum. Order dan pembayaran aktual tetap mengikuti workflow ERP existing.",
        "scope_label": "Akses pribadi",
        "primary_note": "Pelanggan umum belum membuka piutang/worker debt. Prepayment tetap wajib sebelum order diproses.",
    }


def _mandor_persona():
    return {
        "eyebrow": "Portal Mandor",
        "title": "Dashboard Mandor",
        "description": "Ringkasan mandor berdasarkan mapping ke mandor dan lokasi existing.",
        "scope_label": "Scope mandor",
        "primary_note": "Mandor hanya melihat order, invoice, hutang pekerja, dan pembayaran dalam ownership mapping-nya.",
    }


def _pt_persona():
    return {
        "eyebrow": "Portal PT",
        "title": "Dashboard PT",
        "description": "Ringkasan PT/perusahaan berdasarkan mapping client existing.",
        "scope_label": "Scope client/PT",
        "primary_note": "PT melihat mandor/lokasi, invoice, pembayaran, dan closing dalam client ownership existing.",
    }


@portal_bp.route("/customer")
@role_required(ROLE_PORTAL_CUSTOMER)
def customer_dashboard():
    return render_template(
        "portal/role_dashboard.html",
        data=_role_dashboard_data(_customer_persona()),
    )


@portal_bp.route("/customer/order")
@role_required(ROLE_PORTAL_CUSTOMER)
def customer_order():
    return render_template(
        "portal/draft_order.html",
        data={
            **_role_dashboard_data(_customer_persona()),
            "status_label": "Prepayment guard",
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
            "status_label": "Read-only",
            "page_title": "Riwayat Order",
            "page_description": "Riwayat order pelanggan dibaca dari draft portal dan order ERP yang terhubung.",
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
            "status_label": "Read-only",
            "page_title": "Tracking Order",
            "page_description": "Tracking memakai status draft dan order internal existing. Production/delivery ditampilkan saat relasi tersedia.",
            "orders": build_portal_order_status_context(current_user),
        },
    )


@portal_bp.route("/customer/invoices")
@role_required(ROLE_PORTAL_CUSTOMER)
def customer_invoices():
    return render_template(
        "portal/mobile_invoices.html",
        data={
            **_role_dashboard_data(_customer_persona()),
            "page_title": "Invoice",
            "page_description": "Invoice pelanggan umum mengikuti aturan prepayment dan visibility portal.",
            "invoice_model": build_portal_mobile_invoice_cards(current_user),
        },
    )


@portal_bp.route("/customer/payments")
@role_required(ROLE_PORTAL_CUSTOMER)
def customer_payments():
    return render_template(
        "portal/mobile_payments.html",
        data={
            **_role_dashboard_data(_customer_persona()),
            "page_title": "Pembayaran",
            "page_description": "Riwayat pembayaran pelanggan mengikuti payment visibility portal.",
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
            "page_description": "Komplain pelanggan tersambung ke Complaint Management ERP existing.",
            "complaints": build_portal_complaint_model(current_user),
        },
    )


@portal_bp.route("/mandor")
@role_required(ROLE_PORTAL_MANDOR)
def mandor_dashboard():
    return render_template(
        "portal/role_dashboard.html",
        data=_role_dashboard_data(_mandor_persona()),
    )


@portal_bp.route("/mandor/order")
@role_required(ROLE_PORTAL_MANDOR)
def mandor_order():
    return render_template(
        "portal/draft_order.html",
        data={
            **_role_dashboard_data(_mandor_persona()),
            "status_label": "Pending admin",
            "context": build_portal_draft_order_context(current_user),
            "idempotency_key": uuid4().hex,
        },
    )


@portal_bp.route("/mandor/workers")
@role_required(ROLE_PORTAL_MANDOR)
def mandor_workers():
    return render_template(
        "portal/mobile_workers.html",
        data={
            **_role_dashboard_data(_mandor_persona()),
            "worker_model": build_portal_mobile_worker_cards(current_user),
        },
    )


@portal_bp.route("/mandor/catering-debts")
@role_required(ROLE_PORTAL_MANDOR)
def mandor_catering_debts():
    return render_template(
        "portal/mobile_invoices.html",
        data={
            **_role_dashboard_data(_mandor_persona()),
            "page_title": "Hutang Catering",
            "page_description": "Outstanding catering dari invoice ERP existing.",
            "invoice_model": build_portal_mobile_invoice_cards(current_user),
        },
    )


@portal_bp.route("/mandor/canteen-debts")
@role_required(ROLE_PORTAL_MANDOR)
def mandor_canteen_debts():
    return render_template(
        "portal/mobile_debts.html",
        data={
            **_role_dashboard_data(_mandor_persona()),
            "page_title": "Hutang Warung",
            "page_description": "Hutang pekerja dari WorkerDebt ERP existing.",
            "debt_model": build_portal_mobile_debt_cards(current_user),
        },
    )


@portal_bp.route("/mandor/installments")
@role_required(ROLE_PORTAL_MANDOR)
def mandor_installments():
    return render_template(
        "portal/mobile_debts.html",
        data={
            **_role_dashboard_data(_mandor_persona()),
            "page_title": "Cicilan",
            "page_description": "Cicilan ditampilkan sebagai sisa hutang dan riwayat pembayaran dari data ERP existing. Jadwal cicilan formal menunggu approval jika butuh schema.",
            "debt_model": build_portal_mobile_debt_cards(current_user),
        },
    )


@portal_bp.route("/mandor/invoices")
@role_required(ROLE_PORTAL_MANDOR)
def mandor_invoices():
    return render_template(
        "portal/mobile_invoices.html",
        data={
            **_role_dashboard_data(_mandor_persona()),
            "page_title": "Invoice",
            "page_description": "Invoice mandor sesuai ownership mapping.",
            "invoice_model": build_portal_mobile_invoice_cards(current_user),
        },
    )


@portal_bp.route("/mandor/payments")
@role_required(ROLE_PORTAL_MANDOR)
def mandor_payments():
    return render_template(
        "portal/mobile_payments.html",
        data={
            **_role_dashboard_data(_mandor_persona()),
            "page_title": "Riwayat Pembayaran",
            "page_description": "Payment mandor dari payments ERP existing.",
        },
    )


@portal_bp.route("/pt")
@role_required(ROLE_PORTAL_PT)
def pt_dashboard():
    return render_template(
        "portal/role_dashboard.html",
        data=_role_dashboard_data(_pt_persona()),
    )


@portal_bp.route("/pt/mandors")
@role_required(ROLE_PORTAL_PT)
def pt_mandors():
    return render_template(
        "portal/mobile_mandors.html",
        data={
            **_role_dashboard_data(_pt_persona()),
            "mandor_model": build_portal_mobile_mandor_cards(current_user),
        },
    )


@portal_bp.route("/pt/invoices")
@role_required(ROLE_PORTAL_PT)
def pt_invoices():
    return render_template(
        "portal/mobile_invoices.html",
        data={
            **_role_dashboard_data(_pt_persona()),
            "page_title": "Seluruh Invoice",
            "page_description": "Invoice PT dari invoice ERP existing.",
            "invoice_model": build_portal_mobile_invoice_cards(current_user),
        },
    )


@portal_bp.route("/pt/receivables")
@role_required(ROLE_PORTAL_PT)
def pt_receivables():
    return render_template(
        "portal/mobile_invoices.html",
        data={
            **_role_dashboard_data(_pt_persona()),
            "page_title": "Seluruh Piutang",
            "page_description": "Piutang dihitung dari remaining invoice dan payment existing.",
            "invoice_model": build_portal_mobile_invoice_cards(current_user),
        },
    )


@portal_bp.route("/pt/contracts")
@role_required(ROLE_PORTAL_PT)
def pt_contracts():
    return render_template(
        "portal/contracts.html",
        data={
            **_role_dashboard_data(_pt_persona()),
            "page_title": "Seluruh Kontrak",
            "page_description": "Kontrak PT dibaca dari CustomerContract ERP existing sesuai client/PT scope.",
            "contracts": build_portal_contract_model(current_user),
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
            if current_user.role == ROLE_PORTAL_PT
            else _mandor_persona()
            if current_user.role == ROLE_PORTAL_MANDOR
            else _customer_persona()
            if current_user.role == ROLE_PORTAL_CUSTOMER
            else {
                "eyebrow": "Portal",
                "title": "Instruksi Pembayaran",
                "description": "Instruksi pembayaran portal.",
                "scope_label": "Scope portal",
                "primary_note": "Instruksi dibaca dari invoice ERP existing.",
            }
        ),
        "page_title": "Instruksi Pembayaran",
        "page_description": "Upload bukti masuk ke DigitalAttachment ERP existing dan menunggu verifikasi finance.",
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
                "eyebrow": "Portal Client",
                "title": "Dashboard Client",
                "description": "Ringkasan client/PIC berdasarkan mapping client atau delegasi existing.",
                "scope_label": "Scope client",
                "primary_note": "Role ini dipertahankan untuk kompatibilitas data client existing.",
            }
        ),
    )


@portal_bp.route("/delegate")
@role_required(ROLE_PORTAL_DELEGATE)
def delegate_dashboard():
    return render_template(
        "portal/role_dashboard.html",
        data=_role_dashboard_data(
            {
                "eyebrow": "Portal Delegasi",
                "title": "Dashboard Delegasi",
                "description": "Ringkasan delegasi/PIC/lokasi terbatas berdasarkan mapping eksplisit.",
                "scope_label": "Scope delegasi",
                "primary_note": "Delegasi hanya melihat data yang didelegasikan secara eksplisit.",
            }
        ),
    )


@portal_bp.route("/invoices")
@role_required(*PORTAL_READONLY_ROLES)
def invoices():
    data = {
        "status_label": "Read-only",
        "active_role": current_user.role,
        "branch_id": current_user.branch_id,
        "model": build_portal_invoice_read_model(current_user),
    }
    return render_template("portal/invoices.html", data=data)


@portal_bp.route("/payments")
@role_required(*PORTAL_READONLY_ROLES)
def payments():
    data = {
        "status_label": "Read-only",
        "active_role": current_user.role,
        "branch_id": current_user.branch_id,
        "model": build_portal_payment_history_read_model(current_user),
    }
    return render_template("portal/payments.html", data=data)


@portal_bp.route("/debts")
@role_required(*PORTAL_READONLY_ROLES)
def debts():
    data = {
        "status_label": "Read-only",
        "active_role": current_user.role,
        "branch_id": current_user.branch_id,
        "model": build_portal_worker_debt_read_model(current_user),
    }
    return render_template("portal/debts.html", data=data)


@portal_bp.route("/closing")
@role_required(*PORTAL_READONLY_ROLES)
def closing():
    data = {
        "status_label": "Read-only",
        "active_role": current_user.role,
        "branch_id": current_user.branch_id,
        "model": build_portal_closing_visibility(
            current_user,
            year=request.args.get("year"),
            month=request.args.get("month"),
        ),
    }
    return render_template("portal/closing.html", data=data)


@portal_bp.route("/profile")
@role_required(*PORTAL_READONLY_ROLES)
def profile():
    data = {
        "status_label": "Read-only",
        "active_role": current_user.role,
        "branch_id": current_user.branch_id,
        "profile": build_portal_profile(current_user),
    }
    return render_template("portal/profile.html", data=data)


@portal_bp.route("/customers")
@role_required(*PORTAL_INTERNAL_ROLES)
def customers():
    data = {
        "status_label": "Read-only",
        "active_role": current_user.role,
        "branch_id": current_user.branch_id,
        "directory": build_portal_customer_directory(current_user),
    }
    return render_template("portal/customers.html", data=data)


@portal_bp.route("/mandors")
@role_required(*PORTAL_INTERNAL_ROLES)
def mandors():
    data = {
        "status_label": "Read-only",
        "active_role": current_user.role,
        "branch_id": current_user.branch_id,
        "directory": build_portal_mandor_directory(current_user),
    }
    return render_template("portal/mandors.html", data=data)


@portal_bp.route("/locations")
@role_required(*PORTAL_INTERNAL_ROLES)
def locations():
    data = {
        "status_label": "Read-only",
        "active_role": current_user.role,
        "branch_id": current_user.branch_id,
        "directory": build_portal_location_directory(current_user),
    }
    return render_template("portal/locations.html", data=data)


@portal_bp.route("/orders/draft", methods=["GET", "POST"])
@role_required(*PORTAL_READONLY_ROLES)
def draft_order():
    if request.method == "POST":
        draft, created, error = create_portal_order_draft(current_user, request.form)
        if error:
            flash(error, "danger")
            context = build_portal_draft_order_context(current_user)
            return render_template(
                "portal/draft_order.html",
                data={
                    "status_label": "Pending admin",
                    "active_role": current_user.role,
                    "branch_id": current_user.branch_id,
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
        "status_label": "Pending admin",
        "active_role": current_user.role,
        "branch_id": current_user.branch_id,
        "context": context,
        "idempotency_key": uuid4().hex,
    }
    return render_template("portal/draft_order.html", data=data)


@portal_bp.route("/orders/status")
@role_required(*PORTAL_READONLY_ROLES)
def order_status():
    data = {
        **_role_dashboard_data(
            _pt_persona()
            if current_user.role == ROLE_PORTAL_PT
            else _mandor_persona()
            if current_user.role == ROLE_PORTAL_MANDOR
            else _customer_persona()
            if current_user.role == ROLE_PORTAL_CUSTOMER
            else {
                "eyebrow": "Portal",
                "title": "Status Order",
                "description": "Status order portal.",
                "scope_label": "Scope portal",
                "primary_note": "Status dibaca dari ERP existing.",
            }
        ),
        "status_label": "Read-only",
        "active_role": current_user.role,
        "branch_id": current_user.branch_id,
        "page_title": "Status Order Portal",
        "page_description": "Status draft dan order internal milik akun portal ini tanpa detail finansial.",
        "orders": build_portal_order_status_context(current_user),
    }
    return render_template("portal/order_status.html", data=data)


@portal_bp.route("/admin/order-drafts")
@role_required("ADMIN")
def admin_order_drafts():
    data = {
        "status_label": "Admin confirmation",
        "active_role": current_user.role,
        "branch_id": current_user.branch_id,
        "drafts": list_pending_portal_order_drafts(current_user),
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
        "status_label": "Read-only",
        "active_role": current_user.role,
        "branch_id": current_user.branch_id,
        "status": build_portal_status_shell(current_user),
    }
    return render_template("portal/status.html", data=data)


@portal_bp.route("/ownership")
@role_required("ADMIN")
def ownership():
    data = {
        "status_label": "Analysis only",
        "active_role": current_user.role,
        "branch_id": current_user.branch_id,
        "ownership": build_portal_ownership_analysis(current_user),
    }
    return render_template("portal/ownership.html", data=data)
