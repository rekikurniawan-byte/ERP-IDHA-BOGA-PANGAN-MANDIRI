from uuid import uuid4

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.services.portal_access_service import (
    build_portal_access_scope,
    build_portal_customer_directory,
    build_portal_location_directory,
    build_portal_mandor_directory,
    build_portal_ownership_analysis,
    build_portal_profile,
    build_portal_status_shell,
)
from app.services.portal_order_draft_service import (
    build_portal_order_status_context,
    build_portal_draft_order_context,
    confirm_portal_order_draft,
    create_portal_order_draft,
    list_pending_portal_order_drafts,
    reject_portal_order_draft,
)
from app.services.user_management_service import (
    ROLE_PORTAL_CLIENT,
    ROLE_PORTAL_CUSTOMER,
    ROLE_PORTAL_DELEGATE,
    ROLE_PORTAL_MANDOR,
)
from app.utils.decorators import role_required


portal_bp = Blueprint("portal", __name__, url_prefix="/portal")
PORTAL_READONLY_ROLES = (
    "ADMIN",
    ROLE_PORTAL_CLIENT,
    ROLE_PORTAL_MANDOR,
    ROLE_PORTAL_DELEGATE,
    ROLE_PORTAL_CUSTOMER,
)


@portal_bp.before_request
def require_portal_feature_flag():
    if not current_app.config.get("PORTAL_ENABLED", False):
        abort(404)


@portal_bp.route("")
@portal_bp.route("/")
@role_required(*PORTAL_READONLY_ROLES)
def index():
    return redirect(url_for("portal.dashboard"))


@portal_bp.route("/dashboard")
@role_required(*PORTAL_READONLY_ROLES)
def dashboard():
    scope = build_portal_access_scope(current_user)
    data = {
        "status_label": "Preview internal",
        "active_role": current_user.role,
        "branch_id": current_user.branch_id,
        "scope": scope,
        "cards": [
            {
                "title": "Pelanggan",
                "value": scope["counts"]["clients"],
                "caption": "Client, mandor, dan lokasi memakai data master existing.",
            },
            {
                "title": "Mandor",
                "value": scope["counts"]["mandors"],
                "caption": "Scope mandor dibaca dari cabang user atau preview OWNER.",
            },
            {
                "title": "Lokasi",
                "value": scope["counts"]["locations"],
                "caption": "Lokasi pengiriman tetap memakai DeliveryLocation existing.",
            },
        ],
    }
    return render_template("portal/dashboard.html", data=data)


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
@role_required(*PORTAL_READONLY_ROLES)
def customers():
    data = {
        "status_label": "Read-only",
        "active_role": current_user.role,
        "branch_id": current_user.branch_id,
        "directory": build_portal_customer_directory(current_user),
    }
    return render_template("portal/customers.html", data=data)


@portal_bp.route("/mandors")
@role_required(*PORTAL_READONLY_ROLES)
def mandors():
    data = {
        "status_label": "Read-only",
        "active_role": current_user.role,
        "branch_id": current_user.branch_id,
        "directory": build_portal_mandor_directory(current_user),
    }
    return render_template("portal/mandors.html", data=data)


@portal_bp.route("/locations")
@role_required(*PORTAL_READONLY_ROLES)
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
        "status_label": "Read-only",
        "active_role": current_user.role,
        "branch_id": current_user.branch_id,
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
@role_required(*PORTAL_READONLY_ROLES)
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
