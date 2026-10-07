from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.models.system import DigitalAttachment, PortalOrderDraft, PortalPaymentProofClaim
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


def _validate_and_save_claim(
    *,
    attachment: DigitalAttachment,
    draft: PortalOrderDraft,
    claimed_amount: Any = None,
    sender_name: str | None = None,
    transfer_reference: str | None = None,
) -> PortalPaymentProofClaim | None:
    # 1. Satu bukti aktif per draft:
    existing_active = (
        DigitalAttachment.query.filter(
            DigitalAttachment.id != attachment.id,
            DigitalAttachment.module == PORTAL_PAYMENT_MODULE,
            DigitalAttachment.reference_type == PORTAL_DRAFT_PAYMENT_REFERENCE_TYPE,
            DigitalAttachment.reference_id == draft.id,
            DigitalAttachment.is_deleted.is_(False),
            DigitalAttachment.attachment_type.in_(["PAYMENT_PROOF_PENDING", "PAYMENT_PROOF_VERIFIED"]),
        ).first()
    )
    if existing_active:
        raise PortalPaymentProofError("Bukti sebelumnya masih diperiksa admin. Tunggu hasilnya dulu.")

    # 2. Duplikat file (sha256_hash sama di cabang sama, bukan REJECTED):
    if attachment.sha256_hash:
        dup_file = (
            DigitalAttachment.query.filter(
                DigitalAttachment.id != attachment.id,
                DigitalAttachment.module == PORTAL_PAYMENT_MODULE,
                DigitalAttachment.branch_id == draft.branch_id,
                DigitalAttachment.is_deleted.is_(False),
                DigitalAttachment.sha256_hash == attachment.sha256_hash,
                DigitalAttachment.attachment_type != "PAYMENT_PROOF_REJECTED",
            ).first()
        )
        if dup_file:
            raise PortalPaymentProofError("File bukti ini sudah pernah diunggah sebelumnya. Unggah bukti transfer yang benar.")

    # 3. Duplikat no. referensi (cabang sama, attachment bukan REJECTED):
    clean_ref = str(transfer_reference or "").strip().upper() or None
    if clean_ref:
        dup_ref = (
            PortalPaymentProofClaim.query
            .join(DigitalAttachment, PortalPaymentProofClaim.attachment_id == DigitalAttachment.id)
            .filter(
                PortalPaymentProofClaim.branch_id == draft.branch_id,
                PortalPaymentProofClaim.transfer_reference == clean_ref,
                DigitalAttachment.is_deleted.is_(False),
                DigitalAttachment.attachment_type != "PAYMENT_PROOF_REJECTED",
                PortalPaymentProofClaim.attachment_id != attachment.id,
            ).first()
        )
        if dup_ref:
            raise PortalPaymentProofError("No. referensi ini sudah dipakai untuk bukti lain.")

    # 4. Simpan klaim jika claimed_amount diberikan:
    claim = None
    if claimed_amount is not None and str(claimed_amount).strip() != "":
        try:
            claimed_val = Decimal(str(claimed_amount).strip())
        except Exception:
            raise PortalPaymentProofError("Nominal yang diklaim tidak valid.")
        if claimed_val <= Decimal("0"):
            raise PortalPaymentProofError("Nominal pembayaran harus lebih besar dari 0.")

        clean_sender = str(sender_name or "").strip()
        if not clean_sender:
            raise PortalPaymentProofError("Nama pemilik rekening pengirim wajib diisi.")
        if len(clean_sender) > 120:
            raise PortalPaymentProofError("Nama pemilik rekening pengirim maksimal 120 karakter.")

        claim = PortalPaymentProofClaim(
            attachment_id=attachment.id,
            branch_id=draft.branch_id,
            claimed_amount=claimed_val,
            sender_name=clean_sender,
            transfer_reference=clean_ref,
        )
        db.session.add(claim)
        db.session.flush()

    return claim


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
    claimed_amount: Any = None,
    sender_name: str | None = None,
    transfer_reference: str | None = None,
) -> dict:
    """Upload prepayment proof for a portal order draft without creating invoice/payment rows."""
    draft = PortalOrderDraft.query.filter_by(id=draft_id, user_id=getattr(user, "id", None)).first()
    if not draft:
        raise PortalPaymentProofError("Draft order tidak ditemukan untuk user portal ini.")
    if draft.status != "PENDING_ADMIN_CONFIRMATION":
        raise PortalPaymentProofError("Bukti pembayaran awal hanya dapat diunggah untuk draft yang masih menunggu admin.")

    from app.services.portal_order_draft_service import session_closed_reason

    closed_reason = session_closed_reason(
        draft.branch_id,
        draft.order_date,
        draft.meal_type,
        client_id=draft.client_id,
        location_id=draft.delivery_location_id,
    )
    if closed_reason:
        raise PortalPaymentProofError("Pesanan ini sudah lewat batas waktu dan tidak bisa diproses. Hubungi admin.")

    claim = None
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
            claim = _validate_and_save_claim(
                attachment=attachment,
                draft=draft,
                claimed_amount=claimed_amount,
                sender_name=sender_name,
                transfer_reference=transfer_reference,
            )
            _notify_finance_draft_payment_proof_uploaded(user, draft, attachment)
    else:
        attachment = _stage_draft_payment_proof_attachment(user, draft, file_storage, notes)
        try:
            db.session.flush()
            claim = _validate_and_save_claim(
                attachment=attachment,
                draft=draft,
                claimed_amount=claimed_amount,
                sender_name=sender_name,
                transfer_reference=transfer_reference,
            )
            _notify_finance_draft_payment_proof_uploaded(user, draft, attachment)
        except Exception:
            from app.services.digital_attachment_service import get_upload_root
            upload_root = get_upload_root().resolve()
            relative = getattr(attachment, "file_path", None)
            if relative:
                path = (upload_root / relative).resolve()
                if path.exists() and path.is_file():
                    path.unlink()
            raise

    return {
        "uploaded": True,
        "status": "PENDING_FINANCE_VERIFICATION",
        "draft_id": draft.id,
        "attachment_id": attachment.id,
        "attachment_type": attachment.attachment_type,
        "payment_created": False,
        "invoice_created": False,
        "mutation_scope": "ATTACHMENT_ONLY",
        "claim_id": claim.id if claim else None,
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
        target_role="ADMIN",
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
        target_role="ADMIN",
        priority="WARNING",
        reference_type=PORTAL_DRAFT_PAYMENT_REFERENCE_TYPE,
        reference_id=draft.id,
        action_url="/finance/payment-inbox",
        generated_key=f"portal-draft-payment-proof-uploaded-{attachment.id}",
        metadata={
            "attachment_id": attachment.id,
            "draft_id": draft.id,
            "uploaded_by": getattr(user, "id", None),
            "mutation_scope": "NOTIFICATION_ONLY",
        },
        commit=False,
    )


