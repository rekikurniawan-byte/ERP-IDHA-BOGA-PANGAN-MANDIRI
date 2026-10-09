"""Persistent notification service for Idha Boga.

This service is intentionally small and defensive. It stores notification rows,
prevents duplicate generated reminders through generated_key, and keeps read /
dismiss / resolved state separate from the existing Live Reminder Center.
"""
from __future__ import annotations
import logging

import json
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import or_

from app.extensions import db
from app.models.system import Notification
from app.services.live_reminder_service import build_live_reminder_center
from app.utils.roles import RETIRED_ROLE_SUCCESSOR, effective_role

logger = logging.getLogger(__name__)

NOTIFICATION_STATUSES = {"UNREAD", "READ", "DISMISSED", "RESOLVED"}
NOTIFICATION_PRIORITIES = {"CRITICAL", "WARNING", "INFO"}
INTERNAL_ROLES = {"OWNER", "ADMIN", "DAPUR", "PENGANTAR"}
PORTAL_ROLES = {"PORTAL_CLIENT", "PORTAL_SUBCLIENT", "PORTAL_CUSTOMER"}
ROLE_TARGETS = INTERNAL_ROLES | PORTAL_ROLES


def equivalent_target_roles(role: Optional[str]) -> set[str]:
    if not role:
        return set()
    eff = effective_role(role)
    if not eff:
        return set()
    roles = {eff}
    for old_role, new_role in RETIRED_ROLE_SUCCESSOR.items():
        if new_role == eff:
            roles.add(old_role)
    return roles

def visible_target_roles(role: Optional[str]) -> set[str]:
    """Role-target yang boleh DILIHAT user ini.

    OWNER memantau dan ikut menyetujui pekerjaan ADMIN (bukti bayar, pesanan
    portal, persetujuan kredit), jadi notifikasi untuk ADMIN juga tampil untuknya.
    """
    roles = equivalent_target_roles(role)
    if effective_role(role) == "OWNER":
        roles |= equivalent_target_roles("ADMIN")
    return roles


# Finance and stock reminders used to target FINANCE and LOGISTICS. Those
# roles are retired and ADMIN does the work (app/utils/roles.py), so a
# reminder addressed to them would have been stored for nobody and never
# seen. They now go to ADMIN.
SECTION_ROLE_TARGET = {
    "receivable": "ADMIN",
    "payable": "ADMIN",
    "cash_bank": "ADMIN",
    "digital_proof": "ADMIN",
    "stock": "ADMIN",
    "hpp_order": "ADMIN",
    "delivery": "PENGANTAR",
}


def _now() -> datetime:
    return datetime.utcnow()


def _normalize_status(status: Optional[str]) -> str:
    value = str(status or "UNREAD").strip().upper()
    return value if value in NOTIFICATION_STATUSES else "UNREAD"


def _normalize_priority(priority: Optional[str]) -> str:
    value = str(priority or "INFO").strip().upper()
    if value == "HIGH":
        value = "CRITICAL"
    return value if value in NOTIFICATION_PRIORITIES else "INFO"


def _normalize_role(role: Optional[str]) -> Optional[str]:
    # A caller naming a retired role (e.g. a form posting target_role=FINANCE)
    # is addressed to that role's successor rather than silently dropped.
    value = effective_role(role)
    return value if value in ROLE_TARGETS else None


def _json_dumps(metadata: Optional[Dict[str, Any]]) -> Optional[str]:
    if not metadata:
        return None
    return json.dumps(metadata, ensure_ascii=False, default=str, sort_keys=True)


def _json_loads(raw: Optional[str]) -> Dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {"value": value}
    except Exception:
        logger.exception("Suppressed unexpected exception in app/services/notification_service.py:67")
        return {"raw": raw}


def _truncate(value: Any, limit: int) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:limit]


