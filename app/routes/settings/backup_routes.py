"""Settings backup routes.

Route functions moved out without changing URL rules or endpoint names.
"""
from app.routes.settings_routes import *  # noqa: F401,F403


@settings_bp.route("/backups")
@role_required("OWNER")
def backups():
    try:
        status = get_backup_status()
        restore_sop = get_restore_manual_sop()
    except Exception as exc:
        logger.exception("Suppressed unexpected exception in app/routes/settings_routes.py:409")
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
        logger.exception("Suppressed unexpected exception in app/routes/settings_routes.py:438")
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
        logger.exception("Suppressed unexpected exception in app/routes/settings_routes.py:495")
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
        logger.exception("Suppressed unexpected exception in app/routes/settings_routes.py:549")
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
        logger.exception("Suppressed unexpected exception in app/routes/settings_routes.py:608")
        flash(f"Full backup gagal dibuat: {exc}", "danger")

    return redirect(url_for("settings.backups"))


@settings_bp.route("/backups/download-confirm/<path:filename>")
@role_required("OWNER")
def download_backup_confirm(filename):
    try:
        file_path, mimetype = get_backup_file(filename)
    except Exception as exc:
        logger.exception("Suppressed unexpected exception in app/routes/settings_routes.py:619")
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
        logger.exception("Suppressed unexpected exception in app/routes/settings_routes.py:646")
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
