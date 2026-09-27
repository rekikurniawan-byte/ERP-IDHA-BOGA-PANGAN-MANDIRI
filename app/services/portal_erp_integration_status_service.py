from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.exc import SQLAlchemyError

from app.models.accounting import Journal, PeriodClosing
from app.models.complaint import CustomerComplaint
from app.models.contract import CustomerContract
from app.models.delivery import Delivery
from app.models.finance import CashBankTransaction, Invoice, Payment
from app.models.logistics import StockMovement
from app.models.master import Client, DeliveryLocation, Mandor
from app.models.operational import DailyOrder
from app.models.production import Production
from app.models.system import ApprovalRequest, DigitalAttachment, Notification, PortalOrderDraft, PortalUserMapping
from app.services.portal_payment_creation_service import PAYMENT_PROOF_PAYMENT_CREATED_TYPE
from app.services.portal_payment_proof_service import PAYMENT_PROOF_PENDING_TYPE
from app.services.portal_payment_verification_queue_service import (
    PAYMENT_PROOF_REJECTED_TYPE,
    PAYMENT_PROOF_VERIFIED_TYPE,
)
from app.utils.terms import T


logger = logging.getLogger(__name__)


PORTAL_PAYMENT_MODULE = "PORTAL_PAYMENT"
PAYMENT_PROOF_REFERENCE_TYPE = "INVOICE"


STATUS_LABELS = {
    "OK": "Terhubung",
    "WARNING": "Perlu dicek",
    "EMPTY": "Belum ada data",
    "BLOCKED": "Belum aktif",
    "ERROR": "Query gagal",
}


PROOF_STATUS_LABELS = {
    PAYMENT_PROOF_PENDING_TYPE: "Menunggu Finance",
    PAYMENT_PROOF_VERIFIED_TYPE: "Diverifikasi",
    PAYMENT_PROOF_REJECTED_TYPE: "Ditolak",
    PAYMENT_PROOF_PAYMENT_CREATED_TYPE: "Pembayaran Resmi Dibuat",
}


@dataclass(frozen=True)
class QueryResult:
    value: int | Decimal | None
    failed: bool = False


def build_portal_erp_integration_status(user=None, *, branch_id: int | None = None) -> dict:
    """Build read-only proof that portal data is integrated with existing ERP modules.

    This service intentionally creates no rows and performs no posting. It is used by
    finance/admin pages to make the integration boundary explicit after the portal UI
    work, so teams can see which central ERP module owns the real data.
    """
    effective_branch_id = branch_id if branch_id is not None else getattr(user, "branch_id", None)
    cards = [
        _portal_access_card(effective_branch_id),
        _portal_draft_card(effective_branch_id),
        _operational_order_card(effective_branch_id),
        _production_card(effective_branch_id),
        _delivery_card(effective_branch_id),
        _invoice_card(effective_branch_id),
        _payment_card(effective_branch_id),
        _cash_bank_card(effective_branch_id),
        _accounting_card(),
        _stock_card(effective_branch_id),
        _master_data_card(effective_branch_id),
        _complaint_card(effective_branch_id),
        _contract_card(effective_branch_id),
        _approval_card(effective_branch_id),
        _notification_card(effective_branch_id),
        _document_and_closing_card(effective_branch_id),
    ]
    totals = {
        "module_count": len(cards),
        "connected_count": sum(1 for card in cards if card["status"] == "OK"),
        "warning_count": sum(1 for card in cards if card["status"] == "WARNING"),
        "empty_count": sum(1 for card in cards if card["status"] == "EMPTY"),
        "error_count": sum(1 for card in cards if card["status"] == "ERROR"),
        "blocked_count": sum(1 for card in cards if card["status"] == "BLOCKED"),
    }
    if totals["error_count"]:
        overall = "ERROR"
    elif totals["warning_count"]:
        overall = "WARNING"
    elif totals["connected_count"]:
        overall = "OK"
    else:
        overall = "EMPTY"
    return {
        "branch_id": effective_branch_id,
        "status": overall,
        "status_label": STATUS_LABELS[overall],
        "totals": totals,
        "cards": cards,
        "proof_status_labels": PROOF_STATUS_LABELS,
        "principle": "Portal hanya antarmuka. Data resmi tetap berada di tabel dan service ERP existing.",
    }