def notification_to_dict(notification: Notification) -> Dict[str, Any]:
    """Return a UI/report friendly dict without mutating the row."""
    return {
        "id": notification.id,
        "branch_id": notification.branch_id,
        "notification_type": notification.notification_type,
        "title": notification.title,
        "message": notification.message,
        "status": notification.status,
        "priority": notification.priority,
        "target_user_id": notification.target_user_id,
        "target_role": notification.target_role,
        "reference_type": notification.reference_type,
        "reference_id": notification.reference_id,
        "action_url": notification.action_url,
        "due_date": notification.due_date,
        "read_at": notification.read_at,
        "dismissed_at": notification.dismissed_at,
        "resolved_at": notification.resolved_at,
        "generated_key": notification.generated_key,
        "metadata": _json_loads(notification.metadata_json),
        "created_at": notification.created_at,
    }


def get_notification_or_none(notification_id: int, *, branch_id: Optional[int] = None) -> Optional[Notification]:
    query = Notification.query.filter(Notification.id == notification_id)
    if branch_id is not None:
        query = query.filter(Notification.branch_id == branch_id)
    return query.first()


def can_user_access_notification(notification: Notification, user: Any) -> bool:
    """User can only see notifications addressed to them, their role, or general branch."""
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if notification.branch_id != getattr(user, "branch_id", None):
        return False
    user_role = getattr(user, "role", "")
    eff_role = effective_role(user_role)
    user_id = getattr(user, "id", None)
    is_portal = eff_role in PORTAL_ROLES

    # 1. Targeted specifically to a user
    if notification.target_user_id is not None:
        return notification.target_user_id == user_id

    # 2. Targeted to a role
    if notification.target_role:
        allowed = visible_target_roles(eff_role)
        return notification.target_role in allowed

    # 3. General branch notification (target_user_id is None and target_role is None)
    # Portal users cannot see internal branch notifications
    if is_portal:
        return False
    return True


def list_notifications(
    *,
    branch_id: int,
    user: Any = None,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    notification_type: Optional[str] = None,
    target_role: Optional[str] = None,
    include_resolved: bool = False,
    limit: int = 200,
) -> List[Notification]:
    """List persistent notifications with safe role and user filtering."""
    query = Notification.query.filter(Notification.branch_id == branch_id)

    if user is not None:
        user_role = getattr(user, "role", "")
        eff_role = effective_role(user_role)
        user_id = getattr(user, "id", None)
        is_portal = eff_role in PORTAL_ROLES
        allowed_roles = visible_target_roles(eff_role)

        conditions = []
        # 1. Target spesifik user ID ini
        if user_id:
            conditions.append(Notification.target_user_id == user_id)

        # 2. Target role user (hanya notifikasi yang tidak ditujukan ke spesifik user lain)
        if allowed_roles:
            conditions.append(
                Notification.target_user_id.is_(None) & Notification.target_role.in_(allowed_roles)
            )

        # 3. Notifikasi umum cabang internal (hanya untuk staf internal)
        if not is_portal:
            conditions.append(
                Notification.target_user_id.is_(None) & Notification.target_role.is_(None)
            )

        if conditions:
            query = query.filter(or_(*conditions))
        else:
            query = query.filter(db.false())

    if status:
        query = query.filter(Notification.status == _normalize_status(status))
    elif not include_resolved:
        query = query.filter(Notification.status != "RESOLVED")

    if priority:
        query = query.filter(Notification.priority == _normalize_priority(priority))
    if notification_type:
        query = query.filter(Notification.notification_type == notification_type)
    if target_role:
        eq_roles = equivalent_target_roles(target_role)
        if eq_roles:
            query = query.filter(Notification.target_role.in_(eq_roles))

    try:
        limit = max(1, min(int(limit), 500))
    except Exception:
        logger.exception("Suppressed unexpected exception in app/services/notification_service.py:170")
        limit = 200

    return query.order_by(
        Notification.status.asc(),
        Notification.priority.asc(),
        Notification.due_date.asc(),
        Notification.created_at.desc(),
        Notification.id.desc(),
    ).limit(limit).all()


