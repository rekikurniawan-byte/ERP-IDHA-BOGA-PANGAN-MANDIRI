from flask import Blueprint, abort, current_app, redirect, render_template, url_for
from flask_login import current_user

from app.services.portal_access_service import (
    build_portal_access_scope,
    build_portal_customer_directory,
    build_portal_delivery_visibility,
    build_portal_financial_visibility,
    build_portal_inventory_visibility,
    build_portal_mandor_directory,
    build_portal_ownership_analysis,
    build_portal_order_status_visibility,
    build_portal_production_visibility,
    build_portal_status_shell,
)
from app.utils.decorators import role_required


portal_bp = Blueprint("portal", __name__, url_prefix="/portal")


@portal_bp.before_request
def require_portal_feature_flag():
    if not current_app.config.get("PORTAL_ENABLED", False):
        abort(404)


@portal_bp.route("")
@portal_bp.route("/")
@role_required("ADMIN")
def index():
    return redirect(url_for("portal.dashboard"))


@portal_bp.route("/dashboard")
@role_required("ADMIN")
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


@portal_bp.route("/customers")
@role_required("ADMIN")
def customers():
    data = {
        "status_label": "Read-only",
        "active_role": current_user.role,
        "branch_id": current_user.branch_id,
        "directory": build_portal_customer_directory(current_user),
    }
    return render_template("portal/customers.html", data=data)


@portal_bp.route("/mandors")
@role_required("ADMIN")
def mandors():
    data = {
        "status_label": "Read-only",
        "active_role": current_user.role,
        "branch_id": current_user.branch_id,
        "directory": build_portal_mandor_directory(current_user),
    }
    return render_template("portal/mandors.html", data=data)


@portal_bp.route("/status")
@role_required("ADMIN")
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


@portal_bp.route("/financial")
@role_required("ADMIN")
def financial():
    data = {
        "status_label": "Read-only",
        "active_role": current_user.role,
        "branch_id": current_user.branch_id,
        "financial": build_portal_financial_visibility(current_user),
    }
    return render_template("portal/financial.html", data=data)


@portal_bp.route("/orders")
@role_required("ADMIN")
def orders():
    data = {
        "status_label": "Read-only",
        "active_role": current_user.role,
        "branch_id": current_user.branch_id,
        "orders": build_portal_order_status_visibility(current_user),
    }
    return render_template("portal/orders.html", data=data)


@portal_bp.route("/deliveries")
@role_required("ADMIN")
def deliveries():
    data = {
        "status_label": "Read-only",
        "active_role": current_user.role,
        "branch_id": current_user.branch_id,
        "deliveries": build_portal_delivery_visibility(current_user),
    }
    return render_template("portal/deliveries.html", data=data)


@portal_bp.route("/productions")
@role_required("ADMIN")
def productions():
    data = {
        "status_label": "Read-only",
        "active_role": current_user.role,
        "branch_id": current_user.branch_id,
        "productions": build_portal_production_visibility(current_user),
    }
    return render_template("portal/productions.html", data=data)


@portal_bp.route("/inventory")
@role_required("ADMIN")
def inventory():
    data = {
        "status_label": "Read-only",
        "active_role": current_user.role,
        "branch_id": current_user.branch_id,
        "inventory": build_portal_inventory_visibility(current_user),
    }
    return render_template("portal/inventory.html", data=data)
