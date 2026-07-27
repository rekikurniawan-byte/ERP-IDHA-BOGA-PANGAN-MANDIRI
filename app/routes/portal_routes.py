from flask import Blueprint, abort, current_app, redirect, render_template, url_for
from flask_login import current_user

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
    data = {
        "status_label": "Preview internal",
        "active_role": current_user.role,
        "branch_id": current_user.branch_id,
        "cards": [
            {
                "title": "Pelanggan",
                "value": "Read-only",
                "caption": "Client, mandor, dan lokasi memakai data master existing.",
            },
            {
                "title": "Order",
                "value": "Belum aktif",
                "caption": "Batch 1A tidak membuat atau mengubah order.",
            },
            {
                "title": "Pembayaran",
                "value": "Tidak tersambung",
                "caption": "Tidak ada posting payment, invoice, jurnal, atau kas.",
            },
        ],
    }
    return render_template("portal/dashboard.html", data=data)
