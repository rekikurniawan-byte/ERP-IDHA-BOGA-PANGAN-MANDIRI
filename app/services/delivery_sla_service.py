from datetime import date, datetime, time, timedelta
from typing import Any

from app.models.delivery import Delivery, DeliveryDetail
from app.models.production import Production
from app.services.delivery_service import get_delivery_type_from_notes
from app.utils.clock import now_wib, to_wib


DELIVERY_SLA_DEFAULTS = {
    "LUNCH": {
        "label": "Siang",
        "target_dispatch": time(10, 30),
        "target_arrival": time(11, 30),
        "target_ready": time(10, 0),
        "tolerance_minutes": 15,
    },
    "DINNER": {
        "label": "Sore",
        "target_dispatch": time(16, 30),
        "target_arrival": time(17, 30),
        "target_ready": time(16, 0),
        "tolerance_minutes": 15,
    },
}

STATUS_LABELS = {
    "ON_TIME": "Tepat Waktu",
    "LATE": "Terlambat",
    "RISK": "Berisiko Late",
    "SHORTAGE": "Shortage",
    "PENDING": "Menunggu Terima",
    "CANCELLED": "Dibatalkan",
    "NOT_SET": "SLA Belum Lengkap",
    "COMPLETED_NO_TIME": "Selesai, Jam Belum Tercatat",
}

STATUS_BADGE_CLASS = {
    "ON_TIME": "status-locked",
    "LATE": "status-danger",
    "RISK": "status-warning",
    "SHORTAGE": "status-danger",
    "PENDING": "status-draft",
    "CANCELLED": "status-cancelled",
    "NOT_SET": "status-warning",
    "COMPLETED_NO_TIME": "status-progress",
}


def _combine(day_value: date | None, clock_value: time | None) -> datetime | None:
    if not day_value or not clock_value:
        return None
    return datetime.combine(day_value, clock_value)


def _minutes_between(start: datetime | None, end: datetime | None) -> int | None:
    if not start or not end:
        return None
    return int(round((end - start).total_seconds() / 60))


def _fmt_dt(value: datetime | None) -> str:
    if not value:
        return "-"
    return value.strftime("%d-%m-%Y %H:%M")


def _fmt_time(value: datetime | None) -> str:
    if not value:
        return "-"
    return value.strftime("%H:%M")


def get_delivery_sla_defaults(delivery_date: date | None, delivery_type: str | None) -> dict[str, Any]:
    config = DELIVERY_SLA_DEFAULTS.get(delivery_type or "", DELIVERY_SLA_DEFAULTS["LUNCH"])
    return {
        "delivery_type": delivery_type,
        "label": config["label"],
        "target_dispatch_time": _combine(delivery_date, config["target_dispatch"]),
        "target_arrival_time": _combine(delivery_date, config["target_arrival"]),
        "late_tolerance_minutes": config["tolerance_minutes"],
    }


def get_production_sla_defaults(production_date: date | None, production_type: str | None) -> dict[str, Any]:
    config = DELIVERY_SLA_DEFAULTS.get(production_type or "", DELIVERY_SLA_DEFAULTS["LUNCH"])
    return {
        "production_type": production_type,
        "label": config["label"],
        "target_ready_time": _combine(production_date, config["target_ready"]),
        "late_tolerance_minutes": 0,
    }


def ensure_delivery_sla_values(delivery: Delivery) -> dict[str, Any]:
    delivery_type = get_delivery_type_from_notes(delivery.notes)
    defaults = get_delivery_sla_defaults(delivery.delivery_date, delivery_type)
    target_dispatch = delivery.target_dispatch_time or defaults["target_dispatch_time"]
    target_arrival = delivery.target_arrival_time or defaults["target_arrival_time"]
    tolerance = delivery.late_tolerance_minutes
    if tolerance is None:
        tolerance = defaults["late_tolerance_minutes"]
    return {
        "delivery_type": delivery_type,
        "label": defaults["label"],
        "target_dispatch_time": target_dispatch,
        "target_arrival_time": target_arrival,
        # Disimpan UTC; target adalah jam dinding WIB.
        "actual_departure_time": to_wib(delivery.actual_departure_time),
        "late_tolerance_minutes": tolerance,
        "late_limit_time": target_arrival + timedelta(minutes=int(tolerance or 0)) if target_arrival else None,
    }


