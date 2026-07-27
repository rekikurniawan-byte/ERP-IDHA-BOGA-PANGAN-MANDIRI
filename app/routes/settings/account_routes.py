"""Settings company and user account routes.

Route functions moved out without changing URL rules or endpoint names.
"""
from app.routes.settings_routes import *  # noqa: F401,F403


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

        save_company_settings(current_user.branch_id, request.form)
        record_critical_audit_log(
            module="SETTINGS",
            event_type="COMPANY_SETTING_UPDATED",
            action="UPDATE",
            table_name="branch_settings",
            record_id=current_user.branch_id,
            description="Pengaturan PT/cabang diperbarui.",
            metadata={"branch_id": current_user.branch_id, "sensitive_guard": guard_meta},
        )
        flash("Pengaturan PT berhasil disimpan.", "success")
        return redirect(url_for("settings.company_settings"))

    settings = get_company_settings(current_user.branch_id)
    sections = get_company_settings_schema()

    return render_template(
        "settings/company_settings.html",
        settings=settings,
        sections=sections,
    )

@settings_bp.route("/users")
@role_required("OWNER")
def users():
    users = list_users()
    return render_template(
        "settings/users.html",
        users=users,
        role_labels=ROLE_LABELS,
        role_descriptions=ROLE_DESCRIPTIONS,
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
            return render_template(
                "settings/user_form.html",
                target_user=None,
                branches=branches,
                roles=ALLOWED_ROLES,
                role_labels=ROLE_LABELS,
                role_descriptions=ROLE_DESCRIPTIONS,
                form_data=request.form,
            )

        user, error = create_user(request.form)

        if error:
            flash(error, "warning")
            return render_template(
                "settings/user_form.html",
                target_user=None,
                branches=branches,
                roles=ALLOWED_ROLES,
                role_labels=ROLE_LABELS,
                role_descriptions=ROLE_DESCRIPTIONS,
                form_data=request.form,
            )

        record_critical_audit_log(
            module="SECURITY",
            event_type="USER_CREATED",
            action="CREATE",
            table_name="users",
            record_id=user.id,
            description=f"User dibuat: {user.username}",
            metadata={"target_user_id": user.id, "target_username": user.username, "target_role": user.role, "sensitive_guard": guard_meta},
        )
        flash(f"User {user.username} berhasil dibuat.", "success")
        return redirect(url_for("settings.users"))

    return render_template(
        "settings/user_form.html",
        target_user=None,
        branches=branches,
        roles=ALLOWED_ROLES,
        role_labels=ROLE_LABELS,
        role_descriptions=ROLE_DESCRIPTIONS,
        form_data={},
    )


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
            return render_template(
                "settings/user_form.html",
                target_user=target_user,
                branches=branches,
                roles=ALLOWED_ROLES,
                role_labels=ROLE_LABELS,
                role_descriptions=ROLE_DESCRIPTIONS,
                form_data=request.form,
            )

        user, error = update_user(target_user, request.form, current_user)

        if error:
            flash(error, "warning")
            return render_template(
                "settings/user_form.html",
                target_user=target_user,
                branches=branches,
                roles=ALLOWED_ROLES,
                role_labels=ROLE_LABELS,
                role_descriptions=ROLE_DESCRIPTIONS,
                form_data=request.form,
            )

        record_critical_audit_log(
            module="SECURITY",
            event_type="USER_UPDATED",
            action="UPDATE",
            table_name="users",
            record_id=user.id,
            description=f"User diperbarui: {user.username}",
            metadata={"target_user_id": user.id, "target_username": user.username, "target_role": user.role, "is_active": user.is_active, "sensitive_guard": guard_meta},
        )
        flash(f"User {user.username} berhasil diperbarui.", "success")
        return redirect(url_for("settings.users"))

    return render_template(
        "settings/user_form.html",
        target_user=target_user,
        branches=branches,
        roles=ALLOWED_ROLES,
        role_labels=ROLE_LABELS,
        role_descriptions=ROLE_DESCRIPTIONS,
        form_data={},
    )


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
@role_required("OWNER")
def reset_user_password_page(user_id):
    target_user = get_user_or_404(user_id)

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
