from __future__ import annotations

from collections import Counter
from datetime import date, datetime

from app.models.complaint import CustomerComplaint
from app.models.contract import CustomerContract
from app.models.system import DigitalAttachment
from app.services.atomic_transaction_service import atomic_business_action
from app.services.customer_complaint_service import (
    COMPLAINT_CATEGORIES,
    CustomerComplaintError,
    submit_customer_complaint,
)
from app.services.customer_complaint_attachment_service import list_customer_complaint_evidence
from app.services.notification_service import create_or_update_notification
from app.services.portal_mapping_service import build_portal_external_scope, list_active_portal_mappings


def _clean_text(value):
    return str(value or "").strip()


def _first_or_none(values):
    return sorted(values)[0] if values else None


def _portal_reference_ids(user):
    scope = build_portal_external_scope(user)
    client_id = _first_or_none(scope.client_ids)
    mandor_id = _first_or_none(scope.mandor_ids)
    if not client_id and not mandor_id:
        for mapping in list_active_portal_mappings(user):
            if not client_id and getattr(mapping, "client_id", None):
                client_id = mapping.client_id
            if not mandor_id and getattr(mapping, "mandor_id", None):
                mandor_id = mapping.mandor_id
            if not client_id and getattr(mapping, "mandor", None):
                client_id = mapping.mandor.client_id
            if client_id and mandor_id:
                break
    return {
        "scope": scope,
        "branch_id": getattr(user, "branch_id", None),
        "client_id": client_id,
        "mandor_id": mandor_id,
    }


def build_portal_complaint_model(user, *, limit: int = 50) -> dict:
    refs = _portal_reference_ids(user)
    branch_id = refs["branch_id"]
    if not branch_id:
        return {
            "allowed": False,
            "reason": "User portal belum memiliki branch aktif.",
            "scope_mode": refs["scope"].scope_mode,
            "categories": sorted(COMPLAINT_CATEGORIES),
            "rows": [],
            "totals": {"complaint_count": 0, "open_count": 0, "done_count": 0},
        }

    rows = (
        CustomerComplaint.query.filter(
            CustomerComplaint.branch_id == branch_id,
            CustomerComplaint.submitted_by == getattr(user, "id", None),
        )
        .order_by(CustomerComplaint.submitted_at.desc(), CustomerComplaint.id.desc())
        .limit(limit)
        .all()
    )
    category_counts = Counter(row.category for row in rows)
    status_counts = Counter(row.status for row in rows)
    evidence_counts = {
        row.id: len(list_customer_complaint_evidence(complaint_id=row.id, branch_id=branch_id))
        for row in rows
    }
    return_categories = {"FOOD_SHORTAGE", "WRONG_MENU", "PORTION_SHORTAGE", "DAMAGED_FOOD"}
    return {
        "allowed": True,
        "reason": "Komplain dibatasi ke laporan yang dibuat user portal ini.",
        "scope_mode": refs["scope"].scope_mode,
        "categories": sorted(COMPLAINT_CATEGORIES),
        "rows": rows,
        "evidence_counts": evidence_counts,
        "category_counts": dict(category_counts),
        "status_counts": dict(status_counts),
        "totals": {
            "complaint_count": len(rows),
            "open_count": sum(1 for row in rows if row.status in {"OPEN", "IN_PROGRESS"}),
            "done_count": sum(1 for row in rows if row.status in {"RESOLVED", "CLOSED"}),
            "return_related_count": sum(1 for row in rows if row.category in return_categories),
            "evidence_count": sum(evidence_counts.values()),
            "awaiting_response_count": status_counts.get("OPEN", 0),
            "in_progress_count": status_counts.get("IN_PROGRESS", 0),
        },
    }


