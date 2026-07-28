from __future__ import annotations

from decimal import Decimal

from app.models.accounting import PeriodClosing
from app.services.period_closing_service import get_period_bounds
from app.services.portal_debt_visibility_service import build_portal_worker_debt_read_model
from app.services.portal_financial_visibility_service import (
    build_portal_invoice_read_model,
    build_portal_payment_history_read_model,
)
from app.services.portal_mapping_service import build_portal_external_scope
from app.services.user_management_service import ROLE_PORTAL_CUSTOMER


def _empty_period_totals() -> dict:
    return {
        "invoice_count": 0,
        "invoice_total": Decimal("0"),
        "invoice_remaining": Decimal("0"),
        "payment_count": 0,
        "payment_amount": Decimal("0"),
        "worker_debt_count": 0,
        "worker_debt_remaining": Decimal("0"),
    }


def _in_period(value, start_date, end_date) -> bool:
    return bool(value and start_date <= value <= end_date)


def build_portal_closing_visibility(user, *, year=None, month=None) -> dict:
    """Return read-only period closing visibility for portal-owned financial data."""
    scope = build_portal_external_scope(user)
    role = getattr(user, "role", None)
    branch_id = getattr(user, "branch_id", None)
    y, m, start_date, end_date = get_period_bounds(year, month)

    if role == ROLE_PORTAL_CUSTOMER:
        return {
            "allowed": False,
            "scope_mode": "PORTAL_CUSTOMER_CLOSING_VISIBILITY_BLOCKED",
            "reason": "Closing visibility pelanggan umum tidak dibuka pada Stage 2.",
            "year": y,
            "month": m,
            "period_start": start_date,
            "period_end": end_date,
            "closing": _closing_status(None),
            "totals": _empty_period_totals(),
        }

    if not scope.allowed:
        return {
            "allowed": False,
            "scope_mode": scope.scope_mode,
            "reason": scope.reason,
            "year": y,
            "month": m,
            "period_start": start_date,
            "period_end": end_date,
            "closing": _closing_status(None),
            "totals": _empty_period_totals(),
        }

    closing = PeriodClosing.query.filter_by(branch_id=branch_id, period_year=y, period_month=m).first()
    totals = _empty_period_totals()

    invoice_model = build_portal_invoice_read_model(user, limit=1000)
    for row in invoice_model["invoices"]:
        if not _in_period(row["invoice_date"], start_date, end_date):
            continue
        totals["invoice_count"] += 1
        totals["invoice_total"] += row["total_amount"]
        if row["active_receivable"]:
            totals["invoice_remaining"] += row["remaining_amount"]

    payment_model = build_portal_payment_history_read_model(user, limit=1000)
    for row in payment_model["payments"]:
        if not _in_period(row["payment_date"], start_date, end_date):
            continue
        totals["payment_count"] += 1
        totals["payment_amount"] += row["amount"]

    debt_model = build_portal_worker_debt_read_model(user, limit=1000)
    for row in debt_model["debts"]:
        if not _in_period(row["sale_date"], start_date, end_date):
            continue
        totals["worker_debt_count"] += 1
        if row["active_debt"]:
            totals["worker_debt_remaining"] += row["remaining_amount"]

    return {
        "allowed": True,
        "scope_mode": scope.scope_mode,
        "reason": "Closing visibility read-only dibatasi ke data finansial milik user portal.",
        "year": y,
        "month": m,
        "period_start": start_date,
        "period_end": end_date,
        "closing": _closing_status(closing),
        "totals": totals,
    }


def _closing_status(closing: PeriodClosing | None) -> dict:
    if not closing:
        return {
            "is_closed": False,
            "status": "OPEN",
            "closing_date": None,
        }
    return {
        "is_closed": True,
        "status": closing.status,
        "closing_date": closing.closing_date,
    }
