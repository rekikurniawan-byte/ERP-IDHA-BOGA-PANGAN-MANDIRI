from datetime import datetime, timedelta

from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file, abort, current_app
from flask_login import current_user

from app.services.company_settings_service import (
    get_company_settings,
    get_company_settings_schema,
    save_company_settings,
)
from app.services.user_management_service import (
    ALLOWED_ROLES,
    ROLE_DESCRIPTIONS,
    ROLE_LABELS,
    change_own_password,
    create_user,
    get_user_or_404,
    list_active_branches,
    list_users,
    reset_user_password,
    toggle_user_active,
    update_user,
)

from app.services.backup_service import (
    create_database_backup,
    create_full_backup_package,
    get_backup_file,
    get_backup_status,
    get_restore_manual_sop,
    validate_restore_backup_preview,
)
from app.services.audit_log_service import (
    get_audit_filter_options,
    get_audit_log_detail,
    get_audit_log_summary,
    get_audit_logs,
    record_audit_log,
    record_critical_audit_log,
)
from app.services.system_health_service import build_empty_system_health_report, build_system_health_report
from app.services.recovery_center_service import build_empty_recovery_center_report, build_recovery_center_report
from app.services.atomic_transaction_audit_map_service import build_atomic_transaction_audit_map
from app.services.atomic_failure_simulation_service import (
    build_empty_atomic_failure_injection_report,
    run_atomic_failure_injection_smoke,
)
from app.services.sensitive_action_guard_service import validate_sensitive_action_guard
from app.services.live_reminder_service import build_empty_live_reminder_center, build_live_reminder_center
from app.services.visual_sweep_service import build_empty_visual_sweep_report, build_visual_sweep_report
from app.services.final_visual_browser_qa_service import (
    build_empty_final_visual_browser_qa_report,
    build_final_visual_browser_qa_report,
)
from app.services.notification_service import (
    NOTIFICATION_PRIORITIES,
    NOTIFICATION_STATUSES,
    ROLE_TARGETS,
    can_user_access_notification,
    count_unread_notifications,
    generate_notifications_from_live_reminders,
    get_notification_or_none,
    get_notification_status_summary,
    list_notifications,
    mark_notification_dismissed,
    mark_notification_read,
    mark_notification_unread,
)
from app.services.digital_attachment_service import (
    format_file_size,
    get_allowed_extensions,
    get_attachment_file_path,
    get_attachment_filter_options,
    get_attachment_or_none,
    get_max_upload_bytes,
    list_digital_attachments,
    is_inline_view_safe,
    soft_delete_attachment,
)

from app.utils.decorators import role_required


settings_bp = Blueprint("settings", __name__, url_prefix="/settings")


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


@settings_bp.route("/recovery-center")
@role_required("OWNER", "ADMIN")
def recovery_center():
    try:
        branch_id = None if getattr(current_user, "role", None) == "OWNER" else getattr(current_user, "branch_id", None)
        report = build_recovery_center_report(branch_id=branch_id)
    except Exception as exc:
        current_app.logger.exception("Recovery Center final polish report failed")
        report = build_empty_recovery_center_report(str(exc))
        flash("Recovery Center gagal dibaca penuh. Detail error tercatat di terminal/log Flask.", "danger")

    return render_template("settings/recovery_center.html", report=report)


@settings_bp.route("/system-health")
@role_required("OWNER", "ADMIN")
def system_health():
    try:
        health = build_system_health_report()
    except Exception as exc:
        current_app.logger.exception("System Health read-only report failed")
        health = build_empty_system_health_report(str(exc))
        flash("System Health gagal dibaca penuh. Detail error tercatat di terminal/log Flask.", "danger")

    return render_template("settings/system_health.html", health=health)


@settings_bp.route("/atomic-transaction-map")
@role_required("OWNER")
def atomic_transaction_map():
    report = build_atomic_transaction_audit_map()
    return render_template("settings/atomic_transaction_map.html", report=report)


@settings_bp.route("/atomic-smoke-simulation")
@role_required("OWNER")
def atomic_smoke_simulation():
    try:
        report = run_atomic_failure_injection_smoke()
    except Exception as exc:
        current_app.logger.exception("Atomic smoke simulation failed")
        report = build_empty_atomic_failure_injection_report(str(exc))
        flash("Atomic smoke simulation gagal dijalankan. Detail error tercatat di terminal/log Flask.", "danger")

    return render_template("settings/atomic_smoke_simulation.html", report=report)