def build_finance_portal_payment_status(user, *, limit: int = 8) -> dict:
    """Return finance-owned portal payment summary using DigitalAttachment and Payment."""
    branch_id = getattr(user, "branch_id", None)
    proof_rows = _proof_rows(branch_id, limit=limit)
    counts = {
        "pending": _count(_proof_query(branch_id, PAYMENT_PROOF_PENDING_TYPE)),
        "verified": _count(_proof_query(branch_id, PAYMENT_PROOF_VERIFIED_TYPE)),
        "rejected": _count(_proof_query(branch_id, PAYMENT_PROOF_REJECTED_TYPE)),
        "payment_created": _count(_proof_query(branch_id, PAYMENT_PROOF_PAYMENT_CREATED_TYPE)),
    }
    invoice_count = _count(_branch_query(Invoice.query, Invoice.branch_id, branch_id))
    active_invoice_count = _count(
        _branch_query(Invoice.query, Invoice.branch_id, branch_id).filter(
            Invoice.status.notin_(["CANCELLED", "CANCELED", "VOID", "VOIDED"])
        )
    )
    return {
        "counts": {key: _value_or_zero(value) for key, value in counts.items()},
        "invoice_count": _value_or_zero(invoice_count),
        "active_invoice_count": _value_or_zero(active_invoice_count),
        "rows": proof_rows,
        "status_label": "Ada bukti menunggu" if _value_or_zero(counts["pending"]) else "Queue bersih",
        "status": "WARNING" if _value_or_zero(counts["pending"]) else "OK",
    }


def _portal_access_card(branch_id):
    mapping_query = PortalUserMapping.query
    if branch_id is not None:
        mapping_query = mapping_query.filter(PortalUserMapping.user.has(branch_id=branch_id))
    mapping_count = _count(mapping_query)
    active_mapping_count = _count(
        mapping_query.filter(PortalUserMapping.is_active.is_(True))
    )
    return _card(
        key="portal_access",
        title="Portal dan Role",
        owner="User Management",
        source="users + portal_user_mappings",
        count=active_mapping_count,
        detail=f"{_value_or_zero(active_mapping_count)} mapping aktif dari {_value_or_zero(mapping_count)} mapping.",
        href="/portal/dashboard",
        status="OK" if _value_or_zero(active_mapping_count) else "EMPTY",
    )


def _portal_draft_card(branch_id):
    query = _branch_query(PortalOrderDraft.query, PortalOrderDraft.branch_id, branch_id)
    total = _count(query)
    pending = _count(query.filter(PortalOrderDraft.status == "PENDING_ADMIN_CONFIRMATION"))
    converted = _count(query.filter(PortalOrderDraft.converted_daily_order_id.isnot(None)))
    status = "WARNING" if _value_or_zero(pending) else ("OK" if _value_or_zero(total) else "EMPTY")
    return _card(
        key="portal_order_draft",
        title="Draft Order Portal",
        owner="Portal",
        source="portal_order_drafts",
        count=total,
        detail=f"{_value_or_zero(pending)} menunggu admin, {_value_or_zero(converted)} sudah masuk order internal.",
        href="/portal/admin/order-drafts",
        status=status,
    )


def _operational_order_card(branch_id):
    query = _branch_query(DailyOrder.query, DailyOrder.branch_id, branch_id)
    total = _count(query)
    locked = _count(query.filter(DailyOrder.is_locked.is_(True)))
    return _card(
        key="operational_order",
        title="Operasional Order",
        owner="Operasional",
        source="daily_orders + daily_order_details",
        count=total,
        detail=f"{_value_or_zero(locked)} order terkunci menjadi dasar produksi dan invoice.",
        href="/operational/orders",
        status="OK" if _value_or_zero(total) else "EMPTY",
    )


def _production_card(branch_id):
    query = _branch_query(Production.query, Production.branch_id, branch_id)
    total = _count(query)
    completed = _count(query.filter(Production.status == "COMPLETED"))
    return _card(
        key="production",
        title="Produksi",
        owner="Produksi",
        source="productions + production_details",
        count=total,
        detail=f"{_value_or_zero(completed)} produksi selesai.",
        href="/production/",
        status="OK" if _value_or_zero(total) else "EMPTY",
    )


def _delivery_card(branch_id):
    query = _branch_query(Delivery.query, Delivery.branch_id, branch_id)
    total = _count(query)
    delivered = _count(query.filter(Delivery.status == "DELIVERED"))
    return _card(
        key="delivery",
        title="Delivery",
        owner="Logistik",
        source="deliveries + delivery_details",
        count=total,
        detail=f"{_value_or_zero(delivered)} pengiriman selesai.",
        href="/delivery/",
        status="OK" if _value_or_zero(total) else "EMPTY",
    )


def _invoice_card(branch_id):
    query = _branch_query(Invoice.query, Invoice.branch_id, branch_id)
    total = _count(query)
    active = _count(query.filter(Invoice.status.notin_(["CANCELLED", "CANCELED", "VOID", "VOIDED"])))
    outstanding = _sum_remaining(query)
    return _card(
        key="invoice",
        title="Invoice dan Piutang",
        owner="Finance",
        source="invoices + invoice_items",
        count=total,
        detail=f"{_value_or_zero(active)} invoice aktif, outstanding {_money_text(outstanding)}.",
        href="/finance/invoices",
        status="OK" if _value_or_zero(total) else "EMPTY",
    )


