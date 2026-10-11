from uuid import uuid4

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user

from app.models.system import PortalOrderDraft
from app.services.portal_access_service import (
    build_portal_access_scope,
    build_portal_profile,
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
    build_portal_pending_draft_payments,
    confirm_portal_order_draft,
    create_portal_order_draft,
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
from app.extensions import limiter
from app.models.contract import CustomerContract
from app.services.customer_contract_document_service import (
    CustomerContractDocumentError,
    get_contract_document,
    list_contract_documents_for_contract,
    send_contract_signing_otp,
    verify_and_sign_contract_document_otp,
)
from app.services.portal_mapping_service import build_portal_external_scope
from app.services.digital_attachment_service import (
    AttachmentValidationError,
    get_attachment_file_path,
    get_attachment_or_none,
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
    update_portal_user_email,
)
from app.utils.decorators import module_required, role_required
from app.services.branch_module_service import WORKER_DEBT
from app.utils.terms import T
from app.services.public_site_service import auth_context


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
            user = register_portal_customer(request.form, files=request.files.getlist("location_photos"))
        except ValueError as exc:
            flash(str(exc), "danger")
            data = _customer_register_page_data()
            data["form"] = request.form
            return render_template("portal/register.html", data=data, site=auth_context()), 400

        flash("Akun pelanggan berhasil dibuat. Silakan masuk untuk mulai memesan.", "success")
        current_app.logger.info("Registrasi pelanggan portal berhasil untuk user_id=%s", user.id)
        return redirect(url_for("auth.login"))

    return render_template("portal/register.html", data=_customer_register_page_data(), site=auth_context())


def _customer_register_page_data():
    from app.services.pricing_service import active_zones

    branches = list_active_branches()
    data = {
        "title": "Daftar Pelanggan",
        "description": "Buat akun pelanggan umum untuk memesan catering.",
        "branches": branches,
        "zones": [(branch, zone) for branch in branches for zone in active_zones(branch.id)],
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
    """Daftar akun portal dan ke mana masing-masing terhubung (gladi pilot 2026-09-28)."""
    from app.services.user_management_service import portal_account_rows

    branch_id = None if current_user.role == "OWNER" else current_user.branch_id
    rows = portal_account_rows(branch_id)
    draft_query = PortalOrderDraft.query.filter(PortalOrderDraft.status == "PENDING_ADMIN_CONFIRMATION")
    if branch_id is not None:
        draft_query = draft_query.filter(PortalOrderDraft.branch_id == branch_id)

    data = {
        "status_label": "Internal",
        "rows": rows,
        "can_edit_users": current_user.role == "OWNER",
        "cards": [
            {"title": "Akun Portal", "value": len(rows), "caption": f"{T.client}, {T.sub_client_lower}, dan pelanggan umum."},
            {
                "title": "Belum Terhubung",
                "value": sum(1 for row in rows if not row["link"]),
                "caption": "Akun ini belum bisa melihat apa pun sampai dihubungkan.",
            },
            {"title": "Pesanan Menunggu", "value": draft_query.count(), "caption": "Draft portal yang menunggu konfirmasi admin."},
        ],
    }
    return render_template("portal/dashboard.html", data=data)


@portal_bp.route("/my-dashboard")
@role_required(*PORTAL_READONLY_ROLES)
def my_dashboard():
    role_endpoint = PORTAL_ROLE_DASHBOARD_ENDPOINTS.get(current_user.role)
    if role_endpoint:
        return redirect(url_for(role_endpoint))
    if current_user.role in ("OWNER", "ADMIN"):
        # Staf internal tidak punya "dashboard portal"; halaman portal mereka
        # adalah daftar akun portal (perapian menu 2026-09-28).
        return redirect(url_for("portal.dashboard"))

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
    if include_center:
        # Beranda (portal/_dashboard_*.html) hanya membaca data.center dan
        # data.scope; command center sudah membangun pesanan, tagihan,
        # pembayaran, dan hutang sendiri -- jangan dibangun dua kali.
        from app.services.menu_schedule_service import get_customer_today_tomorrow_menu
        from app.services.auto_order_service import build_portal_today_tomorrow_orders_context

        return {
            "persona": persona,
            "active_role": current_user.role,
            "branch_id": current_user.branch_id,
            "scope": build_portal_access_scope(current_user),
            "center": build_portal_command_center(current_user),
            "today_tomorrow_menus": get_customer_today_tomorrow_menu(current_user.branch_id),
            "standing_orders": build_portal_today_tomorrow_orders_context(current_user),
        }
    user = current_user._get_current_object()
    year, month = request.args.get("year"), request.args.get("month")
    # Dihitung hanya bila template halaman benar-benar membacanya (halaman
    # Pesan misalnya tidak memakai tagihan/hutang/closing sama sekali).
    return {
        "persona": persona,
        "active_role": current_user.role,
        "branch_id": current_user.branch_id,
        "scope": build_portal_access_scope(current_user),
        "orders": _LazyModel(lambda: build_portal_order_status_context(user)),
        "invoices": _LazyModel(lambda: build_portal_invoice_read_model(user, limit=5)),
        "payments": _LazyModel(lambda: build_portal_payment_history_read_model(user, limit=5)),
        "debts": _LazyModel(lambda: build_portal_worker_debt_read_model(user, limit=5)),
        "closing": _LazyModel(lambda: build_portal_closing_visibility(user, year=year, month=month)),
    }


class _LazyModel:
    """Model baca portal yang baru dibangun saat pertama dipakai (template/route)."""

    __slots__ = ("_factory", "_value", "_ready")

    def __init__(self, factory):
        self._factory = factory
        self._value = None
        self._ready = False

    def _resolve(self):
        if not self._ready:
            self._value = self._factory()
            self._ready = True
        return self._value

    def __getattr__(self, name):
        return getattr(self._resolve(), name)

    def __getitem__(self, key):
        return self._resolve()[key]

    def __contains__(self, key):
        return key in self._resolve()

    def __iter__(self):
        return iter(self._resolve())

    def __len__(self):
        return len(self._resolve())

    def __bool__(self):
        return bool(self._resolve())

    def get(self, key, default=None):
        return self._resolve().get(key, default)


def _customer_persona():
    return {
        "eyebrow": "Portal Pelanggan Umum",
        "title": "Beranda Pelanggan",
        "description": "Pesanan, pembayaran, dan tagihan Anda di satu tempat.",
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
        "description": "Ringkasan pesanan, tagihan, dan pembayaran.",
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
    from app.services.portal_order_draft_service import build_portal_customer_order_billing

    order_billing = build_portal_customer_order_billing(current_user)
    return render_template(
        "portal/mobile_payments.html",
        data={
            **_role_dashboard_data(_customer_persona()),
            "page_title": "Tagihan & Pembayaran",
            "page_description": "Bayar pesanan di muka, lalu unggah buktinya. Riwayat pembayaran ada di bawah.",
            "order_billing": order_billing,
            "pending_payments": [row for row in order_billing["rows"] if row["needs_payment"]],
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
            "page_description": "Laporkan masalah pesanan; tim kami menindaklanjutinya di sini.",
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
@module_required(WORKER_DEBT)
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
            "page_description": "Sisa tagihan catering Anda.",
            "invoice_model": build_portal_mobile_invoice_cards(current_user),
        },
    )


@portal_bp.route("/mandor/canteen-debts")
@role_required(ROLE_PORTAL_SUBCLIENT)
@module_required(WORKER_DEBT)
def mandor_canteen_debts():
    return render_template(
        "portal/mobile_debts.html",
        data={
            **_role_dashboard_data(_mandor_persona()),
            "page_title": "Hutang Warung",
            "page_description": f"Hutang warung {T.worker_lower} Anda.",
            "debt_model": build_portal_mobile_debt_cards(current_user),
        },
    )


@portal_bp.route("/mandor/installments")
@role_required(ROLE_PORTAL_SUBCLIENT)
@module_required(WORKER_DEBT)
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
            "pending_payments": build_portal_pending_draft_payments(current_user),
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
            "page_description": "Riwayat pembayaran yang sudah diterima.",
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
            "page_description": f"Semua tagihan {T.client_lower} Anda.",
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
            "page_description": "Sisa tagihan yang belum dibayar.",
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
            "page_description": f"Kontrak {T.client_lower} Anda dan masa berlakunya.",
            "contracts": build_portal_contract_model(current_user),
        },
    )


def _can_portal_user_access_contract(user, contract) -> bool:
    if not contract or contract.branch_id != getattr(user, "branch_id", None):
        return False
    scope = build_portal_external_scope(user)
    return contract.client_id in scope.client_ids


@portal_bp.route("/contracts")
@role_required(ROLE_PORTAL_CLIENT, ROLE_PORTAL_SUBCLIENT)
def portal_contracts():
    persona = _pt_persona() if current_user.role == ROLE_PORTAL_CLIENT else _mandor_persona()
    return render_template(
        "portal/contracts.html",
        data={
            **_role_dashboard_data(persona),
            "page_title": "Seluruh Kontrak",
            "page_description": f"Kontrak {T.client_lower} Anda dan dokumen resminya.",
            "contracts": build_portal_contract_model(current_user),
        },
    )


@portal_bp.route("/contracts/<int:contract_id>/documents")
@role_required(ROLE_PORTAL_CLIENT, ROLE_PORTAL_SUBCLIENT)
def portal_contract_documents(contract_id):
    contract = CustomerContract.query.filter_by(id=contract_id, branch_id=current_user.branch_id).first()
    if not contract or not _can_portal_user_access_contract(current_user, contract):
        abort(404)
    persona = _pt_persona() if current_user.role == ROLE_PORTAL_CLIENT else _mandor_persona()
    documents = list_contract_documents_for_contract(contract.id, branch_id=current_user.branch_id)
    return render_template(
        "portal/contract_documents.html",
        data=_role_dashboard_data(persona),
        contract=contract,
        documents=documents,
    )


@portal_bp.route("/contracts/<int:contract_id>/documents/<int:document_id>/print")
@role_required(ROLE_PORTAL_CLIENT, ROLE_PORTAL_SUBCLIENT)
def portal_contract_document_print(contract_id, document_id):
    contract = CustomerContract.query.filter_by(id=contract_id, branch_id=current_user.branch_id).first()
    if not contract or not _can_portal_user_access_contract(current_user, contract):
        abort(404)
    doc = get_contract_document(document_id, branch_id=current_user.branch_id)
    if not doc or doc.contract_id != contract_id:
        abort(404)
    from app.services.customer_contract_document_service import contract_document_print_html

    return contract_document_print_html(doc)


@portal_bp.route("/contracts/<int:contract_id>/documents/<int:document_id>/request-otp", methods=["POST"])
@limiter.limit("3 per 15 minutes", methods=["POST"])
@role_required(ROLE_PORTAL_CLIENT)
def portal_contract_document_request_otp(contract_id, document_id):
    contract = CustomerContract.query.filter_by(id=contract_id, branch_id=current_user.branch_id).first()
    if not contract or not _can_portal_user_access_contract(current_user, contract):
        abort(404)
    try:
        ok, msg = send_contract_signing_otp(
            document_id=document_id,
            user_id=current_user.id,
            branch_id=current_user.branch_id,
        )
        flash(msg, "success")
    except CustomerContractDocumentError as err:
        flash(str(err), "danger")
    return redirect(url_for("portal.portal_contract_documents", contract_id=contract_id))


@portal_bp.route("/contracts/<int:contract_id>/documents/<int:document_id>/verify-otp", methods=["POST"])
@limiter.limit("5 per 15 minutes", methods=["POST"])
@role_required(ROLE_PORTAL_CLIENT)
def portal_contract_document_verify_otp(contract_id, document_id):
    contract = CustomerContract.query.filter_by(id=contract_id, branch_id=current_user.branch_id).first()
    if not contract or not _can_portal_user_access_contract(current_user, contract):
        abort(404)
    otp_code = request.form.get("otp_code")
    try:
        doc = verify_and_sign_contract_document_otp(
            document_id=document_id,
            user_id=current_user.id,
            otp_code=otp_code,
            branch_id=current_user.branch_id,
        )
        flash(f"Dokumen {doc.document_number} berhasil disetujui dan ditandatangani secara digital.", "success")
    except CustomerContractDocumentError as err:
        flash(str(err), "danger")
    return redirect(url_for("portal.portal_contract_documents", contract_id=contract_id))


@portal_bp.route("/contracts/<int:contract_id>/documents/<int:document_id>/scan")
@role_required(ROLE_PORTAL_CLIENT, ROLE_PORTAL_SUBCLIENT)
def portal_contract_document_scan(contract_id, document_id):
    contract = CustomerContract.query.filter_by(id=contract_id, branch_id=current_user.branch_id).first()
    if not contract or not _can_portal_user_access_contract(current_user, contract):
        abort(404)
    doc = get_contract_document(document_id, branch_id=current_user.branch_id)
    if not doc or doc.contract_id != contract_id or not doc.scan_attachment_id:
        abort(404)
    attachment = get_attachment_or_none(doc.scan_attachment_id, branch_id=current_user.branch_id)
    if not attachment:
        abort(404)
    try:
        file_path = get_attachment_file_path(attachment)
    except FileNotFoundError as exc:
        flash(f"File lampiran tidak ditemukan: {exc}", "danger")
        return redirect(url_for("portal.portal_contract_documents", contract_id=contract_id))
    return send_file(
        str(file_path),
        as_attachment=True,
        download_name=attachment.original_filename,
        mimetype=attachment.mime_type or "application/octet-stream",
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
                "primary_note": "Instruksi sesuai tagihan Anda.",
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
            "page_title": "Invoice Portal",
            "page_description": "Invoice yang terhubung dengan akun ini.",
            "empty_message": "Belum ada invoice dalam scope portal",
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
            "page_title": "Riwayat Pembayaran",
            "page_description": "Pembayaran yang tercatat untuk akun ini.",
            "empty_message": "Belum ada pembayaran dalam scope portal",
            "model": build_portal_payment_history_read_model(current_user, limit=50),
        },
    )