@settings_bp.route("/visual-sweep")
@role_required("OWNER", "ADMIN")
def visual_sweep():
    try:
        report = build_visual_sweep_report()
    except Exception as exc:
        current_app.logger.exception("PRODUCTION Visual Sweep failed")
        report = build_empty_visual_sweep_report(str(exc))
        flash("Visual Sweep gagal dibaca penuh. Detail error tercatat di terminal/log Flask.", "danger")

    return render_template("settings/visual_sweep.html", report=report)


@settings_bp.route("/final-visual-qa")
@role_required("OWNER", "ADMIN")
def final_visual_browser_qa():
    try:
        report = build_final_visual_browser_qa_report()
    except Exception as exc:
        current_app.logger.exception("PRODUCTION Final Visual Browser QA failed")
        report = build_empty_final_visual_browser_qa_report(str(exc))
        flash("Final Visual Browser QA gagal dibaca penuh. Detail error tercatat di terminal/log Flask.", "danger")

    return render_template("settings/final_visual_browser_qa.html", report=report)


@settings_bp.route("/backups")
@role_required("OWNER")
def backups():
    try:
        status = get_backup_status()
        restore_sop = get_restore_manual_sop()
    except Exception as exc:
        flash(f"Status backup gagal dibaca: {exc}", "danger")
        restore_sop = None
        status = {
            "database_path": "-",
            "database_size_bytes": 0,
            "database_sha256": "-",
            "upload_dir": "-",
            "upload_file_count": 0,
            "upload_total_size_bytes": 0,
            "backup_dir": "-",
            "backups": [],
            "full_backups": [],
            "legacy_backups": [],
            "legacy_backup_count": 0,
            "folder_policy": {},
            "baseline_audit": {"baseline_pass": False, "errors": [str(exc)], "warnings": [], "successes": [], "attachment_audit": {}},
            "pre_backup_health": {"status": "FAIL", "can_create_backup": False, "errors": [str(exc)], "warnings": [], "successes": [], "checks": []},
        }

    return render_template("settings/backup.html", status=status, restore_sop=restore_sop)


@settings_bp.route("/backups/validate", methods=["POST"])
@role_required("OWNER")
def validate_backup_preview():
    try:
        status = get_backup_status()
        restore_sop = get_restore_manual_sop()
    except Exception as exc:
        flash(f"Status backup gagal dibaca: {exc}", "danger")
        restore_sop = None
        status = {
            "database_path": "-",
            "database_size_bytes": 0,
            "database_sha256": "-",
            "upload_dir": "-",
            "upload_file_count": 0,
            "upload_total_size_bytes": 0,
            "backup_dir": "-",
            "backups": [],
            "full_backups": [],
            "legacy_backups": [],
            "legacy_backup_count": 0,
            "folder_policy": {},
            "baseline_audit": {"baseline_pass": False, "errors": [str(exc)], "warnings": [], "successes": [], "attachment_audit": {}},
            "pre_backup_health": {"status": "FAIL", "can_create_backup": False, "errors": [str(exc)], "warnings": [], "successes": [], "checks": []},
        }

    uploaded_file = request.files.get("restore_backup_file")
    validation_result = None

    guard_ok, guard_message, guard_meta = validate_sensitive_action_guard(
        "BACKUP_RESTORE_PREVIEW",
        form=request.form,
        target={"filename": getattr(uploaded_file, "filename", None)},
    )
    if not guard_ok:
        flash(guard_message, "danger")
        return render_template(
            "settings/backup.html",
            status=status,
            restore_validation=validation_result,
            restore_sop=restore_sop,
        )

    try:
        if not uploaded_file or not uploaded_file.filename:
            raise ValueError("Pilih file backup terlebih dahulu.")

        validation_result = validate_restore_backup_preview(uploaded_file)

        record_critical_audit_log(
            module="BACKUP",
            event_type="RESTORE_PREVIEW_VALIDATED",
            action="VALIDATE",
            table_name="backup_files",
            record_id=None,
            description="Restore preview backup divalidasi dengan sensitive action guard.",
            metadata={"filename": validation_result.get("filename"), "backup_type": validation_result.get("backup_type"), "is_valid_for_manual_restore": validation_result.get("is_valid_for_manual_restore"), "sensitive_guard": guard_meta},
        )

        if validation_result.get("is_valid_for_manual_restore"):
            flash("Validasi backup PASS. File layak untuk restore manual setelah server dihentikan dan SOP diikuti.", "success")
        else:
            flash("Validasi backup menemukan masalah. Jangan gunakan file ini untuk restore sebelum diperbaiki.", "warning")
    except Exception as exc:
        flash(f"Validasi backup gagal: {exc}", "danger")

    return render_template(
        "settings/backup.html",
        status=status,
        restore_validation=validation_result,
        restore_sop=restore_sop,
    )


