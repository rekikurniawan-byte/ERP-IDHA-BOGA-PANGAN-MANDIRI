import hashlib
import json
import math
from typing import Any

from flask import url_for
import segno

from app.extensions import db
from app.models.delivery import Delivery, DeliveryDetail
from app.models.master import BranchSetting
from app.models.operational import DailyOrder, DailyOrderDetail
from app.models.system import AuditLog
from app.services.audit_log_service import record_critical_audit_log
from app.utils.clock import now_wib

DEFAULT_MAX_PORTIONS_PER_CONTAINER = 20
MIN_PORTIONS_PER_CONTAINER = 15
MAX_PORTIONS_PER_CONTAINER = 20

MEAL_TYPE_MAP = {
    "LUNCH": "LUNCH",
    "SIANG": "LUNCH",
    "DINNER": "DINNER",
    "MALAM": "DINNER",
}

MEAL_LABEL_MAP = {
    "LUNCH": "Makan Siang",
    "DINNER": "Makan Malam",
}


def split_containers(qty: int, max_per: int = 20) -> list[int]:
    """Bagi porsi ke dalam wadah secara rata, sisa ditaruh di wadah-wadah awal.

    Contoh max 20:
    45 -> [15, 15, 15]
    50 -> [17, 17, 16]
    12 -> [12]
    """
    if qty <= 0:
        return []
    if max_per <= 0:
        raise ValueError("max_per harus lebih dari 0")

    n_wadah = math.ceil(qty / max_per)
    base = qty // n_wadah
    rem = qty % n_wadah
    return [base + 1 if i < rem else base for i in range(n_wadah)]


def get_kitchen_max_portions_per_container(branch_id: int | None) -> int:
    """Ambil batas maksimal porsi per wadah cabang (default 20, batas 15-20)."""
    if not branch_id:
        return DEFAULT_MAX_PORTIONS_PER_CONTAINER

    setting = BranchSetting.query.filter_by(
        branch_id=branch_id,
        setting_key="kitchen.max_portions_per_container",
    ).first()

    if setting and setting.setting_value:
        try:
            val = int(str(setting.setting_value).strip())
            if MIN_PORTIONS_PER_CONTAINER <= val <= MAX_PORTIONS_PER_CONTAINER:
                return val
        except (ValueError, TypeError):
            pass

    return DEFAULT_MAX_PORTIONS_PER_CONTAINER


def normalize_meal_type(meal_type: str) -> str:
    cleaned = (meal_type or "").strip().upper()
    if cleaned in MEAL_TYPE_MAP:
        return MEAL_TYPE_MAP[cleaned]
    raise ValueError(f"Sesi tidak valid: {meal_type}. Gunakan Siang/Malam (LUNCH/DINNER).")


def calculate_order_session_hash(daily_order: DailyOrder, meal_type: str) -> str:
    """Sidik isi (hash SHA-256) dari daftar detail+porsi pesanan sesi ini."""
    norm_meal = normalize_meal_type(meal_type)
    items = []
    for detail in sorted(daily_order.details, key=lambda d: d.id):
        qty = detail.lunch_qty if norm_meal == "LUNCH" else detail.dinner_qty
        if qty > 0:
            items.append(f"{detail.id}:{detail.mandor_id}:{detail.delivery_location_id}:{qty}")
    payload = ",".join(items)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def get_session_print_history(daily_order: DailyOrder, meal_type: str) -> dict[str, Any]:
    """Ambil riwayat cetak terakhir untuk sesi ini dan status apakah data berubah (stale)."""
    norm_meal = normalize_meal_type(meal_type)
    current_hash = calculate_order_session_hash(daily_order, norm_meal)

    logs = (
        AuditLog.query.filter(
            AuditLog.module == "KITCHEN",
            AuditLog.table_name == "daily_orders",
            AuditLog.record_id == daily_order.id,
            AuditLog.event_type.in_(("KITCHEN_RECAP_PRINTED", "CONTAINER_LABEL_PRINTED")),
        )
        .order_by(AuditLog.id.desc())
        .all()
    )

    last_recap = None
    last_label = None

    for log in logs:
        meta = {}
        if log.metadata_json:
            try:
                meta = json.loads(log.metadata_json)
            except Exception:
                meta = {}
        if meta.get("meal_type") == norm_meal:
            if log.event_type == "KITCHEN_RECAP_PRINTED" and not last_recap:
                last_recap = {"log": log, "meta": meta, "hash": meta.get("content_hash")}
            elif log.event_type == "CONTAINER_LABEL_PRINTED" and not last_label:
                last_label = {"log": log, "meta": meta, "hash": meta.get("content_hash")}

    recap_stale = bool(last_recap and last_recap.get("hash") != current_hash)
    label_stale = bool(last_label and last_label.get("hash") != current_hash)

    return {
        "current_hash": current_hash,
        "last_recap": last_recap,
        "last_label": last_label,
        "recap_stale": recap_stale,
        "label_stale": label_stale,
        "has_printed": bool(last_recap or last_label),
        "is_recap_printed": bool(last_recap),
        "is_label_printed": bool(last_label),
        "recap_history": last_recap["meta"] if last_recap else None,
        "label_history": last_label["meta"] if last_label else None,
        "any_stale": recap_stale or label_stale,
    }


