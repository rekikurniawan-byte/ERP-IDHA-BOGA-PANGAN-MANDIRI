from datetime import datetime

from app.extensions import db
from app.models.delivery import Delivery, DeliveryDetail, DeliveryReceipt
from app.models.master import Driver
from app.models.production import Production


def get_delivery_type_from_notes(notes):
    if not notes:
        return "-"

    if "delivery_type=LUNCH" in notes:
        return "LUNCH"

    if "delivery_type=DINNER" in notes:
        return "DINNER"

    return "-"


def get_default_driver(branch_id):
    return Driver.query.filter_by(
        branch_id=branch_id,
        is_active=True
    ).first()


def get_completed_production(branch_id, production_date, delivery_type):
    return Production.query.filter_by(
        branch_id=branch_id,
        production_date=production_date,
        production_type=delivery_type,
        status="COMPLETED"
    ).first()


def generate_delivery_number(delivery_date, delivery_type):
    date_code = delivery_date.strftime("%Y%m%d")

    count_today = Delivery.query.filter(
        Delivery.delivery_number.like(f"DLV-{date_code}-{delivery_type}-%")
    ).count()

    next_number = count_today + 1
    return f"DLV-{date_code}-{delivery_type}-{next_number:03d}"


def get_delivered_qty_for_order_detail(order_detail_id, delivery_type):
    delivery_details = DeliveryDetail.query.join(Delivery).filter(
        DeliveryDetail.daily_order_detail_id == order_detail_id,
        Delivery.notes.like(f"%delivery_type={delivery_type}%"),
        Delivery.status != "CANCELLED"
    ).all()

    return sum(detail.delivered_qty for detail in delivery_details)


def unreplaced_shortage_qty(order_detail_id, delivery_type):
    """Porsi kurang kirim yang tercatat di tanda terima dan belum diganti.

    Keputusan owner 2026-09-28 (gladi pilot): porsi ini tidak ditagih. Hanya
    kekurangan yang sudah tercatat di tanda terima yang dihitung; pengiriman
    yang belum diterima tetap ditagih penuh supaya tidak ada pesanan lolos.
    Kiriman pengganti (batch=SHORTAGE_REPLACEMENT) yang sudah diterima
    mengurangi kekurangan.
    """
    rows = DeliveryDetail.query.join(Delivery).filter(
        DeliveryDetail.daily_order_detail_id == order_detail_id,
        Delivery.notes.like(f"%delivery_type={delivery_type}%"),
        Delivery.status != "CANCELLED",
    ).all()
    shortage = replaced = 0
    for row in rows:
        if row.receipt is None:
            continue
        if "batch=SHORTAGE_REPLACEMENT" in (row.delivery.notes or ""):
            replaced += int(row.delivered_qty or 0)
        else:
            shortage += int(row.shortage_qty or 0)
    return max(shortage - replaced, 0)


def get_remaining_delivery_rows(daily_order, delivery_type):
    rows = []
    total_order_qty = 0
    total_planned_delivery_qty = 0

    for order_detail in daily_order.details:
        order_qty = order_detail.lunch_qty if delivery_type == "LUNCH" else order_detail.dinner_qty

        if order_qty <= 0:
            continue

        planned_delivery_qty = get_planned_delivery_qty_for_order_detail(
            order_detail_id=order_detail.id,
            delivery_type=delivery_type
        )

        remaining_qty = order_qty - planned_delivery_qty

        total_order_qty += order_qty
        total_planned_delivery_qty += planned_delivery_qty

        if remaining_qty > 0:
            rows.append({
                "order_detail": order_detail,
                "remaining_qty": remaining_qty
            })

    remaining_total = total_order_qty - total_planned_delivery_qty

    if remaining_total < 0:
        remaining_total = 0

    return rows, total_order_qty, total_planned_delivery_qty, remaining_total


def get_delivery_summary_for_order(daily_order, delivery_type):
    deliveries = find_existing_deliveries(
        branch_id=daily_order.branch_id,
        delivery_date=daily_order.order_date,
        delivery_type=delivery_type
    )

    rows, total_order_qty, total_planned_delivery_qty, remaining_total = get_remaining_delivery_rows(
        daily_order=daily_order,
        delivery_type=delivery_type
    )

    return {
        "deliveries": deliveries,
        "latest_delivery": deliveries[0] if deliveries else None,
        "has_delivery": len(deliveries) > 0,
        "delivery_count": len(deliveries),
        "total_order_qty": total_order_qty,
        "total_planned_delivery_qty": total_planned_delivery_qty,
        "remaining_qty": remaining_total,
        "remaining_rows": rows
    }


