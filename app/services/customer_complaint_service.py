from __future__ import annotations

from datetime import date, datetime

from app.extensions import db
from app.models.complaint import CustomerComplaint
from app.models.delivery import Delivery
from app.models.finance import Invoice
from app.models.master import Client, Mandor, User
from app.models.operational import DailyOrder
from app.services.atomic_transaction_service import atomic_business_action
from app.services.audit_log_service import record_audit_log
from app.utils.terms import T


COMPLAINT_CATEGORY_FOOD_SHORTAGE = "FOOD_SHORTAGE"
COMPLAINT_CATEGORY_DAMAGED_FOOD = "DAMAGED_FOOD"
COMPLAINT_CATEGORY_WRONG_MENU = "WRONG_MENU"
COMPLAINT_CATEGORY_LATE_DELIVERY = "LATE_DELIVERY"
COMPLAINT_CATEGORY_PORTION_SHORTAGE = "PORTION_SHORTAGE"
COMPLAINT_CATEGORY_OTHER = "OTHER"

COMPLAINT_CATEGORIES = {
    COMPLAINT_CATEGORY_FOOD_SHORTAGE,
    COMPLAINT_CATEGORY_DAMAGED_FOOD,
    COMPLAINT_CATEGORY_WRONG_MENU,
    COMPLAINT_CATEGORY_LATE_DELIVERY,
    COMPLAINT_CATEGORY_PORTION_SHORTAGE,
    COMPLAINT_CATEGORY_OTHER,
}

COMPLAINT_STATUS_OPEN = "OPEN"
COMPLAINT_STATUS_IN_PROGRESS = "IN_PROGRESS"
COMPLAINT_STATUS_RESOLVED = "RESOLVED"
COMPLAINT_STATUS_CLOSED = "CLOSED"

COMPLAINT_STATUSES = {
    COMPLAINT_STATUS_OPEN,
    COMPLAINT_STATUS_IN_PROGRESS,
    COMPLAINT_STATUS_RESOLVED,
    COMPLAINT_STATUS_CLOSED,
}

ALLOWED_COMPLAINT_TRANSITIONS = {
    COMPLAINT_STATUS_OPEN: {COMPLAINT_STATUS_IN_PROGRESS},
    COMPLAINT_STATUS_IN_PROGRESS: {COMPLAINT_STATUS_RESOLVED},
    COMPLAINT_STATUS_RESOLVED: {COMPLAINT_STATUS_CLOSED},
    COMPLAINT_STATUS_CLOSED: set(),
}


class CustomerComplaintError(ValueError):
    pass


def generate_customer_complaint_number(complaint_date: date | None = None) -> str:
    complaint_date = complaint_date or date.today()
    prefix = f"CMP-{complaint_date.strftime('%Y%m%d')}"
    counter = CustomerComplaint.query.filter(CustomerComplaint.complaint_number.like(f"{prefix}-%")).count() + 1
    while True:
        number = f"{prefix}-{counter:03d}"
        if not CustomerComplaint.query.filter_by(complaint_number=number).first():
            return number
        counter += 1


def submit_customer_complaint(
    *,
    branch_id: int,
    category: str,
    title: str,
    description: str,
    submitted_by: int,
    client_id: int | None = None,
    mandor_id: int | None = None,
    order_id: int | None = None,
    delivery_id: int | None = None,
    invoice_id: int | None = None,
    assigned_to: int | None = None,
    submitted_at: datetime | None = None,
    commit: bool = True,
) -> CustomerComplaint:
    category = _normalize_category(category)
    _assert_branch_id(branch_id)
    _assert_user_in_branch(submitted_by, branch_id, "User submit complaint")
    if assigned_to is not None:
        _assert_user_in_branch(assigned_to, branch_id, "User penanggung jawab complaint")
    _assert_reference_scope(
        branch_id=branch_id,
        client_id=client_id,
        mandor_id=mandor_id,
        order_id=order_id,
        delivery_id=delivery_id,
        invoice_id=invoice_id,
    )

    complaint = CustomerComplaint(
        branch_id=branch_id,
        complaint_number=generate_customer_complaint_number((submitted_at or datetime.utcnow()).date()),
        category=category,
        status=COMPLAINT_STATUS_OPEN,
        title=_required_text(title, "Judul complaint"),
        description=_required_text(description, "Deskripsi complaint"),
        client_id=client_id,
        mandor_id=mandor_id,
        order_id=order_id,
        delivery_id=delivery_id,
        invoice_id=invoice_id,
        submitted_by=submitted_by,
        assigned_to=assigned_to,
        submitted_at=submitted_at or datetime.utcnow(),
    )

    boundary = (
        atomic_business_action(
            module="COMPLAINT",
            action="CUSTOMER_COMPLAINT_SUBMIT",
            description="Submit customer complaint.",
            reference_type="customer_complaints",
            user_id=submitted_by,
            branch_id=branch_id,
            severity="MEDIUM",
            metadata={"category": category, "mutation_scope": "COMPLAINT_ONLY"},
        )
        if commit
        else _NullContext()
    )

    with boundary:
        db.session.add(complaint)
        db.session.flush()
        _record_complaint_audit(
            complaint,
            event_type="CUSTOMER_COMPLAINT_SUBMITTED",
            action="CREATE",
            user_id=submitted_by,
            description=f"Complaint customer dibuat: {complaint.complaint_number}.",
        )
    return complaint


