from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app.extensions import db
from app.models.contract import CustomerContract
from app.services.atomic_transaction_service import atomic_business_action
from app.services.customer_contract_service import CONTRACT_STATUS_ACTIVE
from app.services.notification_service import create_or_update_notification, resolve_generated_notifications_not_in


CONTRACT_EXPIRY_NOTIFICATION_TYPE = "CUSTOMER_CONTRACT_EXPIRY"
CONTRACT_EXPIRY_REFERENCE_TYPE = "CUSTOMER_CONTRACT"
CONTRACT_EXPIRY_KEY_PREFIX = "contract-expiry"
CONTRACT_EXPIRY_TARGET_ROLE = "ADMIN"
CONTRACT_EXPIRY_ACTION_URL = "/customer-success/contracts"
# Pengingat mulai H-30 sebagai peringatan, jadi mendesak mulai H-7.
URGENT_DAYS = 7


def build_contract_expiry_candidates(
    *,
    branch_id: int,
    as_of_date: date | None = None,
    due_days: int = 30,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return active contracts that are expired or close to expiry.

    Read-only by design. This does not set contract status to EXPIRED because
    lifecycle mutation remains an explicit service action.
    """
    today = as_of_date or date.today()
    due_days = _safe_due_days(due_days)
    limit = _safe_limit(limit)
    max_date = today + timedelta(days=due_days)

    contracts = CustomerContract.query.filter(
        CustomerContract.branch_id == branch_id,
        CustomerContract.status == CONTRACT_STATUS_ACTIVE,
        CustomerContract.end_date <= max_date,
    ).order_by(CustomerContract.end_date.asc(), CustomerContract.id.asc()).limit(limit).all()

    return [_candidate_payload(contract, today, due_days) for contract in contracts]


def generate_contract_expiry_notifications(
    *,
    branch_id: int,
    as_of_date: date | None = None,
    due_days: int = 30,
    limit: int = 100,
    generated_by: int | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    """Create/update persistent contract expiry notifications idempotently."""
    candidates = build_contract_expiry_candidates(
        branch_id=branch_id,
        as_of_date=as_of_date,
        due_days=due_days,
        limit=limit,
    )
    key_prefix = _notification_key_prefix(branch_id)

    created = 0
    updated = 0
    active_keys: list[str] = []

    boundary = (
        atomic_business_action(
            module="CONTRACT",
            action="CUSTOMER_CONTRACT_EXPIRY_NOTIFICATIONS_GENERATED",
            description="Generate customer contract expiry notifications.",
            reference_type=CONTRACT_EXPIRY_REFERENCE_TYPE,
            user_id=generated_by,
            branch_id=branch_id,
            severity="LOW",
            metadata={
                "due_days": _safe_due_days(due_days),
                "candidate_count": len(candidates),
                "mutation_scope": "NOTIFICATION_ONLY",
            },
        )
        if commit
        else _NullContext()
    )

    with boundary:
        for item in candidates:
            key = _notification_key(branch_id, item)
            active_keys.append(key)
            _, was_created = create_or_update_notification(
                branch_id=branch_id,
                notification_type=CONTRACT_EXPIRY_NOTIFICATION_TYPE,
                title=item["title"],
                message=item["message"],
                target_role=CONTRACT_EXPIRY_TARGET_ROLE,
                priority=item["priority"],
                reference_type=CONTRACT_EXPIRY_REFERENCE_TYPE,
                reference_id=item["contract_id"],
                action_url=CONTRACT_EXPIRY_ACTION_URL,
                due_date=item["end_date"],
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
            key_prefix=key_prefix,
            commit=False,
        )
        db.session.flush()

    return {
        "created": created,
        "updated": updated,
        "resolved": resolved,
        "active": len(active_keys),
        "due_days": _safe_due_days(due_days),
        "notification_type": CONTRACT_EXPIRY_NOTIFICATION_TYPE,
        "mutation_scope": "NOTIFICATION_ONLY",
    }


def _candidate_payload(contract: CustomerContract, today: date, due_days: int) -> dict[str, Any]:
    days_to_expiry = (contract.end_date - today).days
    overdue = days_to_expiry < 0
    priority = "CRITICAL" if days_to_expiry <= URGENT_DAYS else "WARNING"
    client_name = getattr(contract.client, "name", None) or "-"
    days_text = f"lewat {abs(days_to_expiry)} hari" if overdue else f"{days_to_expiry} hari lagi"
    return {
        "contract_id": contract.id,
        "contract_number": contract.contract_number,
        "client_id": contract.client_id,
        "client_name": client_name,
        "title": f"Kontrak {contract.contract_number} akan berakhir",
        "message": (
            f"Kontrak {client_name} berakhir {days_text}. Perpanjang sebelum habis; sesudah habis termin kembali "
            f"ke bawaan dan pesanan baru perlu persetujuan OWNER."
        ),
        "priority": priority,
        "status": contract.status,
        "start_date": contract.start_date,
        "end_date": contract.end_date,
        "days_to_expiry": days_to_expiry,
        "due_days": due_days,
        "overdue": overdue,
    }


def _notification_key_prefix(branch_id: int) -> str:
    return f"{CONTRACT_EXPIRY_KEY_PREFIX}:{int(branch_id)}:"


def _notification_key(branch_id: int, item: dict[str, Any]) -> str:
    end_date = item["end_date"].isoformat() if hasattr(item.get("end_date"), "isoformat") else str(item.get("end_date"))
    return f"{_notification_key_prefix(branch_id)}{item['contract_id']}:{end_date}"[:180]


def _safe_due_days(due_days: int) -> int:
    try:
        return max(0, min(int(due_days), 365))
    except Exception:
        return 30


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
