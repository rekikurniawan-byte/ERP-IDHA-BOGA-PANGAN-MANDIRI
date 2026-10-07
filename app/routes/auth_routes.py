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
from app.services.public_site_service import auth_context


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
            return render_template("auth/login.html", site=auth_context())

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

    return render_template("auth/login.html", site=auth_context())


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


@auth_bp.route("/forgot-password", methods=["GET", "POST"])
@limiter.limit(os.getenv("PASSWORD_RESET_RATE_LIMIT", "5 per minute"), methods=["POST"])
def forgot_password():
    if current_user.is_authenticated:
        return _post_login_redirect_for(current_user)

    if request.method == "POST":
        identifier = request.form.get("email_or_username") or request.form.get("email")

        def reset_url_builder(raw_token):
            return url_for("auth.reset_password", token=raw_token, _external=True)

        from app.services.password_reset_service import request_password_reset
        _, message = request_password_reset(identifier, reset_url_builder)
        flash(message, "info")
        return redirect(url_for("auth.login"))

    return render_template("auth/forgot_password.html", site=auth_context())


@auth_bp.route("/reset-password/<string:token>", methods=["GET", "POST"])
def reset_password(token):
    if current_user.is_authenticated:
        return _post_login_redirect_for(current_user)

    from app.services.password_reset_service import verify_reset_token, execute_password_reset

    token_record, error = verify_reset_token(token)
    if error:
        flash(error, "danger")
        return redirect(url_for("auth.forgot_password"))

    if request.method == "POST":
        password = request.form.get("password")
        confirmation = request.form.get("password_confirmation")

        success, msg = execute_password_reset(token, password, confirmation)
        if success:
            flash(msg, "success")
            return redirect(url_for("auth.login"))

        flash(msg, "danger")

    return render_template("auth/reset_password.html", token=token, site=auth_context())
