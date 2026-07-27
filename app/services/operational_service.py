import json
from datetime import datetime

from app.extensions import db
from app.models.operational import DailyOrder, DailyOrderDetail, OrderRevision, OrderSnapshot


def _commit_or_rollback():
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise


def generate_order_number(order_date):
    date_code = order_date.strftime("%Y%m%d")

    count_today = DailyOrder.query.filter(
        DailyOrder.order_number.like(f"ORD-{date_code}-%")
    ).count()

    next_number = count_today + 1
    return f"ORD-{date_code}-{next_number:03d}"


def get_or_create_daily_order(branch_id, order_date, created_by, notes=None):
    daily_order = DailyOrder.query.filter_by(
        branch_id=branch_id,
        order_date=order_date
    ).first()

    if daily_order:
        return daily_order

    daily_order = DailyOrder(
        order_number=generate_order_number(order_date),
        branch_id=branch_id,
        order_date=order_date,
        status="DRAFT",
        is_locked=False,
        notes=notes,
        created_by=created_by
    )

    db.session.add(daily_order)
    db.session.commit()

    return daily_order


def add_or_update_order_detail(
    daily_order,
    mandor_id,
    delivery_location_id,
    price_per_portion,
    lunch_qty,
    dinner_qty,
    notes=None
):
    existing_detail = DailyOrderDetail.query.filter_by(
        daily_order_id=daily_order.id,
        mandor_id=mandor_id,
        delivery_location_id=delivery_location_id
    ).first()

    if existing_detail:
        return False, "Mandor dan lokasi ini sudah ada di order. Gunakan revisi jika ingin mengubah jumlah porsi.", existing_detail

    total_qty = int(lunch_qty or 0) + int(dinner_qty or 0)

    detail = DailyOrderDetail(
        daily_order_id=daily_order.id,
        mandor_id=mandor_id,
        delivery_location_id=delivery_location_id,
        price_per_portion=price_per_portion,
        lunch_qty=lunch_qty,
        dinner_qty=dinner_qty,
        total_qty=total_qty,
        notes=notes
    )

    db.session.add(detail)
    db.session.commit()

    return True, "Detail order berhasil disimpan.", detail


def create_order_snapshot(daily_order, created_by, commit=True):
    snapshot_details = []

    for detail in daily_order.details:
        snapshot_details.append({
            "mandor_id": detail.mandor_id,
            "mandor_name": detail.mandor.name if detail.mandor else None,
            "delivery_location_id": detail.delivery_location_id,
            "location_name": detail.delivery_location.location_name if detail.delivery_location else None,
            "price_per_portion": detail.price_per_portion,
            "lunch_qty": detail.lunch_qty,
            "dinner_qty": detail.dinner_qty,
            "total_qty": detail.total_qty,
            "notes": detail.notes
        })

    snapshot = OrderSnapshot(
        daily_order_id=daily_order.id,
        snapshot_time=datetime.utcnow(),
        snapshot_data=json.dumps(snapshot_details),
        created_by=created_by
    )

    db.session.add(snapshot)
    if commit:
        _commit_or_rollback()

    return snapshot


def lock_daily_order(daily_order, locked_by):
    if daily_order.is_locked:
        return False, "Order sudah dalam status LOCKED."

    if not daily_order.details:
        return False, "Order belum memiliki detail mandor/lokasi."

    daily_order.status = "LOCKED"
    daily_order.is_locked = True
    daily_order.locked_at = datetime.utcnow()

    create_order_snapshot(daily_order, locked_by, commit=False)
    _commit_or_rollback()

    return True, "Order berhasil di-lock."


def revise_order_detail(
    detail,
    revision_type,
    revision_direction,
    lunch_qty_change,
    dinner_qty_change,
    reason,
    created_by,
    price_per_portion=None,
    commit=True,
):
    lunch_qty_change = int(lunch_qty_change or 0)
    dinner_qty_change = int(dinner_qty_change or 0)

    if lunch_qty_change < 0 or dinner_qty_change < 0:
        return False, "Jumlah revisi tidak boleh minus."

    if lunch_qty_change == 0 and dinner_qty_change == 0:
        return False, "Minimal salah satu jumlah revisi harus lebih dari 0."

    daily_order = detail.daily_order

    if daily_order.is_locked and revision_direction == "DECREASE":
        return False, "Order sudah LOCKED. Setelah lock tidak boleh mengurangi porsi."

    if revision_direction == "DECREASE":
        if lunch_qty_change > detail.lunch_qty:
            return False, "Pengurangan porsi siang melebihi jumlah order saat ini."

        if dinner_qty_change > detail.dinner_qty:
            return False, "Pengurangan porsi sore melebihi jumlah order saat ini."

        detail.lunch_qty -= lunch_qty_change
        detail.dinner_qty -= dinner_qty_change

    elif revision_direction == "INCREASE":
        detail.lunch_qty += lunch_qty_change
        detail.dinner_qty += dinner_qty_change

    else:
        return False, "Arah revisi tidak valid."

    detail.total_qty = detail.lunch_qty + detail.dinner_qty

    revision_price = float(price_per_portion if price_per_portion is not None else detail.price_per_portion)

    revision = OrderRevision(
        daily_order_detail_id=detail.id,
        revision_time=datetime.utcnow(),
        revision_type=revision_type,
        revision_direction=revision_direction,
        lunch_qty_change=lunch_qty_change,
        dinner_qty_change=dinner_qty_change,
        price_per_portion=revision_price,
        reason=reason,
        created_by=created_by
    )

    db.session.add(revision)
    if commit:
        _commit_or_rollback()

    return True, "Revisi order berhasil disimpan."