def record_print_event(
    user,
    daily_order: DailyOrder,
    meal_type: str,
    print_type: str,  # "RECAP" or "LABEL"
    paper_size: str,  # "A4", "58mm", "80mm"
):
    norm_meal = normalize_meal_type(meal_type)
    content_hash = calculate_order_session_hash(daily_order, norm_meal)
    event_type = "KITCHEN_RECAP_PRINTED" if print_type == "RECAP" else "CONTAINER_LABEL_PRINTED"
    desc = (
        f"Rekap Dapur {MEAL_LABEL_MAP[norm_meal]} dicetak (kertas {paper_size})."
        if print_type == "RECAP"
        else f"Label Wadah {MEAL_LABEL_MAP[norm_meal]} dicetak ({paper_size})."
    )

    meta = {
        "meal_type": norm_meal,
        "print_type": print_type,
        "paper_size": paper_size,
        "content_hash": content_hash,
        "printed_at": now_wib().isoformat(),
        "printed_by": user.id,
        "printed_by_name": getattr(user, "full_name", user.username),
    }

    record_critical_audit_log(
        module="KITCHEN",
        event_type=event_type,
        action="PRINT",
        table_name="daily_orders",
        record_id=daily_order.id,
        description=desc,
        metadata=meta,
        user_id=user.id,
        branch_id=daily_order.branch_id,
        commit=True,
    )


def build_kitchen_recap_data(daily_order: DailyOrder, meal_type: str) -> dict[str, Any]:
    if not daily_order.is_locked:
        raise ValueError("Rekap Dapur hanya dapat dicetak setelah pesanan dikunci (locked).")

    norm_meal = normalize_meal_type(meal_type)
    max_per = get_kitchen_max_portions_per_container(daily_order.branch_id)

    rows = []
    total_portions = 0
    total_containers = 0

    details = DailyOrderDetail.query.filter_by(daily_order_id=daily_order.id).all()

    for detail in details:
        qty = detail.lunch_qty if norm_meal == "LUNCH" else detail.dinner_qty
        if qty <= 0:
            continue

        containers = split_containers(qty, max_per)
        n_wadah = len(containers)
        total_portions += qty
        total_containers += n_wadah

        client_name = "-"
        sub_client_name = ""
        if detail.mandor:
            if detail.mandor.client:
                client_name = detail.mandor.client.name
            if not getattr(detail.mandor, "is_direct_unit", False):
                sub_client_name = detail.mandor.name
            elif client_name == "-":
                client_name = detail.mandor.name

        loc_name = detail.delivery_location.location_name if detail.delivery_location else "-"
        loc_desc = detail.delivery_location.description if detail.delivery_location else ""

        rows.append({
            "detail_id": detail.id,
            "client_name": client_name,
            "sub_client_name": sub_client_name,
            "location_name": loc_name,
            "location_description": loc_desc,
            "portion": qty,
            "container_count": n_wadah,
            "containers_breakdown": ", ".join(f"{c}" for c in containers),
            "notes": detail.notes or "-",
        })

    rows.sort(key=lambda r: (r["client_name"].lower(), r["location_name"].lower()))
    for idx, row in enumerate(rows, start=1):
        row["no"] = idx

    print_status = get_session_print_history(daily_order, norm_meal)

    from app.models.master import MenuSchedule

    schedule = (
        MenuSchedule.query.filter_by(
            branch_id=daily_order.branch_id,
            menu_date=daily_order.order_date,
            meal_type=norm_meal,
        ).first()
    )
    scheduled_menu_name = schedule.menu.menu_name if (schedule and schedule.menu) else None

    return {
        "daily_order": daily_order,
        "meal_type": norm_meal,
        "meal_label": MEAL_LABEL_MAP[norm_meal],
        "scheduled_menu_name": scheduled_menu_name,
        "max_per_container": max_per,
        "rows": rows,
        "total_portions": total_portions,
        "total_containers": total_containers,
        "print_status": print_status,
    }


