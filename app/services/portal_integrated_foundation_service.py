from __future__ import annotations

from collections import Counter
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import false, or_

from app.models.complaint import CustomerComplaint
from app.models.contract import CustomerContract
from app.models.delivery import Delivery, DeliveryDetail
from app.models.finance import Invoice
from app.models.operational import DailyOrder, DailyOrderDetail
from app.models.system import ApprovalRequest, DigitalAttachment, Notification, PortalOrderDraft
from app.services.notification_service import list_notifications, notification_to_dict
from app.services.portal_mapping_service import build_portal_external_scope


def _money(value) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _empty_model(reason, scope, totals=None):
    return {
        "allowed": False,
        "scope_mode": getattr(scope, "scope_mode", "NO_SCOPE"),
        "reason": reason,
        "rows": [],
        "totals": totals or {"total": 0},
    }


def _portal_invoice_filter(scope):
    filters = []
    if scope.client_ids:
        filters.append(Invoice.client_id.in_(sorted(scope.client_ids)))
    if scope.mandor_ids:
        filters.append(Invoice.mandor_id.in_(sorted(scope.mandor_ids)))
    return or_(*filters) if filters else false()


def _portal_order_filter(scope):
    detail_filters = []
    if scope.mandor_ids:
        detail_filters.append(DailyOrder.details.any(DailyOrderDetail.mandor_id.in_(sorted(scope.mandor_ids))))
    if scope.delivery_location_ids:
        detail_filters.append(
            DailyOrder.details.any(DailyOrderDetail.delivery_location_id.in_(sorted(scope.delivery_location_ids)))
        )
    if not detail_filters:
        return false()
    return or_(*detail_filters)


def _attachment_scope_filter(user, scope):
    filters = [DigitalAttachment.uploaded_by == getattr(user, "id", None)]
    invoice_ids = [
        row.id
        for row in Invoice.query.filter(_portal_invoice_filter(scope)).with_entities(Invoice.id).limit(300).all()
    ]
    if invoice_ids:
        filters.append(
            (DigitalAttachment.reference_type == "INVOICE")
            & (DigitalAttachment.reference_id.in_(invoice_ids))
        )
    complaint_ids = [
        row.id
        for row in CustomerComplaint.query.filter(
            CustomerComplaint.branch_id == scope.branch_id,
            CustomerComplaint.submitted_by == getattr(user, "id", None),
        )
        .with_entities(CustomerComplaint.id)
        .limit(300)
        .all()
    ]
    if complaint_ids:
        filters.append(
            (DigitalAttachment.reference_type == "CUSTOMER_COMPLAINT")
            & (DigitalAttachment.reference_id.in_(complaint_ids))
        )
    contract_ids = []
    if scope.client_ids:
        contract_ids = [
            row.id
            for row in CustomerContract.query.filter(
                CustomerContract.branch_id == scope.branch_id,
                CustomerContract.client_id.in_(sorted(scope.client_ids)),
            )
            .with_entities(CustomerContract.id)
            .limit(300)
            .all()
        ]
    if contract_ids:
        filters.append(
            (DigitalAttachment.reference_type == "CUSTOMER_CONTRACT")
            & (DigitalAttachment.reference_id.in_(contract_ids))
        )
    return or_(*filters)


def build_portal_notification_model(user, *, limit=80):
    scope = build_portal_external_scope(user)
    if not getattr(user, "branch_id", None):
        return _empty_model("User portal belum memiliki branch aktif.", scope)
    notifications = list_notifications(
        branch_id=user.branch_id,
        user=user,
        include_resolved=True,
        limit=limit,
    )
    rows = [notification_to_dict(notification) for notification in notifications]
    sections = [
        {
            "key": "UNREAD",
            "title": "Belum Dibaca",
            "rows": [row for row in rows if row["status"] == "UNREAD"],
        },
        {
            "key": "ACTION",
            "title": "Butuh Aksi",
            "rows": [row for row in rows if row.get("action_url") and row["status"] != "DISMISSED"],
        },
        {
            "key": "HISTORY",
            "title": "Riwayat",
            "rows": [row for row in rows if row["status"] != "UNREAD"],
        },
    ]
    return {
        "allowed": True,
        "scope_mode": scope.scope_mode,
        "reason": "Notifikasi dibaca dari pusat notifikasi sesuai akun.",
        "rows": rows,
        "sections": sections,
        "totals": {
            "total": len(rows),
            "unread": sum(1 for row in rows if row["status"] == "UNREAD"),
            "critical": sum(1 for row in rows if row["priority"] == "CRITICAL"),
            "warning": sum(1 for row in rows if row["priority"] == "WARNING"),
            "actionable": sum(1 for row in rows if row.get("action_url") and row["status"] != "DISMISSED"),
            "dismissed": sum(1 for row in rows if row["status"] == "DISMISSED"),
        },
    }


