"""Navigasi mobile pengantar: satu pintu per halaman (aturan owner 2026-10-10 & 2026-10-11)."""

from collections import Counter
from uuid import uuid4
import pytest
from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models.master import Branch, User
from app.services.driver_navigation_service import build_driver_navigation, driver_navigation_map


def _doors(nav):
    doors = [tab["endpoint"] for tab in nav["tabs"] if not tab["segments"]]
    for tab in nav["tabs"]:
        doors += [segment["endpoint"] for segment in tab["segments"]]
    return doors


def _login_user_id(client, user_id):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True


def test_every_driver_page_has_exactly_one_door():
    nav = driver_navigation_map()
    doors = _doors(nav)
    duplicated = [endpoint for endpoint, count in Counter(doors).items() if count > 1]
    assert duplicated == [], f"Ada pintu ganda: {duplicated}"

    # Satu halaman tidak boleh dinyalakan oleh dua pintu berbeda
    lit = []
    for tab in nav["tabs"]:
        if not tab["segments"]:
            lit += tab.get("endpoints", [tab["endpoint"]])
        for segment in tab["segments"]:
            lit += segment["endpoints"]
    duplicated_lit = [endpoint for endpoint, count in Counter(lit).items() if count > 1]
    assert duplicated_lit == [], f"Ada endpoint yang dinyalakan pintu ganda: {duplicated_lit}"


def test_driver_bottom_tabs_count_and_keys():
    nav = driver_navigation_map()
    assert len(nav["tabs"]) == 5
    assert [tab["key"] for tab in nav["tabs"]] == ["home", "delivery", "scan", "history", "account"]
    assert nav["tabs"][2]["prominent"] is True  # Tombol scan menonjol di tengah


def test_notifications_not_in_bottom_tabs():
    nav = driver_navigation_map()
    doors = _doors(nav)
    assert "settings.notifications" not in doors


def test_active_tab_and_segments_follow_endpoint(app):
    with app.test_request_context("/"):
        nav = build_driver_navigation("dashboard.pengantar")
        assert [tab["key"] for tab in nav["tabs"] if tab["active"]] == ["home"]
        assert nav["segments"] == []
        assert not nav["is_child"]

        nav = build_driver_navigation("delivery.today")
        assert [tab["key"] for tab in nav["tabs"] if tab["active"]] == ["delivery"]
        assert [seg["label"] for seg in nav["segments"]] == ["Hari Ini", "Serah Terima"]
        assert next(seg for seg in nav["segments"] if seg["label"] == "Hari Ini")["active"] is True
        assert not nav["is_child"]

        nav = build_driver_navigation("delivery.receiving")
        assert [tab["key"] for tab in nav["tabs"] if tab["active"]] == ["delivery"]
        assert next(seg for seg in nav["segments"] if seg["label"] == "Serah Terima")["active"] is True
        assert not nav["is_child"]

        nav = build_driver_navigation("delivery.scan")
        assert [tab["key"] for tab in nav["tabs"] if tab["active"]] == ["scan"]
        assert not nav["is_child"]

        nav = build_driver_navigation("delivery.history")
        assert [tab["key"] for tab in nav["tabs"] if tab["active"]] == ["history"]
        assert not nav["is_child"]

        nav = build_driver_navigation("settings.account")
        assert [tab["key"] for tab in nav["tabs"] if tab["active"]] == ["account"]
        assert not nav["is_child"]


def test_detail_and_receive_pages_are_children_with_back_links(app):
    with app.test_request_context("/"):
        nav_detail = build_driver_navigation("delivery.detail")
        assert nav_detail["is_child"] is True
        assert nav_detail["back_label"] == "Hari Ini"
        assert "/delivery/today" in nav_detail["back_url"]

        nav_receive = build_driver_navigation("delivery.receive")
        assert nav_receive["is_child"] is True
        assert nav_receive["back_label"] == "Serah Terima"
        assert "/delivery/receiving" in nav_receive["back_url"]

    with app.test_request_context("/?from_scan=1"):
        nav_scan_receive = build_driver_navigation("delivery.receive")
        assert nav_scan_receive["is_child"] is True
        assert nav_scan_receive["back_label"] == "Scan"
        assert "/delivery/scan" in nav_scan_receive["back_url"]

    with app.test_request_context("/"):
        nav_notif = build_driver_navigation("settings.notifications")
        assert nav_notif["is_child"] is True
        assert nav_notif["back_label"] == "Beranda"
        assert "/dashboard/pengantar" in nav_notif["back_url"]


def test_driver_pages_render_driver_mobile_shell_for_pengantar(app, client):
    """Pastikan halaman yang dibuka role PENGANTAR menggunakan layout driver_mobile (driver-mobile-shell)."""
    with app.app_context():
        suffix = uuid4().hex[:6]
        branch = Branch(code=f"BR-DRV-{suffix}", name="Branch Driver Test", is_active=True)
        db.session.add(branch)
        db.session.flush()

        driver_user = User(
            branch_id=branch.id,
            full_name=f"Driver Test {suffix}",
            username=f"driver_{suffix}",
            password_hash=generate_password_hash("password123"),
            role="PENGANTAR",
            is_active=True,
        )
        db.session.add(driver_user)
        db.session.commit()
        driver_id = driver_user.id

    _login_user_id(client, driver_id)

    pages = [
        "/dashboard/pengantar",
        "/delivery/today",
        "/delivery/receiving",
        "/delivery/scan",
        "/delivery/history",
        "/settings/account",
        "/settings/notifications",
        "/sop/delivery",
    ]
    for page in pages:
        res = client.get(page)
        assert res.status_code == 200, f"Halaman {page} gagal dimuat (status {res.status_code})"
        text = res.get_data(as_text=True)
        assert "driver-mobile-shell" in text, f"Halaman {page} tidak memakai driver-mobile-shell"
    # SOP hanya punya satu pintu: daftar di tab Akun.
    assert "/sop/delivery" in client.get("/settings/account").get_data(as_text=True)
    assert "/sop/delivery" not in client.get("/delivery/today").get_data(as_text=True)


def test_driver_pages_render_legacy_layout_for_admin(app, client):
    """Pastikan halaman yang dibuka ADMIN tetap memakai layout internal lama (tanpa driver-mobile-shell)."""
    with app.app_context():
        suffix = uuid4().hex[:6]
        branch = Branch(code=f"BR-ADM-{suffix}", name="Branch Admin Test", is_active=True)
        db.session.add(branch)
        db.session.flush()

        admin_user = User(
            branch_id=branch.id,
            full_name=f"Admin Test {suffix}",
            username=f"admin_{suffix}",
            password_hash=generate_password_hash("password123"),
            role="ADMIN",
            is_active=True,
        )
        db.session.add(admin_user)
        db.session.commit()
        admin_id = admin_user.id

    _login_user_id(client, admin_id)

    # Halaman-halaman delivery & settings untuk ADMIN harus memakai layout internal lama
    pages = [
        "/delivery/today",
        "/delivery/receiving",
        "/delivery/scan",
        "/delivery/history",
        "/settings/account",
        "/settings/notifications",
    ]
    for page in pages:
        res = client.get(page)
        assert res.status_code == 200, f"Halaman {page} untuk admin gagal dimuat (status {res.status_code})"
        text = res.get_data(as_text=True)
        assert "driver-mobile-shell" not in text, f"Halaman {page} untuk admin tidak boleh memakai driver-mobile-shell"