def submit_portal_customer_complaint(user, form):
    refs = _portal_reference_ids(user)
    branch_id = refs["branch_id"]
    if not branch_id:
        return None, "User portal belum memiliki branch aktif."

    category = _clean_text(form.get("category"))
    title = _clean_text(form.get("title"))
    description = _clean_text(form.get("description"))
    if not title:
        return None, "Judul komplain wajib diisi."
    if not description:
        return None, "Deskripsi komplain wajib diisi."

    try:
        with atomic_business_action(
            module="PORTAL",
            action="PORTAL_CUSTOMER_COMPLAINT_SUBMIT",
            description="Submit komplain portal beserta notifikasi admin.",
            reference_type="customer_complaints",
            user_id=user.id,
            branch_id=branch_id,
            severity="MEDIUM",
            metadata={"mutation_scope": "COMPLAINT_AND_NOTIFICATION"},
        ):
            complaint = submit_customer_complaint(
                branch_id=branch_id,
                category=category,
                title=title,
                description=description,
                submitted_by=user.id,
                client_id=refs["client_id"],
                mandor_id=refs["mandor_id"],
                submitted_at=datetime.utcnow(),
                commit=False,
            )
            create_or_update_notification(
                branch_id=branch_id,
                notification_type="PORTAL_CUSTOMER_COMPLAINT",
                title=f"Komplain portal masuk: {complaint.complaint_number}",
                message=f"{complaint.title} - {complaint.category.replace('_', ' ')}",
                target_role="ADMIN",
                priority="WARNING",
                reference_type="CUSTOMER_COMPLAINT",
                reference_id=complaint.id,
                action_url="/customer-success/complaints",
                generated_key=f"portal-complaint-submitted-{complaint.id}",
                metadata={
                    "submitted_by": user.id,
                    "client_id": complaint.client_id,
                    "mandor_id": complaint.mandor_id,
                    "mutation_scope": "NOTIFICATION_ONLY",
                },
                commit=False,
            )
    except CustomerComplaintError as exc:
        return None, str(exc)

    return complaint, None


def build_portal_contract_model(user, *, limit: int = 100) -> dict:
    refs = _portal_reference_ids(user)
    scope = refs["scope"]
    branch_id = refs["branch_id"]
    if not branch_id:
        return {
            "allowed": False,
            "reason": "User portal belum memiliki branch aktif.",
            "scope_mode": scope.scope_mode,
            "rows": [],
            "health_rows": [],
            "totals": {
                "contract_count": 0,
                "active_count": 0,
                "credit_limit": 0,
                "expiring_soon_count": 0,
                "expired_count": 0,
                "document_count": 0,
            },
        }

    query = CustomerContract.query.filter(CustomerContract.branch_id == branch_id)
    if scope.client_ids:
        query = query.filter(CustomerContract.client_id.in_(sorted(scope.client_ids)))
    else:
        query = query.filter(CustomerContract.id.in_([-1]))

    rows = query.order_by(CustomerContract.end_date.asc(), CustomerContract.id.asc()).limit(limit).all()
    contract_ids = [row.id for row in rows]
    document_counts = {}
    if contract_ids:
        attachments = (
            DigitalAttachment.query.filter(
                DigitalAttachment.branch_id == branch_id,
                DigitalAttachment.reference_type == "CUSTOMER_CONTRACT",
                DigitalAttachment.reference_id.in_(contract_ids),
                DigitalAttachment.is_deleted.is_(False),
            )
            .with_entities(DigitalAttachment.reference_id)
            .all()
        )
        document_counts = Counter(reference_id for (reference_id,) in attachments)

    today = date.today()
    health_rows = []
    for contract in rows:
        days_remaining = (contract.end_date - today).days if contract.end_date else None
        status = str(contract.status or "-").upper()
        if days_remaining is not None and days_remaining < 0:
            lifecycle = "EXPIRED"
            tone = "red"
        elif status == "ACTIVE" and days_remaining is not None and days_remaining <= 30:
            lifecycle = "EXPIRING_SOON"
            tone = "orange"
        elif status == "ACTIVE":
            lifecycle = "ACTIVE"
            tone = "green"
        elif status == "DRAFT":
            lifecycle = "DRAFT"
            tone = "slate"
        else:
            lifecycle = status
            tone = "purple"
        health_rows.append(
            {
                "contract": contract,
                "contract_id": contract.id,
                "contract_number": contract.contract_number,
                "title": contract.title,
                "client_name": contract.client.name if contract.client else "-",
                "status": status,
                "lifecycle": lifecycle,
                "tone": tone,
                "start_date": contract.start_date,
                "end_date": contract.end_date,
                "days_remaining": days_remaining,
                "payment_terms": contract.payment_terms,
                "credit_limit": contract.credit_limit or 0,
                "version_no": contract.version_no,
                "notes": contract.notes,
                "document_count": document_counts.get(contract.id, 0),
            }
        )

    return {
        "allowed": scope.allowed and bool(scope.client_ids),
        "reason": "Kontrak dibaca sesuai akses perusahaan/PT.",
        "scope_mode": scope.scope_mode,
        "rows": rows,
        "health_rows": health_rows,
        "totals": {
            "contract_count": len(rows),
            "active_count": sum(1 for row in rows if row.status == "ACTIVE"),
            "credit_limit": sum(row.credit_limit or 0 for row in rows),
            "expiring_soon_count": sum(1 for row in health_rows if row["lifecycle"] == "EXPIRING_SOON"),
            "expired_count": sum(1 for row in health_rows if row["lifecycle"] == "EXPIRED"),
            "document_count": sum(row["document_count"] for row in health_rows),
        },
    }
