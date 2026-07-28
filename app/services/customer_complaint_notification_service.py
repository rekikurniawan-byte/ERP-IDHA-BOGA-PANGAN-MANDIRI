from __future__ import annotations

from datetime import datetime
from typing import Any

from app.extensions import db
from app.models.complaint import CustomerComplaint
from app.services.atomic_transaction_service import atomic_business_action
from app.services.customer_complaint_service import COMPLAINT_STATUS_IN_PROGRESS, COMPLAINT_STATUS_OPEN
from app.services.notification_service import create_or_update_notification, resolve_generated_notifications_not_in


COMPLAINT_NOTIFICATION_TYPE = "CUSTOMER_COMPLAINT"
COMPLAINT_REFERENCE_TYPE = "CUSTOMER_COMPLAINT"
COMPLAINT_NOTIFICATION_KEY_PREFIX = "customer-complaint"
COMPLAINT_NOTIFICATION_TARGET_ROLE = "ADMIN"
ACTIVE_COMPLAINT_STATUSES = {COMPLAINT_STATUS_OPEN, COMPLAINT_STATUS_IN_PROGRESS}


def build_customer_complaint_queue(
    *,
    branch_id: int,
    status: str = "ACTIVE",
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Build a read-only queue for unresolved customer complaints."""
    query = CustomerComplaint.query.filter(CustomerComplaint.branch_id == branch_id)
    normalized_status = str(status or "ACTIVE").strip().upper()
    if normalized_status == "ACTIVE":
        query = query.filter(CustomerComplaint.status.in_(ACTIVE_COMPLAINT_STATUSES))
    elif normalized_status != "ALL":
        query = query.filter(CustomerComplaint.status == normalized_status)

    rows = query.order_by(
        CustomerComplaint.status.asc(),
        CustomerComplaint.submitted_at.asc(),
        CustomerComplaint.id.asc(),
    ).limit(_safe_limit(limit)).all()
    return [_queue_item(row) for row in rows]


def generate_customer_complaint_notifications(
    *,
    branch_id: int,
    generated_by: int | None = None,
    limit: int = 100,
    commit: bool = True,
) -> dict[str, Any]:
    """Generate idempotent notifications for OPEN/IN_PROGRESS complaints."""
    queue = build_customer_complaint_queue(branch_id=branch_id, status="ACTIVE", limit=limit)
    active_keys: list[str] = []
    created = 0
    updated = 0

    boundary = (
        atomic_business_action(
            module="COMPLAINT",
            action="CUSTOMER_COMPLAINT_NOTIFICATIONS_GENERATED",
            description="Generate customer complaint queue notifications.",
            reference_type=COMPLAINT_REFERENCE_TYPE,
            user_id=generated_by,
            branch_id=branch_id,
            severity="LOW",
            metadata={"active_count": len(queue), "mutation_scope": "NOTIFICATION_ONLY"},
        )
        if commit
        else _NullContext()
    )

    with boundary:
        for item in queue:
            key = _notification_key(branch_id, item)
            active_keys.append(key)
            _, was_created = create_or_update_notification(
                branch_id=branch_id,
                notification_type=COMPLAINT_NOTIFICATION_TYPE,
                title=item["title"],
                message=item["message"],
                target_role=COMPLAINT_NOTIFICATION_TARGET_ROLE,
                priority=item["priority"],
                reference_type=COMPLAINT_REFERENCE_TYPE,
                reference_id=item["complaint_id"],
                action_url="#",
                due_date=None,
                generated_key=key,
                metadata=item,
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
            key_prefix=_notification_key_prefix(branch_id),
            commit=False,
        )
        db.session.flush()

    return {
        "created": created,
        "updated": updated,
        "resolved": resolved,
        "active": len(active_keys),
        "notification_type": COMPLAINT_NOTIFICATION_TYPE,
        "mutation_scope": "NOTIFICATION_ONLY",
    }


def _queue_item(complaint: CustomerComplaint) -> dict[str, Any]:
    submitted_at = complaint.submitted_at or complaint.created_at
    age_hours = _age_hours(submitted_at)
    priority = "WARNING" if complaint.status == COMPLAINT_STATUS_OPEN else "INFO"
    client_name = getattr(complaint.client, "name", None) or "-"
    mandor_name = getattr(complaint.mandor, "name", None) or "-"
    return {
        "complaint_id": complaint.id,
        "complaint_number": complaint.complaint_number,
        "category": complaint.category,
        "status": complaint.status,
        "client_id": complaint.client_id,
        "client_name": client_name,
        "mandor_id": complaint.mandor_id,
        "mandor_name": mandor_name,
        "title": f"Complaint {complaint.complaint_number} perlu ditindaklanjuti",
        "message": f"{complaint.title} | {client_name} / {mandor_name} | Status {complaint.status}.",
        "priority": priority,
        "submitted_at": submitted_at,
        "age_hours": age_hours,
        "assigned_to": complaint.assigned_to,
        "reference": {
            "order_id": complaint.order_id,
            "delivery_id": complaint.delivery_id,
            "invoice_id": complaint.invoice_id,
        },
    }


def _age_hours(submitted_at) -> int:
    if not submitted_at:
        return 0
    delta = datetime.utcnow() - submitted_at
    return max(0, int(delta.total_seconds() // 3600))


def _notification_key_prefix(branch_id: int) -> str:
    return f"{COMPLAINT_NOTIFICATION_KEY_PREFIX}:{int(branch_id)}:"


def _notification_key(branch_id: int, item: dict[str, Any]) -> str:
    return f"{_notification_key_prefix(branch_id)}{item['complaint_id']}"[:180]


def _safe_limit(limit: int) -> int:
    try:
        return max(1, min(int(limit), 500))
    except Exception:
        return 100


class _NullContext:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False
