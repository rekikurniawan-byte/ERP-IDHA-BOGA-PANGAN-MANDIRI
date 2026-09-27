import logging
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

logger = logging.getLogger(__name__)


settings_bp = Blueprint("settings", __name__, url_prefix="/settings")


# Domain route modules. Imported after shared helpers are defined so decorators bind to the same blueprint.
from app.routes.settings import account_routes as _settings_account_routes  # noqa: F401,E402
from app.routes.settings import recovery_health_routes as _settings_recovery_health_routes  # noqa: F401,E402
from app.routes.settings import backup_routes as _settings_backup_routes  # noqa: F401,E402
from app.routes.settings import audit_attachment_routes as _settings_audit_attachment_routes  # noqa: F401,E402
from app.routes.settings import notification_routes as _settings_notification_routes  # noqa: F401,E402
from app.routes.settings import approval_routes as _settings_approval_routes  # noqa: F401,E402
from app.routes.settings import pricing_routes as _settings_pricing_routes  # noqa: F401,E402