def _payment_card(branch_id):
    payments = _count(_branch_query(Payment.query, Payment.branch_id, branch_id))
    pending = _count(_proof_query(branch_id, PAYMENT_PROOF_PENDING_TYPE))
    created = _count(_proof_query(branch_id, PAYMENT_PROOF_PAYMENT_CREATED_TYPE))
    status = "WARNING" if _value_or_zero(pending) else ("OK" if _value_or_zero(payments) or _value_or_zero(created) else "EMPTY")
    return _card(
        key="payment",
        title="Pembayaran Portal",
        owner="Finance",
        source="digital_attachments -> payments",
        count=payments,
        detail=f"{_value_or_zero(pending)} bukti menunggu finance, {_value_or_zero(created)} bukti sudah menjadi payment resmi.",
        href="/finance/portal-payment-proofs",
        status=status,
    )


def _cash_bank_card(branch_id):
    total = _count(_branch_query(CashBankTransaction.query, CashBankTransaction.branch_id, branch_id))
    unreconciled = _count(
        _branch_query(CashBankTransaction.query, CashBankTransaction.branch_id, branch_id).filter(
            CashBankTransaction.is_reconciled.is_(False)
        )
    )
    return _card(
        key="cash_bank",
        title="Kas dan Bank",
        owner="Finance",
        source="cash_bank_transactions",
        count=total,
        detail=f"{_value_or_zero(unreconciled)} transaksi belum rekonsiliasi.",
        href="/finance/cash-bank-ledger",
        status="OK" if _value_or_zero(total) else "EMPTY",
    )


def _accounting_card():
    total = _count(Journal.query)
    payment_journals = _count(Journal.query.filter(Journal.reference_type == "PAYMENT"))
    return _card(
        key="accounting",
        title="Jurnal Akuntansi",
        owner="Akuntansi",
        source="journals + journal_details",
        count=total,
        detail=f"{_value_or_zero(payment_journals)} jurnal payment tercatat.",
        href="/accounting/journals",
        status="OK" if _value_or_zero(total) else "EMPTY",
    )


def _stock_card(branch_id):
    total = _count(_branch_query(StockMovement.query, StockMovement.branch_id, branch_id))
    return _card(
        key="stock",
        title="Stok dan Gudang",
        owner="Logistik",
        source="stock_movements",
        count=total,
        detail=f"{_value_or_zero(total)} mutasi stok terbaca.",
        href="/logistics/",
        status="OK" if _value_or_zero(total) else "EMPTY",
    )


def _master_data_card(branch_id):
    clients = _count(Client.query)
    mandors = _count(_branch_query(Mandor.query, Mandor.branch_id, branch_id))
    locations = _count(DeliveryLocation.query.join(Mandor).filter(Mandor.branch_id == branch_id) if branch_id else DeliveryLocation.query)
    total = _value_or_zero(clients) + _value_or_zero(mandors) + _value_or_zero(locations)
    return _card(
        key="master_data",
        title="Master Data",
        owner="Master Data",
        source="clients + mandors + delivery_locations",
        count=QueryResult(total),
        detail=f"{_value_or_zero(clients)} {T.client_lower}, {_value_or_zero(mandors)} {T.sub_client_lower}, {_value_or_zero(locations)} lokasi.",
        href="/master/",
        status="OK" if total else "EMPTY",
    )


def _complaint_card(branch_id):
    query = _branch_query(CustomerComplaint.query, CustomerComplaint.branch_id, branch_id)
    total = _count(query)
    open_count = _count(query.filter(CustomerComplaint.status.in_(["OPEN", "IN_PROGRESS"])))
    return _card(
        key="complaints",
        title="Komplain dan Retur",
        owner="Customer Success",
        source="customer_complaints",
        count=total,
        detail=f"{_value_or_zero(open_count)} komplain masih terbuka.",
        href="/customer-success/complaints",
        status="WARNING" if _value_or_zero(open_count) else ("OK" if _value_or_zero(total) else "EMPTY"),
    )


def _contract_card(branch_id):
    query = _branch_query(CustomerContract.query, CustomerContract.branch_id, branch_id)
    total = _count(query)
    active = _count(query.filter(CustomerContract.status == "ACTIVE"))
    return _card(
        key="contracts",
        title=f"Kontrak {T.client}",
        owner="Contract Management",
        source="customer_contracts",
        count=total,
        detail=f"{_value_or_zero(active)} kontrak aktif.",
        href="/customer-success/contracts",
        status="OK" if _value_or_zero(total) else "EMPTY",
    )