@portal_bp.route("/debts")
@role_required(*PORTAL_READONLY_ROLES)
@module_required(WORKER_DEBT)
def debts():
    if current_user.role == ROLE_PORTAL_CUSTOMER:
        return redirect(url_for("portal.customer_dashboard"))
    return render_template(
        "portal/debts.html",
        data={
            **_role_dashboard_data(_current_portal_persona()),
            "status_label": "Read-only",
            "page_title": f"Hutang {T.worker}",
            "page_description": f"Hutang warung {T.worker_lower} sesuai akses {T.sub_client_lower}.",
            "empty_message": f"Belum ada hutang {T.worker_lower} dalam scope portal",
            "model": build_portal_worker_debt_read_model(current_user, limit=50),
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
            "page_description": "Jadwal pesanan, pengiriman, jatuh tempo tagihan, dan kontrak.",
            "calendar": build_portal_calendar_model(current_user),
        },
    )


@portal_bp.route("/addresses", methods=["GET", "POST"])
@role_required(ROLE_PORTAL_CUSTOMER, ROLE_PORTAL_SUBCLIENT, ROLE_PORTAL_CLIENT)
def addresses():
    """Alamat antar + titik GPS (keputusan owner 2026-10-04)."""
    from app.services.portal_address_service import PortalAddressError, add_address, address_book, update_address

    if request.method == "POST":
        location_id = request.form.get("location_id", type=int)
        try:
            if location_id:
                location = update_address(current_user, location_id, request.form, files=request.files.getlist("location_photos"))
                flash(f"Alamat {location.location_name} diperbarui.", "success")
            else:
                location = add_address(current_user, request.form, files=request.files.getlist("location_photos"))
                flash(f"Alamat {location.location_name} ditambahkan dan bisa dipilih saat memesan.", "success")
        except PortalAddressError as error:
            flash(str(error), "danger")
        return redirect(url_for("portal.addresses"))
    return render_template(
        "portal/addresses.html",
        data={
            "persona": _current_portal_persona(),
            "book": address_book(current_user),
            "page_title": "Alamat Saya",
            "page_description": "Alamat antar dan titik lokasinya di peta.",
        },
    )


