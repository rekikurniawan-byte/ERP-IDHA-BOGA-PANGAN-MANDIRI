"""Settings reminder and notification routes.

Route functions moved out without changing URL rules or endpoint names.
"""
from app.routes.settings_routes import *  # noqa: F401,F403
from app.services.live_reminder_service import allowed_reminder_sections


@settings_bp.route("/reminders")
@role_required("OWNER", "ADMIN", "FINANCE", "ACCOUNTING", "LOGISTICS", "HR", "DAPUR", "PENGANTAR")
def live_reminders():
    allowed = allowed_reminder_sections(current_user)
    if not allowed:
        flash("Akses ditolak. Role kamu tidak memiliki reminder internal.", "danger")
        return redirect(url_for("dashboard.index"))

    due_days_raw = (request.args.get("due_days") or "7").strip()
    try:
        due_days = max(0, min(int(due_days_raw), 60))
    except Exception:
        logger.exception("Suppressed unexpected exception in app/routes/settings_routes.py:877")
        due_days = 7
        flash("Filter hari reminder tidak valid, sistem memakai 7 hari.", "warning")

    try:
        reminder_center = build_live_reminder_center(
            current_user.branch_id,
            user=current_user,
            due_days=due_days,
            limit_per_section=15,
        )
    except Exception as exc:
        current_app.logger.exception("Live reminder center failed")
        reminder_center = build_empty_live_reminder_center(
            user=current_user,
            due_days=due_days,
            runtime_warning=f"Ada bagian reminder yang belum bisa dihitung: {exc}",
        )
        flash("Pengingat tetap dibuka dalam mode aman. Detail error tercatat di log server.", "warning")

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
        logger.exception("Suppressed unexpected exception in app/routes/settings_routes.py:969")
        due_days = 7
    due_days = max(1, min(due_days, 60))

    try:
        limit_per_section = int(request.form.get("limit_per_section") or 15)
    except Exception:
        logger.exception("Suppressed unexpected exception in app/routes/settings_routes.py:975")
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
