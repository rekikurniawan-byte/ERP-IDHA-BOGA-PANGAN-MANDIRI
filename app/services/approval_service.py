"""Maker-checker approval request helpers for sensitive ERP actions."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Mapping

from app.extensions import db
from app.models.system import ApprovalRequest


APPROVAL_STATUS_SUBMITTED = "SUBMITTED"
APPROVAL_STATUS_APPROVED = "APPROVED"
APPROVAL_STATUS_REJECTED = "REJECTED"
APPROVAL_TERMINAL_STATUSES = {APPROVAL_STATUS_APPROVED, APPROVAL_STATUS_REJECTED}


class ApprovalError(ValueError):
    """Raised when a maker-checker approval rule is violated."""


def _normalize_key(value: str) -> str:
    return str(value or "").strip().upper()


def get_latest_action_request(*, branch_id: int, action_key: str, reference_type: str, reference_id: int) -> ApprovalRequest | None:
    return ApprovalRequest.query.filter_by(
        branch_id=branch_id,
        action_key=_normalize_key(action_key),
        reference_type=_normalize_key(reference_type),
        reference_id=reference_id,
    ).order_by(ApprovalRequest.id.desc()).first()


def ensure_action_has_approval(
    *,
    branch_id: int,
    action_key: str,
    reference_type: str,
    reference_id: int,
    requested_by: int,
    requested_reason: str,
    payload: Mapping[str, Any] | None = None,
) -> tuple[bool, ApprovalRequest, str]:
    request_row = get_latest_action_request(
        branch_id=branch_id,
        action_key=action_key,
        reference_type=reference_type,
        reference_id=reference_id,
    )
    if request_row and request_row.status == APPROVAL_STATUS_APPROVED:
        return True, request_row, "Approval sudah disetujui."
    if request_row and request_row.status == APPROVAL_STATUS_SUBMITTED:
        return False, request_row, "Approval sudah diajukan dan menunggu checker."

    request_row = create_approval_request(
        branch_id=branch_id,
        action_key=action_key,
        reference_type=reference_type,
        reference_id=reference_id,
        requested_by=requested_by,
        requested_reason=requested_reason,
        payload=payload,
        commit=False,
    )
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return False, request_row, "Approval maker-checker dibuat. Checker harus menyetujui sebelum aksi diproses."


def create_approval_request(
    *,
    branch_id: int,
    action_key: str,
    reference_type: str,
    reference_id: int,
    requested_by: int,
    requested_reason: str,
    payload: Mapping[str, Any] | None = None,
    commit: bool = True,
) -> ApprovalRequest:
    reason = str(requested_reason or "").strip()
    if not reason:
        raise ApprovalError("Alasan pengajuan approval wajib diisi.")

    request_row = ApprovalRequest(
        branch_id=branch_id,
        action_key=_normalize_key(action_key),
        reference_type=_normalize_key(reference_type),
        reference_id=reference_id,
        status=APPROVAL_STATUS_SUBMITTED,
        requested_by=requested_by,
        requested_reason=reason,
        payload_json=json.dumps(payload or {}, sort_keys=True, default=str),
    )
    db.session.add(request_row)
    if commit:
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
    return request_row


def approve_request(request_row: ApprovalRequest, *, reviewed_by: int, review_note: str = "", commit: bool = True) -> ApprovalRequest:
    if request_row.status in APPROVAL_TERMINAL_STATUSES:
        raise ApprovalError("Approval request sudah final.")
    if request_row.requested_by == reviewed_by:
        raise ApprovalError("Maker dan checker tidak boleh user yang sama.")

    request_row.status = APPROVAL_STATUS_APPROVED
    request_row.reviewed_by = reviewed_by
    request_row.review_note = str(review_note or "").strip() or None
    request_row.reviewed_at = datetime.utcnow()
    if commit:
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
    return request_row


def reject_request(request_row: ApprovalRequest, *, reviewed_by: int, review_note: str, commit: bool = True) -> ApprovalRequest:
    note = str(review_note or "").strip()
    if not note:
        raise ApprovalError("Alasan reject approval wajib diisi.")
    if request_row.status in APPROVAL_TERMINAL_STATUSES:
        raise ApprovalError("Approval request sudah final.")
    if request_row.requested_by == reviewed_by:
        raise ApprovalError("Maker dan checker tidak boleh user yang sama.")

    request_row.status = APPROVAL_STATUS_REJECTED
    request_row.reviewed_by = reviewed_by
    request_row.review_note = note
    request_row.reviewed_at = datetime.utcnow()
    if commit:
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
    return request_row


def has_approved_request(*, branch_id: int, action_key: str, reference_type: str, reference_id: int) -> bool:
    return ApprovalRequest.query.filter_by(
        branch_id=branch_id,
        action_key=_normalize_key(action_key),
        reference_type=_normalize_key(reference_type),
        reference_id=reference_id,
        status=APPROVAL_STATUS_APPROVED,
    ).first() is not None