def _approval_card(branch_id):
    query = _branch_query(ApprovalRequest.query, ApprovalRequest.branch_id, branch_id)
    total = _count(query)
    submitted = _count(query.filter(ApprovalRequest.status == "SUBMITTED"))
    return _card(
        key="approvals",
        title="Approval Engine",
        owner="Sistem",
        source="approval_requests",
        count=total,
        detail=f"{_value_or_zero(submitted)} approval menunggu keputusan.",
        href="/settings/approvals",
        status="WARNING" if _value_or_zero(submitted) else ("OK" if _value_or_zero(total) else "EMPTY"),
    )


def _notification_card(branch_id):
    query = _branch_query(Notification.query, Notification.branch_id, branch_id)
    total = _count(query)
    unread = _count(query.filter(Notification.status == "UNREAD"))
    return _card(
        key="notifications",
        title="Notification Center",
        owner="Sistem",
        source="notifications",
        count=total,
        detail=f"{_value_or_zero(unread)} notifikasi belum dibaca.",
        href="/settings/notifications",
        status="WARNING" if _value_or_zero(unread) else ("OK" if _value_or_zero(total) else "EMPTY"),
    )


def _document_and_closing_card(branch_id):
    documents = _count(_branch_query(DigitalAttachment.query, DigitalAttachment.branch_id, branch_id).filter(DigitalAttachment.is_deleted.is_(False)))
    closings = _count(_branch_query(PeriodClosing.query, PeriodClosing.branch_id, branch_id))
    status = "OK" if _value_or_zero(documents) or _value_or_zero(closings) else "EMPTY"
    return _card(
        key="documents_closing",
        title="Dokumen dan Closing",
        owner="Sistem dan Akuntansi",
        source="digital_attachments + period_closings",
        count=QueryResult(_value_or_zero(documents) + _value_or_zero(closings)),
        detail=f"{_value_or_zero(documents)} dokumen, {_value_or_zero(closings)} closing periode.",
        href="/portal/documents",
        status=status,
    )


def _proof_rows(branch_id, *, limit: int) -> list[dict]:
    query = _base_proof_query(branch_id).order_by(DigitalAttachment.created_at.desc(), DigitalAttachment.id.desc()).limit(limit)
    try:
        rows = query.all()
    except SQLAlchemyError:
        logger.exception("Gagal membaca ringkasan bukti pembayaran portal.")
        return []
    return [
        {
            "attachment_id": row.id,
            "filename": row.original_filename,
            "status": row.attachment_type,
            "status_label": PROOF_STATUS_LABELS.get(row.attachment_type, row.attachment_type),
            "uploaded_at": row.created_at,
            "reference_id": row.reference_id,
            "uploaded_by": row.uploaded_by,
        }
        for row in rows
    ]


def _base_proof_query(branch_id):
    return _branch_query(
        DigitalAttachment.query.filter(
            DigitalAttachment.module == PORTAL_PAYMENT_MODULE,
            DigitalAttachment.reference_type == PAYMENT_PROOF_REFERENCE_TYPE,
            DigitalAttachment.is_deleted.is_(False),
        ),
        DigitalAttachment.branch_id,
        branch_id,
    )


def _proof_query(branch_id, attachment_type):
    return _base_proof_query(branch_id).filter(DigitalAttachment.attachment_type == attachment_type)


def _branch_query(query, branch_column, branch_id):
    if branch_id is None:
        return query
    return query.filter(branch_column == branch_id)


def _count(query) -> QueryResult:
    try:
        return QueryResult(query.count())
    except SQLAlchemyError:
        logger.exception("Gagal menghitung status integrasi ERP portal.")
        return QueryResult(None, failed=True)


def _sum_remaining(query) -> QueryResult:
    try:
        rows = query.with_entities(Invoice.remaining_amount).all()
    except SQLAlchemyError:
        logger.exception("Gagal menghitung outstanding invoice portal.")
        return QueryResult(None, failed=True)
    total = sum((_money(row[0]) for row in rows), Decimal("0"))
    return QueryResult(total)


def _money(value) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _card(*, key, title, owner, source, count, detail, href, status):
    failed = isinstance(count, QueryResult) and count.failed
    status_key = "ERROR" if failed else status
    return {
        "key": key,
        "title": title,
        "owner": owner,
        "source": source,
        "count": _value_or_zero(count),
        "amount": count.value if isinstance(count, QueryResult) and isinstance(count.value, Decimal) else None,
        "detail": "Query modul ini gagal. Cek log aplikasi." if failed else detail,
        "href": href,
        "status": status_key,
        "status_label": STATUS_LABELS[status_key],
    }


def _value_or_zero(result) -> int:
    if isinstance(result, QueryResult):
        if result.failed or result.value is None:
            return 0
        return int(result.value)
    return int(result or 0)


def _money_text(result) -> str:
    if isinstance(result, QueryResult):
        value = result.value or Decimal("0")
    else:
        value = result or Decimal("0")
    return f"Rp {float(value):,.0f}".replace(",", ".")