DELIVERY_TYPE_LABELS = {
    "LUNCH": "Siang",
    "DINNER": "Sore",
}


def get_delivery_type_label(delivery_type):
    return DELIVERY_TYPE_LABELS.get(delivery_type, delivery_type or "-")


def build_delivery_next_action_for_order(daily_order, delivery_type):
    """
    PRODUCTION read-only guard builder.

    Tujuan fungsi ini hanya membuat status/alert/action context agar admin
    sadar ketika produksi sudah COMPLETED tetapi delivery belum dibuat.
    Fungsi ini tidak membuat delivery, tidak mengubah order, dan tidak mengubah DB.
    """
    summary = get_delivery_summary_for_order(daily_order, delivery_type)
    production = get_completed_production(
        branch_id=daily_order.branch_id,
        production_date=daily_order.order_date,
        delivery_type=delivery_type,
    )
    driver = get_default_driver(daily_order.branch_id)

    label = get_delivery_type_label(delivery_type)
    total_order_qty = int(summary.get("total_order_qty") or 0)
    remaining_qty = int(summary.get("remaining_qty") or 0)
    has_delivery = bool(summary.get("has_delivery"))

    blocking_reasons = []

    if delivery_type not in DELIVERY_TYPE_LABELS:
        blocking_reasons.append("Tipe delivery tidak valid.")

    if not daily_order.is_locked:
        blocking_reasons.append("Order belum LOCKED.")

    if total_order_qty <= 0:
        blocking_reasons.append(f"Tidak ada porsi {label} pada order ini.")

    if not production:
        blocking_reasons.append(f"Produksi {label} belum COMPLETED.")

    if remaining_qty <= 0 and total_order_qty > 0:
        blocking_reasons.append(f"Semua porsi {label} sudah masuk delivery.")

    if not driver:
        blocking_reasons.append("Driver aktif belum tersedia di master data.")

    production_completed = production is not None
    needs_attention = bool(
        daily_order.is_locked
        and production_completed
        and total_order_qty > 0
        and remaining_qty > 0
    )
    can_create_delivery = bool(needs_attention and driver)
    is_additional = bool(has_delivery and remaining_qty > 0)

    if needs_attention:
        if is_additional:
            title = f"Delivery tambahan {label} perlu dibuat"
            description = (
                f"Produksi {label} sudah selesai, tetapi masih ada {remaining_qty} "
                "porsi revisi/tambahan yang belum masuk delivery."
            )
            action_label = f"Buat Delivery Tambahan {label}"
        else:
            title = f"Produksi {label} selesai, delivery belum dibuat"
            description = (
                f"Order sudah LOCKED dan produksi {label} sudah COMPLETED. "
                f"Buat delivery agar muncul di halaman pengantar."
            )
            action_label = f"Buat Delivery {label}"
    else:
        title = f"Delivery {label}"
        description = blocking_reasons[0] if blocking_reasons else f"Delivery {label} tidak membutuhkan aksi lanjutan."
        action_label = f"Buat Delivery {label}"

    return {
        "delivery_type": delivery_type,
        "label": label,
        "daily_order": daily_order,
        "daily_order_id": daily_order.id,
        "order_number": daily_order.order_number,
        "order_date": daily_order.order_date,
        "summary": summary,
        "production": production,
        "production_completed": production_completed,
        "driver": driver,
        "has_driver": driver is not None,
        "total_order_qty": total_order_qty,
        "total_planned_delivery_qty": int(summary.get("total_planned_delivery_qty") or 0),
        "remaining_qty": remaining_qty,
        "delivery_count": int(summary.get("delivery_count") or 0),
        "latest_delivery": summary.get("latest_delivery"),
        "has_delivery": has_delivery,
        "needs_attention": needs_attention,
        "can_create_delivery": can_create_delivery,
        "is_additional": is_additional,
        "title": title,
        "description": description,
        "action_label": action_label,
        "blocking_reasons": blocking_reasons,
        "blocking_reason": "; ".join(blocking_reasons),
    }


def get_delivery_next_actions_for_order(daily_order):
    return [
        build_delivery_next_action_for_order(daily_order, "LUNCH"),
        build_delivery_next_action_for_order(daily_order, "DINNER"),
    ]