def calculate_delivery_detail_sla(detail: DeliveryDetail, now: datetime | None = None) -> dict[str, Any]:
    # now dan jam terima disimpan UTC; target_arrival = tanggal kirim + jam WIB.
    # Bandingkan dalam WIB (dulu UTC vs WIB: telat 7 jam pun tercatat tepat waktu).
    now = to_wib(now) if now else now_wib()
    delivery = detail.delivery
    if not delivery:
        return {"status": "NOT_SET", "label": STATUS_LABELS["NOT_SET"], "badge_class": STATUS_BADGE_CLASS["NOT_SET"]}

    base = ensure_delivery_sla_values(delivery)
    target_arrival = base.get("target_arrival_time")
    late_limit = base.get("late_limit_time")
    receipt = detail.receipt
    actual_receive = to_wib(receipt.receive_time) if receipt else None
    minutes_late = 0
    reason = "Menunggu penerimaan."
    status = "PENDING"

    if delivery.status == "CANCELLED":
        status = "CANCELLED"
        reason = "Delivery dibatalkan dan tidak dihitung SLA."
    elif receipt and int(detail.shortage_qty or 0) > 0:
        status = "SHORTAGE"
        reason = "Porsi diterima lebih kecil dari planned qty."
        minutes_late = max(_minutes_between(late_limit, actual_receive) or 0, 0) if late_limit else 0
    elif receipt:
        if target_arrival and late_limit:
            minutes_late = max(_minutes_between(late_limit, actual_receive) or 0, 0)
            if actual_receive <= late_limit:
                status = "ON_TIME"
                reason = "Diterima sebelum batas toleransi SLA."
            else:
                status = "LATE"
                reason = f"Diterima lewat batas SLA {minutes_late} menit."
        else:
            status = "NOT_SET"
            reason = "Target arrival belum tersedia."
    else:
        if late_limit and now > late_limit:
            status = "LATE"
            minutes_late = max(_minutes_between(late_limit, now) or 0, 0)
            reason = f"Belum ada penerimaan dan sudah lewat SLA {minutes_late} menit."
        elif target_arrival and (target_arrival - timedelta(minutes=60)) <= now <= late_limit:
            status = "RISK"
            reason = "Mendekati target arrival, belum ada penerimaan."
        elif not target_arrival:
            status = "NOT_SET"
            reason = "Target arrival belum tersedia."

    return {
        **base,
        "status": status,
        "label": STATUS_LABELS.get(status, status),
        "badge_class": STATUS_BADGE_CLASS.get(status, "status-draft"),
        "reason": reason,
        "actual_receive_time": actual_receive,
        "minutes_late": int(minutes_late or 0),
        "target_arrival_label": _fmt_dt(target_arrival),
        "late_limit_label": _fmt_dt(late_limit),
        "actual_receive_label": _fmt_dt(actual_receive),
    }


