from __future__ import annotations

from app.models.system import DigitalAttachment
from app.models.system import PortalOrderDraft
from app.extensions import db
from app.services.atomic_transaction_service import atomic_business_action
from app.services.digital_attachment_service import stage_digital_attachment
from app.services.notification_service import create_or_update_notification
from app.services.portal_payment_instruction_service import build_portal_payment_instruction


PORTAL_PAYMENT_MODULE = "PORTAL_PAYMENT"
PAYMENT_PROOF_REFERENCE_TYPE = "INVOICE"
PORTAL_DRAFT_PAYMENT_REFERENCE_TYPE = "PORTAL_ORDER_DRAFT"
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
            _notify_finance_payment_proof_uploaded(user, invoice, attachment)
    else:
        attachment = _stage_payment_proof_attachment(user, invoice, file_storage, notes)
        db.session.flush()
        _notify_finance_payment_proof_uploaded(user, invoice, attachment)

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


def upload_portal_order_draft_payment_proof(
    user,
    *,
    draft_id: int,
    file_storage,
    notes: str | None = None,
    commit: bool = True,
) -> dict:
    """Upload prepayment proof for a portal order draft without creating invoice/payment rows."""
    draft = PortalOrderDraft.query.filter_by(id=draft_id, user_id=getattr(user, "id", None)).first()
    if not draft:
        raise PortalPaymentProofError("Draft order tidak ditemukan untuk user portal ini.")
    if draft.status != "PENDING_ADMIN_CONFIRMATION":
        raise PortalPaymentProofError("Bukti pembayaran awal hanya dapat diunggah untuk draft yang masih menunggu admin.")

    if commit:
        with atomic_business_action(
            module=PORTAL_PAYMENT_MODULE,
            action="PORTAL_DRAFT_PAYMENT_PROOF_UPLOADED",
            description="Portal draft prepayment proof upload staged for finance verification.",
            reference_type=PORTAL_DRAFT_PAYMENT_REFERENCE_TYPE,
            reference_id=draft.id,
            user_id=getattr(user, "id", None),
            branch_id=draft.branch_id,
            severity="MEDIUM",
            metadata={
                "draft_id": draft.id,
                "mutation_scope": "ATTACHMENT_ONLY",
                "invoice_created": False,
                "payment_created": False,
            },
        ) as boundary:
            attachment = _stage_draft_payment_proof_attachment(user, draft, file_storage, notes)
            boundary.track_attachment(attachment)
            db.session.flush()
            _notify_finance_draft_payment_proof_uploaded(user, draft, attachment)
    else:
        attachment = _stage_draft_payment_proof_attachment(user, draft, file_storage, notes)
        db.session.flush()
        _notify_finance_draft_payment_proof_uploaded(user, draft, attachment)

    return {
        "uploaded": True,
        "status": "PENDING_FINANCE_VERIFICATION",
        "draft_id": draft.id,
        "attachment_id": attachment.id,
        "attachment_type": attachment.attachment_type,
        "payment_created": False,
        "invoice_created": False,
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


def _stage_draft_payment_proof_attachment(user, draft: PortalOrderDraft, file_storage, notes: str | None) -> DigitalAttachment:
    return stage_digital_attachment(
        file_storage=file_storage,
        module=PORTAL_PAYMENT_MODULE,
        reference_type=PORTAL_DRAFT_PAYMENT_REFERENCE_TYPE,
        reference_id=draft.id,
        attachment_type=PAYMENT_PROOF_PENDING_TYPE,
        branch_id=draft.branch_id,
        uploaded_by=getattr(user, "id", None),
        notes=_proof_notes(notes),
    )


def _proof_notes(notes: str | None) -> str:
    clean = str(notes or "").strip()
    prefix = "PENDING_FINANCE_VERIFICATION"
    return f"{prefix}: {clean}" if clean else prefix


def _notify_finance_payment_proof_uploaded(user, invoice: dict, attachment: DigitalAttachment) -> None:
    create_or_update_notification(
        branch_id=getattr(user, "branch_id", None),
        notification_type="PORTAL_PAYMENT_PROOF",
        title=f"Bukti pembayaran portal masuk: {invoice['invoice_number']}",
        message=f"User portal mengupload bukti pembayaran untuk invoice {invoice['invoice_number']}. Finance perlu verifikasi.",
        target_role="FINANCE",
        priority="WARNING",
        reference_type=PAYMENT_PROOF_REFERENCE_TYPE,
        reference_id=invoice["invoice_id"],
        action_url="/finance/portal-payment-proofs",
        generated_key=f"portal-payment-proof-uploaded-{attachment.id}",
        metadata={
            "attachment_id": attachment.id,
            "uploaded_by": getattr(user, "id", None),
            "mutation_scope": "NOTIFICATION_ONLY",
        },
        commit=False,
    )


def _notify_finance_draft_payment_proof_uploaded(user, draft: PortalOrderDraft, attachment: DigitalAttachment) -> None:
    create_or_update_notification(
        branch_id=draft.branch_id,
        notification_type="PORTAL_DRAFT_PAYMENT_PROOF",
        title=f"Bukti pembayaran awal draft #{draft.id}",
        message=(
            f"User portal mengunggah bukti pembayaran awal untuk draft order "
            f"{draft.order_date.strftime('%d-%m-%Y') if draft.order_date else '-'} "
            f"{draft.meal_type} {draft.portion_qty} porsi. Finance perlu verifikasi."
        ),
        target_role="FINANCE",
        priority="WARNING",
        reference_type=PORTAL_DRAFT_PAYMENT_REFERENCE_TYPE,
        reference_id=draft.id,
        action_url="/finance/portal-payment-proofs",
        generated_key=f"portal-draft-payment-proof-uploaded-{attachment.id}",
        metadata={
            "attachment_id": attachment.id,
            "draft_id": draft.id,
            "uploaded_by": getattr(user, "id", None),
            "mutation_scope": "NOTIFICATION_ONLY",
        },
        commit=False,
    )


def list_pending_portal_payment_proofs(*, branch_id: int | None = None) -> list[DigitalAttachment]:
    """Small read helper for the next finance verification queue batch."""
    query = DigitalAttachment.query.filter_by(
        module=PORTAL_PAYMENT_MODULE,
        attachment_type=PAYMENT_PROOF_PENDING_TYPE,
        is_deleted=False,
    )
    if branch_id is not None:
        query = query.filter(DigitalAttachment.branch_id == branch_id)
    return query.order_by(DigitalAttachment.created_at.asc(), DigitalAttachment.id.asc()).all()