@portal_bp.route("/profile", methods=["GET", "POST"])
@role_required(*PORTAL_READONLY_ROLES)
def profile():
    from app.services.user_profile_service import (
        UserProfileError,
        change_user_password as profile_change_password,
        delete_user_avatar,
        update_user_profile,
        upload_user_avatar,
    )

    if request.method == "POST":
        action = request.form.get("action")
        if action == "upload_avatar":
            try:
                upload_user_avatar(current_user, request.files.get("avatar_file"))
                flash("Foto profil berhasil diperbarui.", "success")
            except (UserProfileError, ValueError) as error:
                flash(str(error), "warning")
            return redirect(url_for("portal.profile"))

        elif action == "delete_avatar":
            try:
                delete_user_avatar(current_user)
                flash("Foto profil berhasil dihapus.", "success")
            except (UserProfileError, ValueError) as error:
                flash(str(error), "warning")
            return redirect(url_for("portal.profile"))

        elif action == "change_password":
            try:
                profile_change_password(current_user, request.form)
                flash("Password berhasil diganti.", "success")
            except (UserProfileError, ValueError) as error:
                flash(str(error), "warning")
            return redirect(url_for("portal.profile", _anchor="ganti-password"))

        elif action == "update_profile" or request.form.get("full_name"):
            try:
                update_user_profile(current_user, request.form, is_portal=True)
                flash("Data diri berhasil diperbarui.", "success")
            except (UserProfileError, ValueError) as error:
                flash(str(error), "danger")
            return redirect(url_for("portal.profile"))

        else:
            # Backward compatibility for direct email submit
            new_email = request.form.get("email")
            current_password = request.form.get("current_password")
            success, error = update_portal_user_email(current_user, new_email, current_password)
            if error:
                flash(error, "danger")
            else:
                flash("Email akun portal berhasil diperbarui.", "success")
            return redirect(url_for("portal.profile"))

    from app.models.system import AuditLog

    last_login = (
        AuditLog.query.filter(
            AuditLog.user_id == current_user.id,
            AuditLog.event_type == "LOGIN_SUCCESS",
        )
        .order_by(AuditLog.created_at.desc())
        .first()
    )
    last_login_at = last_login.created_at if last_login else None

    return render_template(
        "portal/profile.html",
        data={
            **_role_dashboard_data(_current_portal_persona()),
            "profile": build_portal_profile(current_user),
            "last_login_at": last_login_at,
            "page_title": "Akun Saya",
            "page_description": "Kelola data diri, foto profil, dan keamanan akun portal Anda.",
        },
    )


