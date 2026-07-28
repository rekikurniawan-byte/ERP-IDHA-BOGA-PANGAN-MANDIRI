from __future__ import annotations

from datetime import datetime

from app.extensions import db
from app.models.finance import Invoice, Payment
from app.models.system import DigitalAttachment
from app.services.atomic_transaction_service import atomic_business_action
from app.services.portal_payment_proof_service import (
    PAYMENT_PROOF_PENDING_TYPE,
    PAYMENT_PROOF_REFERENCE_TYPE,
    PORTAL_PAYMENT_MODULE,
)


PAYMENT_PROOF_VERIFIED_TYPE = "PAYMENT_PROOF_VERIFIED"
PAYMENT_PROOF_REJECTED_TYPE = "PAYMENT_PROOF_REJECTED"

_STATE_BY_DECISION = {
    "VERIFIED": PAYMENT_PROOF_VERIFIED_TYPE,
    "REJECTED": PAYMENT_PROOF_REJECTED_TYPE,
}

_QUEUE_STATE_TYPES = {
    "PENDING": PAYMENT_PROOF_PENDING_TYPE,
    "VERIFIED": PAYMENT_PROOF_VERIFIED_TYPE,
    "REJECTED": PAYMENT_PROOF_REJECTED_TYPE,
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
    invoice = _get_attachment_invoice(attachment)
    payment_count_before = Payment.query.count()

    if attachment.attachment_type == target_type:
        return _decision_result(
            attachment=attachment,
            invoice=invoice,
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
            reference_type=PAYMENT_PROOF_REFERENCE_TYPE,
            reference_id=invoice.id,
            user_id=getattr(finance_user, "id", None),
            branch_id=getattr(finance_user, "branch_id", None),
            severity="MEDIUM",
            metadata={
                "attachment_id": attachment.id,
                "invoice_number": invoice.invoice_number,
                "payment_created": False,
                "invoice_mutated": False,
            },
        ):
            _apply_decision(attachment, decision_key, finance_user, notes)
            db.session.flush()
    else:
        _apply_decision(attachment, decision_key, finance_user, notes)
        db.session.flush()

    return _decision_result(
        attachment=attachment,
        invoice=invoice,
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
        DigitalAttachment.reference_type == PAYMENT_PROOF_REFERENCE_TYPE,
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


def _build_queue_item(attachment: DigitalAttachment) -> dict:
    invoice = _get_attachment_invoice(attachment)
    return {
        "attachment_id": attachment.id,
        "attachment_type": attachment.attachment_type,
        "invoice_id": invoice.id,
        "invoice_number": invoice.invoice_number,
        "invoice_status": invoice.status,
        "invoice_total": invoice.total_amount,
        "invoice_paid": invoice.paid_amount,
        "invoice_remaining": invoice.remaining_amount,
        "original_filename": attachment.original_filename,
        "uploaded_by": attachment.uploaded_by,
        "created_at": attachment.created_at,
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


def _decision_result(
    *,
    attachment: DigitalAttachment,
    invoice: Invoice,
    decision: str,
    changed: bool,
    payment_count_before: int,
) -> dict:
    return {
        "attachment_id": attachment.id,
        "attachment_type": attachment.attachment_type,
        "invoice_id": invoice.id,
        "invoice_number": invoice.invoice_number,
        "decision": decision,
        "changed": changed,
        "payment_created": False,
        "invoice_paid_amount": invoice.paid_amount,
        "invoice_remaining_amount": invoice.remaining_amount,
        "payment_count_before": payment_count_before,
        "payment_count_after": Payment.query.count(),
        "mutation_scope": "ATTACHMENT_DECISION_ONLY",
    }
