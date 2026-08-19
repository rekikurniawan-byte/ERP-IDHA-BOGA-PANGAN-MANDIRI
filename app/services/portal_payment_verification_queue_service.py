from __future__ import annotations

from datetime import datetime

from app.extensions import db
from app.models.finance import Invoice, Payment
from app.models.system import DigitalAttachment, PortalOrderDraft
from app.services.atomic_transaction_service import atomic_business_action
from app.services.notification_service import create_or_update_notification
from app.services.portal_payment_proof_service import (
    PAYMENT_PROOF_PENDING_TYPE,
    PAYMENT_PROOF_REFERENCE_TYPE,
    PORTAL_DRAFT_PAYMENT_REFERENCE_TYPE,
    PORTAL_PAYMENT_MODULE,
)


PAYMENT_PROOF_VERIFIED_TYPE = "PAYMENT_PROOF_VERIFIED"
PAYMENT_PROOF_REJECTED_TYPE = "PAYMENT_PROOF_REJECTED"
PAYMENT_PROOF_PAYMENT_CREATED_TYPE = "PAYMENT_PROOF_PAYMENT_CREATED"

PAYMENT_PROOF_QUEUE_LABELS = {
    "PENDING": "Menunggu Finance",
    "VERIFIED": "Diverifikasi",
    "REJECTED": "Ditolak",
    "PAYMENT_CREATED": "Pembayaran Resmi Dibuat",
}

_STATE_BY_DECISION = {
    "VERIFIED": PAYMENT_PROOF_VERIFIED_TYPE,
    "REJECTED": PAYMENT_PROOF_REJECTED_TYPE,
}

_QUEUE_STATE_TYPES = {
    "PENDING": PAYMENT_PROOF_PENDING_TYPE,
    "VERIFIED": PAYMENT_PROOF_VERIFIED_TYPE,
    "REJECTED": PAYMENT_PROOF_REJECTED_TYPE,
    "PAYMENT_CREATED": PAYMENT_PROOF_PAYMENT_CREATED_TYPE,
}


class PaymentProofVerificationError(ValueError):
    pass


def list_payment_proof_verification_queue(finance_user, *, status: str = "PENDING", limit: int = 100) -> list[dict]:
    """Return branch-scoped portal proof queue for finance review."""
    attachment_type = _queue_attachment_type(status)
    query = _base_attachment_query(getattr(finance_user, "branch_id", None)).filter(
        DigitalAttachment.attachment_type == attachment_type,
    )
    attachments = query.order_by(DigitalAttachment.created_at.asc(), DigitalAttachment.id.asc()).limit(limit).all()
    return [_build_queue_item(attachment) for attachment in attachments]


def build_payment_proof_verification_summary(finance_user) -> dict:
    branch_id = getattr(finance_user, "branch_id", None)
    counts = {}
    amounts = {}
    for status, attachment_type in _QUEUE_STATE_TYPES.items():
        query = _base_attachment_query(branch_id).filter(DigitalAttachment.attachment_type == attachment_type)
        attachments = query.all()
        rows = [_build_queue_item(attachment) for attachment in attachments]
        counts[status] = len(rows)
        amounts[status] = sum(float(row["invoice_remaining"] or 0) for row in rows)
    return {
        "counts": counts,
        "amounts": amounts,
        "labels": PAYMENT_PROOF_QUEUE_LABELS,
        "total_count": sum(counts.values()),
        "pending_count": counts.get("PENDING", 0),
        "verified_count": counts.get("VERIFIED", 0),
        "payment_created_count": counts.get("PAYMENT_CREATED", 0),
    }


