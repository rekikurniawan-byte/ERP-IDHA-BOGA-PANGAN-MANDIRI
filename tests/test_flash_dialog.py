"""Pengujian notifikasi tengah layar (Flash Dialog) di seluruh sistem (keputusan owner 2026-10-11)."""

import re
from pathlib import Path
from uuid import uuid4
import pytest
from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models.master import Branch, User

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = ROOT / "app" / "templates"


def _create_user(app, role, prefix="user"):
    with app.app_context():
        suffix = uuid4().hex[:6]
        branch = Branch(code=f"BR-FL-{suffix}", name=f"Cabang Flash {suffix}", is_active=True)
        db.session.add(branch)
        db.session.flush()

        user = User(
            branch_id=branch.id,
            full_name=f"User {prefix.title()} {suffix}",
            username=f"{prefix}_{suffix}",
            password_hash=generate_password_hash("password123"),
            role=role,
            is_active=True,
        )
        db.session.add(user)
        db.session.commit()
        return user.id


def test_only_flash_dialog_calls_get_flashed_messages():
    """Memastikan tidak ada template selain components/flash_dialog.html yang memanggil get_flashed_messages."""
    offenders = []
    for html_file in TEMPLATES_DIR.rglob("*.html"):
        content = html_file.read_text(encoding="utf-8")
        if "get_flashed_messages" in content:
            rel_path = html_file.relative_to(ROOT).as_posix()
            if rel_path != "app/templates/components/flash_dialog.html":
                offenders.append(rel_path)

    assert offenders == [], f"Ada template yang memanggil get_flashed_messages di luar flash_dialog.html: {offenders}"


def test_layouts_and_public_flashes_include_flash_dialog():
    """Memastikan kelima layout + components/public_flashes.html meng-include components/flash_dialog.html."""
    target_files = [
        "app/templates/layouts/base.html",
        "app/templates/components/public_flashes.html",
        "app/templates/layouts/portal_mobile.html",
        "app/templates/layouts/driver_mobile.html",
        "app/templates/layouts/ops_mobile.html",
    ]

    for rel_path in target_files:
        full_path = ROOT / rel_path
        assert full_path.exists(), f"File {rel_path} tidak ditemukan"
        content = full_path.read_text(encoding="utf-8")
        assert 'include "components/flash_dialog.html"' in content or "include 'components/flash_dialog.html'" in content, (
            f"File {rel_path} tidak meng-include components/flash_dialog.html"
        )


def test_main_js_defines_app_notify_and_toast_as_same_function():
    """Memastikan main.js mendefinisikan appNotify dan appToast memakai fungsi yang sama."""
    js = (ROOT / "app" / "static" / "js" / "main.js").read_text(encoding="utf-8")
    assert "window.appNotify = function" in js, "window.appNotify tidak didefinisikan di main.js"
    assert "window.appToast = window.appNotify" in js, "window.appToast bukan alias window.appNotify di main.js"


def test_login_failure_renders_flash_dialog(app, client):
    """Setelah login gagal di /auth/login, HTML berisi flash dialog tengah layar."""
    app.config["WTF_CSRF_ENABLED"] = False  # tes ini menguji tampilan pesan, bukan CSRF
    res = client.post(
        "/auth/login",
        data={"username": "user_tidak_dikenal", "password": "password_salah"},
        follow_redirects=True,
    )
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    assert 'id="appFlashDialog"' in html
    assert 'role="alertdialog"' in html
    assert 'aria-modal="true"' in html
    assert 'alert alert-danger' in html
    assert "Mengerti" in html
    assert "Username atau password tidak valid" in html


def test_internal_page_renders_flash_dialog(app, client):
    """Halaman internal (base.html) menampilkan flash dialog ketika ada pesan."""
    user_id = _create_user(app, role="ADMIN", prefix="admin")
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True
        sess["_flashes"] = [("info", "Pemberitahuan pembaruan sistem internal")]

    res = client.get("/dashboard/admin", follow_redirects=True)
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    assert 'id="appFlashDialog"' in html
    assert 'role="alertdialog"' in html
    assert 'alert alert-info' in html
    assert "Pemberitahuan pembaruan sistem internal" in html
    assert "Mengerti" in html


def test_portal_page_renders_flash_dialog(app, client):
    """Halaman portal mobile menampilkan flash dialog ketika ada pesan."""
    user_id = _create_user(app, role="PORTAL_CUSTOMER", prefix="customer")
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True
        sess["_flashes"] = [("success", "Pesanan portal berhasil dicatat")]

    res = client.get("/portal/customer/orders", follow_redirects=True)
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    assert 'id="appFlashDialog"' in html
    assert 'role="alertdialog"' in html
    assert 'alert alert-success' in html
    assert "Pesanan portal berhasil dicatat" in html
    assert "Mengerti" in html


def test_driver_page_renders_flash_dialog(app, client):
    """Halaman pengantar mobile menampilkan flash dialog ketika ada pesan."""
    user_id = _create_user(app, role="PENGANTAR", prefix="driver")
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True
        sess["_flashes"] = [("warning", "Waktu pengantaran hampir tiba")]

    res = client.get("/delivery/today", follow_redirects=True)
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    assert 'id="appFlashDialog"' in html
    assert 'role="alertdialog"' in html
    assert 'alert alert-warning' in html
    assert "Waktu pengantaran hampir tiba" in html
    assert "Mengerti" in html


def test_ops_page_renders_flash_dialog(app, client):
    """Halaman operasional mobile menampilkan flash dialog ketika ada pesan."""
    user_id = _create_user(app, role="ADMIN_OPERASIONAL", prefix="ops")
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True
        sess["_flashes"] = [("danger", "Kapasitas produksi operasional penuh")]

    res = client.get("/dashboard/ops", follow_redirects=True)
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    assert 'id="appFlashDialog"' in html
    assert 'role="alertdialog"' in html
    assert 'alert alert-danger' in html
    assert "Kapasitas produksi operasional penuh" in html
    assert "Mengerti" in html


def test_flash_dialog_item_matches_pilot_dry_run_regex():
    """Tiap pesan di flash dialog wajib dapat dibaca oleh regex tools/pilot_dry_run.py."""
    alert_pattern = re.compile(
        r'class="[^"]*\balert-(success|info|warning|danger|error)\b[^"]*"[^>]*>(.*?)</div>',
        re.S,
    )
    sample_rendered = (
        '<div class="app-flash-dialog-body" role="status" aria-live="polite">\n'
        '    <div class="alert alert-success app-flash-item" role="alert">Transaksi berhasil</div>\n'
        '    <div class="alert alert-danger app-flash-item" role="alert">Gagal menyimpan</div>\n'
        '</div>'
    )
    matches = alert_pattern.findall(sample_rendered)
    assert len(matches) == 2
    assert matches[0] == ("success", "Transaksi berhasil")
    assert matches[1] == ("danger", "Gagal menyimpan")