def build_portal_document_model(user, *, limit=80):
    scope = build_portal_external_scope(user)
    if not scope.allowed:
        return _empty_model(
            scope.reason or "Akses portal belum aktif.",
            scope,
            {"total": 0, "own_upload": 0, "payment_proof": 0, "other": 0},
        )
    query = DigitalAttachment.query.filter(DigitalAttachment.is_deleted.is_(False))
    query = query.filter((DigitalAttachment.branch_id == scope.branch_id) | (DigitalAttachment.branch_id.is_(None)))
    rows = (
        query.filter(_attachment_scope_filter(user, scope))
        .order_by(DigitalAttachment.created_at.desc(), DigitalAttachment.id.desc())
        .limit(limit)
        .all()
    )
    modules = Counter(row.module for row in rows)
    reference_types = Counter(row.reference_type for row in rows)
    sections = [
        {
            "key": "PAYMENT_PROOF",
            "title": "Bukti Pembayaran",
            "rows": [row for row in rows if row.module == "PORTAL_PAYMENT"],
        },
        {
            "key": "COMPLAINT",
            "title": "Bukti Komplain",
            "rows": [row for row in rows if row.reference_type == "CUSTOMER_COMPLAINT"],
        },
        {
            "key": "CONTRACT",
            "title": "Kontrak",
            "rows": [row for row in rows if row.reference_type == "CUSTOMER_CONTRACT"],
        },
        {
            "key": "OTHER",
            "title": "Dokumen Lain",
            "rows": [
                row
                for row in rows
                if row.module != "PORTAL_PAYMENT"
                and row.reference_type not in {"CUSTOMER_COMPLAINT", "CUSTOMER_CONTRACT"}
            ],
        },
    ]
    return {
        "allowed": True,
        "scope_mode": scope.scope_mode,
        "reason": "Dokumen dibatasi ke upload user dan referensi invoice/kontrak/komplain dalam ownership portal.",
        "rows": rows,
        "sections": sections,
        "totals": {
            "total": len(rows),
            "own_upload": sum(1 for row in rows if row.uploaded_by == getattr(user, "id", None)),
            "payment_proof": modules.get("PORTAL_PAYMENT", 0),
            "complaint_evidence": reference_types.get("CUSTOMER_COMPLAINT", 0),
            "contract_document": reference_types.get("CUSTOMER_CONTRACT", 0),
            "other": len(rows) - modules.get("PORTAL_PAYMENT", 0),
        },
    }


def get_portal_owned_document(user, attachment_id: int) -> DigitalAttachment | None:
    scope = build_portal_external_scope(user)
    if not scope.allowed:
        return None
    query = DigitalAttachment.query.filter(
        DigitalAttachment.id == attachment_id,
        DigitalAttachment.is_deleted.is_(False),
    )
    query = query.filter((DigitalAttachment.branch_id == scope.branch_id) | (DigitalAttachment.branch_id.is_(None)))
    return query.filter(_attachment_scope_filter(user, scope)).first()


def build_portal_approval_model(user, *, limit=80):
    scope = build_portal_external_scope(user)
    if not getattr(user, "branch_id", None):
        return _empty_model(
            "Akun portal belum memiliki cabang aktif.",
            scope,
            {"total": 0, "submitted": 0, "approved": 0, "rejected": 0},
        )
    rows = (
        ApprovalRequest.query.filter(
            ApprovalRequest.branch_id == user.branch_id,
            ApprovalRequest.requested_by == getattr(user, "id", None),
        )
        .order_by(ApprovalRequest.created_at.desc(), ApprovalRequest.id.desc())
        .limit(limit)
        .all()
    )
    return {
        "allowed": True,
        "scope_mode": scope.scope_mode,
        "reason": "Approval portal hanya menampilkan request yang dibuat user ini.",
        "rows": rows,
        "totals": {
            "total": len(rows),
            "submitted": sum(1 for row in rows if row.status == "SUBMITTED"),
            "approved": sum(1 for row in rows if row.status == "APPROVED"),
            "rejected": sum(1 for row in rows if row.status == "REJECTED"),
        },
    }