@settings_bp.route("/backups/create", methods=["POST"])
@role_required("OWNER")
def create_backup():
    guard_ok, guard_message, guard_meta = validate_sensitive_action_guard(
        "BACKUP_CREATE_DB_ONLY",
        form=request.form,
        target={"backup_type": "DB_ONLY"},
    )
    if not guard_ok:
        flash(guard_message, "danger")
        return redirect(url_for("settings.backups"))

    try:
        backup = create_database_backup()
        record_critical_audit_log(
            module="SETTINGS",
            event_type="BACKUP_CREATED",
            action="CREATE",
            table_name="database_backups",
            record_id=None,
            description=f"Backup database dibuat: {backup['name']}",
            metadata={
                "filename": backup.get("name"),
                "sha256": backup.get("sha256"),
                "pre_backup_health_status": backup.get("pre_backup_health_status"),
                "pre_backup_error_count": backup.get("pre_backup_error_count"),
                "pre_backup_warning_count": backup.get("pre_backup_warning_count"),
                "post_backup_verification_status": backup.get("post_backup_verification_status"),
                "post_backup_error_count": backup.get("post_backup_error_count"),
                "post_backup_warning_count": backup.get("post_backup_warning_count"),
                "restore_dry_run_status": backup.get("restore_dry_run_status"),
                "restore_dry_run_error_count": backup.get("restore_dry_run_error_count"),
                "restore_dry_run_warning_count": backup.get("restore_dry_run_warning_count"),
                "restore_dry_run_schema_version": backup.get("restore_dry_run_schema_version"),
                "is_verified_backup": backup.get("is_verified_backup"),
                "post_verification_schema_version": backup.get("post_verification_schema_version"),
                "sensitive_guard": guard_meta,
            },
        )
        flash(
            f"Backup DB-only berhasil dibuat: {backup['name']} | Pre-check: {backup.get('pre_backup_health_status')} | SHA256: {backup['sha256']}",
            "success",
        )
    except Exception as exc:
        flash(f"Backup DB-only gagal dibuat: {exc}", "danger")

    return redirect(url_for("settings.backups"))


@settings_bp.route("/backups/create-full", methods=["POST"])
@role_required("OWNER")
def create_full_backup():
    guard_ok, guard_message, guard_meta = validate_sensitive_action_guard(
        "BACKUP_CREATE_FULL",
        form=request.form,
        target={"backup_type": "FULL_SYSTEM_BACKUP"},
    )
    if not guard_ok:
        flash(guard_message, "danger")
        return redirect(url_for("settings.backups"))

    try:
        backup = create_full_backup_package(created_by=current_user)
        record_critical_audit_log(
            module="SETTINGS",
            event_type="FULL_BACKUP_CREATED",
            action="CREATE",
            table_name="full_backup_packages",
            record_id=None,
            description=f"Full backup DB + uploads dibuat: {backup['name']}",
            metadata={
                "filename": backup.get("name"),
                "sha256": backup.get("sha256"),
                "database_sha256": backup.get("database_sha256"),
                "upload_file_count": backup.get("upload_file_count"),
                "upload_total_size_bytes": backup.get("upload_total_size_bytes"),
                "alembic_version": backup.get("alembic_version"),
                "package_status": backup.get("package_status"),
                "verification_status": backup.get("verification_status"),
                "backup_type": backup.get("backup_type"),
                "app_version": backup.get("app_version"),
                "contract_version": backup.get("contract_version"),
                "manifest_schema_version": backup.get("manifest_schema_version"),
                "pre_backup_health_status": backup.get("pre_backup_health_status"),
                "pre_backup_error_count": backup.get("pre_backup_error_count"),
                "pre_backup_warning_count": backup.get("pre_backup_warning_count"),
                "post_backup_verification_status": backup.get("post_backup_verification_status"),
                "post_backup_error_count": backup.get("post_backup_error_count"),
                "post_backup_warning_count": backup.get("post_backup_warning_count"),
                "restore_dry_run_status": backup.get("restore_dry_run_status"),
                "restore_dry_run_error_count": backup.get("restore_dry_run_error_count"),
                "restore_dry_run_warning_count": backup.get("restore_dry_run_warning_count"),
                "restore_dry_run_schema_version": backup.get("restore_dry_run_schema_version"),
                "is_verified_backup": backup.get("is_verified_backup"),
                "post_verification_schema_version": backup.get("post_verification_schema_version"),
                "sensitive_guard": guard_meta,
            },
        )
        flash(
            f"Full backup B3 VERIFIED dibuat: {backup['name']} | Pre-check: {backup.get('pre_backup_health_status')} | Post-check: {backup.get('post_backup_verification_status')} | Restore dry-run: {backup.get('restore_dry_run_status')} | Verified: {backup.get('is_verified_backup')} | File lampiran: {backup.get('upload_file_count', 0)} | SHA256 ZIP: {backup['sha256']}",
            "success",
        )
    except Exception as exc:
        flash(f"Full backup gagal dibuat: {exc}", "danger")

    return redirect(url_for("settings.backups"))


