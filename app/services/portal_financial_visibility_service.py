from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import false, or_

from app.models.finance import Invoice, Payment
from app.models.system import DigitalAttachment
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
    ROLE_PORTAL_SUBCLIENT,
    ROLE_PORTAL_PT,
)


EXCLUDED_ACTIVE_RECEIVABLE_STATUSES = {"CANCELLED", "VOID", "VOIDED"}
PORTAL_PAYMENT_MODULE = "PORTAL_PAYMENT"
PAYMENT_PROOF_REFERENCE_TYPE = "INVOICE"
PAYMENT_PROOF_STATUS_LABELS = {
    "PAYMENT_PROOF_PENDING": "Menunggu Finance",
    "PAYMENT_PROOF_VERIFIED": "Diverifikasi",
    "PAYMENT_PROOF_REJECTED": "Ditolak",
    "PAYMENT_PROOF_PAYMENT_CREATED": "Pembayaran Resmi Dibuat",
}
PORTAL_CUSTOMER_FINANCIAL_BLOCKED_REASON = (
    "Financial visibility pelanggan umum menunggu prepayment/payment flow Stage 3."
)
INVOICE_STATUS_LABELS = {
    "DRAFT": "Draft",
    "OPEN": "Terbuka",
    "PARTIAL": "Dibayar Sebagian",
    "PARTIAL_PAID": "Dibayar Sebagian",
    "PAID": "Lunas",
    "OVERDUE": "Jatuh Tempo",
    "CLOSED": "Ditutup",
    "CANCELLED": "Dibatalkan",
    "CANCELED": "Dibatalkan",
    "VOID": "Dibatalkan",
    "VOIDED": "Dibatalkan",
}


def _money(value) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _normalized_status(value) -> str:
    return str(value or "").strip().upper()


def _status_label(value) -> str:
    status = _normalized_status(value)
    return INVOICE_STATUS_LABELS.get(status, status.replace("_", " ").title() if status else "-")


def _is_active_receivable(invoice: Invoice) -> bool:
    status = _normalized_status(invoice.status)
    return status not in EXCLUDED_ACTIVE_RECEIVABLE_STATUSES


def _days_overdue(invoice: Invoice) -> int:
    if not invoice.due_date:
        return 0
    if not _is_active_receivable(invoice):
        return 0
    if _money(invoice.remaining_amount) <= 0:
        return 0
    return max((date.today() - invoice.due_date).days, 0)


def _aging_bucket(days_overdue: int) -> str:
    if days_overdue <= 0:
        return "CURRENT"
    if days_overdue <= 7:
        return "DUE_1_7"
    if days_overdue <= 30:
        return "DUE_8_30"
    return "DUE_OVER_30"


def _invoice_party(invoice: Invoice) -> dict:
    client = invoice.client
    mandor = invoice.mandor
    client_pic = invoice.client_pic
    snapshot_name = invoice.client_name_snapshot or invoice.client_pic_name_snapshot
    if invoice.bill_to_type == "MANDOR" and mandor:
        label = mandor.name
    elif client_pic:
        label = client_pic.name
    elif client:
        label = client.name
    else:
        label = snapshot_name or "-"
    return {
        "label": label,
        "client_name": client.name if client else invoice.client_name_snapshot,
        "mandor_name": mandor.name if mandor else None,
        "client_pic_name": client_pic.name if client_pic else invoice.client_pic_name_snapshot,
        "phone": (
            invoice.client_pic_phone_snapshot
            or (client_pic.phone if client_pic else None)
            or (mandor.phone if mandor else None)
            or (client.phone if client else None)
        ),
    }


def _proof_rows_for_invoice_ids(invoice_ids: list[int]) -> dict[int, list[dict]]:
    if not invoice_ids:
        return {}
    attachments = (
        DigitalAttachment.query.filter(
            DigitalAttachment.module == PORTAL_PAYMENT_MODULE,
            DigitalAttachment.reference_type == PAYMENT_PROOF_REFERENCE_TYPE,
            DigitalAttachment.reference_id.in_(invoice_ids),
            DigitalAttachment.is_deleted.is_(False),
        )
        .order_by(DigitalAttachment.created_at.desc(), DigitalAttachment.id.desc())
        .all()
    )
    grouped: dict[int, list[dict]] = {invoice_id: [] for invoice_id in invoice_ids}
    for attachment in attachments:
        grouped.setdefault(attachment.reference_id, []).append(
            {
                "attachment_id": attachment.id,
                "attachment_type": attachment.attachment_type,
                "status_label": PAYMENT_PROOF_STATUS_LABELS.get(
                    attachment.attachment_type,
                    attachment.attachment_type,
                ),
                "filename": attachment.original_filename,
                "file_size": attachment.file_size,
                "uploaded_at": attachment.created_at,
                "uploaded_by": attachment.uploaded_by,
                "notes": attachment.notes,
            }
        )
    return grouped


def _proof_summary(proofs: list[dict]) -> dict:
    by_type = {}
    for proof in proofs:
        by_type[proof["attachment_type"]] = by_type.get(proof["attachment_type"], 0) + 1
    latest = proofs[0] if proofs else None
    return {
        "count": len(proofs),
        "pending": by_type.get("PAYMENT_PROOF_PENDING", 0),
        "verified": by_type.get("PAYMENT_PROOF_VERIFIED", 0),
        "rejected": by_type.get("PAYMENT_PROOF_REJECTED", 0),
        "payment_created": by_type.get("PAYMENT_PROOF_PAYMENT_CREATED", 0),
        "latest_status": latest["status_label"] if latest else "Belum ada bukti",
        "latest_uploaded_at": latest["uploaded_at"] if latest else None,
    }


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

    if role == ROLE_PORTAL_SUBCLIENT:
        if not scope.mandor_ids:
            return false()
        return Invoice.mandor_id.in_(sorted(scope.mandor_ids))

    if role == ROLE_PORTAL_DELEGATE:
        filters = _direct_delegate_filters(user)
        return or_(*filters) if filters else false()

    return false()