def transition_customer_complaint(
    complaint_id: int,
    *,
    branch_id: int,
    new_status: str,
    updated_by: int,
    assigned_to: int | None = None,
    resolution_note: str | None = None,
    commit: bool = True,
) -> CustomerComplaint:
    complaint = _get_complaint_or_raise(complaint_id, branch_id)
    new_status = _normalize_status(new_status)
    if new_status not in ALLOWED_COMPLAINT_TRANSITIONS.get(complaint.status, set()):
        raise CustomerComplaintError(f"Transisi complaint {complaint.status} -> {new_status} tidak valid.")
    _assert_user_in_branch(updated_by, branch_id, "User update complaint")
    if assigned_to is not None:
        _assert_user_in_branch(assigned_to, branch_id, "User penanggung jawab complaint")
    if new_status == COMPLAINT_STATUS_RESOLVED and not str(resolution_note or "").strip():
        raise CustomerComplaintError("Catatan resolusi wajib diisi saat complaint diselesaikan.")

    boundary = (
        atomic_business_action(
            module="COMPLAINT",
            action=f"CUSTOMER_COMPLAINT_{new_status}",
            description=f"Transition customer complaint {complaint.complaint_number} to {new_status}.",
            reference_type="customer_complaints",
            reference_id=complaint.id,
            user_id=updated_by,
            branch_id=branch_id,
            severity="MEDIUM",
            metadata={"old_status": complaint.status, "new_status": new_status, "mutation_scope": "COMPLAINT_ONLY"},
        )
        if commit
        else _NullContext()
    )

    with boundary:
        old_status = complaint.status
        complaint.status = new_status
        if assigned_to is not None:
            complaint.assigned_to = assigned_to
        if new_status == COMPLAINT_STATUS_IN_PROGRESS and complaint.assigned_to is None:
            complaint.assigned_to = updated_by
        if new_status == COMPLAINT_STATUS_RESOLVED:
            complaint.resolved_by = updated_by
            complaint.resolved_at = datetime.utcnow()
            complaint.resolution_note = _required_text(resolution_note, "Catatan resolusi")
        if new_status == COMPLAINT_STATUS_CLOSED:
            complaint.closed_by = updated_by
            complaint.closed_at = datetime.utcnow()
        db.session.flush()
        _record_complaint_audit(
            complaint,
            event_type="CUSTOMER_COMPLAINT_STATUS_CHANGED",
            action="UPDATE",
            user_id=updated_by,
            description=f"Complaint {complaint.complaint_number}: {old_status} -> {new_status}.",
            metadata={"old_status": old_status, "new_status": new_status},
        )
    return complaint


def get_customer_complaint(complaint_id: int, *, branch_id: int) -> CustomerComplaint | None:
    return CustomerComplaint.query.filter_by(id=complaint_id, branch_id=branch_id).first()


def list_customer_complaints(
    branch_id: int,
    *,
    status: str = "ALL",
    category: str | None = None,
    client_id: int | None = None,
    mandor_id: int | None = None,
    limit: int = 200,
) -> list[CustomerComplaint]:
    query = CustomerComplaint.query.filter_by(branch_id=branch_id)
    if status and status != "ALL":
        query = query.filter(CustomerComplaint.status == _normalize_status(status))
    if category:
        query = query.filter(CustomerComplaint.category == _normalize_category(category))
    if client_id:
        query = query.filter(CustomerComplaint.client_id == client_id)
    if mandor_id:
        query = query.filter(CustomerComplaint.mandor_id == mandor_id)
    try:
        limit = max(1, min(int(limit), 500))
    except Exception:
        limit = 200
    return query.order_by(CustomerComplaint.created_at.desc(), CustomerComplaint.id.desc()).limit(limit).all()