def decide_payment_proof(
    finance_user,
    *,
    attachment_id: int,
    decision: str,
    notes: str | None = None,
    commit: bool = True,
) -> dict:
    """Mark a portal payment proof as verified/rejected without creating payment rows."""
    decision_key = str(decision or "").strip().upper()
    if decision_key not in _STATE_BY_DECISION:
        raise PaymentProofVerificationError("Keputusan verifikasi bukti pembayaran tidak valid.")

    target_type = _STATE_BY_DECISION[decision_key]
    attachment = _get_reviewable_attachment(finance_user, attachment_id)
    source = _get_attachment_source(attachment)
    payment_count_before = Payment.query.count()

    if attachment.attachment_type == target_type:
        return _decision_result(
            attachment=attachment,
            source=source,
            decision=decision_key,
            changed=False,
            payment_count_before=payment_count_before,
        )

    if attachment.attachment_type != PAYMENT_PROOF_PENDING_TYPE:
        raise PaymentProofVerificationError("Bukti pembayaran sudah diputuskan dan tidak bisa diubah pada batch ini.")

    if commit:
        with atomic_business_action(
            module=PORTAL_PAYMENT_MODULE,
            action=f"PAYMENT_PROOF_{decision_key}",
            description=f"Finance {decision_key.lower()} portal payment proof without payment creation.",
            reference_type=attachment.reference_type,
            reference_id=attachment.reference_id,
            user_id=getattr(finance_user, "id", None),
            branch_id=getattr(finance_user, "branch_id", None),
            severity="MEDIUM",
            metadata={
                "attachment_id": attachment.id,
                "source_type": attachment.reference_type,
                "payment_created": False,
                "source_mutated": False,
            },
        ):
            _apply_decision(attachment, decision_key, finance_user, notes)
            db.session.flush()
            _notify_portal_payment_proof_decision(attachment, source, decision_key, finance_user)
    else:
        _apply_decision(attachment, decision_key, finance_user, notes)
        db.session.flush()
        _notify_portal_payment_proof_decision(attachment, source, decision_key, finance_user)

    return _decision_result(
        attachment=attachment,
        source=source,
        decision=decision_key,
        changed=True,
        payment_count_before=payment_count_before,
    )


def _queue_attachment_type(status: str) -> str:
    key = str(status or "PENDING").strip().upper()
    if key not in _QUEUE_STATE_TYPES:
        raise PaymentProofVerificationError("Status queue bukti pembayaran tidak valid.")
    return _QUEUE_STATE_TYPES[key]


def _base_attachment_query(branch_id: int | None):
    query = DigitalAttachment.query.filter(
        DigitalAttachment.module == PORTAL_PAYMENT_MODULE,
        DigitalAttachment.reference_type.in_([PAYMENT_PROOF_REFERENCE_TYPE, PORTAL_DRAFT_PAYMENT_REFERENCE_TYPE]),
        DigitalAttachment.is_deleted.is_(False),
    )
    if branch_id is not None:
        query = query.filter(DigitalAttachment.branch_id == branch_id)
    return query


def _get_reviewable_attachment(finance_user, attachment_id: int) -> DigitalAttachment:
    attachment = _base_attachment_query(getattr(finance_user, "branch_id", None)).filter(
        DigitalAttachment.id == attachment_id,
    ).first()
    if not attachment:
        raise PaymentProofVerificationError("Bukti pembayaran tidak ditemukan untuk cabang finance ini.")
    return attachment


def _get_attachment_invoice(attachment: DigitalAttachment) -> Invoice:
    invoice = Invoice.query.filter(
        Invoice.id == attachment.reference_id,
        Invoice.branch_id == attachment.branch_id,
    ).first()
    if not invoice:
        raise PaymentProofVerificationError("Invoice sumber bukti pembayaran tidak ditemukan.")
    return invoice


def _get_attachment_draft(attachment: DigitalAttachment) -> PortalOrderDraft:
    draft = PortalOrderDraft.query.filter(
        PortalOrderDraft.id == attachment.reference_id,
        PortalOrderDraft.branch_id == attachment.branch_id,
    ).first()
    if not draft:
        raise PaymentProofVerificationError("Draft order sumber bukti pembayaran tidak ditemukan.")
    return draft


def _get_attachment_source(attachment: DigitalAttachment):
    if attachment.reference_type == PAYMENT_PROOF_REFERENCE_TYPE:
        return _get_attachment_invoice(attachment)
    if attachment.reference_type == PORTAL_DRAFT_PAYMENT_REFERENCE_TYPE:
        return _get_attachment_draft(attachment)
    raise PaymentProofVerificationError("Tipe sumber bukti pembayaran portal tidak didukung.")


