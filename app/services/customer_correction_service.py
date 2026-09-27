from __future__ import annotations

from datetime import date, datetime

from app.extensions import db
from app.models.complaint import CustomerComplaint
from app.models.correction import CustomerCorrection
from app.models.delivery import Delivery
from app.models.finance import Invoice
from app.models.master import Client, Mandor, User
from app.models.operational import DailyOrder
from app.services.atomic_transaction_service import atomic_business_action
from app.services.audit_log_service import record_audit_log
from app.services.business_logic_guard_service import decimal_money
from app.utils.terms import T


CORRECTION_TYPE_RETURN = "RETURN"
CORRECTION_TYPE_CORRECTION = "CORRECTION"
CORRECTION_TYPE_COMPENSATION = "COMPENSATION"
CORRECTION_TYPES = {
    CORRECTION_TYPE_RETURN,
    CORRECTION_TYPE_CORRECTION,
    CORRECTION_TYPE_COMPENSATION,
}

CORRECTION_STATUS_DRAFT = "DRAFT"
CORRECTION_STATUS_SUBMITTED = "SUBMITTED"
CORRECTION_STATUS_APPROVED = "APPROVED"
CORRECTION_STATUS_REJECTED = "REJECTED"
CORRECTION_STATUS_CLOSED = "CLOSED"
CORRECTION_STATUS_CANCELLED = "CANCELLED"
CORRECTION_STATUSES = {
    CORRECTION_STATUS_DRAFT,
    CORRECTION_STATUS_SUBMITTED,
    CORRECTION_STATUS_APPROVED,
    CORRECTION_STATUS_REJECTED,
    CORRECTION_STATUS_CLOSED,
    CORRECTION_STATUS_CANCELLED,
}

EFFECT_NONE = "NONE"
EFFECT_PENDING = "PENDING"
EFFECT_POSTED = "POSTED"
EFFECT_NOT_APPLICABLE = "NOT_APPLICABLE"
EFFECT_STATUSES = {EFFECT_NONE, EFFECT_PENDING, EFFECT_POSTED, EFFECT_NOT_APPLICABLE}


class CustomerCorrectionError(ValueError):
    pass


def generate_customer_correction_number(correction_date: date | None = None) -> str:
    correction_date = correction_date or date.today()
    prefix = f"CRC-{correction_date.strftime('%Y%m%d')}"
    counter = CustomerCorrection.query.filter(CustomerCorrection.correction_number.like(f"{prefix}-%")).count() + 1
    while True:
        number = f"{prefix}-{counter:03d}"
        if not CustomerCorrection.query.filter_by(correction_number=number).first():
            return number
        counter += 1


def create_customer_correction(
    *,
    branch_id: int,
    correction_type: str,
    reason: str,
    proposed_action: str,
    submitted_by: int,
    correction_amount=0,
    complaint_id: int | None = None,
    client_id: int | None = None,
    mandor_id: int | None = None,
    order_id: int | None = None,
    delivery_id: int | None = None,
    invoice_id: int | None = None,
    stock_effect: str = EFFECT_NONE,
    financial_effect: str = EFFECT_NONE,
    notes: str | None = None,
    status: str = CORRECTION_STATUS_DRAFT,
    commit: bool = True,
) -> CustomerCorrection:
    _assert_branch_id(branch_id)
    _assert_user_in_branch(submitted_by, branch_id)
    correction_type = _normalize_correction_type(correction_type)
    status = _normalize_status(status)
    if status not in {CORRECTION_STATUS_DRAFT, CORRECTION_STATUS_SUBMITTED}:
        raise CustomerCorrectionError("Koreksi baru hanya boleh DRAFT atau SUBMITTED.")
    stock_effect = _normalize_effect(stock_effect)
    financial_effect = _normalize_effect(financial_effect)
    _assert_reference_scope(
        branch_id=branch_id,
        complaint_id=complaint_id,
        client_id=client_id,
        mandor_id=mandor_id,
        order_id=order_id,
        delivery_id=delivery_id,
        invoice_id=invoice_id,
    )

    correction = CustomerCorrection(
        branch_id=branch_id,
        correction_number=generate_customer_correction_number(),
        correction_type=correction_type,
        status=status,
        complaint_id=complaint_id,
        order_id=order_id,
        delivery_id=delivery_id,
        invoice_id=invoice_id,
        client_id=client_id,
        mandor_id=mandor_id,
        reason=_required_text(reason, "Alasan koreksi"),
        proposed_action=_required_text(proposed_action, "Rencana tindakan"),
        correction_amount=decimal_money(correction_amount, label="Nominal koreksi"),
        stock_effect=stock_effect,
        financial_effect=financial_effect,
        submitted_by=submitted_by,
        submitted_at=datetime.utcnow() if status == CORRECTION_STATUS_SUBMITTED else None,
        notes=_optional_text(notes),
    )

    boundary = (
        atomic_business_action(
            module="CUSTOMER_CORRECTION",
            action="CUSTOMER_CORRECTION_CREATE",
            description="Create customer correction request.",
            reference_type="customer_corrections",
            user_id=submitted_by,
            branch_id=branch_id,
            severity="MEDIUM",
            metadata={
                "correction_type": correction_type,
                "status": status,
                "mutation_scope": "CORRECTION_REQUEST_ONLY",
            },
        )
        if commit
        else _NullContext()
    )

    with boundary:
        db.session.add(correction)
        db.session.flush()
        _record_correction_audit(
            correction,
            event_type="CUSTOMER_CORRECTION_CREATED",
            action="CREATE",
            user_id=submitted_by,
            description=f"Request koreksi customer dibuat: {correction.correction_number}.",
        )

    return correction