def get_ready_delivery_next_actions_for_order(daily_order):
    return [
        action for action in get_delivery_next_actions_for_order(daily_order)
        if action.get("needs_attention")
    ]


def get_pending_delivery_next_actions(branch_id, target_date=None, limit=10):
    """
    Read-only panel untuk dashboard/today page.
    Mengambil order locked yang produksinya completed tetapi delivery normal belum dibuat
    atau masih ada sisa porsi delivery tambahan.
    """
    from app.models.operational import DailyOrder

    query = DailyOrder.query.filter_by(branch_id=branch_id, is_locked=True)

    if target_date is not None:
        query = query.filter(DailyOrder.order_date == target_date)

    orders = query.order_by(
        DailyOrder.order_date.desc(),
        DailyOrder.id.desc(),
    ).limit(max(limit * 5, 20)).all()

    actions = []

    for daily_order in orders:
        for action in get_ready_delivery_next_actions_for_order(daily_order):
            actions.append(action)
            if len(actions) >= limit:
                return actions

    return actions


def create_delivery_from_order(daily_order, delivery_type, created_by):
    if not daily_order.is_locked:
        return False, "Delivery hanya bisa dibuat dari order yang sudah LOCKED.", None

    if delivery_type not in ["LUNCH", "DINNER"]:
        return False, "Tipe delivery tidak valid.", None

    completed_production = get_completed_production(
        branch_id=daily_order.branch_id,
        production_date=daily_order.order_date,
        delivery_type=delivery_type
    )

    if not completed_production:
        return False, f"Produksi {delivery_type} belum COMPLETED. Selesaikan realisasi produksi dulu.", None

    driver = get_default_driver(daily_order.branch_id)

    if not driver:
        return False, "Driver belum tersedia. Tambahkan driver aktif di Master Data.", None

    remaining_rows, total_order_qty, total_planned_delivery_qty, remaining_total = get_remaining_delivery_rows(
        daily_order=daily_order,
        delivery_type=delivery_type
    )

    latest_delivery = find_existing_delivery(
        branch_id=daily_order.branch_id,
        delivery_date=daily_order.order_date,
        delivery_type=delivery_type
    )

    if remaining_total <= 0:
        return False, f"Tidak ada sisa porsi {delivery_type} untuk dibuat delivery baru.", latest_delivery

    delivery_count = len(find_existing_deliveries(
        branch_id=daily_order.branch_id,
        delivery_date=daily_order.order_date,
        delivery_type=delivery_type
    ))

    batch_label = "MAIN" if delivery_count == 0 else "ADDITIONAL"

    from app.services.delivery_sla_service import get_delivery_sla_defaults

    sla_defaults = get_delivery_sla_defaults(daily_order.order_date, delivery_type)

    delivery = Delivery(
        delivery_number=generate_delivery_number(daily_order.order_date, delivery_type),
        branch_id=daily_order.branch_id,
        delivery_date=daily_order.order_date,
        driver_id=driver.id,
        status="PREPARING",
        target_dispatch_time=sla_defaults["target_dispatch_time"],
        target_arrival_time=sla_defaults["target_arrival_time"],
        late_tolerance_minutes=sla_defaults["late_tolerance_minutes"],
        notes=f"delivery_type={delivery_type}; batch={batch_label}; dibuat dari order {daily_order.order_number}",
        created_by=created_by
    )

    db.session.add(delivery)
    db.session.flush()

    for row in remaining_rows:
        order_detail = row["order_detail"]
        remaining_qty = row["remaining_qty"]

        detail = DeliveryDetail(
            delivery_id=delivery.id,
            daily_order_detail_id=order_detail.id,
            mandor_id=order_detail.mandor_id,
            delivery_location_id=order_detail.delivery_location_id,
            planned_qty=remaining_qty,
            delivered_qty=0,
            shortage_qty=remaining_qty,
            notes=f"Pengiriman {delivery_type} {batch_label} dari order {daily_order.order_number}"
        )

        db.session.add(detail)

    db.session.commit()

    if batch_label == "ADDITIONAL":
        return True, f"Delivery tambahan {delivery_type} berhasil dibuat untuk sisa {remaining_total} porsi.", delivery

    return True, f"Delivery {delivery_type} berhasil dibuat untuk {remaining_total} porsi.", delivery


