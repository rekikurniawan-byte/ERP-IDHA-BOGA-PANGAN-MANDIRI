import os

from flask import Blueprint, current_app, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, current_user, login_required

from app.services.auth_service import authenticate_user
from app.extensions import limiter
from app.services.audit_log_service import record_audit_log, record_critical_audit_log
from app.services.user_management_service import (
    PORTAL_EXTERNAL_ROLES,
    get_portal_role_landing_endpoint,
)


auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


def _post_login_redirect_for(user):
    """Keep external portal users out of the internal ERP landing page."""
    if (
        current_app.config.get("PORTAL_ENABLED", False)
        and getattr(user, "role", None) in PORTAL_EXTERNAL_ROLES
    ):
        endpoint = get_portal_role_landing_endpoint(getattr(user, "role", None)) or "portal.my_dashboard"
        return redirect(url_for(endpoint))
    return redirect(url_for("dashboard.index"))


@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit(os.getenv("LOGIN_RATE_LIMIT", "5 per minute"), methods=["POST"])
def login():
    if current_user.is_authenticated:
        return _post_login_redirect_for(current_user)

    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        user, error = authenticate_user(username, password)

        if error:
            record_critical_audit_log(
                module="AUTH",
                event_type="LOGIN_FAILED",
                action="FAILED",
                description="Percobaan login gagal.",
                metadata={"username": username},
                severity="MEDIUM",
                reason="Login gagal / kredensial tidak valid",
                reference_type="auth_login_attempt",
                reference_id=None,
                user_id=None,
                branch_id=None,
                username_snapshot=username,
            )
            flash(error, "danger")
            return render_template("auth/login.html")

        login_user(user)
        record_audit_log(
            module="AUTH",
            event_type="LOGIN_SUCCESS",
            action="LOGIN",
            table_name="users",
            record_id=user.id,
            description="User berhasil login.",
            user_id=user.id,
            branch_id=user.branch_id,
            username_snapshot=user.username,
            user_role_snapshot=user.role,
        )
        flash("Login berhasil.", "success")
        return _post_login_redirect_for(user)

    return render_template("auth/login.html")


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    """Logout resmi: audit aman, session dibersihkan, lalu redirect ke login."""
    try:
        record_audit_log(
            module="AUTH",
            event_type="LOGOUT",
            action="LOGOUT",
            table_name="users",
            record_id=getattr(current_user, "id", None),
            description="User logout.",
            user_id=getattr(current_user, "id", None),
            branch_id=getattr(current_user, "branch_id", None),
            username_snapshot=getattr(current_user, "username", None),
            user_role_snapshot=getattr(current_user, "role", None),
        )
    except Exception:
        # Logout tidak boleh gagal hanya karena audit log bermasalah.
        current_app.logger.exception("Audit logout gagal.")

    logout_user()
    flash("Logout berhasil. Silakan login kembali jika ingin masuk ke dashboard.", "success")
    return redirect(url_for("auth.login"))
