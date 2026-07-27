from flask import Blueprint, abort, current_app, redirect, render_template, url_for
from flask_login import current_user

from app.services.portal_access_service import (
    build_portal_access_scope,
    build_portal_customer_directory,
    build_portal_mandor_directory,
    build_portal_ownership_analysis,
    build_portal_profile,
    build_portal_status_shell,
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