def calculate_delivery_sla_summary(delivery: Delivery, now: datetime | None = None) -> dict[str, Any]:
    detail_statuses = [calculate_delivery_detail_sla(detail, now=now) for detail in delivery.details]
    statuses = [item.get("status") for item in detail_statuses]
    total_planned = sum(int(detail.planned_qty or 0) for detail in delivery.details)
    total_delivered = sum(int(detail.delivered_qty or 0) for detail in delivery.details)
    max_minutes_late = max([int(item.get("minutes_late") or 0) for item in detail_statuses] or [0])

    if delivery.status == "CANCELLED":
        aggregate = "CANCELLED"
    elif "SHORTAGE" in statuses:
        aggregate = "SHORTAGE"
    elif "LATE" in statuses:
        aggregate = "LATE"
    elif "RISK" in statuses:
        aggregate = "RISK"
    elif statuses and all(status == "ON_TIME" for status in statuses):
        aggregate = "ON_TIME"
    elif "NOT_SET" in statuses:
        aggregate = "NOT_SET"
    else:
        aggregate = "PENDING"

    base = ensure_delivery_sla_values(delivery)
    return {
        **base,
        "status": aggregate,
        "label": STATUS_LABELS.get(aggregate, aggregate),
        "badge_class": STATUS_BADGE_CLASS.get(aggregate, "status-draft"),
        "details": detail_statuses,
        "total_planned": total_planned,
        "total_delivered": total_delivered,
        "shortage_qty": max(total_planned - total_delivered, 0),
        "max_minutes_late": max_minutes_late,
        "target_dispatch_label": _fmt_time(base.get("target_dispatch_time")),
        "target_arrival_label": _fmt_time(base.get("target_arrival_time")),
        "late_limit_label": _fmt_time(base.get("late_limit_time")),
        "actual_departure_label": _fmt_time(base.get("actual_departure_time")),
    }


def calculate_production_sla(production: Production, now: datetime | None = None) -> dict[str, Any]:
    now = to_wib(now) if now else now_wib()
    defaults = get_production_sla_defaults(production.production_date, production.production_type)
    target_ready = production.target_ready_time or defaults["target_ready_time"]
    tolerance = production.late_tolerance_minutes
    if tolerance is None:
        tolerance = defaults["late_tolerance_minutes"]
    late_limit = target_ready + timedelta(minutes=int(tolerance or 0)) if target_ready else None
    actual_completed = to_wib(production.actual_completed_time)

    if production.status == "CANCELLED":
        status = "CANCELLED"
        reason = "Produksi dibatalkan."
        minutes_late = 0
    elif production.status == "COMPLETED":
        if actual_completed and late_limit:
            minutes_late = max(_minutes_between(late_limit, actual_completed) or 0, 0)
            status = "ON_TIME" if actual_completed <= late_limit else "LATE"
            reason = "Produksi selesai sebelum SLA." if status == "ON_TIME" else f"Produksi selesai terlambat {minutes_late} menit."
        else:
            status = "COMPLETED_NO_TIME"
            reason = "Produksi sudah COMPLETED, tetapi jam selesai belum tercatat dari data lama."
            minutes_late = 0
    else:
        if late_limit and now > late_limit:
            status = "RISK"
            minutes_late = max(_minutes_between(late_limit, now) or 0, 0)
            reason = f"Produksi belum completed dan target siap sudah lewat {minutes_late} menit."
        elif target_ready and (target_ready - timedelta(minutes=60)) <= now <= late_limit:
            status = "RISK"
            minutes_late = 0
            reason = "Mendekati target siap produksi."
        elif not target_ready:
            status = "NOT_SET"
            reason = "Target ready produksi belum tersedia."
            minutes_late = 0
        else:
            status = "PENDING"
            reason = "Produksi masih dalam batas waktu."
            minutes_late = 0

    return {
        "status": status,
        "label": STATUS_LABELS.get(status, status),
        "badge_class": STATUS_BADGE_CLASS.get(status, "status-draft"),
        "reason": reason,
        "target_ready_time": target_ready,
        "target_ready_label": _fmt_time(target_ready),
        "late_limit_time": late_limit,
        "late_limit_label": _fmt_time(late_limit),
        "actual_completed_time": actual_completed,
        "actual_completed_label": _fmt_time(actual_completed),
        "late_tolerance_minutes": int(tolerance or 0),
        "minutes_late": int(minutes_late or 0),
    }
