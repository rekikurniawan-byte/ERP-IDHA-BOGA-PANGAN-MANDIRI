"""Peta navigasi mobile pengantar (kurir): satu sumber untuk tab bawah, sub-tab, dan tautan kembali.

Aturan owner (2026-10-10 & 2026-10-11):
- Setiap halaman hanya punya SATU pintu.
- Tab bawah 5:
  1. Beranda = dashboard pengantar (ringkasan hari ini, TANPA tombol pintasan ke halaman lain).
  2. Antar = sub-tab: Hari Ini (delivery.today) · Serah Terima (delivery.receiving).
  3. Scan (tombol tengah menonjol) = delivery.scan.
  4. Riwayat = delivery.history.
  5. Akun = Akun Saya + ganti password + tombol Keluar (Keluar HANYA di sini).
- Notifikasi hanya lewat lonceng di header (settings.notifications).
- Halaman rincian (detail pengiriman, form terima) memakai panah kembali ke daftar asalnya -- bukan pintu baru.
"""

from __future__ import annotations

from flask import request, url_for

ROLE_PENGANTAR = "PENGANTAR"

HOME_ENDPOINTS = ["dashboard.pengantar"]


def _seg(label, endpoint, also=()):
    """Satu sub-tab: label, endpoint utama, dan endpoint turunan."""
    return {"label": label, "endpoint": endpoint, "endpoints": [endpoint, *also]}


def driver_navigation_map():
    """Peta mentah navigasi pengantar (tanpa URL) agar bisa diuji tanpa request context."""
    antar_segments = [
        _seg("Hari Ini", "delivery.today"),
        _seg("Serah Terima", "delivery.receiving"),
    ]
    return {
        "tabs": [
            {
                "key": "home",
                "label": "Beranda",
                "icon": "home",
                "endpoint": "dashboard.pengantar",
                "endpoints": HOME_ENDPOINTS,
                "segments": [],
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
                "key": "scan",
                "label": "Scan",
                "icon": "qr_code_scanner",
                "endpoint": "delivery.scan",
                "endpoints": ["delivery.scan", "delivery.scan_qr"],
                "segments": [],
                "prominent": True,
            },
            {
                "key": "history",
                "label": "Riwayat",
                "icon": "history",
                "endpoint": "delivery.history",
                "endpoints": ["delivery.history"],
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


def build_driver_navigation(endpoint):
    """Navigasi siap pakai untuk template mobile pengantar."""
    nav = driver_navigation_map()
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

    # Child pages resolution (detail pengiriman & serah terima & notifikasi)
    is_child = False
    back_url = None
    back_label = "Kembali"

    if endpoint == "delivery.detail":
        active_key = "delivery"
        is_child = True
        back_url = url_for("delivery.today")
        back_label = "Hari Ini"
    elif endpoint == "delivery.receive":
        active_key = "delivery"
        is_child = True
        # Jika datang dari scan (argumen from_scan), arahkan kembali ke Scan
        if request and (request.args.get("from_scan") == "1" or request.form.get("from_scan") == "1"):
            back_url = url_for("delivery.scan")
            back_label = "Scan"
        else:
            back_url = url_for("delivery.receiving")
            back_label = "Serah Terima"
    elif endpoint == "sop.role_sop":
        # SOP dibuka dari tab Akun (satu-satunya pintunya).
        active_key = "account"
        is_child = True
        back_url = url_for("settings.account")
        back_label = "Akun"
    elif endpoint == "settings.notifications":
        is_child = True
        back_url = url_for("dashboard.pengantar")
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