def submit_customer_correction(
    correction_id: int,
    *,
    branch_id: int,
    submitted_by: int,
    commit: bool = True,
) -> CustomerCorrection:
    correction = _get_correction_or_raise(correction_id, branch_id)
    if correction.status != CORRECTION_STATUS_DRAFT:
        raise CustomerCorrectionError("Hanya koreksi DRAFT yang bisa diajukan.")
    _assert_user_in_branch(submitted_by, branch_id)

    boundary = (
        atomic_business_action(
            module="CUSTOMER_CORRECTION",
            action="CUSTOMER_CORRECTION_SUBMIT",
            description=f"Submit customer correction {correction.correction_number}.",
            reference_type="customer_corrections",
            reference_id=correction.id,
            user_id=submitted_by,
            branch_id=branch_id,
            severity="MEDIUM",
            metadata={"old_status": correction.status, "new_status": CORRECTION_STATUS_SUBMITTED},
        )
        if commit
        else _NullContext()
    )

    with boundary:
        correction.status = CORRECTION_STATUS_SUBMITTED
        correction.submitted_at = datetime.utcnow()
        db.session.flush()
        _record_correction_audit(
            correction,
            event_type="CUSTOMER_CORRECTION_SUBMITTED",
            action="UPDATE",
            user_id=submitted_by,
            description=f"Request koreksi customer diajukan: {correction.correction_number}.",
        )

    return correction


def get_customer_correction(correction_id: int, *, branch_id: int) -> CustomerCorrection | None:
    return CustomerCorrection.query.filter_by(id=correction_id, branch_id=branch_id).first()


def list_customer_corrections(
    branch_id: int,
    *,
    status: str = "ALL",
    correction_type: str | None = None,
    limit: int = 200,
) -> list[CustomerCorrection]:
    query = CustomerCorrection.query.filter_by(branch_id=branch_id)
    if status and status != "ALL":
        query = query.filter(CustomerCorrection.status == _normalize_status(status))
    if correction_type:
        query = query.filter(CustomerCorrection.correction_type == _normalize_correction_type(correction_type))
    try:
        limit = max(1, min(int(limit), 500))
    except (TypeError, ValueError):
        limit = 200
    return query.order_by(CustomerCorrection.created_at.desc(), CustomerCorrection.id.desc()).limit(limit).all()


def _get_correction_or_raise(correction_id: int, branch_id: int) -> CustomerCorrection:
    correction = get_customer_correction(correction_id, branch_id=branch_id)
    if not correction:
        raise CustomerCorrectionError("Request koreksi customer tidak ditemukan.")
    return correction