@settings_bp.route("/backups/download-confirm/<path:filename>")
@role_required("OWNER")
def download_backup_confirm(filename):
    try:
        file_path, mimetype = get_backup_file(filename)
    except Exception as exc:
        flash(f"File backup tidak bisa dibaca: {exc}", "danger")
        return redirect(url_for("settings.backups"))

    return render_template(
        "settings/backup_download_confirm.html",
        filename=filename,
        file_name=file_path.name,
        mimetype=mimetype,
        file_size_bytes=file_path.stat().st_size if file_path.exists() else 0,
    )


@settings_bp.route("/backups/download/<path:filename>", methods=["POST"])
@role_required("OWNER")
def download_backup(filename):
    guard_ok, guard_message, guard_meta = validate_sensitive_action_guard(
        "BACKUP_DOWNLOAD",
        form=request.form,
        target={"filename": filename},
    )
    if not guard_ok:
        flash(guard_message, "danger")
        return redirect(url_for("settings.download_backup_confirm", filename=filename))

    try:
        file_path, mimetype = get_backup_file(filename)
    except Exception as exc:
        flash(f"File backup tidak bisa diunduh: {exc}", "danger")
        return redirect(url_for("settings.backups"))

    record_critical_audit_log(
        module="BACKUP",
        event_type="BACKUP_DOWNLOADED",
        action="DOWNLOAD",
        table_name="backup_files",
        record_id=None,
        description=f"File backup/checksum diunduh: {file_path.name}",
        metadata={"filename": file_path.name, "mimetype": mimetype, "sensitive_guard": guard_meta},
    )
    return send_file(str(file_path), as_attachment=True, download_name=file_path.name, mimetype=mimetype)


@settings_bp.route("/audit-logs")
@role_required("OWNER")
def audit_logs():
    date_from_raw = (request.args.get("date_from") or "").strip()
    date_to_raw = (request.args.get("date_to") or "").strip()
    module = (request.args.get("module") or "").strip()
    event_type = (request.args.get("event_type") or "").strip()
    action = (request.args.get("action") or "").strip()
    severity = (request.args.get("severity") or "").strip().upper()
    critical_only = request.args.get("critical_only") == "1"
    q = (request.args.get("q") or "").strip()

    date_from = None
    date_to = None

    try:
        if date_from_raw:
            date_from = datetime.strptime(date_from_raw, "%Y-%m-%d")
        if date_to_raw:
            date_to = datetime.strptime(date_to_raw, "%Y-%m-%d") + timedelta(days=1)
    except Exception:
        flash("Filter tanggal audit log tidak valid.", "warning")
        date_from = None
        date_to = None

    options = get_audit_filter_options(branch_id=current_user.branch_id)
    logs = get_audit_logs(
        branch_id=current_user.branch_id,
        module=module or None,
        event_type=event_type or None,
        action=action or None,
        q=q or None,
        date_from=date_from,
        date_to=date_to,
        severity=severity or None,
        critical_only=critical_only,
        limit=300,
    )
    audit_summary = get_audit_log_summary(logs)

    return render_template(
        "settings/audit_logs.html",
        logs=logs,
        options=options,
        summary=audit_summary,
        filters={
            "date_from": date_from_raw,
            "date_to": date_to_raw,
            "module": module,
            "event_type": event_type,
            "action": action,
            "severity": severity,
            "critical_only": critical_only,
            "q": q,
        },
    )


