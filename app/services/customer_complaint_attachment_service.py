from __future__ import annotations

from app.extensions import db
from app.models.system import DigitalAttachment
from app.services.atomic_transaction_service import atomic_business_action
from app.services.audit_log_service import record_audit_log
from app.services.customer_complaint_service import CustomerComplaintError, get_customer_complaint
from app.services.digital_attachment_service import stage_digital_attachment


CUSTOMER_COMPLAINT_ATTACHMENT_MODULE = "CUSTOMER_COMPLAINT"
CUSTOMER_COMPLAINT_REFERENCE_TYPE = "CUSTOMER_COMPLAINT"
COMPLAINT_EVIDENCE_TYPE = "COMPLAINT_EVIDENCE"
COMPLAINT_RESOLUTION_EVIDENCE_TYPE = "COMPLAINT_RESOLUTION_EVIDENCE"

ALLOWED_COMPLAINT_ATTACHMENT_TYPES = {
    COMPLAINT_EVIDENCE_TYPE,
    COMPLAINT_RESOLUTION_EVIDENCE_TYPE,
}


class CustomerComplaintAttachmentError(ValueError):
    pass


def attach_customer_complaint_evidence(
    *,
    complaint_id: int,
    branch_id: int,
    file_storage,
    uploaded_by: int | None,
    attachment_type: str = COMPLAINT_EVIDENCE_TYPE,
    notes: str | None = None,
    commit: bool = True,
) -> DigitalAttachment:
    complaint = _get_complaint_or_raise(complaint_id, branch_id)
    attachment_type = _normalize_attachment_type(attachment_type)

    boundary = (
        atomic_business_action(
            module=CUSTOMER_COMPLAINT_ATTACHMENT_MODULE,
            action="CUSTOMER_COMPLAINT_EVIDENCE_ATTACHED",
            description=f"Attach evidence to customer complaint {complaint.complaint_number}.",
            reference_type=CUSTOMER_COMPLAINT_REFERENCE_TYPE,
            reference_id=complaint.id,
            user_id=uploaded_by,
            branch_id=complaint.branch_id,
            severity="MEDIUM",
            metadata={
                "complaint_number": complaint.complaint_number,
                "attachment_type": attachment_type,
                "mutation_scope": "ATTACHMENT_ONLY",
            },
        )
        if commit
        else _NullContext()
    )

    with boundary:
        attachment = stage_digital_attachment(
            file_storage=file_storage,
            module=CUSTOMER_COMPLAINT_ATTACHMENT_MODULE,
            reference_type=CUSTOMER_COMPLAINT_REFERENCE_TYPE,
            reference_id=complaint.id,
            attachment_type=attachment_type,
            branch_id=complaint.branch_id,
            uploaded_by=uploaded_by,
            notes=_evidence_notes(attachment_type, notes),
        )
        if commit:
            boundary.track_attachment(attachment)
        db.session.flush()
        _record_complaint_attachment_audit(complaint, attachment, uploaded_by)
    return attachment


def list_customer_complaint_evidence(
    *,
    complaint_id: int,
    branch_id: int,
    attachment_type: str | None = None,
    include_deleted: bool = False,
) -> list[DigitalAttachment]:
    complaint = _get_complaint_or_raise(complaint_id, branch_id)
    query = DigitalAttachment.query.filter(
        DigitalAttachment.branch_id == complaint.branch_id,
        DigitalAttachment.module == CUSTOMER_COMPLAINT_ATTACHMENT_MODULE,
        DigitalAttachment.reference_type == CUSTOMER_COMPLAINT_REFERENCE_TYPE,
        DigitalAttachment.reference_id == complaint.id,
    )
    if attachment_type:
        query = query.filter(DigitalAttachment.attachment_type == _normalize_attachment_type(attachment_type))
    if not include_deleted:
        query = query.filter(DigitalAttachment.is_deleted.is_(False))
    return query.order_by(DigitalAttachment.created_at.desc(), DigitalAttachment.id.desc()).all()


def _get_complaint_or_raise(complaint_id: int, branch_id: int):
    complaint = get_customer_complaint(complaint_id, branch_id=branch_id)
    if not complaint:
        raise CustomerComplaintAttachmentError("Complaint customer tidak ditemukan untuk branch ini.")
    return complaint


def _normalize_attachment_type(attachment_type: str) -> str:
    normalized = str(attachment_type or "").strip().upper()
    if normalized not in ALLOWED_COMPLAINT_ATTACHMENT_TYPES:
        allowed = ", ".join(sorted(ALLOWED_COMPLAINT_ATTACHMENT_TYPES))
        raise CustomerComplaintAttachmentError(f"Tipe bukti complaint tidak valid. Pilihan: {allowed}.")
    return normalized


def _evidence_notes(attachment_type: str, notes: str | None) -> str:
    clean = str(notes or "").strip()
    return f"{attachment_type}: {clean}" if clean else attachment_type


def _record_complaint_attachment_audit(complaint, attachment: DigitalAttachment, uploaded_by: int | None) -> None:
    record_audit_log(
        module="COMPLAINT",
        event_type="CUSTOMER_COMPLAINT_EVIDENCE_ATTACHED",
        action="CREATE",
        table_name="digital_attachments",
        record_id=attachment.id,
        description=f"Bukti complaint customer diarsipkan: {complaint.complaint_number}.",
        metadata={
            "complaint_id": complaint.id,
            "complaint_number": complaint.complaint_number,
            "attachment_type": attachment.attachment_type,
            "original_filename": attachment.original_filename,
            "file_size": attachment.file_size,
            "sha256": attachment.sha256_hash,
            "mutation_scope": "ATTACHMENT_ONLY",
        },
        user_id=uploaded_by,
        branch_id=complaint.branch_id,
        commit=False,
    )


class _NullContext:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False