def _assert_reference_scope(
    *,
    branch_id: int,
    complaint_id: int | None,
    client_id: int | None,
    mandor_id: int | None,
    order_id: int | None,
    delivery_id: int | None,
    invoice_id: int | None,
) -> None:
    if complaint_id:
        complaint = CustomerComplaint.query.filter_by(id=complaint_id, branch_id=branch_id).first()
        if not complaint:
            raise CustomerCorrectionError("Complaint referensi tidak ditemukan untuk branch ini.")
        if client_id and complaint.client_id and complaint.client_id != client_id:
            raise CustomerCorrectionError(f"Complaint tidak sesuai {T.client_lower}.")
        if mandor_id and complaint.mandor_id and complaint.mandor_id != mandor_id:
            raise CustomerCorrectionError(f"Complaint tidak sesuai {T.sub_client_lower}.")
    if client_id and not Client.query.filter_by(id=client_id).first():
        raise CustomerCorrectionError(f"{T.client} koreksi tidak ditemukan.")
    if mandor_id:
        mandor = Mandor.query.filter_by(id=mandor_id, branch_id=branch_id).first()
        if not mandor:
            raise CustomerCorrectionError(f"{T.sub_client} koreksi tidak ditemukan untuk branch ini.")
        if client_id and mandor.client_id != client_id:
            raise CustomerCorrectionError(f"{T.sub_client} koreksi tidak sesuai {T.client_lower}.")
    if order_id and not DailyOrder.query.filter_by(id=order_id, branch_id=branch_id).first():
        raise CustomerCorrectionError("Order koreksi tidak ditemukan untuk branch ini.")
    if delivery_id and not Delivery.query.filter_by(id=delivery_id, branch_id=branch_id).first():
        raise CustomerCorrectionError("Delivery koreksi tidak ditemukan untuk branch ini.")
    if invoice_id:
        invoice = Invoice.query.filter_by(id=invoice_id, branch_id=branch_id).first()
        if not invoice:
            raise CustomerCorrectionError("Invoice koreksi tidak ditemukan untuk branch ini.")
        if client_id and invoice.client_id and invoice.client_id != client_id:
            raise CustomerCorrectionError(f"Invoice koreksi tidak sesuai {T.client_lower}.")
        if mandor_id and invoice.mandor_id and invoice.mandor_id != mandor_id:
            raise CustomerCorrectionError(f"Invoice koreksi tidak sesuai {T.sub_client_lower}.")


def _assert_user_in_branch(user_id: int, branch_id: int) -> None:
    if not User.query.filter_by(id=user_id, branch_id=branch_id, is_active=True).first():
        raise CustomerCorrectionError("User koreksi tidak valid untuk branch ini.")


def _assert_branch_id(branch_id: int) -> None:
    if not branch_id:
        raise CustomerCorrectionError("Branch koreksi wajib diisi.")


def _normalize_correction_type(correction_type: str) -> str:
    normalized = str(correction_type or "").strip().upper()
    if normalized not in CORRECTION_TYPES:
        allowed = ", ".join(sorted(CORRECTION_TYPES))
        raise CustomerCorrectionError(f"Tipe koreksi tidak valid. Pilihan: {allowed}.")
    return normalized


def _normalize_status(status: str) -> str:
    normalized = str(status or "").strip().upper()
    if normalized not in CORRECTION_STATUSES:
        allowed = ", ".join(sorted(CORRECTION_STATUSES))
        raise CustomerCorrectionError(f"Status koreksi tidak valid. Pilihan: {allowed}.")
    return normalized


def _normalize_effect(effect: str) -> str:
    normalized = str(effect or "").strip().upper()
    if normalized not in EFFECT_STATUSES:
        allowed = ", ".join(sorted(EFFECT_STATUSES))
        raise CustomerCorrectionError(f"Status efek koreksi tidak valid. Pilihan: {allowed}.")
    return normalized


def _required_text(value: object, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise CustomerCorrectionError(f"{label} wajib diisi.")
    return text


def _optional_text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _record_correction_audit(
    correction: CustomerCorrection,
    *,
    event_type: str,
    action: str,
    user_id: int,
    description: str,
) -> None:
    record_audit_log(
        module="CUSTOMER_CORRECTION",
        event_type=event_type,
        action=action,
        table_name="customer_corrections",
        record_id=correction.id,
        description=description,
        metadata={
            "correction_number": correction.correction_number,
            "correction_type": correction.correction_type,
            "status": correction.status,
            "stock_effect": correction.stock_effect,
            "financial_effect": correction.financial_effect,
            "mutation_scope": "CORRECTION_REQUEST_ONLY",
        },
        user_id=user_id,
        branch_id=correction.branch_id,
        commit=False,
    )


class _NullContext:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False