def build_portal_return_model(user, *, limit=80):
    scope = build_portal_external_scope(user)
    if not getattr(user, "branch_id", None):
        return _empty_model(
            "Akun portal belum memiliki cabang aktif.",
            scope,
            {"total": 0, "open": 0, "done": 0},
        )
    rows = (
        CustomerComplaint.query.filter(
            CustomerComplaint.branch_id == user.branch_id,
            CustomerComplaint.submitted_by == getattr(user, "id", None),
            CustomerComplaint.category.in_(["FOOD_SHORTAGE", "WRONG_MENU", "PORTION_SHORTAGE", "DAMAGED_FOOD"]),
        )
        .order_by(CustomerComplaint.submitted_at.desc(), CustomerComplaint.id.desc())
        .limit(limit)
        .all()
    )
    category_counts = Counter(row.category for row in rows)
    return {
        "allowed": True,
        "scope_mode": scope.scope_mode,
        "reason": "Retur portal memakai CustomerComplaint existing kategori kekurangan/salah/rusak tanpa tabel paralel.",
        "rows": rows,
        "category_counts": {
            "FOOD_SHORTAGE": category_counts.get("FOOD_SHORTAGE", 0),
            "WRONG_MENU": category_counts.get("WRONG_MENU", 0),
            "PORTION_SHORTAGE": category_counts.get("PORTION_SHORTAGE", 0),
            "DAMAGED_FOOD": category_counts.get("DAMAGED_FOOD", 0),
        },
        "totals": {
            "total": len(rows),
            "open": sum(1 for row in rows if row.status in {"OPEN", "IN_PROGRESS"}),
            "done": sum(1 for row in rows if row.status in {"RESOLVED", "CLOSED"}),
            "with_invoice": sum(1 for row in rows if row.invoice_id),
            "with_delivery": sum(1 for row in rows if row.delivery_id),
        },
    }


def build_portal_subscription_model(user, *, limit=80):
    scope = build_portal_external_scope(user)
    if not scope.allowed:
        return _empty_model(
            scope.reason or "Akses portal belum aktif.",
            scope,
            {"total": 0, "draft_count": 0, "repeat_pattern": 0},
        )
    drafts = (
        PortalOrderDraft.query.filter(PortalOrderDraft.user_id == getattr(user, "id", None))
        .order_by(PortalOrderDraft.order_date.desc(), PortalOrderDraft.id.desc())
        .limit(limit)
        .all()
    )
    grouped = Counter((draft.delivery_location_id, draft.meal_type, draft.portion_qty) for draft in drafts)
    rows = []
    for key, total in grouped.most_common(20):
        location_id, meal_type, portion_qty = key
        sample = next(
            draft
            for draft in drafts
            if (draft.delivery_location_id, draft.meal_type, draft.portion_qty) == key
        )
        rows.append(
            {
                "location_name": sample.delivery_location.location_name if sample.delivery_location else "-",
                "meal_type": meal_type,
                "portion_qty": portion_qty,
                "repeat_count": total,
                "last_order_date": sample.order_date,
                "status": "POLA_DRAFT",
            }
        )
    return {
        "allowed": True,
        "scope_mode": scope.scope_mode,
        "reason": "Langganan belum membuat order otomatis; halaman ini membaca pola draft portal.",
        "rows": rows,
        "totals": {
            "total": len(rows),
            "draft_count": len(drafts),
            "repeat_pattern": sum(1 for row in rows if row["repeat_count"] > 1),
        },
    }


