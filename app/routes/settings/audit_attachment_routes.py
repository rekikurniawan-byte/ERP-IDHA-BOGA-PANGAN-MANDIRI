"""Settings audit log and attachment routes.

Route functions moved out without changing URL rules or endpoint names.
"""
import csv
from io import StringIO

from flask import Response

from app.routes.settings_routes import *  # noqa: F401,F403


def _parse_audit_log_filters(args):
    date_from_raw = (args.get("date_from") or "").strip()
    date_to_raw = (args.get("date_to") or "").strip()
    module = (args.get("module") or "").strip()
    event_type = (args.get("event_type") or "").strip()
    action = (args.get("action") or "").strip()
    severity = (args.get("severity") or "").strip().upper()
    critical_only = args.get("critical_only") == "1"
    q = (args.get("q") or "").strip()

    date_from = None
    date_to = None
    try:
        if date_from_raw:
            date_from = datetime.strptime(date_from_raw, "%Y-%m-%d")
        if date_to_raw:
            date_to = datetime.strptime(date_to_raw, "%Y-%m-%d") + timedelta(days=1)
    except Exception:
        logger.exception("Suppressed unexpected exception in app/routes/settings_routes.py:682")
        flash("Filter tanggal audit log tidak valid.", "warning")
        date_from = None
        date_to = None

    return {
        "date_from_raw": date_from_raw,
        "date_to_raw": date_to_raw,
        "date_from": date_from,
        "date_to": date_to,
        "module": module,
        "event_type": event_type,
        "action": action,
        "severity": severity,
        "critical_only": critical_only,
        "q": q,
    }


@settings_bp.route("/audit-logs")
@role_required("OWNER")
def audit_logs():
    filters = _parse_audit_log_filters(request.args)

    options = get_audit_filter_options(branch_id=current_user.branch_id)
    logs = get_audit_logs(
        branch_id=current_user.branch_id,
        module=filters["module"] or None,
        event_type=filters["event_type"] or None,
        action=filters["action"] or None,
        q=filters["q"] or None,
        date_from=filters["date_from"],
        date_to=filters["date_to"],
        severity=filters["severity"] or None,
        critical_only=filters["critical_only"],
        limit=300,
    )
    audit_summary = get_audit_log_summary(logs)

    return render_template(
        "settings/audit_logs.html",
        logs=logs,
        options=options,
        summary=audit_summary,
        filters={
            "date_from": filters["date_from_raw"],
            "date_to": filters["date_to_raw"],
            "module": filters["module"],
            "event_type": filters["event_type"],
            "action": filters["action"],
            "severity": filters["severity"],
            "critical_only": filters["critical_only"],
            "q": filters["q"],
        },
    )


@settings_bp.route("/audit-logs/export.csv")
@role_required("OWNER")
def export_audit_logs_csv():
    filters = _parse_audit_log_filters(request.args)
    logs = get_audit_logs(
        branch_id=current_user.branch_id,
        module=filters["module"] or None,
        event_type=filters["event_type"] or None,
        action=filters["action"] or None,
        q=filters["q"] or None,
        date_from=filters["date_from"],
        date_to=filters["date_to"],
        severity=filters["severity"] or None,
        critical_only=filters["critical_only"],
        limit=5000,
    )

    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        "id",
        "created_at",
        "module",
        "event_type",
        "action",
        "severity",
        "username",
        "table_name",
        "record_id",
        "description",
    ])
    for log in logs:
        writer.writerow([
            log.id,
            log.created_at.isoformat() if log.created_at else "",
            log.module,
            log.event_type,
            log.action,
            getattr(log, "audit_severity", None) or "-",
            log.username_snapshot,
            log.table_name,
            log.record_id,
            log.description,
        ])

    record_audit_log(
        module="AUDIT",
        event_type="AUDIT_LOG_EXPORTED",
        action="EXPORT",
        description=f"Audit log diekspor ke CSV sebanyak {len(logs)} baris.",
        metadata={"filters": filters, "row_count": len(logs)},
    )

    response = Response(buffer.getvalue(), mimetype="text/csv")
    response.headers["Content-Disposition"] = "attachment; filename=audit_logs.csv"
    response.headers["Cache-Control"] = "no-store"
    return response


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
    except FileNotFoundError:
        logger.warning("File lampiran digital hilang: attachment_id=%s", attachment_id)
        file_exists = False
    except Exception:
        logger.exception("Suppressed unexpected exception in app/routes/settings_routes.py:778")
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
    except FileNotFoundError as exc:
        logger.warning("File lampiran digital hilang: attachment_id=%s", attachment_id)
        flash(f"File lampiran tidak ditemukan: {exc}", "warning")
        return redirect(url_for("settings.digital_attachment_detail", attachment_id=attachment_id))
    except Exception as exc:
        logger.exception("Suppressed unexpected exception in app/routes/settings_routes.py:798")
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
    except FileNotFoundError as exc:
        logger.warning("File lampiran digital hilang: attachment_id=%s", attachment_id)
        flash(f"File lampiran tidak ditemukan: {exc}", "warning")
        return redirect(url_for("settings.digital_attachment_detail", attachment_id=attachment_id))
    except Exception as exc:
        logger.exception("Suppressed unexpected exception in app/routes/settings_routes.py:822")
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
