"""Settings company and user account routes.

Route functions moved out without changing URL rules or endpoint names.
"""
from pathlib import Path
from uuid import uuid4

from flask import current_app
from werkzeug.utils import secure_filename

from app.routes.settings_routes import *  # noqa: F401,F403
from app.services.branch_module_service import (
    MODULES,
    ModuleChangeError,
    build_module_status,
    module_change_errors,
    module_changes,
)


ALLOWED_COMPANY_LOGO_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}


def _save_company_logo_upload(upload):
    if not upload or not upload.filename:
        return None, None

    filename = secure_filename(upload.filename)
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension not in ALLOWED_COMPANY_LOGO_EXTENSIONS:
        return None, "Logo harus berupa PNG, JPG, JPEG, atau WEBP."

    upload_dir = Path(current_app.root_path) / "static" / "uploads" / "company"
    upload_dir.mkdir(parents=True, exist_ok=True)

    target_name = f"company-logo-{current_user.branch_id}-{uuid4().hex[:10]}.{extension}"
    target_path = upload_dir / target_name
    upload.save(target_path)
    return url_for("static", filename=f"uploads/company/{target_name}"), None


@settings_bp.route("/company", methods=["GET", "POST"])
@role_required("OWNER")
def company_settings():
    if request.method == "POST":
        guard_ok, guard_message, guard_meta = validate_sensitive_action_guard(
            "COMPANY_SETTINGS_UPDATE",
            form=request.form,
            target={"branch_id": current_user.branch_id},
        )
        if not guard_ok:
            flash(guard_message, "danger")
            return redirect(url_for("settings.company_settings"))

        form_payload = request.form.to_dict()
        # Sebelum logo diunggah: kalau modul ditolak, tidak ada file yatim.
        module_errors = module_change_errors(current_user.branch_id, form_payload)
        if module_errors:
            for message in module_errors:
                flash(message, "danger")
            flash("Pengaturan tidak disimpan.", "warning")
            return redirect(url_for("settings.company_settings"))
        changed_modules = module_changes(current_user.branch_id, form_payload)

        logo_url, logo_error = _save_company_logo_upload(request.files.get("company_logo_file"))
        if logo_error:
            flash(logo_error, "warning")
            return redirect(url_for("settings.company_settings"))

        if logo_url:
            form_payload["company_logo_url"] = logo_url
        elif form_payload.get("remove_company_logo") == "1":
            form_payload["company_logo_url"] = ""

        try:
            save_company_settings(current_user.branch_id, form_payload)
        except (ModuleChangeError, ValueError) as error:
            if isinstance(error, ModuleChangeError):
                for message in error.errors:
                    flash(message, "danger")
            else:
                flash(str(error), "danger")
            return redirect(url_for("settings.company_settings"))
        module_note = "".join(f" Modul {key}: {old} → {new}." for key, (old, new) in changed_modules.items())
        record_critical_audit_log(
            module="SETTINGS",
            event_type="COMPANY_SETTING_UPDATED",
            action="UPDATE",
            table_name="branch_settings",
            record_id=current_user.branch_id,
            description=f"Pengaturan perusahaan/cabang diperbarui.{module_note}",
            metadata={
                "branch_id": current_user.branch_id,
                "sensitive_guard": guard_meta,
                "module_changes": changed_modules,
            },
        )
        flash("Pengaturan perusahaan berhasil disimpan.", "success")
        return redirect(url_for("settings.company_settings"))

    settings = get_company_settings(current_user.branch_id)
    sections = get_company_settings_schema()

    return render_template(
        "settings/company_settings.html",
        settings=settings,
        sections=sections,
        module_status={MODULES[name]["key"]: status for name, status in build_module_status(current_user.branch_id).items()},
    )

@settings_bp.route("/users")
@role_required("OWNER", "ADMIN")
def users():
    users = list_users()
    return render_template(
        "settings/users.html",
        users=users,
        role_labels=ROLE_LABELS,
        role_descriptions=ROLE_DESCRIPTIONS,
    )


def _portal_link_label(user):
    from app.services.user_management_service import current_portal_link

    return current_portal_link(user).get("label")


def _render_user_form(target_user, branches, form_data):
    from app.services.user_management_service import (
        ROLE_PORTAL_CUSTOMER,
        current_portal_link,
        portal_link_options,
    )

    # Pelanggan umum mendaftar sendiri; role itu hanya tampil untuk akun yang sudah ada.
    roles = [role for role in ALLOWED_ROLES if role != ROLE_PORTAL_CUSTOMER or (target_user and target_user.role == role)]
    return render_template(
        "settings/user_form.html",
        target_user=target_user,
        branches=branches,
        roles=roles,
        role_labels=ROLE_LABELS,
        role_descriptions=ROLE_DESCRIPTIONS,
        form_data=form_data,
        portal_options=portal_link_options(),
        portal_link=current_portal_link(target_user) if target_user else {},
    )


