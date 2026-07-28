from __future__ import annotations

from datetime import datetime

from app.models.complaint import CustomerComplaint
from app.models.contract import CustomerContract
from app.services.customer_complaint_service import (
    COMPLAINT_CATEGORIES,
    CustomerComplaintError,
    submit_customer_complaint,
)
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
    return {
        "allowed": True,
        "reason": "Komplain dibatasi ke laporan yang dibuat user portal ini.",
        "scope_mode": refs["scope"].scope_mode,
        "categories": sorted(COMPLAINT_CATEGORIES),
        "rows": rows,
        "totals": {
            "complaint_count": len(rows),
            "open_count": sum(1 for row in rows if row.status in {"OPEN", "IN_PROGRESS"}),
            "done_count": sum(1 for row in rows if row.status in {"RESOLVED", "CLOSED"}),
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
        complaint = submit_customer_complaint(
            branch_id=branch_id,
            category=category,
            title=title,
            description=description,
            submitted_by=user.id,
            client_id=refs["client_id"],
            mandor_id=refs["mandor_id"],
            submitted_at=datetime.utcnow(),
            commit=True,
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
            "totals": {"contract_count": 0, "active_count": 0, "credit_limit": 0},
        }

    query = CustomerContract.query.filter(CustomerContract.branch_id == branch_id)
    if scope.client_ids:
        query = query.filter(CustomerContract.client_id.in_(sorted(scope.client_ids)))
    else:
        query = query.filter(CustomerContract.id.in_([-1]))

    rows = query.order_by(CustomerContract.end_date.asc(), CustomerContract.id.asc()).limit(limit).all()
    return {
        "allowed": scope.allowed and bool(scope.client_ids),
        "reason": "Kontrak dibaca dari CustomerContract ERP existing sesuai client/PT scope.",
        "scope_mode": scope.scope_mode,
        "rows": rows,
        "totals": {
            "contract_count": len(rows),
            "active_count": sum(1 for row in rows if row.status == "ACTIVE"),
            "credit_limit": sum(row.credit_limit or 0 for row in rows),
        },
    }