@portal_bp.route("/profile/email", methods=["POST"])
@role_required(*PORTAL_READONLY_ROLES)
def update_profile_email():
    new_email = request.form.get("email")
    current_password = request.form.get("current_password")
    success, error = update_portal_user_email(current_user, new_email, current_password)
    if error:
        flash(error, "danger")
    else:
        flash("Email akun portal berhasil diperbarui.", "success")
    return redirect(url_for("portal.profile"))


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
            flash("Draf pesanan portal berhasil dikirim dan menunggu konfirmasi admin.", "success")
        else:
            flash("Draf pesanan yang sama sudah pernah diterima. Tidak dibuat duplikat.", "info")
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
        # Nominal dari pelanggan hanya keterangan untuk Finance; yang dijurnal
        # adalah nominal yang Finance catat saat memverifikasi.
        paid_amount = (request.form.get("paid_amount") or "").strip()
        sender_name = (request.form.get("sender_name") or "").strip()
        transfer_reference = (request.form.get("transfer_reference") or "").strip()
        notes = (request.form.get("notes") or "").strip()
        if paid_amount:
            notes = f"Nominal dibayar pelanggan: Rp {paid_amount}. {notes}".strip()
        result = upload_portal_order_draft_payment_proof(
            current_user,
            draft_id=draft_id,
            file_storage=request.files.get("proof_file"),
            notes=notes or None,
            claimed_amount=paid_amount or None,
            sender_name=sender_name or None,
            transfer_reference=transfer_reference or None,
        )
    except (PortalPaymentProofError, AttachmentValidationError) as exc:
        flash(str(exc), "danger")
    else:
        flash(f"Bukti pembayaran awal draft #{result['draft_id']} berhasil diunggah dan menunggu pemeriksaan keuangan.", "success")
    # Kembali ke tab Tagihan, tempat form bayar pesanan berada.
    billing_endpoint = {
        ROLE_PORTAL_CUSTOMER: "portal.customer_payments",
        ROLE_PORTAL_SUBCLIENT: "portal.mandor_invoices",
    }.get(current_user.role, "portal.order_status")
    return redirect(url_for(billing_endpoint))


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
                "primary_note": "Status terbaru pesanan Anda.",
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
        owner_override=request.form.get("owner_override") == "1",
    )
    if error:
        flash(error, "warning")
    elif converted:
        flash("Draf pesanan portal berhasil dikonfirmasi ke order harian.", "success")
    else:
        flash("Draf pesanan sudah pernah dikonfirmasi. Tidak dibuat duplikat.", "info")
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
        flash("Draf pesanan portal ditolak.", "success")
        # Kalau pelanggan sudah membayar, uangnya harus dikembalikan (keputusan OWNER).
        from app.services.prepaid_order_service import draft_prepayments, rupiah

        paid = [advance for advance in draft_prepayments(_draft) if float(advance.remaining_amount or 0) > 0]
        if paid:
            numbers = ", ".join(advance.advance_number for advance in paid)
            total = sum(float(advance.remaining_amount or 0) for advance in paid)
            flash(
                f"Pelanggan sudah membayar {rupiah(total)} untuk draft ini ({numbers}). "
                "Owner perlu mengembalikannya di Keuangan → Uang Muka.",
                "warning",
            )
    return redirect(url_for("portal.admin_order_drafts"))