@settings_bp.route("/audit-logs/<int:log_id>")
@role_required("OWNER")
def audit_log_detail(log_id):
    detail = get_audit_log_detail(log_id, branch_id=current_user.branch_id)
    if not detail:
        abort(404)

    return render_template("settings/audit_log_detail.html", detail=detail, log=detail["log"])


@settings_bp.route("/digital-attachments")
@role_required("OWNER")
def digital_attachments():
    module = (request.args.get("module") or "").strip()
    reference_type = (request.args.get("reference_type") or "").strip()
    attachment_type = (request.args.get("attachment_type") or "").strip()
    q = (request.args.get("q") or "").strip()
    include_deleted = request.args.get("include_deleted") == "1"

    attachments = list_digital_attachments(
        branch_id=current_user.branch_id,
        module=module or None,
        reference_type=reference_type or None,
        attachment_type=attachment_type or None,
        q=q or None,
        include_deleted=include_deleted,
        limit=300,
    )
    options = get_attachment_filter_options(branch_id=current_user.branch_id)

    return render_template(
        "settings/digital_attachments.html",
        attachments=attachments,
        options=options,
        filters={
            "module": module,
            "reference_type": reference_type,
            "attachment_type": attachment_type,
            "q": q,
            "include_deleted": include_deleted,
        },
        allowed_extensions=sorted(get_allowed_extensions()),
        max_upload_mb=round(get_max_upload_bytes() / (1024 * 1024), 2),
        format_file_size=format_file_size,
    )


@settings_bp.route("/digital-attachments/<int:attachment_id>")
@role_required("OWNER")
def digital_attachment_detail(attachment_id):
    attachment = get_attachment_or_none(attachment_id, branch_id=current_user.branch_id, include_deleted=True)
    if not attachment:
        abort(404)

    file_exists = False
    try:
        get_attachment_file_path(attachment)
        file_exists = True
    except Exception:
        file_exists = False

    return render_template(
        "settings/digital_attachment_detail.html",
        attachment=attachment,
        file_exists=file_exists,
        format_file_size=format_file_size,
    )


