from __future__ import annotations

from app.models.system import DigitalAttachment
from app.extensions import db
from app.services.atomic_transaction_service import atomic_business_action
from app.services.digital_attachment_service import stage_digital_attachment
from app.services.portal_payment_instruction_service import build_portal_payment_instruction


PORTAL_PAYMENT_MODULE = "PORTAL_PAYMENT"
PAYMENT_PROOF_REFERENCE_TYPE = "INVOICE"
PAYMENT_PROOF_PENDING_TYPE = "PAYMENT_PROOF_PENDING"


class PortalPaymentProofError(ValueError):
    pass


def upload_portal_payment_proof(
    user,
    *,
    invoice_id: int,
    file_storage,
    notes: str | None = None,
    commit: bool = True,
) -> dict:
    """Upload proof for an owned payable invoice without creating payment rows."""
    instruction = build_portal_payment_instruction(user, invoice_id=invoice_id)
    if not instruction["allowed"]:
        raise PortalPaymentProofError(instruction["reason"])
    if not instruction["payable"]:
        raise PortalPaymentProofError("Invoice tidak dalam status payable untuk upload bukti pembayaran.")

    invoice = instruction["invoice"]
    if commit:
        with atomic_business_action(
            module=PORTAL_PAYMENT_MODULE,
            action="PORTAL_PAYMENT_PROOF_UPLOADED",
            description="Portal payment proof upload staged for finance verification.",
            reference_type=PAYMENT_PROOF_REFERENCE_TYPE,
            reference_id=invoice["invoice_id"],
            user_id=getattr(user, "id", None),
            branch_id=getattr(user, "branch_id", None),
            severity="MEDIUM",
            metadata={
                "invoice_number": invoice["invoice_number"],
                "mutation_scope": "ATTACHMENT_ONLY",
                "payment_created": False,
            },
        ) as boundary:
            attachment = _stage_payment_proof_attachment(user, invoice, file_storage, notes)
            boundary.track_attachment(attachment)
            db.session.flush()
    else:
        attachment = _stage_payment_proof_attachment(user, invoice, file_storage, notes)
        db.session.flush()

    return {
        "uploaded": True,
        "status": "PENDING_FINANCE_VERIFICATION",
        "invoice_id": invoice["invoice_id"],
        "invoice_number": invoice["invoice_number"],
        "attachment_id": attachment.id,
        "attachment_type": attachment.attachment_type,
        "payment_created": False,
        "invoice_marked_paid": False,
        "mutation_scope": "ATTACHMENT_ONLY",
    }


def _stage_payment_proof_attachment(user, invoice: dict, file_storage, notes: str | None) -> DigitalAttachment:
    return stage_digital_attachment(
        file_storage=file_storage,
        module=PORTAL_PAYMENT_MODULE,
        reference_type=PAYMENT_PROOF_REFERENCE_TYPE,
        reference_id=invoice["invoice_id"],
        attachment_type=PAYMENT_PROOF_PENDING_TYPE,
        branch_id=getattr(user, "branch_id", None),
        uploaded_by=getattr(user, "id", None),
        notes=_proof_notes(notes),
    )


def _proof_notes(notes: str | None) -> str:
    clean = str(notes or "").strip()
    prefix = "PENDING_FINANCE_VERIFICATION"
    return f"{prefix}: {clean}" if clean else prefix


def list_pending_portal_payment_proofs(*, branch_id: int | None = None) -> list[DigitalAttachment]:
    """Small read helper for the next finance verification queue batch."""
    query = DigitalAttachment.query.filter_by(
        module=PORTAL_PAYMENT_MODULE,
        reference_type=PAYMENT_PROOF_REFERENCE_TYPE,
        attachment_type=PAYMENT_PROOF_PENDING_TYPE,
        is_deleted=False,
    )
    if branch_id is not None:
        query = query.filter(DigitalAttachment.branch_id == branch_id)
    return query.order_by(DigitalAttachment.created_at.asc(), DigitalAttachment.id.asc()).all()