def _get_complaint_or_raise(complaint_id: int, branch_id: int) -> CustomerComplaint:
    complaint = get_customer_complaint(complaint_id, branch_id=branch_id)
    if not complaint:
        raise CustomerComplaintError("Complaint customer tidak ditemukan.")
    return complaint


def _assert_reference_scope(
    *,
    branch_id: int,
    client_id: int | None,
    mandor_id: int | None,
    order_id: int | None,
    delivery_id: int | None,
    invoice_id: int | None,
) -> None:
    if client_id and not Client.query.filter_by(id=client_id).first():
        raise CustomerComplaintError(f"{T.client} complaint tidak ditemukan.")
    if mandor_id:
        mandor = Mandor.query.filter_by(id=mandor_id, branch_id=branch_id).first()
        if not mandor:
            raise CustomerComplaintError(f"{T.sub_client} complaint tidak ditemukan untuk branch ini.")
        if client_id and mandor.client_id != client_id:
            raise CustomerComplaintError(f"{T.sub_client} complaint tidak sesuai {T.client_lower}.")
    if order_id and not DailyOrder.query.filter_by(id=order_id, branch_id=branch_id).first():
        raise CustomerComplaintError("Order complaint tidak ditemukan untuk branch ini.")
    if delivery_id and not Delivery.query.filter_by(id=delivery_id, branch_id=branch_id).first():
        raise CustomerComplaintError("Delivery complaint tidak ditemukan untuk branch ini.")
    if invoice_id:
        invoice = Invoice.query.filter_by(id=invoice_id, branch_id=branch_id).first()
        if not invoice:
            raise CustomerComplaintError("Invoice complaint tidak ditemukan untuk branch ini.")
        if client_id and invoice.client_id and invoice.client_id != client_id:
            raise CustomerComplaintError(f"Invoice complaint tidak sesuai {T.client_lower}.")
        if mandor_id and invoice.mandor_id and invoice.mandor_id != mandor_id:
            raise CustomerComplaintError(f"Invoice complaint tidak sesuai {T.sub_client_lower}.")


def _assert_user_in_branch(user_id: int, branch_id: int, label: str) -> None:
    if not User.query.filter_by(id=user_id, branch_id=branch_id, is_active=True).first():
        raise CustomerComplaintError(f"{label} tidak valid untuk branch ini.")


def _assert_branch_id(branch_id: int) -> None:
    if not branch_id:
        raise CustomerComplaintError("Branch complaint wajib diisi.")


def _normalize_category(category: str) -> str:
    normalized = str(category or "").strip().upper()
    if normalized not in COMPLAINT_CATEGORIES:
        allowed = ", ".join(sorted(COMPLAINT_CATEGORIES))
        raise CustomerComplaintError(f"Kategori complaint tidak valid. Pilihan: {allowed}.")
    return normalized


def _normalize_status(status: str) -> str:
    normalized = str(status or "").strip().upper()
    if normalized not in COMPLAINT_STATUSES:
        allowed = ", ".join(sorted(COMPLAINT_STATUSES))
        raise CustomerComplaintError(f"Status complaint tidak valid. Pilihan: {allowed}.")
    return normalized


def _required_text(value: object, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise CustomerComplaintError(f"{label} wajib diisi.")
    return text


def _record_complaint_audit(
    complaint: CustomerComplaint,
    *,
    event_type: str,
    action: str,
    user_id: int,
    description: str,
    metadata: dict | None = None,
) -> None:
    payload = {
        "complaint_number": complaint.complaint_number,
        "category": complaint.category,
        "status": complaint.status,
        "client_id": complaint.client_id,
        "mandor_id": complaint.mandor_id,
        "order_id": complaint.order_id,
        "delivery_id": complaint.delivery_id,
        "invoice_id": complaint.invoice_id,
        "mutation_scope": "COMPLAINT_ONLY",
    }
    payload.update(metadata or {})
    record_audit_log(
        module="COMPLAINT",
        event_type=event_type,
        action=action,
        table_name="customer_complaints",
        record_id=complaint.id,
        description=description,
        metadata=payload,
        user_id=user_id,
        branch_id=complaint.branch_id,
        commit=False,
    )


class _NullContext:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False