def update_delivery_receipt(delivery_detail, delivered_qty, receiver_name, notes):
    delivered_qty = int(delivered_qty or 0)
    notes = (notes or "").strip()

    if delivered_qty < 0:
        return False, "Jumlah terkirim tidak boleh minus."

    if delivered_qty > delivery_detail.planned_qty:
        return False, "Jumlah terkirim tidak boleh melebihi planned qty. Jika ada tambahan, lakukan revisi order tambah terlebih dahulu."

    shortage_qty = delivery_detail.planned_qty - delivered_qty

    delivery_detail.delivered_qty = delivered_qty
    delivery_detail.shortage_qty = shortage_qty
    receipt_time = datetime.utcnow()

    if delivery_detail.receipt:
        receipt = delivery_detail.receipt
        receipt.receiver_name = receiver_name
        receipt.receive_time = receipt_time
        receipt.notes = notes
    else:
        receipt = DeliveryReceipt(
            delivery_detail_id=delivery_detail.id,
            receiver_name=receiver_name,
            receive_time=receipt_time,
            notes=notes
        )
        db.session.add(receipt)

    delivery = delivery_detail.delivery

    from app.services.delivery_sla_service import calculate_delivery_detail_sla
    sla_result = calculate_delivery_detail_sla(delivery_detail, now=receipt_time)
    delivery_detail.sla_status = sla_result.get("status")
    delivery_detail.sla_minutes_late = int(sla_result.get("minutes_late") or 0)

    all_received = True
    any_received = False

    for detail in delivery.details:
        if detail.id == delivery_detail.id or detail.receipt:
            any_received = True
        else:
            all_received = False

    if all_received:
        delivery.status = "DELIVERED"
    elif any_received:
        delivery.status = "ON_THE_WAY"
    else:
        delivery.status = "PREPARING"

    db.session.commit()

    return True, "Penerimaan pengiriman berhasil disimpan."




# === PATCH_SHORTAGE_REPLACEMENT_DELIVERY ===
def get_planned_delivery_qty_for_order_detail(order_detail_id, delivery_type):
    """
    Override aman:
    planned delivery normal dihitung dari MAIN/ADDITIONAL saja.
    Delivery pengganti shortage tidak dihitung sebagai planned order baru,
    supaya status order tidak terlihat over-delivery.
    """
    from app.models.delivery import Delivery, DeliveryDetail

    delivery_details = DeliveryDetail.query.join(Delivery).filter(
        DeliveryDetail.daily_order_detail_id == order_detail_id,
        Delivery.notes.like(f"%delivery_type={delivery_type}%"),
        Delivery.status != "CANCELLED",
        ~Delivery.notes.like("%batch=SHORTAGE_REPLACEMENT%")
    ).all()

    return sum(detail.planned_qty for detail in delivery_details)


def get_shortage_replacement_delivery(source_delivery_detail_id):
    """
    Cek apakah shortage dari detail tertentu sudah pernah dibuatkan delivery pengganti.
    """
    from app.models.delivery import Delivery, DeliveryDetail

    replacement_detail = DeliveryDetail.query.join(Delivery).filter(
        Delivery.status != "CANCELLED",
        Delivery.notes.like(f"%shortage_source_detail_id={source_delivery_detail_id}%")
    ).first()

    return replacement_detail.delivery if replacement_detail else None