@settings_bp.route("/users/create", methods=["GET", "POST"])
@role_required("OWNER")
def create_user_page():
    branches = list_active_branches()

    if request.method == "POST":
        guard_ok, guard_message, guard_meta = validate_sensitive_action_guard(
            "USER_CREATE",
            form=request.form,
            target={"username": request.form.get("username"), "role": request.form.get("role")},
        )
        if not guard_ok:
            flash(guard_message, "danger")
            return _render_user_form(None, branches, request.form)

        user, error = create_user(request.form, acted_by=current_user.id)

        if error:
            flash(error, "warning")
            return _render_user_form(None, branches, request.form)

        record_critical_audit_log(
            module="SECURITY",
            event_type="USER_CREATED",
            action="CREATE",
            table_name="users",
            record_id=user.id,
            description=f"User dibuat: {user.username}",
            metadata={"target_user_id": user.id, "target_username": user.username, "target_role": user.role, "portal_link": _portal_link_label(user), "sensitive_guard": guard_meta},
        )
        flash(f"User {user.username} berhasil dibuat.", "success")
        return redirect(url_for("settings.users"))

    return _render_user_form(None, branches, {})


@settings_bp.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
@role_required("OWNER")
def edit_user_page(user_id):
    target_user = get_user_or_404(user_id)
    branches = list_active_branches()

    if request.method == "POST":
        guard_ok, guard_message, guard_meta = validate_sensitive_action_guard(
            "USER_UPDATE",
            form=request.form,
            target={"user_id": target_user.id, "username": target_user.username, "new_role": request.form.get("role")},
        )
        if not guard_ok:
            flash(guard_message, "danger")
            return _render_user_form(target_user, branches, request.form)

        user, error = update_user(target_user, request.form, current_user)

        if error:
            flash(error, "warning")
            return _render_user_form(target_user, branches, request.form)

        record_critical_audit_log(
            module="SECURITY",
            event_type="USER_UPDATED",
            action="UPDATE",
            table_name="users",
            record_id=user.id,
            description=f"User diperbarui: {user.username}",
            metadata={"target_user_id": user.id, "target_username": user.username, "target_role": user.role, "is_active": user.is_active, "portal_link": _portal_link_label(user), "sensitive_guard": guard_meta},
        )
        flash(f"User {user.username} berhasil diperbarui.", "success")
        return redirect(url_for("settings.users"))

    return _render_user_form(target_user, branches, {})


@settings_bp.route("/users/<int:user_id>/toggle", methods=["POST"])
@role_required("OWNER")
def toggle_user_page(user_id):
    target_user = get_user_or_404(user_id)
    guard_ok, guard_message, guard_meta = validate_sensitive_action_guard(
        "USER_STATUS_TOGGLE",
        form=request.form,
        target={"user_id": target_user.id, "username": target_user.username, "current_is_active": target_user.is_active},
    )
    if not guard_ok:
        flash(guard_message, "danger")
        return redirect(url_for("settings.users"))

    success, error = toggle_user_active(target_user, current_user)

    if error:
        flash(error, "danger")
    elif success:
        record_critical_audit_log(
            module="SECURITY",
            event_type="USER_STATUS_CHANGED",
            action="UPDATE",
            table_name="users",
            record_id=target_user.id,
            description=f"Status user diubah: {target_user.username}",
            metadata={"target_user_id": target_user.id, "target_username": target_user.username, "is_active": target_user.is_active, "sensitive_guard": guard_meta},
        )
        flash("Status user berhasil diubah.", "success")

    return redirect(url_for("settings.users"))


@settings_bp.route("/users/<int:user_id>/reset-password", methods=["GET", "POST"])
@role_required("OWNER", "ADMIN")
def reset_user_password_page(user_id):
    target_user = get_user_or_404(user_id)
    if target_user.role == "OWNER" and current_user.role != "OWNER":
        flash("Reset password OWNER hanya boleh dilakukan oleh OWNER.", "danger")
        return redirect(url_for("settings.users"))

    if request.method == "POST":
        guard_ok, guard_message, guard_meta = validate_sensitive_action_guard(
            "USER_PASSWORD_RESET",
            form=request.form,
            target={"user_id": target_user.id, "username": target_user.username},
        )
        if not guard_ok:
            flash(guard_message, "danger")
            return render_template("settings/reset_password.html", target_user=target_user)

        success, error = reset_user_password(
            target_user,
            request.form.get("password"),
            request.form.get("password_confirmation"),
            current_user,
        )

        if error:
            flash(error, "warning")
            return render_template("settings/reset_password.html", target_user=target_user)

        record_critical_audit_log(
            module="SECURITY",
            event_type="USER_PASSWORD_RESET",
            action="UPDATE",
            table_name="users",
            record_id=target_user.id,
            description=f"Password user direset: {target_user.username}",
            metadata={"target_user_id": target_user.id, "target_username": target_user.username, "sensitive_guard": guard_meta},
        )
        flash(f"Password user {target_user.username} berhasil direset.", "success")
        return redirect(url_for("settings.users"))

    return render_template("settings/reset_password.html", target_user=target_user)


@settings_bp.route("/change-password", methods=["GET", "POST"])
@role_required("OWNER", "ADMIN", "FINANCE", "ACCOUNTING", "LOGISTICS", "HR", "DAPUR", "PENGANTAR")
def change_password():
    if request.method == "POST":
        success, error = change_own_password(
            current_user,
            request.form.get("current_password"),
            request.form.get("password"),
            request.form.get("password_confirmation"),
        )

        if error:
            flash(error, "warning")
            return render_template("settings/change_password.html")

        record_critical_audit_log(
            module="AUTH",
            event_type="PASSWORD_CHANGED",
            action="UPDATE",
            table_name="users",
            record_id=current_user.id,
            description="User mengganti password sendiri.",
        )
        flash("Password berhasil diganti. Silakan gunakan password baru saat login berikutnya.", "success")
        return redirect(url_for("dashboard.index"))

    return render_template("settings/change_password.html")