def count_unread_notifications(*, branch_id: int, user: Any = None) -> Dict[str, int]:
    """Count unread persistent notifications visible to the user."""
    rows = list_notifications(
        branch_id=branch_id,
        user=user,
        status="UNREAD",
        include_resolved=False,
        limit=500,
    )
    return {
        "total": len(rows),
        "critical": sum(1 for row in rows if row.priority == "CRITICAL"),
        "warning": sum(1 for row in rows if row.priority == "WARNING"),
        "info": sum(1 for row in rows if row.priority == "INFO"),
    }


def get_notification_status_summary(*, branch_id: int, user: Any = None) -> Dict[str, int]:
    """Return status/priority counts visible to the user for the notification center."""
    visible = list_notifications(
        branch_id=branch_id,
        user=user,
        status=None,
        include_resolved=True,
        limit=500,
    )
    return {
        "total": len(visible),
        "unread": sum(1 for row in visible if row.status == "UNREAD"),
        "read": sum(1 for row in visible if row.status == "READ"),
        "dismissed": sum(1 for row in visible if row.status == "DISMISSED"),
        "resolved": sum(1 for row in visible if row.status == "RESOLVED"),
        "critical": sum(1 for row in visible if row.priority == "CRITICAL" and row.status == "UNREAD"),
        "warning": sum(1 for row in visible if row.priority == "WARNING" and row.status == "UNREAD"),
        "info": sum(1 for row in visible if row.priority == "INFO" and row.status == "UNREAD"),
    }


def create_or_update_notification(
    *,
    branch_id: int,
    notification_type: str,
    title: str,
    message: str,
    target_user_id: Optional[int] = None,
    target_role: Optional[str] = None,
    priority: str = "INFO",
    reference_type: Optional[str] = None,
    reference_id: Optional[int] = None,
    action_url: Optional[str] = None,
    due_date: Optional[date] = None,
    generated_key: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    status: str = "UNREAD",
    commit: bool = True,
) -> Tuple[Notification, bool]:
    """Create/update a persistent notification.

    Returns (notification, created). If generated_key exists, the row is updated
    instead of duplicated. Dismissed rows are kept dismissed unless explicitly
    passed a different status by a caller in a future controlled workflow.
    """
    if not branch_id:
        raise ValueError("branch_id wajib diisi.")
    notification_type = _truncate(notification_type, 50)
    title = _truncate(title, 150)
    message = str(message or "").strip()
    if not notification_type:
        raise ValueError("notification_type wajib diisi.")
    if not title:
        raise ValueError("title notifikasi wajib diisi.")
    if not message:
        raise ValueError("message notifikasi wajib diisi.")

    normalized_status = _normalize_status(status)
    normalized_priority = _normalize_priority(priority)
    normalized_role = _normalize_role(target_role)
    generated_key = _truncate(generated_key, 180)

    notification = None
    created = False
    if generated_key:
        notification = Notification.query.filter_by(generated_key=generated_key).first()

    if notification is None:
        notification = Notification(
            branch_id=branch_id,
            notification_type=notification_type,
            title=title,
            message=message,
            status=normalized_status,
            target_user_id=target_user_id,
            target_role=normalized_role,
            priority=normalized_priority,
            reference_type=_truncate(reference_type, 80),
            reference_id=reference_id,
            action_url=_truncate(action_url, 500),
            due_date=due_date,
            generated_key=generated_key,
            metadata_json=_json_dumps(metadata),
        )
        db.session.add(notification)
        created = True
    else:
        notification.notification_type = notification_type
        notification.title = title
        notification.message = message
        notification.target_user_id = target_user_id
        notification.target_role = normalized_role
        notification.priority = normalized_priority
        notification.reference_type = _truncate(reference_type, 80)
        notification.reference_id = reference_id
        notification.action_url = _truncate(action_url, 500)
        notification.due_date = due_date
        notification.metadata_json = _json_dumps(metadata)
        # Reopen resolved generated notifications when the condition becomes active again.
        if notification.status == "RESOLVED" and normalized_status == "UNREAD":
            notification.status = "UNREAD"
            notification.read_at = None
            notification.dismissed_at = None
            notification.resolved_at = None
        elif notification.status not in {"DISMISSED", "READ", "UNREAD"}:
            notification.status = normalized_status

    if commit:
        db.session.commit()
    return notification, created


