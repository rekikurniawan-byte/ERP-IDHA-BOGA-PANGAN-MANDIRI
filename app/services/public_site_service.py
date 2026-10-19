"""Data halaman publik (beranda, masuk, daftar): semua angka dibaca dari ERP.

Hanya membaca. Setiap bagian dibaca terpisah; kalau satu bagian gagal (tabel
belum ada, data kosong) bagian itu bernilai None dan halaman tetap tampil.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from decimal import Decimal

from app.utils.clock import today_wib

from sqlalchemy import func

from app.extensions import db

logger = logging.getLogger(__name__)

COMPANY_EMAIL = "idhabogapanganmandiri@gmail.com"
MENU_TYPE_LABELS = {"CATERING": "Katering harian", "BOX": "Nasi kotak", "SNACK": "Snack", "CUSTOM": "Pesanan khusus"}


MONTHS_SHORT = ("Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des")


def _main_branch():
    from app.models.master import Branch

    return Branch.query.filter_by(is_active=True).order_by(Branch.id.asc()).first()


def main_branch_id():
    branch = _safe("cabang", _main_branch)
    return branch.id if branch else None


def _common(branch):
    from flask import current_app

    from app.services.company_settings_service import get_company_settings

    settings = _safe("pengaturan perusahaan", lambda: get_company_settings(branch.id)) if branch else None
    email = str((settings or {}).get("company_email") or "").strip()
    return {
        "whatsapp_url": whatsapp_link((settings or {}).get("company_phone")),
        # Alamat contoh (.local/example) diganti email resmi perusahaan.
        "email": email if "@" in email and not email.endswith((".local", "example.com")) else COMPANY_EMAIL,
        "portal_enabled": bool(current_app.config.get("PORTAL_ENABLED", False)),
        "year": today_wib().year,
    }


def _safe(label, reader):
    try:
        return reader()
    except Exception:  # bagian publik tidak boleh menjatuhkan halaman
        db.session.rollback()
        logger.exception("Data halaman publik gagal dibaca: %s", label)
        return None


def _performance(branch_id, today):
    """Kinerja pengiriman 30 hari terakhir + porsi terkirim per hari (grafik mini)."""
    from app.models.delivery import Delivery, DeliveryDetail
    from app.services.dashboard_analytics_service import get_operational_efficiency_chart_data

    start = today - timedelta(days=29)
    efficiency = get_operational_efficiency_chart_data(branch_id, start.isoformat(), today.isoformat())
    rows = (
        db.session.query(Delivery.delivery_date, func.coalesce(func.sum(DeliveryDetail.delivered_qty), 0))
        .join(DeliveryDetail, DeliveryDetail.delivery_id == Delivery.id)
        .filter(Delivery.branch_id == branch_id, Delivery.delivery_date >= start, Delivery.delivery_date <= today)
        .group_by(Delivery.delivery_date)
        .all()
    )
    per_day = {row[0]: int(row[1] or 0) for row in rows}
    days = [start + timedelta(days=i) for i in range(30)]
    series = [{"label": f"{day.day} {MONTHS_SHORT[day.month - 1]}", "qty": per_day.get(day, 0)} for day in days]
    delivered = sum(item["qty"] for item in series)
    if not delivered:
        return None
    return {
        "delivered_qty": delivered,
        "on_time_rate": round(float(efficiency.get("ok_rate") or 0), 1) if not efficiency.get("is_empty") else None,
        "delivery_count": int(efficiency.get("total") or 0),
        "days_served": sum(1 for item in series if item["qty"]),
        "series": series,
    }


def _arrivals(branch_id, today):
    """Rata-rata jam tiba makan siang & sore 30 hari terakhir, dalam WIB.

    receive_time disimpan UTC (delivery_service memakai datetime.utcnow)."""
    from app.models.delivery import Delivery, DeliveryDetail, DeliveryReceipt
    from app.services.delivery_service import get_delivery_type_from_notes
    from app.utils.clock import to_wib

    start = today - timedelta(days=29)
    rows = (
        db.session.query(Delivery.notes, DeliveryReceipt.receive_time)
        .join(DeliveryDetail, DeliveryDetail.delivery_id == Delivery.id)
        .join(DeliveryReceipt, DeliveryReceipt.delivery_detail_id == DeliveryDetail.id)
        .filter(Delivery.branch_id == branch_id, Delivery.delivery_date >= start, Delivery.delivery_date <= today)
        .all()
    )
    minutes = {"LUNCH": [], "DINNER": []}
    for notes, received in rows:
        kind = get_delivery_type_from_notes(notes)
        if kind in minutes and received is not None:
            local = to_wib(received)
            minutes[kind].append(local.hour * 60 + local.minute)
    result = {}
    for kind, values in minutes.items():
        if len(values) >= 3:
            average = round(sum(values) / len(values))
            result[kind] = f"{average // 60:02d}.{average % 60:02d}"
    return result


def _locations(branch_id):
    from app.models.master import DeliveryLocation, Mandor

    return (
        DeliveryLocation.query.join(Mandor, Mandor.id == DeliveryLocation.mandor_id)
        .filter(Mandor.branch_id == branch_id, DeliveryLocation.is_active.is_(True), Mandor.is_active.is_(True))
        .count()
    )


def _pricing(branch_id, today):
    from app.services.pricing_service import (
        active_zones,
        fee_in_effect,
        free_delivery_min_portions,
        general_min_portions,
        quote_price,
    )

    quote = quote_price(branch_id, None, today)
    zones = []
    for zone in active_zones(branch_id):
        fee = fee_in_effect(branch_id, zone_id=zone.id, on_date=today)
        if fee is not None:
            zones.append({"id": zone.id, "name": zone.name, "fee": float(Decimal(fee.fee))})
    from app.services.geo_service import distance_fee_settings

    distance = distance_fee_settings(branch_id)
    return {
        "price": float(quote.price) if quote else None,
        "zones": zones,
        "min_portions": general_min_portions(branch_id),
        "free_delivery_min": free_delivery_min_portions(branch_id),
        # Ongkir per km dari titik dapur (keputusan owner 2026-10-04).
        "distance": {
            "per_km": float(distance["per_km"]),
            "minimum": float(distance["minimum"]),
            "road_factor": float(distance["road_factor"]),
            "origin_label": distance["origin"]["label"] if distance["origin"] else None,
        } if distance["enabled"] else None,
    }


def _menus(branch_id):
    from app.models.master import Menu

    menus = Menu.query.filter_by(branch_id=branch_id, is_active=True).order_by(Menu.menu_name.asc()).limit(8).all()
    return [{"name": menu.menu_name, "type": MENU_TYPE_LABELS.get(menu.menu_type, "Katering")} for menu in menus]


def _cutoffs():
    from app.services.portal_order_draft_service import PORTAL_CUTOFF_TIMES

    return {key: value.strftime("%H.%M") for key, value in PORTAL_CUTOFF_TIMES.items()}


def whatsapp_link(phone):
    digits = "".join(ch for ch in str(phone or "") if ch.isdigit())
    if digits.startswith("0"):
        digits = "62" + digits[1:]
    if len(digits) < 9 or sum(ch != "0" for ch in digits[2:]) <= 1:  # nomor contoh 0800...0
        return None
    return f"https://wa.me/{digits}"


def _menu_week(branch_id, today):
    from app.services.menu_schedule_service import get_weekly_schedule_matrix

    end_date = today + timedelta(days=6)
    m1 = get_weekly_schedule_matrix(branch_id, today)
    all_days = list(m1.get("days") or [])
    if end_date > m1["end_sunday"]:
        m2 = get_weekly_schedule_matrix(branch_id, end_date)
        all_days.extend(m2.get("days") or [])

    week_days = [d for d in all_days if today <= d["date"] <= end_date]
    week_days.sort(key=lambda x: x["date"])

    has_any = any(
        (d.get("lunch") and d["lunch"].get("menu") and d["lunch"]["menu"].is_active) or
        (d.get("dinner") and d["dinner"].get("menu") and d["dinner"]["menu"].is_active)
        for d in week_days
    )
    if not has_any:
        return None

    items = []
    for d in week_days:
        lunch = d.get("lunch") or {}
        dinner = d.get("dinner") or {}
        l_raw = lunch.get("menu")
        d_raw = dinner.get("menu")
        l_menu = l_raw if (l_raw and getattr(l_raw, "is_active", False)) else None
        d_menu = d_raw if (d_raw and getattr(d_raw, "is_active", False)) else None
        l_photo = lunch.get("photo") if l_menu else None
        d_photo = dinner.get("photo") if d_menu else None

        items.append({
            "date": d["date"],
            "date_str": d.get("date_str") or d["date"].strftime("%Y-%m-%d"),
            "day_name": d.get("day_name") or d["date"].strftime("%A"),
            "is_today": d.get("is_today", False),
            "lunch_name": l_menu.menu_name if l_menu else None,
            "lunch_photo_id": l_photo.id if l_photo else None,
            "dinner_name": d_menu.menu_name if d_menu else None,
            "dinner_photo_id": d_photo.id if d_photo else None,
            "primary_photo_id": l_photo.id if l_photo else (d_photo.id if d_photo else None),
            "has_menu": bool(l_menu or d_menu),
        })
    return items


def landing_context(today=None):
    today = today or today_wib()
    branch = _safe("cabang", _main_branch)
    if not branch:
        return {"performance": None, "arrivals": {}, "locations": None, "pricing": None, "menus": [], "weekly_menus": [],
                "menu_week": None, "cutoffs": _safe("batas pesan", _cutoffs) or {}, **_common(None)}
    return {
        **_common(branch),
        "performance": _safe("kinerja", lambda: _performance(branch.id, today)),
        "arrivals": _safe("jam tiba", lambda: _arrivals(branch.id, today)) or {},
        "locations": _safe("lokasi", lambda: _locations(branch.id)),
        "pricing": _safe("harga", lambda: _pricing(branch.id, today)),
        "menus": _safe("menu", lambda: _menus(branch.id)) or [],
        "weekly_menus": _safe(
            "menu mingguan",
            lambda: __import__("app.services.menu_schedule_service", fromlist=["get_public_weekly_menu"]).get_public_weekly_menu(branch.id, today),
        ) or [],
        "menu_week": _safe("menu minggu ini", lambda: _menu_week(branch.id, today)),
        "cutoffs": _safe("batas pesan", _cutoffs) or {},
    }


def auth_context(today=None):
    """Ringkasan aturan untuk panel samping halaman masuk & daftar."""
    today = today or today_wib()
    branch = _safe("cabang", _main_branch)
    pricing = _safe("harga", lambda: _pricing(branch.id, today)) if branch else None
    arrivals = _safe("jam tiba", lambda: _arrivals(branch.id, today)) if branch else None
    return {"pricing": pricing, "cutoffs": _safe("batas pesan", _cutoffs) or {}, "arrivals": arrivals or {},
            "geo": geo_context(branch), **_common(branch)}


def geo_context(branch=None):
    """Titik dapur + tarif per km untuk pemilih titik lokasi di halaman publik."""
    from app.services.geo_service import picker_context

    branch = branch or _safe("cabang", _main_branch)
    return _safe("titik dapur", lambda: picker_context(branch.id)) if branch else None


def partnership_context(today=None):
    """Halaman /kerja-sama: aturan pesan, jam tiba, dan titik dapur untuk peta."""
    today = today or today_wib()
    branch = _safe("cabang", _main_branch)
    if not branch:
        return {"pricing": None, "cutoffs": _safe("batas pesan", _cutoffs) or {}, "arrivals": {}, "geo": None,
                "performance": None, **_common(None)}
    return {
        **_common(branch),
        "pricing": _safe("harga", lambda: _pricing(branch.id, today)),
        "cutoffs": _safe("batas pesan", _cutoffs) or {},
        "arrivals": _safe("jam tiba", lambda: _arrivals(branch.id, today)) or {},
        "performance": _safe("kinerja", lambda: _performance(branch.id, today)),
        "geo": geo_context(branch),
    }
