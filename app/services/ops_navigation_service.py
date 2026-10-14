"""Peta navigasi mobile operasional (ADMIN_OPERASIONAL): satu sumber untuk tab bawah, sub-tab, dan tautan kembali.

Aturan owner (2026-10-10 & 2026-10-11):
- Setiap halaman hanya punya SATU pintu.
- Tab bawah 5:
  1. Beranda = ringkasan hari ini (jumlah pesanan & porsi per sesi, draf portal menunggu, produksi, pengiriman berjalan, kendala) TANPA tombol pintasan.
  2. Pesanan = sub-tab: Hari Ini (operational.orders) · Draf Portal (portal.admin_order_drafts) · Perubahan Porsi (operational.order_qty_changes) · Jadwal Menu (operational.menu_schedule).
  3. Dapur = sub-tab: Produksi (production.index) · Rekap Dapur (operational.kitchen_recap_hub) · Apel Tim (workforce.attendance).
  4. Antar = sub-tab: Pengiriman (delivery.today) · Serah Terima (delivery.receiving).
  4b. Warung (2026-10-13) = kasir cepat (canteen.quick_sale); belanja & bayar hutang di satu layar.
      Tab ini hanya tampil bila modul Warung cabang aktif.
  5. Akun = Akun Saya + ganti password + SOP + tombol Keluar (Keluar HANYA di sini).
- Notifikasi hanya lewat lonceng di header (settings.notifications).
- Halaman rincian memakai panah kembali ke daftar asalnya, sub-tab disembunyikan.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from flask import request, url_for

ROLE_ADMIN_OPERASIONAL = "ADMIN_OPERASIONAL"

HOME_ENDPOINTS = ["dashboard.ops", "dashboard.ops_door"]


def _seg(label: str, endpoint: str, also: tuple = ()):
    """Satu sub-tab: label, endpoint utama, dan endpoint turunan."""
    return {"label": label, "endpoint": endpoint, "endpoints": [endpoint, *also]}


def ops_navigation_map() -> Dict[str, Any]:
    """Peta mentah navigasi operasional (tanpa URL) agar bisa diuji tanpa request context."""
    pesanan_segments = [
        _seg("Hari Ini", "operational.orders"),
        _seg("Draf Portal", "portal.admin_order_drafts"),
        _seg("Perubahan Porsi", "operational.order_qty_changes"),
        _seg("Jadwal Menu", "operational.menu_schedule"),
    ]
    dapur_segments = [
        _seg("Produksi", "production.index"),
        _seg("Rekap Dapur", "operational.kitchen_recap_hub"),
        _seg("Apel Tim", "workforce.attendance"),
    ]
    antar_segments = [
        _seg("Pengiriman", "delivery.today"),
        _seg("Serah Terima", "delivery.receiving"),
    ]

    return {
        "tabs": [
            {
                "key": "home",
                "label": "Beranda",
                "icon": "home",
                "endpoint": "dashboard.ops",
                "endpoints": HOME_ENDPOINTS,
                "segments": [],
            },
            {
                "key": "orders",
                "label": "Pesanan",
                "icon": "receipt_long",
                "endpoint": "operational.orders",
                "endpoints": [
                    "operational.orders",
                    "portal.admin_order_drafts",
                    "operational.order_qty_changes",
                    "operational.menu_schedule",
                ],
                "segments": pesanan_segments,
            },
            {
                "key": "kitchen",
                "label": "Dapur",
                "icon": "skillet",
                "endpoint": "production.index",
                "endpoints": ["production.index", "operational.kitchen_recap_hub", "workforce.attendance"],
                "segments": dapur_segments,
            },
            {
                "key": "delivery",
                "label": "Antar",
                "icon": "local_shipping",
                "endpoint": "delivery.today",
                "endpoints": ["delivery.today", "delivery.receiving"],
                "segments": antar_segments,
            },
            {
                "key": "warung",
                "label": "Warung",
                "icon": "storefront",
                "endpoint": "canteen.quick_sale",
                "endpoints": ["canteen.quick_sale"],
                "segments": [],
            },
            {
                "key": "account",
                "label": "Akun",
                "icon": "person",
                "endpoint": "settings.account",
                "endpoints": ["settings.account", "settings.change_password"],
                "segments": [],
            },
        ],
    }


def uses_ops_ui(user: Optional[Any] = None) -> bool:
    """True bila role ADMIN_OPERASIONAL, atau role OWNER/ADMIN dan session.get('ops_mode')."""
    from flask import session
    from flask_login import current_user

    u = user if user is not None else current_user
    if not u or not getattr(u, "is_authenticated", False):
        return False
    role = getattr(u, "role", None)
    if role == ROLE_ADMIN_OPERASIONAL:
        return True
    if role in ("OWNER", "ADMIN") and session.get("ops_mode"):
        return True
    return False


def is_ops_context(role: Optional[str] = None, endpoint: Optional[str] = None, user: Optional[Any] = None) -> bool:
    """Tentukan apakah konteks saat ini berada dalam shell mobile operasional."""
    if uses_ops_ui(user):
        return True
    if role == ROLE_ADMIN_OPERASIONAL:
        return True
    if endpoint in ("dashboard.ops", "dashboard.ops_door"):
        return True
    return False



def build_ops_navigation(endpoint: str) -> Dict[str, Any]:
    """Navigasi siap pakai untuk template mobile operasional."""
    from app.services.branch_module_service import WARUNG, module_enabled

    nav = ops_navigation_map()
    if not module_enabled(WARUNG):
        nav["tabs"] = [tab for tab in nav["tabs"] if tab["key"] != "warung"]
    active_key = None

    for tab in nav["tabs"]:
        tab["url"] = url_for(tab["endpoint"])
        for segment in tab["segments"]:
            segment["url"] = url_for(segment["endpoint"])
            segment["active"] = endpoint in segment["endpoints"]
        if any(segment["active"] for segment in tab["segments"]):
            active_key = tab["key"]
        elif endpoint in tab.get("endpoints", [tab["endpoint"]]):
            active_key = active_key or tab["key"]

    # Child pages resolution (detail pesanan, produksi, antar, dll)
    is_child = False
    back_url = None
    back_label = "Kembali"

    if endpoint == "operational.order_detail":
        active_key = "orders"
        is_child = True
        back_url = url_for("operational.orders")
        back_label = "Hari Ini"
    elif endpoint in ("operational.create_order", "operational.add_order_detail", "operational.add_increase_after_lock_route", "operational.create_revision"):
        active_key = "orders"
        is_child = True
        back_url = url_for("operational.orders")
        back_label = "Pesanan"
    elif endpoint == "production.detail":
        active_key = "kitchen"
        is_child = True
        back_url = url_for("production.index")
        back_label = "Produksi"
    elif endpoint in ("operational.kitchen_recap", "operational.container_labels"):
        active_key = "kitchen"
        is_child = True
        back_url = url_for("operational.kitchen_recap_hub")
        back_label = "Rekap Dapur"
    elif endpoint == "workforce.leave_create":
        active_key = "kitchen"
        is_child = True
        back_url = url_for("workforce.attendance")
        back_label = "Apel Tim"
    elif endpoint == "delivery.detail":
        active_key = "delivery"
        is_child = True
        back_url = url_for("delivery.today")
        back_label = "Pengiriman"
    elif endpoint == "delivery.receive":
        active_key = "delivery"
        is_child = True
        back_url = url_for("delivery.receiving")
        back_label = "Serah Terima"
    elif endpoint == "delivery.history":
        active_key = "delivery"
        is_child = True
        back_url = url_for("delivery.today")
        back_label = "Pengiriman"
    elif endpoint in ("delivery.scan", "delivery.scan_qr"):
        active_key = "delivery"
        is_child = True
        back_url = url_for("delivery.receiving")
        back_label = "Serah Terima"
    elif endpoint == "sop.role_sop":
        active_key = "account"
        is_child = True
        back_url = url_for("settings.account")
        back_label = "Akun"
    elif endpoint == "settings.notifications":
        is_child = True
        back_url = url_for("dashboard.ops")
        back_label = "Beranda"

    for tab in nav["tabs"]:
        tab["active"] = tab["key"] == active_key

    active_tab = next((tab for tab in nav["tabs"] if tab["active"]), None)
    # Halaman rincian memakai panah kembali; sub-tab hanya di halaman daftar.
    nav["segments"] = active_tab["segments"] if active_tab and len(active_tab["segments"]) > 1 and not is_child else []
    nav["active_key"] = active_key
    nav["is_child"] = is_child
    nav["back_url"] = back_url
    nav["back_label"] = back_label
    return nav


def get_ops_dashboard_data(branch_id: int) -> Dict[str, Any]:
    """Ringkasan kondisi operasional hari ini untuk Beranda ops mobile."""
    from app.utils.clock import today_wib
    from app.models.operational import DailyOrder
    from app.models.system import PortalOrderDraft
    from app.models.production import Production
    from app.models.delivery import Delivery, DeliveryDetail
    from app.models.complaint import CustomerComplaint

    today = today_wib()

    # 1. Pesanan Harian Hari Ini
    orders = DailyOrder.query.filter_by(branch_id=branch_id, order_date=today).all()
    total_orders = len(orders)
    total_lunch = sum(
        sum(int(d.lunch_qty or 0) for d in o.details) for o in orders
    )
    total_dinner = sum(
        sum(int(d.dinner_qty or 0) for d in o.details) for o in orders
    )
    total_portions = total_lunch + total_dinner
    all_locked = bool(orders) and all(o.is_locked for o in orders)

    # 2. Draf Portal Menunggu Konfirmasi
    drafts = PortalOrderDraft.query.filter_by(branch_id=branch_id, status="PENDING").all()
    draft_count = len(drafts)
    draft_portions = sum(int(d.portion_qty or 0) for d in drafts)

    # 3. Produksi Dapur
    productions = Production.query.filter_by(branch_id=branch_id, production_date=today).all()
    prod_summary = {
        "total": len(productions),
        "completed": sum(1 for p in productions if p.status == "COMPLETED"),
        "in_progress": sum(1 for p in productions if p.status == "IN_PROGRESS"),
        "draft": sum(1 for p in productions if p.status == "DRAFT"),
    }

    # 4. Pengiriman Berjalan
    deliveries = Delivery.query.filter_by(branch_id=branch_id, delivery_date=today).all()
    deliv_summary = {
        "total": len(deliveries),
        "planned": sum(1 for d in deliveries if d.status == "PLANNED"),
        "dispatched": sum(1 for d in deliveries if d.status == "DISPATCHED"),
        "delivered": sum(1 for d in deliveries if d.status == "DELIVERED"),
    }

    # 5. Kendala (Kurang Kirim & Komplain)
    shortage_details = (
        DeliveryDetail.query.join(Delivery)
        .filter(
            Delivery.branch_id == branch_id,
            Delivery.delivery_date == today,
            DeliveryDetail.shortage_qty > 0,
        )
        .all()
    )
    shortage_count = len(shortage_details)

    active_complaints = CustomerComplaint.query.filter(
        CustomerComplaint.branch_id == branch_id,
        CustomerComplaint.status.in_(["SUBMITTED", "IN_REVIEW"]),
    ).all()
    complaints_count = len(active_complaints)

    return {
        "today": today,
        "orders": {
            "total_orders": total_orders,
            "total_lunch": total_lunch,
            "total_dinner": total_dinner,
            "total_portions": total_portions,
            "all_locked": all_locked,
            "items": orders,
        },
        "drafts": {
            "count": draft_count,
            "portions": draft_portions,
            "items": drafts[:5],
        },
        "production": prod_summary,
        "delivery": deliv_summary,
        "issues": {
            "shortage_count": shortage_count,
            "complaints_count": complaints_count,
        },
    }