def create_shortage_replacement_delivery(source_delivery_detail, created_by):
    """
    Membuat delivery pengganti untuk shortage.
    Ini bukan order baru, bukan revisi tambah, dan nanti tidak boleh menjadi dasar invoice.
    """
    from app.extensions import db
    from app.models.delivery import Delivery, DeliveryDetail

    source_delivery = source_delivery_detail.delivery

    if not source_delivery:
        return False, "Data delivery sumber tidak ditemukan.", None

    if not source_delivery_detail.receipt:
        return False, "Penerimaan harus dicatat dulu sebelum membuat delivery pengganti shortage.", source_delivery

    shortage_qty = int(source_delivery_detail.shortage_qty or 0)

    if shortage_qty <= 0:
        return False, "Tidak ada shortage yang perlu dibuatkan delivery pengganti.", source_delivery

    existing_replacement = get_shortage_replacement_delivery(source_delivery_detail.id)

    if existing_replacement:
        return False, "Delivery pengganti untuk shortage ini sudah pernah dibuat.", existing_replacement

    delivery_type = get_delivery_type_from_notes(source_delivery.notes)

    if delivery_type not in ["LUNCH", "DINNER"]:
        return False, "Tipe delivery sumber tidak valid.", source_delivery

    from app.services.delivery_sla_service import get_delivery_sla_defaults

    replacement_sla_defaults = get_delivery_sla_defaults(source_delivery.delivery_date, delivery_type)

    replacement_delivery = Delivery(
        delivery_number=generate_delivery_number(source_delivery.delivery_date, delivery_type),
        branch_id=source_delivery.branch_id,
        delivery_date=source_delivery.delivery_date,
        driver_id=source_delivery.driver_id,
        status="PREPARING",
        target_dispatch_time=source_delivery.target_dispatch_time or replacement_sla_defaults["target_dispatch_time"],
        target_arrival_time=source_delivery.target_arrival_time or replacement_sla_defaults["target_arrival_time"],
        late_tolerance_minutes=source_delivery.late_tolerance_minutes or replacement_sla_defaults["late_tolerance_minutes"],
        notes=(
            f"delivery_type={delivery_type}; "
            f"batch=SHORTAGE_REPLACEMENT; "
            f"shortage_source_detail_id={source_delivery_detail.id}; "
            f"pengganti shortage dari delivery {source_delivery.delivery_number}"
        ),
        created_by=created_by
    )

    db.session.add(replacement_delivery)
    db.session.flush()

    replacement_detail = DeliveryDetail(
        delivery_id=replacement_delivery.id,
        daily_order_detail_id=source_delivery_detail.daily_order_detail_id,
        mandor_id=source_delivery_detail.mandor_id,
        delivery_location_id=source_delivery_detail.delivery_location_id,
        planned_qty=shortage_qty,
        delivered_qty=0,
        shortage_qty=shortage_qty,
        notes=(
            f"Delivery pengganti shortage {shortage_qty} porsi "
            f"dari detail delivery {source_delivery_detail.id}"
        )
    )

    db.session.add(replacement_detail)
    db.session.commit()

    return True, f"Delivery pengganti shortage berhasil dibuat untuk {shortage_qty} porsi.", replacement_delivery





# === PATCH_CANCEL_DELIVERY ===
def cancel_delivery(delivery, cancelled_by, reason=None):
    """
    Membatalkan delivery yang belum memiliki penerimaan.
    Delivery yang sudah ada receipt tidak boleh dicancel agar audit distribusi tetap aman.
    """
    from datetime import datetime
    from app.extensions import db

    if delivery.status == "CANCELLED":
        return False, "Delivery sudah berstatus CANCELLED."

    if delivery.status == "DELIVERED":
        return False, "Delivery yang sudah DELIVERED tidak boleh dibatalkan."

    has_receipt = any(detail.receipt for detail in delivery.details)

    if has_receipt:
        return False, "Delivery sudah memiliki data penerimaan. Tidak boleh dibatalkan."

    cancel_reason = (reason or "").strip() or "Delivery dibatalkan sebelum penerimaan."

    for detail in delivery.details:
        detail.delivered_qty = 0
        detail.shortage_qty = 0

    old_notes = delivery.notes or ""
    cancel_note = (
        f"; cancelled_by={cancelled_by}; "
        f"cancelled_at={datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}; "
        f"cancel_reason={cancel_reason}"
    )

    delivery.status = "CANCELLED"
    delivery.notes = old_notes + cancel_note

    db.session.commit()

    return True, "Delivery berhasil dibatalkan."





# === PATCH_ACTIVE_DELIVERY_COUNT_ONLY ===
def find_existing_deliveries(branch_id, delivery_date, delivery_type):
    """
    Override:
    Untuk status order, delivery yang dihitung hanya delivery aktif.
    Delivery CANCELLED dan SHORTAGE_REPLACEMENT tidak dihitung sebagai delivery order normal.
    """
    from app.models.delivery import Delivery

    return Delivery.query.filter(
        Delivery.branch_id == branch_id,
        Delivery.delivery_date == delivery_date,
        Delivery.notes.like(f"%delivery_type={delivery_type}%"),
        Delivery.status != "CANCELLED",
        ~Delivery.notes.like("%batch=SHORTAGE_REPLACEMENT%")
    ).order_by(
        Delivery.id.desc()
    ).all()


def find_existing_delivery(branch_id, delivery_date, delivery_type):
    deliveries = find_existing_deliveries(
        branch_id=branch_id,
        delivery_date=delivery_date,
        delivery_type=delivery_type
    )

    return deliveries[0] if deliveries else None

