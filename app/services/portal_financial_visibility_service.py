from __future__ import annotations

from decimal import Decimal

from sqlalchemy import false, or_

from app.models.finance import Invoice, Payment
from app.services.portal_mapping_service import (
    PRINCIPAL_CLIENT_PIC,
    PRINCIPAL_DELEGATE,
    build_portal_external_scope,
    list_active_portal_mappings,
)
from app.services.user_management_service import (
    ROLE_PORTAL_CLIENT,
    ROLE_PORTAL_CUSTOMER,
    ROLE_PORTAL_DELEGATE,
    ROLE_PORTAL_MANDOR,
    ROLE_PORTAL_PT,
)


EXCLUDED_ACTIVE_RECEIVABLE_STATUSES = {"CANCELLED", "VOID", "VOIDED"}


def _money(value) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _normalized_status(value) -> str:
    return str(value or "").strip().upper()


def _is_active_receivable(invoice: Invoice) -> bool:
    status = _normalized_status(invoice.status)
    return status not in EXCLUDED_ACTIVE_RECEIVABLE_STATUSES


def _payment_sum(invoice: Invoice) -> Decimal:
    return sum((_money(payment.amount) for payment in invoice.payments), Decimal("0"))


def _direct_delegate_filters(user):
    """Build only explicitly delegated financial ownership filters.

    The portal scope resolver intentionally expands location/mandor mappings into
    client identity for directory/profile context. Financial visibility is
    stricter: a location delegate must not automatically see every client-level
    invoice under the same client.
    """
    direct_client_ids = set()
    direct_mandor_ids = set()
    direct_client_pic_ids = set()

    for mapping in list_active_portal_mappings(user):
        if mapping.principal_type == PRINCIPAL_CLIENT_PIC and mapping.client_pic_id:
            direct_client_pic_ids.add(mapping.client_pic_id)
            continue

        if mapping.principal_type != PRINCIPAL_DELEGATE:
            continue

        if mapping.client_id and not mapping.mandor_id and not mapping.delivery_location_id:
            direct_client_ids.add(mapping.client_id)

        if mapping.mandor_id:
            direct_mandor_ids.add(mapping.mandor_id)

        if mapping.delivery_location and mapping.delivery_location.mandor_id:
            direct_mandor_ids.add(mapping.delivery_location.mandor_id)

        if mapping.client_pic_id:
            direct_client_pic_ids.add(mapping.client_pic_id)

    filters = []
    if direct_client_ids:
        filters.append(Invoice.client_id.in_(sorted(direct_client_ids)))
    if direct_mandor_ids:
        filters.append(Invoice.mandor_id.in_(sorted(direct_mandor_ids)))
    if direct_client_pic_ids:
        filters.append(Invoice.client_pic_id.in_(sorted(direct_client_pic_ids)))
    return filters


def _ownership_filter_for_scope(user, scope):
    role = getattr(user, "role", None)

    if role in {ROLE_PORTAL_CLIENT, ROLE_PORTAL_PT}:
        if not scope.client_ids:
            return false()
        return Invoice.client_id.in_(sorted(scope.client_ids))

    if role == ROLE_PORTAL_MANDOR:
        if not scope.mandor_ids:
            return false()
        return Invoice.mandor_id.in_(sorted(scope.mandor_ids))

    if role == ROLE_PORTAL_DELEGATE:
        filters = _direct_delegate_filters(user)
        return or_(*filters) if filters else false()

    return false()


def _invoice_row(invoice: Invoice) -> dict:
    payment_total = _payment_sum(invoice)
    total_amount = _money(invoice.total_amount)
    paid_amount = _money(invoice.paid_amount)
    remaining_amount = _money(invoice.remaining_amount)
    active_receivable = _is_active_receivable(invoice)

    return {
        "invoice_id": invoice.id,
        "invoice_number": invoice.invoice_number,
        "invoice_date": invoice.invoice_date,
        "due_date": invoice.due_date,
        "status": _normalized_status(invoice.status),
        "bill_to_type": invoice.bill_to_type,
        "client_id": invoice.client_id,
        "mandor_id": invoice.mandor_id,
        "client_pic_id": invoice.client_pic_id,
        "total_amount": total_amount,
        "paid_amount": paid_amount,
        "remaining_amount": remaining_amount,
        "payment_total": payment_total,
        "payment_count": len(invoice.payments),
        "payment_mismatch": payment_total != paid_amount,
        "active_receivable": active_receivable,
    }


def build_portal_invoice_read_model(user, *, limit: int = 100) -> dict:
    """Return read-only invoice/outstanding data for portal financial visibility."""
    scope = build_portal_external_scope(user)
    role = getattr(user, "role", None)

    if role == ROLE_PORTAL_CUSTOMER:
        return {
            "allowed": False,
            "scope_mode": "PORTAL_CUSTOMER_FINANCIAL_BLOCKED",
            "reason": "Financial visibility pelanggan umum menunggu prepayment/payment flow Stage 3.",
            "invoices": [],
            "totals": _empty_totals(),
        }

    if not scope.allowed:
        return {
            "allowed": False,
            "scope_mode": scope.scope_mode,
            "reason": scope.reason,
            "invoices": [],
            "totals": _empty_totals(),
        }

    ownership_filter = _ownership_filter_for_scope(user, scope)
    invoices = (
        Invoice.query.filter(ownership_filter)
        .order_by(Invoice.invoice_date.desc(), Invoice.id.desc())
        .limit(limit)
        .all()
    )
    rows = [_invoice_row(invoice) for invoice in invoices]

    return {
        "allowed": True,
        "scope_mode": scope.scope_mode,
        "reason": "Invoice read model dibatasi oleh portal ownership mapping.",
        "invoices": rows,
        "totals": _build_totals(rows),
    }