def build_container_labels_data(daily_order: DailyOrder, meal_type: str, paper_size: str = "58mm") -> dict[str, Any]:
    if not daily_order.is_locked:
        raise ValueError("Label wadah hanya dapat dicetak setelah pesanan dikunci (locked).")

    norm_meal = normalize_meal_type(meal_type)
    max_per = get_kitchen_max_portions_per_container(daily_order.branch_id)

    deliveries = (
        Delivery.query.filter(
            Delivery.branch_id == daily_order.branch_id,
            Delivery.delivery_date == daily_order.order_date,
            Delivery.status != "CANCELLED",
        ).all()
    )

    session_deliveries = [
        d for d in deliveries
        if (norm_meal == "LUNCH" and "delivery_type=LUNCH" in (d.notes or ""))
        or (norm_meal == "DINNER" and "delivery_type=DINNER" in (d.notes or ""))
        or (norm_meal in (d.delivery_number or ""))
    ]

    delivery_detail_seq_map = {}
    if session_deliveries:
        for d in session_deliveries:
            for seq_idx, dd in enumerate(d.details, start=1):
                delivery_detail_seq_map[dd.daily_order_detail_id] = seq_idx

    details = DailyOrderDetail.query.filter_by(daily_order_id=daily_order.id).all()

    active_details = []
    for detail in details:
        qty = detail.lunch_qty if norm_meal == "LUNCH" else detail.dinner_qty
        if qty > 0:
            active_details.append((detail, qty))

    has_delivery_sequence = bool(delivery_detail_seq_map)
    if has_delivery_sequence:
        active_details.sort(key=lambda item: delivery_detail_seq_map.get(item[0].id, 9999))
    else:
        active_details.sort(key=lambda item: (item[0].delivery_location.location_name.lower() if item[0].delivery_location else ""))

    labels = []
    total_containers_count = 0

    for detail, qty in active_details:
        containers = split_containers(qty, max_per)
        n_wadah = len(containers)
        total_containers_count += n_wadah

        client_name = "-"
        sub_client_name = ""
        if detail.mandor:
            if detail.mandor.client:
                client_name = detail.mandor.client.name
            if not getattr(detail.mandor, "is_direct_unit", False):
                sub_client_name = detail.mandor.name
            elif client_name == "-":
                client_name = detail.mandor.name

        loc = detail.delivery_location
        loc_name = loc.location_name if loc else "-"
        loc_desc = loc.description if loc else "-"

        receiver_name = "-"
        receiver_phone = "-"
        if detail.mandor and detail.mandor.phone:
            receiver_phone = detail.mandor.phone
            receiver_name = detail.mandor.name
        elif detail.mandor and detail.mandor.client and detail.mandor.client.phone:
            receiver_phone = detail.mandor.client.phone
            receiver_name = detail.mandor.client.name

        seq_num = delivery_detail_seq_map.get(detail.id) if has_delivery_sequence else None

        for idx, portion in enumerate(containers, start=1):
            container_scan_url = url_for(
                "delivery.scan_qr",
                daily_order_detail_id=detail.id,
                sesi=norm_meal,
                w=idx,
                n=n_wadah,
                _external=True,
            )
            container_qr_obj = segno.make(container_scan_url, error="m")
            container_qr_svg = container_qr_obj.svg_inline(scale=2, border=1)

            labels.append({
                "detail_id": detail.id,
                "customer_name": client_name,
                "sub_client_name": sub_client_name,
                "portion": portion,
                "total_order_portions": qty,
                "container_index": idx,
                "container_total": n_wadah,
                "container_label": f"Wadah {idx}/{n_wadah}",
                "location_name": loc_name,
                "location_benchmark": loc_desc,
                "receiver_name": receiver_name,
                "receiver_phone": receiver_phone,
                "date_str": daily_order.order_date.strftime("%d/%m/%Y"),
                "session_label": "Siang" if norm_meal == "LUNCH" else "Malam",
                "seq_number": seq_num,
                "scan_url": container_scan_url,
                "qr_svg": container_qr_svg,
            })

    print_status = get_session_print_history(daily_order, norm_meal)

    return {
        "daily_order": daily_order,
        "meal_type": norm_meal,
        "meal_label": MEAL_LABEL_MAP[norm_meal],
        "paper_size": paper_size,
        "labels": labels,
        "total_containers": total_containers_count,
        "print_status": print_status,
    }