def mark_notification_read(notification: Notification, *, commit: bool = True) -> Notification:
    if notification.status == "UNREAD":
        notification.status = "READ"
        notification.read_at = _now()
    if commit:
        db.session.commit()
    return notification


def mark_notification_unread(notification: Notification, *, commit: bool = True) -> Notification:
    if notification.status in {"READ", "DISMISSED"}:
        notification.status = "UNREAD"
        notification.read_at = None
        notification.dismissed_at = None
    if commit:
        db.session.commit()
    return notification


def mark_notification_dismissed(notification: Notification, *, commit: bool = True) -> Notification:
    notification.status = "DISMISSED"
    notification.dismissed_at = _now()
    if commit:
        db.session.commit()
    return notification


def resolve_generated_notifications_not_in(
    *,
    branch_id: int,
    generated_keys: Iterable[str],
    key_prefix: Optional[str] = None,
    commit: bool = True,
) -> int:
    """Mark old generated notifications resolved when their live issue disappeared."""
    active_keys = {str(key) for key in generated_keys if key}
    query = Notification.query.filter(
        Notification.branch_id == branch_id,
        Notification.generated_key.isnot(None),
        Notification.status != "RESOLVED",
    )
    if key_prefix:
        query = query.filter(Notification.generated_key.like(f"{key_prefix}%"))

    count = 0
    for notification in query.all():
        if notification.generated_key not in active_keys:
            notification.status = "RESOLVED"
            notification.resolved_at = _now()
            count += 1

    if commit:
        db.session.commit()
    return count


def _generated_key_from_live_item(branch_id: int, section_key: str, item: Dict[str, Any]) -> str:
    reference_label = str(item.get("reference_label") or "-").strip()
    title = str(item.get("title") or "-").strip()
    # Reference label is usually invoice number, bill number, ledger id, order number, etc.
    return f"live:{branch_id}:{section_key}:{reference_label}:{title}"[:180]


def generate_notifications_from_live_reminders(
    *,
    branch_id: int,
    due_days: int = 7,
    limit_per_section: int = 15,
    commit: bool = True,
) -> Dict[str, Any]:
    """Generate persistent notifications from Live Reminder Center.

    This function is safe/idempotent through generated_key. It is intentionally
    callable manually by a future UI, not as a background job.
    """
    center = build_live_reminder_center(branch_id, due_days=due_days, limit_per_section=limit_per_section)
    created = 0
    updated = 0
    active_keys: List[str] = []

    for section in center.get("sections", []):
        section_key = section.get("key") or "general"
        target_role = SECTION_ROLE_TARGET.get(section_key)
        for item in section.get("items", []):
            key = _generated_key_from_live_item(branch_id, section_key, item)
            active_keys.append(key)
            notification, was_created = create_or_update_notification(
                branch_id=branch_id,
                notification_type=str(section_key).upper(),
                title=item.get("title") or section.get("title") or "Reminder",
                message=item.get("message") or "Reminder perlu dicek.",
                target_role=target_role,
                priority=item.get("severity") or "INFO",
                reference_type=str(section_key).upper(),
                reference_id=None,
                action_url=item.get("action_url") or "#",
                due_date=item.get("due_date"),
                generated_key=key,
                metadata={
                    "section": section_key,
                    "reference_label": item.get("reference_label"),
                    "amount": item.get("amount"),
                    "action_label": item.get("action_label"),
                    "live_metadata": item.get("metadata") or {},
                },
                status="UNREAD",
                commit=False,
            )
            if was_created:
                created += 1
            else:
                updated += 1

    resolved = resolve_generated_notifications_not_in(
        branch_id=branch_id,
        generated_keys=active_keys,
        key_prefix=f"live:{branch_id}:",
        commit=False,
    )

    if commit:
        db.session.commit()

    return {
        "created": created,
        "updated": updated,
        "resolved": resolved,
        "active": len(active_keys),
        "summary": center.get("summary", {}),
    }