def _invoice_row(invoice: Invoice, proofs_by_invoice: dict[int, list[dict]] | None = None) -> dict:
    payment_total = _payment_sum(invoice)
    total_amount = _money(invoice.total_amount)
    paid_amount = _money(invoice.paid_amount)
    remaining_amount = _money(invoice.remaining_amount)
    active_receivable = _is_active_receivable(invoice)
    days_overdue = _days_overdue(invoice)
    proofs = (proofs_by_invoice or {}).get(invoice.id, [])

    return {
        "invoice_id": invoice.id,
        "invoice_number": invoice.invoice_number,
        "invoice_date": invoice.invoice_date,
        "due_date": invoice.due_date,
        "period_start": invoice.period_start,
        "period_end": invoice.period_end,
        "status": _normalized_status(invoice.status),
        "status_label": _status_label(invoice.status),
        "bill_to_type": invoice.bill_to_type,
        "client_id": invoice.client_id,
        "mandor_id": invoice.mandor_id,
        "client_pic_id": invoice.client_pic_id,
        "party": _invoice_party(invoice),
        "total_amount": total_amount,
        "paid_amount": paid_amount,
        "remaining_amount": remaining_amount,
        "payment_total": payment_total,
        "payment_count": len(invoice.payments),
        "payment_mismatch": payment_total != paid_amount,
        "active_receivable": active_receivable,
        "payable": active_receivable and remaining_amount > 0,
        "days_overdue": days_overdue,
        "aging_bucket": _aging_bucket(days_overdue),
        "input_source": invoice.input_source,
        "source_type": invoice.source_type,
        "proofs": proofs,
        "proof_summary": _proof_summary(proofs),
    }


def build_portal_invoice_read_model(user, *, limit: int = 100) -> dict:
    """Return read-only invoice/outstanding data for portal financial visibility."""
    scope = build_portal_external_scope(user)
    role = getattr(user, "role", None)

    if role == ROLE_PORTAL_CUSTOMER:
        return {
            "allowed": False,
            "scope_mode": "PORTAL_CUSTOMER_FINANCIAL_BLOCKED",
            "reason": PORTAL_CUSTOMER_FINANCIAL_BLOCKED_REASON,
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
    proofs_by_invoice = _proof_rows_for_invoice_ids([invoice.id for invoice in invoices])
    rows = [_invoice_row(invoice, proofs_by_invoice) for invoice in invoices]

    return {
        "allowed": True,
        "scope_mode": scope.scope_mode,
            "reason": "Tagihan ditampilkan sesuai akun.",
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
            "reason": PORTAL_CUSTOMER_FINANCIAL_BLOCKED_REASON,
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
            "reason": "Invoice tidak ditemukan untuk akun ini.",
            "invoice": None,
        }

    return {
        "allowed": True,
        "scope_mode": scope.scope_mode,
        "reason": "Invoice ditemukan.",
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
            "reason": "Riwayat pembayaran pelanggan umum menunggu alur bayar di awal aktif.",
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
            "reason": "Riwayat pembayaran ditampilkan sesuai akun.",
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
        "notes": payment.notes,
        "bank_account": {
            "bank_name": payment.bank_account.bank_name if payment.bank_account else None,
            "account_name": payment.bank_account.account_name if payment.bank_account else None,
            "account_number": payment.bank_account.account_number if payment.bank_account else None,
        },
        "invoice_id": payment.invoice_id,
        "invoice_number": invoice.invoice_number if invoice else None,
        "invoice_status": _normalized_status(invoice.status) if invoice else None,
        "invoice_status_label": _status_label(invoice.status) if invoice else "-",
        "invoice_active_receivable": _is_active_receivable(invoice) if invoice else False,
        "invoice_remaining_amount": _money(invoice.remaining_amount) if invoice else Decimal("0"),
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
        "overdue_invoice_count": 0,
        "overdue_outstanding_amount": Decimal("0"),
        "payable_invoice_count": 0,
        "proof_count": 0,
        "pending_proof_count": 0,
        "verified_proof_count": 0,
        "rejected_proof_count": 0,
        "aging": {
            "CURRENT": Decimal("0"),
            "DUE_1_7": Decimal("0"),
            "DUE_8_30": Decimal("0"),
            "DUE_OVER_30": Decimal("0"),
        },
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
        if row["payable"]:
            totals["payable_invoice_count"] += 1
        if row["days_overdue"] > 0:
            totals["overdue_invoice_count"] += 1
            totals["overdue_outstanding_amount"] += row["remaining_amount"]
        totals["proof_count"] += row["proof_summary"]["count"]
        totals["pending_proof_count"] += row["proof_summary"]["pending"]
        totals["verified_proof_count"] += row["proof_summary"]["verified"]
        totals["rejected_proof_count"] += row["proof_summary"]["rejected"]
        totals["aging"][row["aging_bucket"]] += row["remaining_amount"]
    return totals


def _build_payment_totals(rows: list[dict]) -> dict:
    totals = _empty_payment_totals()
    totals["payment_count"] = len(rows)
    for row in rows:
        totals["payment_amount"] += row["amount"]
    return totals
