from datetime import date, datetime

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import lazyload

from app.extensions import db
from app.models.master import DeliveryLocation
from app.models.operational import DailyOrder, DailyOrderDetail
from app.models.system import PortalOrderDraft
from app.services.portal_mapping_service import ACCESS_DRAFT_ORDER, build_portal_external_scope
from app.services.operational_service import generate_order_number


DRAFT_STATUS_PENDING = "PENDING_ADMIN_CONFIRMATION"
DRAFT_STATUS_CONFIRMED = "CONFIRMED"
DRAFT_STATUS_REJECTED = "REJECTED"
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


def _commit_or_rollback():
    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        raise


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


def build_portal_order_status_context(user, limit=50):
    drafts = list_portal_order_drafts(user, limit=limit)
    rows = []
    for draft in drafts:
        order = draft.converted_daily_order
        rows.append(
            {
                "draft_id": draft.id,
                "order_date": draft.order_date,
                "meal_type": draft.meal_type,
                "portion_qty": draft.portion_qty,
                "location_name": draft.delivery_location.location_name if draft.delivery_location else "-",
                "draft_status": draft.status,
                "internal_order_number": order.order_number if order else "-",
                "internal_order_status": order.status if order else "-",
                "internal_order_locked": order.is_locked if order else False,
                "review_note": draft.review_note,
            }
        )
    return {
        "rows": rows,
        "total": len(rows),
        "pending": sum(1 for row in rows if row["draft_status"] == DRAFT_STATUS_PENDING),
        "confirmed": sum(1 for row in rows if row["draft_status"] == DRAFT_STATUS_CONFIRMED),
        "rejected": sum(1 for row in rows if row["draft_status"] == DRAFT_STATUS_REJECTED),
    }


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
        _commit_or_rollback()
    except IntegrityError:
        existing = PortalOrderDraft.query.filter(
            PortalOrderDraft.user_id == payload["user_id"],
            PortalOrderDraft.idempotency_key == payload["idempotency_key"],
        ).first()
        if existing:
            return existing, False, None
        return None, False, "Draft order gagal disimpan karena konflik data."

    return draft, True, None


def count_existing_operational_orders():
    return DailyOrder.query.count()


def _admin_can_review_draft(admin_user, draft):
    if getattr(admin_user, "role", None) == "OWNER":
        return True
    return draft.branch_id == getattr(admin_user, "branch_id", None)


def list_pending_portal_order_drafts(admin_user, limit=100):
    query = PortalOrderDraft.query.filter(PortalOrderDraft.status == DRAFT_STATUS_PENDING)
    if getattr(admin_user, "role", None) != "OWNER":
        query = query.filter(PortalOrderDraft.branch_id == getattr(admin_user, "branch_id", None))
    return query.order_by(
        PortalOrderDraft.order_date.asc(),
        PortalOrderDraft.submitted_at.asc(),
        PortalOrderDraft.id.asc(),
    ).limit(limit).all()


def get_portal_order_draft_or_404(draft_id):
    return PortalOrderDraft.query.get_or_404(draft_id)


def confirm_portal_order_draft(draft_id, admin_user, review_note=None):
    draft = (
        PortalOrderDraft.query.filter(PortalOrderDraft.id == draft_id)
        .options(lazyload("*"))
        .with_for_update(of=PortalOrderDraft)
        .first()
    )
    if not draft:
        return None, False, "Draft order tidak ditemukan."

    if draft.status == DRAFT_STATUS_CONFIRMED and draft.converted_daily_order_id:
        return draft, False, None

    if draft.status != DRAFT_STATUS_PENDING:
        return draft, False, "Draft order sudah tidak dalam status pending."

    if not _admin_can_review_draft(admin_user, draft):
        return draft, False, "Draft order tidak sesuai cabang admin."

    daily_order = DailyOrder.query.filter_by(
        branch_id=draft.branch_id,
        order_date=draft.order_date,
    ).first()

    if daily_order and daily_order.is_locked:
        return draft, False, "Order harian sudah LOCKED. Draft tidak bisa dikonfirmasi otomatis."

    if not daily_order:
        daily_order = DailyOrder(
            order_number=generate_order_number(draft.order_date),
            branch_id=draft.branch_id,
            order_date=draft.order_date,
            status="DRAFT",
            is_locked=False,
            notes=f"Dibuat dari portal draft #{draft.id}",
            created_by=admin_user.id,
        )
        db.session.add(daily_order)
        db.session.flush()

    existing_detail = DailyOrderDetail.query.filter_by(
        daily_order_id=daily_order.id,
        mandor_id=draft.mandor_id,
        delivery_location_id=draft.delivery_location_id,
    ).first()
    if existing_detail:
        return draft, False, "Detail mandor/lokasi sudah ada di order harian. Review manual diperlukan."

    lunch_qty = draft.portion_qty if draft.meal_type == "LUNCH" else 0
    dinner_qty = draft.portion_qty if draft.meal_type == "DINNER" else 0
    detail = DailyOrderDetail(
        daily_order_id=daily_order.id,
        mandor_id=draft.mandor_id,
        delivery_location_id=draft.delivery_location_id,
        price_per_portion=0,
        lunch_qty=lunch_qty,
        dinner_qty=dinner_qty,
        total_qty=draft.portion_qty,
        notes=f"Konfirmasi portal draft #{draft.id}. {draft.notes or ''}".strip(),
    )
    db.session.add(detail)

    draft.status = DRAFT_STATUS_CONFIRMED
    draft.converted_daily_order_id = daily_order.id
    draft.reviewed_by = admin_user.id
    draft.reviewed_at = datetime.utcnow()
    draft.review_note = _clean_text(review_note) or "Dikonfirmasi ke order harian existing."

    _commit_or_rollback()
    return draft, True, None


def reject_portal_order_draft(draft_id, admin_user, review_note):
    draft = (
        PortalOrderDraft.query.filter(PortalOrderDraft.id == draft_id)
        .options(lazyload("*"))
        .with_for_update(of=PortalOrderDraft)
        .first()
    )
    if not draft:
        return None, False, "Draft order tidak ditemukan."

    if draft.status != DRAFT_STATUS_PENDING:
        return draft, False, "Draft order sudah tidak dalam status pending."

    if not _admin_can_review_draft(admin_user, draft):
        return draft, False, "Draft order tidak sesuai cabang admin."

    draft.status = DRAFT_STATUS_REJECTED
    draft.reviewed_by = admin_user.id
    draft.reviewed_at = datetime.utcnow()
    draft.review_note = _clean_text(review_note) or "Ditolak admin."

    _commit_or_rollback()
    return draft, True, None