def get_portal_owned_invoice(user, invoice_id: int) -> dict:
    """Resolve one invoice only if the portal user owns it."""
    scope = build_portal_external_scope(user)
    role = getattr(user, "role", None)

    if role == ROLE_PORTAL_CUSTOMER:
        return {
            "allowed": False,
            "scope_mode": "PORTAL_CUSTOMER_FINANCIAL_BLOCKED",
            "reason": "Financial visibility pelanggan umum menunggu prepayment/payment flow Stage 3.",
            "invoice": None,
        }

    if not scope.allowed:
        return {
            "allowed": False,
            "scope_mode": scope.scope_mode,
            "reason": scope.reason,
            "invoice": None,
        }

    invoice = (
        Invoice.query.filter(Invoice.id == invoice_id)
        .filter(_ownership_filter_for_scope(user, scope))
        .first()
    )

    if not invoice:
        return {
            "allowed": False,
            "scope_mode": scope.scope_mode,
            "reason": "Invoice tidak ditemukan dalam ownership portal user.",
            "invoice": None,
        }

    return {
        "allowed": True,
        "scope_mode": scope.scope_mode,
        "reason": "Invoice ditemukan dalam ownership portal user.",
        "invoice": invoice,
    }


def build_portal_payment_history_read_model(user, *, limit: int = 100) -> dict:
    """Return read-only payment history for invoices visible to the portal user."""
    scope = build_portal_external_scope(user)
    role = getattr(user, "role", None)

    if role == ROLE_PORTAL_CUSTOMER:
        return {
            "allowed": False,
            "scope_mode": "PORTAL_CUSTOMER_PAYMENT_HISTORY_BLOCKED",
            "reason": "Payment history pelanggan umum menunggu prepayment/payment flow Stage 3.",
            "payments": [],
            "totals": _empty_payment_totals(),
        }

    if not scope.allowed:
        return {
            "allowed": False,
            "scope_mode": scope.scope_mode,
            "reason": scope.reason,
            "payments": [],
            "totals": _empty_payment_totals(),
        }

    ownership_filter = _ownership_filter_for_scope(user, scope)
    payments = (
        Payment.query.join(Invoice, Payment.invoice_id == Invoice.id)
        .filter(ownership_filter)
        .order_by(Payment.payment_date.desc(), Payment.id.desc())
        .limit(limit)
        .all()
    )
    rows = [_payment_row(payment) for payment in payments]

    return {
        "allowed": True,
        "scope_mode": scope.scope_mode,
        "reason": "Payment history dibatasi oleh invoice ownership mapping.",
        "payments": rows,
        "totals": _build_payment_totals(rows),
    }


def _payment_row(payment: Payment) -> dict:
    invoice = payment.invoice
    return {
        "payment_id": payment.id,
        "payment_number": payment.payment_number,
        "payment_date": payment.payment_date,
        "payment_method": payment.payment_method,
        "amount": _money(payment.amount),
        "reference_number": payment.reference_number,
        "invoice_id": payment.invoice_id,
        "invoice_number": invoice.invoice_number if invoice else None,
        "invoice_status": _normalized_status(invoice.status) if invoice else None,
        "invoice_active_receivable": _is_active_receivable(invoice) if invoice else False,
    }


def _empty_totals() -> dict:
    return {
        "invoice_count": 0,
        "active_invoice_count": 0,
        "total_amount": Decimal("0"),
        "paid_amount": Decimal("0"),
        "remaining_amount": Decimal("0"),
        "active_outstanding_amount": Decimal("0"),
        "payment_total": Decimal("0"),
        "payment_mismatch_count": 0,
    }


def _empty_payment_totals() -> dict:
    return {
        "payment_count": 0,
        "payment_amount": Decimal("0"),
    }


def _build_totals(rows: list[dict]) -> dict:
    totals = _empty_totals()
    totals["invoice_count"] = len(rows)
    for row in rows:
        totals["total_amount"] += row["total_amount"]
        totals["paid_amount"] += row["paid_amount"]
        totals["remaining_amount"] += row["remaining_amount"]
        totals["payment_total"] += row["payment_total"]
        if row["payment_mismatch"]:
            totals["payment_mismatch_count"] += 1
        if row["active_receivable"]:
            totals["active_invoice_count"] += 1
            totals["active_outstanding_amount"] += row["remaining_amount"]
    return totals


def _build_payment_totals(rows: list[dict]) -> dict:
    totals = _empty_payment_totals()
    totals["payment_count"] = len(rows)
    for row in rows:
        totals["payment_amount"] += row["amount"]
    return totals
