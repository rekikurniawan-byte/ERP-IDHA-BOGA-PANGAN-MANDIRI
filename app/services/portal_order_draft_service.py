from datetime import date, datetime

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.extensions import db
from app.models.master import DeliveryLocation
from app.models.operational import DailyOrder
from app.models.system import PortalOrderDraft
from app.services.portal_mapping_service import ACCESS_DRAFT_ORDER, build_portal_external_scope


DRAFT_STATUS_PENDING = "PENDING_ADMIN_CONFIRMATION"
MEAL_TYPES = {"LUNCH", "DINNER"}


def _clean_text(value):
    return (value or "").strip()


def _parse_date(value):
    try:
        return date.fromisoformat(_clean_text(value))
    except (TypeError, ValueError):
        return None


def _parse_positive_int(value):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _allowed_location_options(scope):
    if not scope.allowed:
        return []
    if not scope.delivery_location_ids:
        return []
    return (
        DeliveryLocation.query.filter(DeliveryLocation.id.in_(sorted(scope.delivery_location_ids)))
        .order_by(DeliveryLocation.location_name.asc())
        .all()
    )


def build_portal_draft_order_context(user):
    scope = build_portal_external_scope(user)
    return {
        "allowed": scope.allowed and ACCESS_DRAFT_ORDER in scope.access_levels,
        "scope": scope,
        "reason": scope.reason if scope.allowed else scope.reason,
        "location_options": _allowed_location_options(scope),
        "drafts": list_portal_order_drafts(user),
    }


def list_portal_order_drafts(user, limit=25):
    user_id = getattr(user, "id", None)
    if not user_id:
        return []
    return (
        PortalOrderDraft.query.filter(PortalOrderDraft.user_id == user_id)
        .order_by(PortalOrderDraft.submitted_at.desc(), PortalOrderDraft.id.desc())
        .limit(limit)
        .all()
    )


def _validate_draft_payload(user, form):
    scope = build_portal_external_scope(user)
    if not scope.allowed:
        return None, scope.reason or "User portal belum memiliki scope aktif."

    if ACCESS_DRAFT_ORDER not in scope.access_levels:
        return None, "Mapping portal masih read-only dan belum boleh membuat draft order."

    order_date = _parse_date(form.get("order_date"))
    if not order_date:
        return None, "Tanggal order wajib valid."

    meal_type = _clean_text(form.get("meal_type")).upper()
    if meal_type not in MEAL_TYPES:
        return None, "Tipe makan wajib LUNCH atau DINNER."

    portion_qty = _parse_positive_int(form.get("portion_qty"))
    if not portion_qty:
        return None, "Jumlah porsi wajib lebih dari 0."

    delivery_location_id = _parse_positive_int(form.get("delivery_location_id"))
    if not delivery_location_id or delivery_location_id not in scope.delivery_location_ids:
        return None, "Lokasi tidak termasuk scope portal user."

    location = DeliveryLocation.query.get(delivery_location_id)
    if not location or not location.mandor:
        return None, "Lokasi tidak valid."

    if location.mandor_id not in scope.mandor_ids:
        return None, "Mandor lokasi tidak termasuk scope portal user."

    idempotency_key = _clean_text(form.get("idempotency_key"))
    if not idempotency_key:
        return None, "Idempotency key wajib tersedia untuk mencegah double submit."

    return {
        "user_id": user.id,
        "branch_id": location.mandor.branch_id,
        "client_id": location.mandor.client_id,
        "mandor_id": location.mandor_id,
        "delivery_location_id": location.id,
        "order_date": order_date,
        "meal_type": meal_type,
        "portion_qty": portion_qty,
        "notes": _clean_text(form.get("notes")) or None,
        "idempotency_key": idempotency_key,
    }, None


def create_portal_order_draft(user, form):
    payload, error = _validate_draft_payload(user, form)
    if error:
        return None, False, error

    existing = PortalOrderDraft.query.filter(
        PortalOrderDraft.user_id == payload["user_id"],
        PortalOrderDraft.idempotency_key == payload["idempotency_key"],
    ).first()
    if existing:
        return existing, False, None

    draft = PortalOrderDraft(
        **payload,
        status=DRAFT_STATUS_PENDING,
        submitted_at=datetime.utcnow(),
    )
    db.session.add(draft)

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        existing = PortalOrderDraft.query.filter(
            PortalOrderDraft.user_id == payload["user_id"],
            PortalOrderDraft.idempotency_key == payload["idempotency_key"],
        ).first()
        if existing:
            return existing, False, None
        return None, False, "Draft order gagal disimpan karena konflik data."
    except SQLAlchemyError:
        db.session.rollback()
        raise

    return draft, True, None


def count_existing_operational_orders():
    return DailyOrder.query.count()
