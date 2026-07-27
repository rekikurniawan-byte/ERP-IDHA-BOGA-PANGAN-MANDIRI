from flask import Blueprint, abort, current_app, redirect, render_template, url_for
from flask_login import current_user

from app.services.portal_access_service import build_portal_access_scope
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
