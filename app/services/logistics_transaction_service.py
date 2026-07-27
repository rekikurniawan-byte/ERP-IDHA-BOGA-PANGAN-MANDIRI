from app.extensions import db
from app.models.logistics import ItemRequest, ItemRequestDetail, StockMovement
from app.services.business_logic_guard_service import validate_stock_movement_guard
from app.services.stock_service import get_item_stock_for_update, is_integer_unit


def _commit_or_rollback():
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise


def create_stock_audit_movement(
    *,
    branch_id,
    item_id,
    movement_date,
    movement_type,
    qty,
    notes,
    created_by,
):
    movement = StockMovement(
        branch_id=branch_id,
        item_id=item_id,
        movement_date=movement_date,
        movement_type=movement_type,
        reference_type="AUDIT_STOK",
        reference_id=None,
        qty=qty,
        notes=notes,
        created_by=created_by,
    )
    db.session.add(movement)
    _commit_or_rollback()
    return movement


def create_item_request_record(
    *,
    request_number,
    branch_id,
    request_date,
    requested_by,
    purpose,
    notes,
    rows,
):
    item_request = ItemRequest(
        request_number=request_number,
        branch_id=branch_id,
        request_date=request_date,
        requested_by=requested_by,
        status="PENDING",
        purpose=purpose,
        notes=notes,
    )

    db.session.add(item_request)
    db.session.flush()

    for row in rows:
        item = row["item"]
        requested_qty = row["requested_qty"]
        db.session.add(ItemRequestDetail(
            item_request_id=item_request.id,
            item_id=item.id,
            qty=requested_qty,
            unit=item.unit,
            requested_qty=requested_qty,
            approved_qty=0,
            fulfilled_qty=0,
            notes=row["notes"],
        ))

    _commit_or_rollback()
    return item_request


def approve_item_request_record(item_request, *, owner_note):
    for detail in item_request.details:
        requested_qty = float(getattr(detail, "requested_qty", 0) or getattr(detail, "qty", 0) or 0)
        detail.approved_qty = requested_qty

    item_request.status = "APPROVED"

    if owner_note:
        old_notes = item_request.notes or ""
        item_request.notes = (old_notes + f" | Catatan owner: {owner_note}").strip(" |")

    _commit_or_rollback()
    return item_request


def reject_item_request_record(item_request, *, reject_reason):
    for detail in item_request.details:
        detail.approved_qty = 0
        detail.fulfilled_qty = 0

    old_notes = item_request.notes or ""
    item_request.notes = (old_notes + f" | Alasan ditolak: {reject_reason}").strip(" |")
    item_request.status = "REJECTED"
    _commit_or_rollback()
    return item_request


def fulfill_item_request_record(item_request, *, branch_id, fulfilled_by, fulfill_note):
    for detail in item_request.details:
        item = detail.item
        approved_qty = float(getattr(detail, "approved_qty", 0) or 0)

        if approved_qty <= 0:
            approved_qty = float(getattr(detail, "requested_qty", 0) or getattr(detail, "qty", 0) or 0)

        notes = (
            f"Pemenuhan permintaan dapur {item_request.request_number} | "
            f"Tujuan: {item_request.purpose}"
        )

        if fulfill_note:
            notes += f" | Catatan owner: {fulfill_note}"

        current_stock = get_item_stock_for_update(branch_id, item.id)
        validate_stock_movement_guard(
            "OUT",
            approved_qty,
            current_stock=current_stock,
            item_unit=item.unit,
            is_integer_unit=is_integer_unit(item.unit),
        )

        db.session.add(StockMovement(
            branch_id=branch_id,
            item_id=item.id,
            movement_date=item_request.request_date,
            movement_type="OUT",
            reference_type="PERMINTAAN_BARANG_DAPUR",
            reference_id=item_request.id,
            qty=approved_qty,
            notes=notes,
            created_by=fulfilled_by,
        ))

        detail.fulfilled_qty = approved_qty

    old_notes = item_request.notes or ""

    if fulfill_note:
        item_request.notes = (old_notes + f" | Catatan pemenuhan: {fulfill_note}").strip(" |")

    item_request.status = "FULFILLED"
    _commit_or_rollback()
    return item_request
