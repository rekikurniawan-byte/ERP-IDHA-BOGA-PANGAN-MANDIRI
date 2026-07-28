from __future__ import annotations

from app.extensions import db
from app.models.system import DigitalAttachment
from app.services.atomic_transaction_service import atomic_business_action
from app.services.audit_log_service import record_audit_log
from app.services.customer_contract_service import CustomerContractError, get_customer_contract
from app.services.digital_attachment_service import stage_digital_attachment


CUSTOMER_CONTRACT_DOCUMENT_MODULE = "CUSTOMER_CONTRACT"
CUSTOMER_CONTRACT_REFERENCE_TYPE = "CUSTOMER_CONTRACT"
CONTRACT_DOCUMENT_TYPE = "CONTRACT_DOCUMENT"
CONTRACT_AMENDMENT_TYPE = "CONTRACT_AMENDMENT"
CONTRACT_TERMINATION_TYPE = "CONTRACT_TERMINATION"

ALLOWED_CONTRACT_ATTACHMENT_TYPES = {
    CONTRACT_DOCUMENT_TYPE,
    CONTRACT_AMENDMENT_TYPE,
    CONTRACT_TERMINATION_TYPE,
}


class CustomerContractDocumentError(ValueError):
    pass


def attach_customer_contract_document(
    *,
    contract_id: int,
    branch_id: int,
    file_storage,
    uploaded_by: int | None,
    attachment_type: str = CONTRACT_DOCUMENT_TYPE,
    notes: str | None = None,
    commit: bool = True,
) -> DigitalAttachment:
    """Attach a private document to an existing customer contract.

    This service only archives the file metadata through DigitalAttachment. It
    does not alter contract status, payment terms, credit limit, or numbering.
    """
    contract = _get_contract_or_raise(contract_id, branch_id)
    attachment_type = _normalize_attachment_type(attachment_type)

    if commit:
        with atomic_business_action(
            module=CUSTOMER_CONTRACT_DOCUMENT_MODULE,
            action="CUSTOMER_CONTRACT_DOCUMENT_ATTACHED",
            description=f"Attach document to customer contract {contract.contract_number}.",
            reference_type=CUSTOMER_CONTRACT_REFERENCE_TYPE,
            reference_id=contract.id,
            user_id=uploaded_by,
            branch_id=contract.branch_id,
            severity="MEDIUM",
            metadata={
                "contract_number": contract.contract_number,
                "attachment_type": attachment_type,
                "mutation_scope": "ATTACHMENT_ONLY",
            },
        ) as boundary:
            attachment = _stage_contract_document(contract, file_storage, uploaded_by, attachment_type, notes)
            boundary.track_attachment(attachment)
            db.session.flush()
            _record_contract_document_audit(contract, attachment, uploaded_by)
    else:
        attachment = _stage_contract_document(contract, file_storage, uploaded_by, attachment_type, notes)
        db.session.flush()
        _record_contract_document_audit(contract, attachment, uploaded_by)

    return attachment


def list_customer_contract_documents(
    *,
    contract_id: int,
    branch_id: int,
    attachment_type: str | None = None,
    include_deleted: bool = False,
) -> list[DigitalAttachment]:
    contract = _get_contract_or_raise(contract_id, branch_id)
    query = DigitalAttachment.query.filter(
        DigitalAttachment.branch_id == contract.branch_id,
        DigitalAttachment.module == CUSTOMER_CONTRACT_DOCUMENT_MODULE,
        DigitalAttachment.reference_type == CUSTOMER_CONTRACT_REFERENCE_TYPE,
        DigitalAttachment.reference_id == contract.id,
    )
    if attachment_type:
        query = query.filter(DigitalAttachment.attachment_type == _normalize_attachment_type(attachment_type))
    if not include_deleted:
        query = query.filter(DigitalAttachment.is_deleted.is_(False))
    return query.order_by(DigitalAttachment.created_at.desc(), DigitalAttachment.id.desc()).all()


def get_customer_contract_document(*, attachment_id: int, branch_id: int) -> DigitalAttachment | None:
    attachment = DigitalAttachment.query.filter(
        DigitalAttachment.id == attachment_id,
        DigitalAttachment.branch_id == branch_id,
        DigitalAttachment.module == CUSTOMER_CONTRACT_DOCUMENT_MODULE,
        DigitalAttachment.reference_type == CUSTOMER_CONTRACT_REFERENCE_TYPE,
        DigitalAttachment.is_deleted.is_(False),
    ).first()
    if not attachment:
        return None
    if not get_customer_contract(attachment.reference_id, branch_id=branch_id):
        return None
    return attachment


def _stage_contract_document(contract, file_storage, uploaded_by: int | None, attachment_type: str, notes: str | None) -> DigitalAttachment:
    return stage_digital_attachment(
        file_storage=file_storage,
        module=CUSTOMER_CONTRACT_DOCUMENT_MODULE,
        reference_type=CUSTOMER_CONTRACT_REFERENCE_TYPE,
        reference_id=contract.id,
        attachment_type=attachment_type,
        branch_id=contract.branch_id,
        uploaded_by=uploaded_by,
        notes=_contract_document_notes(attachment_type, notes),
    )


def _record_contract_document_audit(contract, attachment: DigitalAttachment, uploaded_by: int | None) -> None:
    record_audit_log(
        module="CONTRACT",
        event_type="CUSTOMER_CONTRACT_DOCUMENT_ATTACHED",
        action="CREATE",
        table_name="digital_attachments",
        record_id=attachment.id,
        description=f"Dokumen kontrak customer diarsipkan: {contract.contract_number}.",
        metadata={
            "contract_id": contract.id,
            "contract_number": contract.contract_number,
            "attachment_type": attachment.attachment_type,
            "original_filename": attachment.original_filename,
            "file_size": attachment.file_size,
            "sha256": attachment.sha256_hash,
            "mutation_scope": "ATTACHMENT_ONLY",
        },
        user_id=uploaded_by,
        branch_id=contract.branch_id,
        commit=False,
    )


def _get_contract_or_raise(contract_id: int, branch_id: int):
    contract = get_customer_contract(contract_id, branch_id=branch_id)
    if not contract:
        raise CustomerContractDocumentError("Kontrak customer tidak ditemukan untuk branch ini.")
    return contract


def _normalize_attachment_type(attachment_type: str) -> str:
    normalized = str(attachment_type or "").strip().upper()
    if normalized not in ALLOWED_CONTRACT_ATTACHMENT_TYPES:
        allowed = ", ".join(sorted(ALLOWED_CONTRACT_ATTACHMENT_TYPES))
        raise CustomerContractDocumentError(f"Tipe dokumen kontrak tidak valid. Pilihan: {allowed}.")
    return normalized


def _contract_document_notes(attachment_type: str, notes: str | None) -> str:
    clean = str(notes or "").strip()
    prefix = attachment_type
    return f"{prefix}: {clean}" if clean else prefix