@portal_bp.route("/orders/update-qty", methods=["POST"])
@role_required(ROLE_PORTAL_CLIENT, ROLE_PORTAL_SUBCLIENT)
def update_order_qty():
    """Ubah porsi dari portal untuk client/sub client kontrak."""
    from datetime import date
    from app.services.auto_order_service import update_order_qty_from_portal

    mandor_id = request.form.get("mandor_id", type=int)
    delivery_location_id = request.form.get("delivery_location_id", type=int)
    meal_type = (request.form.get("meal_type") or "").strip().upper()
    order_date_str = (request.form.get("order_date") or "").strip()
    new_qty = request.form.get("new_qty", type=int)
    reason_code = (request.form.get("reason_code") or "").strip() or None
    note = (request.form.get("note") or "").strip() or None
    resume_date_str = (request.form.get("resume_date") or "").strip() or None

    resume_date = None
    if resume_date_str:
        try:
            resume_date = date.fromisoformat(resume_date_str)
        except ValueError:
            flash("Format tanggal kembali pesan tidak valid.", "danger")
            return redirect(request.referrer or url_for("portal.my_dashboard"))

    try:
        order_date = date.fromisoformat(order_date_str)
    except (ValueError, TypeError):
        flash("Tanggal order tidak valid.", "danger")
        return redirect(request.referrer or url_for("portal.my_dashboard"))

    if new_qty is None:
        flash("Jumlah porsi wajib diisi.", "danger")
        return redirect(request.referrer or url_for("portal.my_dashboard"))

    success, message, _detail = update_order_qty_from_portal(
        user=current_user,
        mandor_id=mandor_id,
        delivery_location_id=delivery_location_id,
        meal_type=meal_type,
        order_date=order_date,
        new_qty=new_qty,
        reason_code=reason_code,
        note=note,
        resume_date=resume_date,
    )

    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return {"success": success, "message": message}, (200 if success else 400)

    flash(message, "success" if success else "danger")
    return redirect(request.referrer or url_for("portal.my_dashboard"))


