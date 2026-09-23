from __future__ import annotations

from decimal import Decimal

from sqlalchemy import false

from app.models.canteen import WorkerDebt
from app.models.master import Worker
from app.services.portal_mapping_service import (
    PRINCIPAL_DELEGATE,
    build_portal_external_scope,
    list_active_portal_mappings,
)
from app.services.user_management_service import (
    ROLE_PORTAL_CLIENT,
    ROLE_PORTAL_CUSTOMER,
    ROLE_PORTAL_DELEGATE,
    ROLE_PORTAL_SUBCLIENT,
    ROLE_PORTAL_PT,
)


INACTIVE_DEBT_STATUSES = {"PAID", "CANCELLED", "VOID", "VOIDED"}


def _money(value) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _normalized_status(value) -> str:
    return str(value or "").strip().upper()


def _payment_sum(worker_debt: WorkerDebt) -> Decimal:
    return sum((_money(payment.amount) for payment in worker_debt.payments), Decimal("0"))


def _remaining_amount(worker_debt: WorkerDebt) -> Decimal:
    remaining = _money(worker_debt.debt_amount) - _payment_sum(worker_debt)
    return max(remaining, Decimal("0"))


def _direct_delegate_mandor_ids(user) -> set[int]:
    mandor_ids = set()
    for mapping in list_active_portal_mappings(user):
        if mapping.principal_type != PRINCIPAL_DELEGATE:
            continue
        if mapping.mandor_id:
            mandor_ids.add(mapping.mandor_id)
        if mapping.delivery_location and mapping.delivery_location.mandor_id:
            mandor_ids.add(mapping.delivery_location.mandor_id)
    return mandor_ids


def _mandor_ids_for_worker_debt_scope(user, scope) -> set[int]:
    role = getattr(user, "role", None)

    if role in {ROLE_PORTAL_CLIENT, ROLE_PORTAL_PT, ROLE_PORTAL_SUBCLIENT}:
        return set(scope.mandor_ids)

    if role == ROLE_PORTAL_DELEGATE:
        return _direct_delegate_mandor_ids(user)

    return set()


def _worker_debt_row(worker_debt: WorkerDebt) -> dict:
    worker = worker_debt.worker
    sale = worker_debt.sale
    paid_amount = _payment_sum(worker_debt)
    remaining_amount = _remaining_amount(worker_debt)
    status = _normalized_status(worker_debt.status)
    active_debt = status not in INACTIVE_DEBT_STATUSES and remaining_amount > 0

    return {
        "worker_debt_id": worker_debt.id,
        "worker_id": worker_debt.worker_id,
        "worker_name": worker.full_name if worker else "-",
        "mandor_id": worker.mandor_id if worker else None,
        "mandor_name": worker.mandor.name if worker and worker.mandor else "-",
        "sale_id": worker_debt.sale_id,
        "sale_date": sale.sale_date if sale else None,
        "debt_amount": _money(worker_debt.debt_amount),
        "paid_amount": paid_amount,
        "remaining_amount": remaining_amount,
        "payment_count": len(worker_debt.payments),
        "status": status,
        "active_debt": active_debt,
    }


def build_portal_worker_debt_read_model(user, *, limit: int = 100) -> dict:
    """Return read-only worker debt detail scoped to portal ownership."""
    scope = build_portal_external_scope(user)
    role = getattr(user, "role", None)

    if role == ROLE_PORTAL_CUSTOMER:
        return {
            "allowed": False,
            "scope_mode": "PORTAL_CUSTOMER_DEBT_BLOCKED",
            "reason": "Worker debt visibility pelanggan umum tidak dibuka pada Stage 2.",
            "debts": [],
            "totals": _empty_totals(),
        }

    if not scope.allowed:
        return {
            "allowed": False,
            "scope_mode": scope.scope_mode,
            "reason": scope.reason,
            "debts": [],
            "totals": _empty_totals(),
        }

    mandor_ids = _mandor_ids_for_worker_debt_scope(user, scope)
    if not mandor_ids:
        query_filter = false()
    else:
        query_filter = Worker.mandor_id.in_(sorted(mandor_ids))

    debts = (
        WorkerDebt.query.join(Worker, Worker.id == WorkerDebt.worker_id)
        .filter(query_filter)
        .order_by(WorkerDebt.id.desc())
        .limit(limit)
        .all()
    )
    rows = [_worker_debt_row(debt) for debt in debts]

    return {
        "allowed": True,
        "scope_mode": scope.scope_mode,
        "reason": "Worker debt read model dibatasi oleh mandor ownership mapping.",
        "debts": rows,
        "totals": _build_totals(rows),
    }


def _empty_totals() -> dict:
    return {
        "debt_count": 0,
        "active_debt_count": 0,
        "debt_amount": Decimal("0"),
        "paid_amount": Decimal("0"),
        "remaining_amount": Decimal("0"),
        "active_remaining_amount": Decimal("0"),
    }


def _build_totals(rows: list[dict]) -> dict:
    totals = _empty_totals()
    totals["debt_count"] = len(rows)
    for row in rows:
        totals["debt_amount"] += row["debt_amount"]
        totals["paid_amount"] += row["paid_amount"]
        totals["remaining_amount"] += row["remaining_amount"]
        if row["active_debt"]:
            totals["active_debt_count"] += 1
            totals["active_remaining_amount"] += row["remaining_amount"]
    return totals