def _build_queue_item(attachment: DigitalAttachment) -> dict:
    source = _get_attachment_source(attachment)
    status_key = next(
        (key for key, attachment_type in _QUEUE_STATE_TYPES.items() if attachment_type == attachment.attachment_type),
        attachment.attachment_type,
    )
    is_invoice = attachment.reference_type == PAYMENT_PROOF_REFERENCE_TYPE
    source_label = source.invoice_number if is_invoice else f"Draft Order #{source.id}"
    return {
        "attachment_id": attachment.id,
        "attachment_type": attachment.attachment_type,
        "status_key": status_key,
        "status_label": PAYMENT_PROOF_QUEUE_LABELS.get(status_key, attachment.attachment_type),
        "source_type": attachment.reference_type,
        "source_label": source_label,
        "is_invoice_source": is_invoice,
        "is_draft_source": not is_invoice,
        "invoice_id": source.id if is_invoice else None,
        "invoice_number": source.invoice_number if is_invoice else "-",
        "invoice_status": source.status,
        "invoice_total": source.total_amount if is_invoice else 0,
        "invoice_paid": source.paid_amount if is_invoice else 0,
        "invoice_remaining": source.remaining_amount if is_invoice else 0,
        "draft_id": None if is_invoice else source.id,
        "draft_date": None if is_invoice else source.order_date,
        "draft_meal_type": None if is_invoice else source.meal_type,
        "draft_portion_qty": None if is_invoice else source.portion_qty,
        "original_filename": attachment.original_filename,
        "uploaded_by": attachment.uploaded_by,
        "created_at": attachment.created_at,
        "idempotency_key": f"portal-proof-{attachment.id}-{status_key.lower()}",
        "payment_created": False,
        "mutation_scope": "ATTACHMENT_DECISION_ONLY",
    }


def _apply_decision(attachment: DigitalAttachment, decision: str, finance_user, notes: str | None) -> None:
    attachment.attachment_type = _STATE_BY_DECISION[decision]
    attachment.notes = _append_decision_note(attachment.notes, decision, finance_user, notes)


def _append_decision_note(existing: str | None, decision: str, finance_user, notes: str | None) -> str:
    clean_note = str(notes or "").strip()
    reviewer_id = getattr(finance_user, "id", None)
    reviewed_at = datetime.utcnow().isoformat(timespec="seconds")
    decision_line = f"FINANCE_VERIFICATION {decision} by user_id={reviewer_id} at {reviewed_at}"
    if clean_note:
        decision_line = f"{decision_line}: {clean_note}"
    return f"{existing}\n{decision_line}" if existing else decision_line


def _notify_portal_payment_proof_decision(
    attachment: DigitalAttachment,
    source,
    decision: str,
    finance_user,
) -> None:
    if not attachment.uploaded_by:
        return
    title_status = "diverifikasi" if decision == "VERIFIED" else "ditolak"
    is_invoice = attachment.reference_type == PAYMENT_PROOF_REFERENCE_TYPE
    source_name = source.invoice_number if is_invoice else f"draft order #{source.id}"
    create_or_update_notification(
        branch_id=source.branch_id,
        notification_type="PORTAL_PAYMENT_PROOF_DECISION",
        title=f"Bukti pembayaran {title_status}",
        message=f"Bukti pembayaran {source_name} sudah {title_status} oleh finance.",
        target_user_id=attachment.uploaded_by,
        priority="INFO" if decision == "VERIFIED" else "WARNING",
        reference_type=attachment.reference_type,
        reference_id=attachment.reference_id,
        action_url=f"/portal/invoices/{source.id}/payment" if is_invoice else "/portal/orders/status",
        generated_key=f"portal-payment-proof-{decision.lower()}-{attachment.id}",
        metadata={
            "attachment_id": attachment.id,
            "reviewed_by": getattr(finance_user, "id", None),
            "decision": decision,
            "mutation_scope": "NOTIFICATION_ONLY",
        },
        commit=False,
    )


def _decision_result(
    *,
    attachment: DigitalAttachment,
    source,
    decision: str,
    changed: bool,
    payment_count_before: int,
) -> dict:
    is_invoice = attachment.reference_type == PAYMENT_PROOF_REFERENCE_TYPE
    return {
        "attachment_id": attachment.id,
        "attachment_type": attachment.attachment_type,
        "source_type": attachment.reference_type,
        "source_label": source.invoice_number if is_invoice else f"Draft Order #{source.id}",
        "invoice_id": source.id if is_invoice else None,
        "invoice_number": source.invoice_number if is_invoice else "-",
        "draft_id": None if is_invoice else source.id,
        "decision": decision,
        "changed": changed,
        "payment_created": False,
        "invoice_paid_amount": source.paid_amount if is_invoice else 0,
        "invoice_remaining_amount": source.remaining_amount if is_invoice else 0,
        "payment_count_before": payment_count_before,
        "payment_count_after": Payment.query.count(),
        "mutation_scope": "ATTACHMENT_DECISION_ONLY",
    }