def add_increase_after_lock(
    daily_order,
    mandor_id,
    delivery_location_id,
    price_per_portion,
    lunch_qty,
    dinner_qty,
    reason,
    created_by
):
    if not daily_order.is_locked:
        return False, "Order belum LOCKED. Gunakan input detail biasa.", None

    mandor_id = int(mandor_id)
    delivery_location_id = int(delivery_location_id)
    price_per_portion = float(price_per_portion or 0)
    lunch_qty = int(lunch_qty or 0)
    dinner_qty = int(dinner_qty or 0)

    if price_per_portion <= 0:
        return False, "Harga per porsi wajib lebih dari 0.", None

    if lunch_qty < 0 or dinner_qty < 0:
        return False, "Jumlah tambahan tidak boleh minus.", None

    if lunch_qty == 0 and dinner_qty == 0:
        return False, "Minimal salah satu jumlah tambahan harus lebih dari 0.", None

    existing_detail = DailyOrderDetail.query.filter_by(
        daily_order_id=daily_order.id,
        mandor_id=mandor_id,
        delivery_location_id=delivery_location_id
    ).first()

    if existing_detail:
        old_price = float(existing_detail.price_per_portion or 0)
        new_price = float(price_per_portion or 0)

        success, message = revise_order_detail(
            detail=existing_detail,
            revision_type="AFTER_LOCK_PRICE_REVISION" if abs(old_price - new_price) > 0.01 else "AFTER_LOCK",
            revision_direction="INCREASE",
            lunch_qty_change=lunch_qty,
            dinner_qty_change=dinner_qty,
            reason=reason or (
                f"Penambahan order setelah lock. Harga revisi Rp {new_price:,.0f}, harga awal Rp {old_price:,.0f}."
                if abs(old_price - new_price) > 0.01
                else "Penambahan order setelah lock"
            ),
            created_by=created_by,
            price_per_portion=new_price,
            commit=False,
        )

        if success:
            _commit_or_rollback()

        if success and abs(old_price - new_price) > 0.01:
            return True, "Tambahan setelah lock berhasil disimpan sebagai revisi harga baru. Harga awal detail tidak berubah.", existing_detail

        return success, message, existing_detail

    detail = DailyOrderDetail(
        daily_order_id=daily_order.id,
        mandor_id=mandor_id,
        delivery_location_id=delivery_location_id,
        price_per_portion=price_per_portion,
        lunch_qty=lunch_qty,
        dinner_qty=dinner_qty,
        total_qty=lunch_qty + dinner_qty,
        notes=reason or "Detail tambahan setelah lock"
    )

    db.session.add(detail)
    db.session.flush()

    revision = OrderRevision(
        daily_order_detail_id=detail.id,
        revision_time=datetime.utcnow(),
        revision_type="AFTER_LOCK_NEW_DETAIL",
        revision_direction="INCREASE",
        lunch_qty_change=lunch_qty,
        dinner_qty_change=dinner_qty,
        price_per_portion=price_per_portion,
        reason=reason or "Penambahan mandor/lokasi setelah lock",
        created_by=created_by
    )

    db.session.add(revision)
    _commit_or_rollback()

    return True, "Tambahan mandor/lokasi baru setelah lock berhasil disimpan.", detail


def _to_optional_int(value):
    try:
        if value in (None, ""):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _active_branch_record(model, record_id, branch_id):
    if not record_id:
        return None

    record = model.query.get(record_id)
    if not record:
        return None

    if getattr(record, "branch_id", None) != branch_id:
        return None

    if hasattr(record, "is_active") and not record.is_active:
        return None

    return record


def update_order_hpp_defaults(daily_order, form_data):
    """
    Simpan default HPP order untuk prefill snapshot.
    Tidak membuat snapshot, tidak memotong stok, tidak membuat jurnal/invoice.
    """
    from app.models.master import Menu, PackagingProfile, OverheadProfile

    branch_id = daily_order.branch_id
    lunch_menu_id = _to_optional_int(form_data.get("default_lunch_menu_id"))
    dinner_menu_id = _to_optional_int(form_data.get("default_dinner_menu_id"))
    packaging_profile_id = _to_optional_int(form_data.get("default_packaging_profile_id"))
    overhead_profile_id = _to_optional_int(form_data.get("default_overhead_profile_id"))

    if lunch_menu_id and not _active_branch_record(Menu, lunch_menu_id, branch_id):
        return False, "Menu siang default tidak valid atau tidak sesuai cabang."

    if dinner_menu_id and not _active_branch_record(Menu, dinner_menu_id, branch_id):
        return False, "Menu sore default tidak valid atau tidak sesuai cabang."

    if packaging_profile_id and not _active_branch_record(PackagingProfile, packaging_profile_id, branch_id):
        return False, "Profil kemasan default tidak valid atau tidak sesuai cabang."

    if overhead_profile_id and not _active_branch_record(OverheadProfile, overhead_profile_id, branch_id):
        return False, "Profil overhead default tidak valid atau tidak sesuai cabang."

    daily_order.lunch_menu_id = lunch_menu_id
    daily_order.dinner_menu_id = dinner_menu_id
    daily_order.packaging_profile_id = packaging_profile_id
    daily_order.overhead_profile_id = overhead_profile_id

    db.session.commit()
    return True, "Default HPP order berhasil disimpan. Snapshot tetap harus dibuat manual."