def build_portal_calendar_model(user, *, days=45):
    scope = build_portal_external_scope(user)
    if not scope.allowed:
        return _empty_model(
            scope.reason or "Akses portal belum aktif.",
            scope,
            {
                "total": 0,
                "draft": 0,
                "invoice": 0,
                "delivery": 0,
                "contract": 0,
                "today": 0,
                "next_7_days": 0,
            },
        )
    start = date.today()
    end = start + timedelta(days=days)
    rows = []
    draft_rows = (
        PortalOrderDraft.query.filter(
            PortalOrderDraft.user_id == getattr(user, "id", None),
            PortalOrderDraft.order_date >= start,
            PortalOrderDraft.order_date <= end,
        )
        .order_by(PortalOrderDraft.order_date.asc(), PortalOrderDraft.id.asc())
        .limit(80)
        .all()
    )
    for draft in draft_rows:
        rows.append(
            {
                "date": draft.order_date,
                "type": "DRAFT_ORDER",
                "title": f"{draft.meal_type} {draft.portion_qty} porsi",
                "status": draft.status,
                "source": "portal_order_drafts",
            }
        )
    if scope.client_ids:
        invoice_rows = (
            Invoice.query.filter(
                _portal_invoice_filter(scope),
                Invoice.due_date >= start,
                Invoice.due_date <= end,
            )
            .order_by(Invoice.due_date.asc(), Invoice.id.asc())
            .limit(80)
            .all()
        )
        for invoice in invoice_rows:
            rows.append(
                {
                    "date": invoice.due_date,
                    "type": "INVOICE_DUE",
                    "title": invoice.invoice_number,
                    "status": invoice.status,
                    "source": "invoices",
                    "amount": _money(invoice.remaining_amount),
                }
            )
        contract_rows = (
            CustomerContract.query.filter(
                CustomerContract.client_id.in_(sorted(scope.client_ids)),
                CustomerContract.end_date >= start,
                CustomerContract.end_date <= end,
            )
            .order_by(CustomerContract.end_date.asc(), CustomerContract.id.asc())
            .limit(80)
            .all()
        )
        for contract in contract_rows:
            rows.append(
                {
                    "date": contract.end_date,
                    "type": "CONTRACT_END",
                    "title": contract.contract_number,
                    "status": contract.status,
                    "source": "customer_contracts",
                }
            )
    if scope.mandor_ids or scope.delivery_location_ids:
        delivery_query = (
            Delivery.query.join(DeliveryDetail, DeliveryDetail.delivery_id == Delivery.id)
            .filter(
                Delivery.branch_id == scope.branch_id,
                Delivery.delivery_date >= start,
                Delivery.delivery_date <= end,
            )
        )
        delivery_scope_filters = []
        if scope.mandor_ids:
            delivery_scope_filters.append(DeliveryDetail.mandor_id.in_(sorted(scope.mandor_ids)))
        if scope.delivery_location_ids:
            delivery_scope_filters.append(DeliveryDetail.delivery_location_id.in_(sorted(scope.delivery_location_ids)))
        delivery_rows = (
            delivery_query.filter(or_(*delivery_scope_filters))
            .distinct()
            .order_by(Delivery.delivery_date.asc(), Delivery.id.asc())
            .limit(80)
            .all()
        )
    else:
        delivery_rows = []
    for delivery in delivery_rows:
        rows.append(
            {
                "date": delivery.delivery_date,
                "type": "DELIVERY",
                "title": delivery.delivery_number,
                "status": delivery.status,
                "source": "deliveries",
            }
        )
    rows = sorted(rows, key=lambda row: (row["date"], row["type"], row["title"]))[:160]
    next_week_end = start + timedelta(days=7)
    sections = {
        "today": [row for row in rows if row["date"] == start],
        "next_7_days": [row for row in rows if start <= row["date"] <= next_week_end],
        "draft": [row for row in rows if row["type"] == "DRAFT_ORDER"],
        "invoice": [row for row in rows if row["type"] == "INVOICE_DUE"],
        "delivery": [row for row in rows if row["type"] == "DELIVERY"],
        "contract": [row for row in rows if row["type"] == "CONTRACT_END"],
    }
    return {
        "allowed": True,
        "scope_mode": scope.scope_mode,
        "reason": "Kalender membaca draft, jatuh tempo invoice, kontrak, dan pengiriman.",
        "rows": rows,
        "sections": sections,
        "totals": {
            "total": len(rows),
            "draft": sum(1 for row in rows if row["type"] == "DRAFT_ORDER"),
            "invoice": sum(1 for row in rows if row["type"] == "INVOICE_DUE"),
            "delivery": sum(1 for row in rows if row["type"] == "DELIVERY"),
            "contract": sum(1 for row in rows if row["type"] == "CONTRACT_END"),
            "today": len(sections["today"]),
            "next_7_days": len(sections["next_7_days"]),
        },
    }