@settings_bp.route("/digital-attachments/<int:attachment_id>/download")
@role_required("OWNER")
def download_digital_attachment(attachment_id):
    attachment = get_attachment_or_none(attachment_id, branch_id=current_user.branch_id)
    if not attachment:
        abort(404)

    try:
        file_path = get_attachment_file_path(attachment)
    except Exception as exc:
        flash(f"File lampiran tidak bisa diunduh: {exc}", "danger")
        return redirect(url_for("settings.digital_attachment_detail", attachment_id=attachment_id))

    response = send_file(
        str(file_path),
        as_attachment=True,
        download_name=attachment.original_filename,
        mimetype=attachment.mime_type or "application/octet-stream",
        max_age=0,
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@settings_bp.route("/digital-attachments/<int:attachment_id>/view")
@role_required("OWNER")
def view_digital_attachment(attachment_id):
    attachment = get_attachment_or_none(attachment_id, branch_id=current_user.branch_id)
    if not attachment:
        abort(404)

    try:
        file_path = get_attachment_file_path(attachment)
    except Exception as exc:
        flash(f"File lampiran tidak bisa dibuka: {exc}", "danger")
        return redirect(url_for("settings.digital_attachment_detail", attachment_id=attachment_id))

    if not is_inline_view_safe(attachment):
        abort(403)

    response = send_file(
        str(file_path),
        as_attachment=False,
        download_name=attachment.original_filename,
        mimetype=attachment.mime_type or "application/octet-stream",
        max_age=0,
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@settings_bp.route("/digital-attachments/<int:attachment_id>/delete", methods=["POST"])
@role_required("OWNER")
def delete_digital_attachment(attachment_id):
    attachment = get_attachment_or_none(attachment_id, branch_id=current_user.branch_id)
    if not attachment:
        abort(404)

    note = (request.form.get("delete_note") or "").strip()
    guard_ok, guard_message, guard_meta = validate_sensitive_action_guard(
        "DIGITAL_ATTACHMENT_SOFT_DELETE",
        form=request.form,
        target={"attachment_id": attachment.id, "stored_filename": attachment.stored_filename, "reference_type": attachment.reference_type, "reference_id": attachment.reference_id},
    )
    if not guard_ok:
        flash(guard_message, "danger")
        return redirect(url_for("settings.digital_attachment_detail", attachment_id=attachment.id))

    soft_delete_attachment(attachment, deleted_by=current_user.id, note=note or None)
    record_critical_audit_log(
        module="ATTACHMENT",
        event_type="DIGITAL_ATTACHMENT_SOFT_DELETED",
        action="DELETE",
        table_name="digital_attachments",
        record_id=attachment.id,
        description="Lampiran digital dihapus lunak dengan sensitive action guard.",
        metadata={"delete_note": note, "sensitive_guard": guard_meta},
    )
    flash("Lampiran digital berhasil dihapus lunak. File fisik tetap disimpan untuk audit.", "success")
    return redirect(url_for("settings.digital_attachments"))


@settings_bp.route("/reminders")
@role_required("OWNER", "ADMIN", "FINANCE", "ACCOUNTING", "LOGISTICS", "HR", "DAPUR", "PENGANTAR")
def live_reminders():
    due_days_raw = (request.args.get("due_days") or "7").strip()
    try:
        due_days = max(0, min(int(due_days_raw), 60))
    except Exception:
        due_days = 7
        flash("Filter hari reminder tidak valid, sistem memakai 7 hari.", "warning")

    try:
        reminder_center = build_live_reminder_center(
            current_user.branch_id,
            due_days=due_days,
            limit_per_section=15,
        )
    except Exception as exc:
        current_app.logger.exception("Live reminder center failed")
        reminder_center = build_empty_live_reminder_center(
            due_days=due_days,
            runtime_warning=f"Ada bagian reminder yang belum bisa dihitung: {exc}",
        )
        flash("Reminder Live tetap dibuka dalam mode aman. Detail error tercatat di terminal/log Flask.", "warning")

    return render_template(
        "settings/live_reminders.html",
        reminder_center=reminder_center,
        due_days=due_days,
    )


@settings_bp.route("/notifications")
@role_required("OWNER", "ADMIN", "FINANCE", "ACCOUNTING", "LOGISTICS", "HR", "DAPUR", "PENGANTAR")
def notifications():
    status_filter = (request.args.get("status") or "UNREAD").strip().upper()
    priority_filter = (request.args.get("priority") or "").strip().upper()
    type_filter = (request.args.get("type") or "").strip().upper()
    role_filter = (request.args.get("role") or "").strip().upper()

    status_arg = None
    include_resolved = False
    if status_filter in NOTIFICATION_STATUSES:
        status_arg = status_filter
    elif status_filter == "ALL":
        include_resolved = True
    elif status_filter == "ACTIVE":
        status_filter = "ACTIVE"
    else:
        status_filter = "UNREAD"
        status_arg = "UNREAD"
        flash("Filter status notifikasi tidak valid, sistem memakai UNREAD.", "warning")

    if priority_filter and priority_filter not in NOTIFICATION_PRIORITIES:
        priority_filter = ""
    if role_filter and role_filter not in ROLE_TARGETS:
        role_filter = ""

    rows = list_notifications(
        branch_id=current_user.branch_id,
        user=current_user,
        status=status_arg,
        priority=priority_filter or None,
        notification_type=type_filter or None,
        target_role=role_filter or None,
        include_resolved=include_resolved,
        limit=250,
    )
    summary = get_notification_status_summary(branch_id=current_user.branch_id, user=current_user)
    unread_summary = count_unread_notifications(branch_id=current_user.branch_id, user=current_user)
    type_options = sorted({row.notification_type for row in rows if row.notification_type})

    return render_template(
        "settings/notifications.html",
        notifications=rows,
        summary=summary,
        unread_summary=unread_summary,
        status_filter=status_filter,
        priority_filter=priority_filter,
        type_filter=type_filter,
        role_filter=role_filter,
        status_options=sorted(NOTIFICATION_STATUSES),
        priority_options=sorted(NOTIFICATION_PRIORITIES),
        role_options=sorted(ROLE_TARGETS),
        type_options=type_options,
    )



@settings_bp.route("/notifications/generate", methods=["POST"])
@role_required("OWNER", "ADMIN")
def generate_notifications_route():
    """Manually generate persistent notifications from Live Reminder Center.

    This action writes only notification rows. It does not mutate business
    transactions, stock, journal, cash/bank, invoice, or procurement data.
    """
    try:
        due_days = int(request.form.get("due_days") or 7)
    except Exception:
        due_days = 7
    due_days = max(1, min(due_days, 60))

    try:
        limit_per_section = int(request.form.get("limit_per_section") or 15)
    except Exception:
        limit_per_section = 15
    limit_per_section = max(1, min(limit_per_section, 50))

    try:
        result = generate_notifications_from_live_reminders(
            branch_id=current_user.branch_id,
            due_days=due_days,
            limit_per_section=limit_per_section,
            commit=True,
        )
        record_audit_log(
            module="NOTIFICATION",
            event_type="NOTIFICATION_GENERATED_FROM_LIVE_REMINDER",
            action="CREATE",
            table_name="notifications",
            record_id=None,
            description="Persistent notification digenerate manual dari Reminder Live.",
            metadata={
                "due_days": due_days,
                "limit_per_section": limit_per_section,
                "created": result.get("created", 0),
                "updated": result.get("updated", 0),
                "resolved": result.get("resolved", 0),
                "active": result.get("active", 0),
            },
        )
        flash(
            f"Generate notifikasi selesai: {result.get('created', 0)} baru, "
            f"{result.get('updated', 0)} diperbarui, "
            f"{result.get('resolved', 0)} resolved.",
            "success",
        )
    except Exception as exc:
        current_app.logger.exception("Generate persistent notifications failed")
        flash(f"Generate notifikasi gagal: {exc}", "danger")

    return redirect(url_for("settings.notifications", status="ACTIVE"))

def _get_accessible_notification_or_404(notification_id):
    notification = get_notification_or_none(notification_id, branch_id=current_user.branch_id)
    if not notification or not can_user_access_notification(notification, current_user):
        abort(404)
    return notification


@settings_bp.route("/notifications/<int:notification_id>/read", methods=["POST"])
@role_required("OWNER", "ADMIN", "FINANCE", "ACCOUNTING", "LOGISTICS", "HR", "DAPUR", "PENGANTAR")
def mark_notification_read_route(notification_id):
    notification = _get_accessible_notification_or_404(notification_id)
    mark_notification_read(notification)
    record_audit_log(
        module="NOTIFICATION",
        event_type="NOTIFICATION_MARKED_READ",
        action="UPDATE",
        table_name="notifications",
        record_id=notification.id,
        description="Notifikasi ditandai sudah dibaca.",
    )
    flash("Notifikasi ditandai sudah dibaca.", "success")
    return redirect(request.referrer or url_for("settings.notifications"))


@settings_bp.route("/notifications/<int:notification_id>/unread", methods=["POST"])
@role_required("OWNER", "ADMIN", "FINANCE", "ACCOUNTING", "LOGISTICS", "HR", "DAPUR", "PENGANTAR")
def mark_notification_unread_route(notification_id):
    notification = _get_accessible_notification_or_404(notification_id)
    mark_notification_unread(notification)
    record_audit_log(
        module="NOTIFICATION",
        event_type="NOTIFICATION_MARKED_UNREAD",
        action="UPDATE",
        table_name="notifications",
        record_id=notification.id,
        description="Notifikasi ditandai belum dibaca.",
    )
    flash("Notifikasi ditandai belum dibaca.", "success")
    return redirect(request.referrer or url_for("settings.notifications"))


@settings_bp.route("/notifications/<int:notification_id>/dismiss", methods=["POST"])
@role_required("OWNER", "ADMIN", "FINANCE", "ACCOUNTING", "LOGISTICS", "HR", "DAPUR", "PENGANTAR")
def dismiss_notification_route(notification_id):
    notification = _get_accessible_notification_or_404(notification_id)
    mark_notification_dismissed(notification)
    record_audit_log(
        module="NOTIFICATION",
        event_type="NOTIFICATION_DISMISSED",
        action="UPDATE",
        table_name="notifications",
        record_id=notification.id,
        description="Notifikasi di-dismiss oleh user.",
    )
    flash("Notifikasi berhasil diabaikan/dismiss.", "success")
    return redirect(request.referrer or url_for("settings.notifications"))


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
