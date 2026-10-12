"""Navigasi mobile operasional: satu pintu per halaman (aturan owner 2026-10-10 & 2026-10-11)."""

from collections import Counter
from uuid import uuid4
import pytest
from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models.master import Branch, User
from app.services.ops_navigation_service import build_ops_navigation, ops_navigation_map


def _doors(nav):
    doors = [tab["endpoint"] for tab in nav["tabs"] if not tab["segments"]]
    for tab in nav["tabs"]:
        doors += [segment["endpoint"] for segment in tab["segments"]]
    return doors


def _login_user_id(client, user_id):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True


def test_every_ops_page_has_exactly_one_door():
    """Setiap sub-tab/tab hanya punya satu endpoint pintu masuk."""
    nav = ops_navigation_map()
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


def test_ops_bottom_tabs_count_and_keys():
    """Tab bawah ada 5: Beranda, Pesanan, Dapur, Antar, Akun."""
    nav = ops_navigation_map()
    assert len(nav["tabs"]) == 5
    assert [tab["key"] for tab in nav["tabs"]] == ["home", "orders", "kitchen", "delivery", "account"]


def test_notifications_not_in_bottom_tabs():
    """Notifikasi hanya lewat lonceng header, tidak boleh ada di tab bawah."""
    nav = ops_navigation_map()
    doors = _doors(nav)
    assert "settings.notifications" not in doors


def test_all_endpoints_in_ops_map_exist_in_url_map(app):
    """Semua endpoint yang dipetakan di ops_navigation_service benar-benar terdaftar di url_map aplikasi."""
    nav = ops_navigation_map()
    all_endpoints = set()

    for tab in nav["tabs"]:
        all_endpoints.add(tab["endpoint"])
        all_endpoints.update(tab.get("endpoints", []))
        for segment in tab.get("segments", []):
            all_endpoints.add(segment["endpoint"])
            all_endpoints.update(segment.get("endpoints", []))

    # Child endpoints yang dirujuk build_ops_navigation
    child_endpoints = {
        "operational.order_detail",
        "operational.create_order",
        "operational.add_order_detail",
        "operational.add_increase_after_lock_route",
        "operational.create_revision",
        "production.detail",
        "operational.kitchen_recap",
        "operational.container_labels",
        "delivery.detail",
        "delivery.receive",
        "delivery.history",
        "delivery.scan",
        "delivery.scan_qr",
        "sop.role_sop",
        "settings.notifications",
    }
    all_endpoints.update(child_endpoints)

    registered_endpoints = set(app.view_functions.keys())
    missing = [ep for ep in all_endpoints if ep not in registered_endpoints]
    assert missing == [], f"Endpoint di peta ops navigasi tidak terdaftar di aplikasi: {missing}"


def test_active_tab_and_segments_follow_endpoint(app):
    """Tab dan sub-tab aktif sesuai dengan endpoint yang diminta."""
    with app.test_request_context("/"):
        nav = build_ops_navigation("dashboard.ops")
        assert [tab["key"] for tab in nav["tabs"] if tab["active"]] == ["home"]
        assert nav["segments"] == []
        assert not nav["is_child"]

        nav = build_ops_navigation("operational.orders")
        assert [tab["key"] for tab in nav["tabs"] if tab["active"]] == ["orders"]
        assert [seg["label"] for seg in nav["segments"]] == ["Hari Ini", "Draf Portal", "Perubahan Porsi", "Jadwal Menu"]
        assert next(seg for seg in nav["segments"] if seg["label"] == "Hari Ini")["active"] is True
        assert not nav["is_child"]

        nav = build_ops_navigation("portal.admin_order_drafts")
        assert [tab["key"] for tab in nav["tabs"] if tab["active"]] == ["orders"]
        assert next(seg for seg in nav["segments"] if seg["label"] == "Draf Portal")["active"] is True
        assert not nav["is_child"]

        nav = build_ops_navigation("operational.order_qty_changes")
        assert [tab["key"] for tab in nav["tabs"] if tab["active"]] == ["orders"]
        assert next(seg for seg in nav["segments"] if seg["label"] == "Perubahan Porsi")["active"] is True
        assert not nav["is_child"]

        nav = build_ops_navigation("operational.menu_schedule")
        assert [tab["key"] for tab in nav["tabs"] if tab["active"]] == ["orders"]
        assert next(seg for seg in nav["segments"] if seg["label"] == "Jadwal Menu")["active"] is True
        assert not nav["is_child"]

        nav = build_ops_navigation("production.index")
        assert [tab["key"] for tab in nav["tabs"] if tab["active"]] == ["kitchen"]
        assert [seg["label"] for seg in nav["segments"]] == ["Produksi", "Rekap Dapur", "Apel Tim"]
        assert next(seg for seg in nav["segments"] if seg["label"] == "Produksi")["active"] is True
        assert not nav["is_child"]

        nav = build_ops_navigation("operational.kitchen_recap_hub")
        assert [tab["key"] for tab in nav["tabs"] if tab["active"]] == ["kitchen"]
        assert next(seg for seg in nav["segments"] if seg["label"] == "Rekap Dapur")["active"] is True
        assert not nav["is_child"]

        nav = build_ops_navigation("delivery.today")
        assert [tab["key"] for tab in nav["tabs"] if tab["active"]] == ["delivery"]
        assert [seg["label"] for seg in nav["segments"]] == ["Pengiriman", "Serah Terima"]
        assert next(seg for seg in nav["segments"] if seg["label"] == "Pengiriman")["active"] is True
        assert not nav["is_child"]

        nav = build_ops_navigation("delivery.receiving")
        assert [tab["key"] for tab in nav["tabs"] if tab["active"]] == ["delivery"]
        assert next(seg for seg in nav["segments"] if seg["label"] == "Serah Terima")["active"] is True
        assert not nav["is_child"]

        nav = build_ops_navigation("settings.account")
        assert [tab["key"] for tab in nav["tabs"] if tab["active"]] == ["account"]
        assert nav["segments"] == []
        assert not nav["is_child"]


def test_ops_child_pages_have_back_links(app):
    """Halaman detail/formulir operasional memiliki panah kembali ke daftar asalnya."""
    with app.test_request_context("/"):
        nav_order_detail = build_ops_navigation("operational.order_detail")
        assert nav_order_detail["is_child"] is True
        assert nav_order_detail["back_label"] == "Hari Ini"
        assert "/orders" in nav_order_detail["back_url"]

        nav_revision = build_ops_navigation("operational.create_revision")
        assert nav_revision["is_child"] is True
        assert nav_revision["back_label"] == "Pesanan"
        assert "/orders" in nav_revision["back_url"]

        nav_prod_detail = build_ops_navigation("production.detail")
        assert nav_prod_detail["is_child"] is True
        assert nav_prod_detail["back_label"] == "Produksi"
        assert "/production" in nav_prod_detail["back_url"]

        nav_deliv_detail = build_ops_navigation("delivery.detail")
        assert nav_deliv_detail["is_child"] is True
        assert nav_deliv_detail["back_label"] == "Pengiriman"
        assert "/delivery/today" in nav_deliv_detail["back_url"]

        nav_receive = build_ops_navigation("delivery.receive")
        assert nav_receive["is_child"] is True
        assert nav_receive["back_label"] == "Serah Terima"
        assert "/delivery/receiving" in nav_receive["back_url"]

        nav_history = build_ops_navigation("delivery.history")
        assert nav_history["is_child"] is True
        assert nav_history["back_label"] == "Pengiriman"
        assert "/delivery/today" in nav_history["back_url"]

        nav_scan = build_ops_navigation("delivery.scan")
        assert nav_scan["is_child"] is True
        assert nav_scan["back_label"] == "Serah Terima"
        assert "/delivery/receiving" in nav_scan["back_url"]

        nav_sop = build_ops_navigation("sop.role_sop")
        assert nav_sop["is_child"] is True
        assert nav_sop["back_label"] == "Akun"
        assert "/settings/account" in nav_sop["back_url"]

        nav_notif = build_ops_navigation("settings.notifications")
        assert nav_notif["is_child"] is True
        assert nav_notif["back_label"] == "Beranda"
        assert "/dashboard/ops" in nav_notif["back_url"]


def test_ops_pages_render_ops_mobile_shell_for_admin_operasional(app, client):
    """Pastikan halaman yang dibuka role ADMIN_OPERASIONAL menggunakan layout ops_mobile (ops-mobile-shell)."""
    with app.app_context():
        suffix = uuid4().hex[:6]
        branch = Branch(code=f"BR-OPS-{suffix}", name="Branch Ops Test", is_active=True)
        db.session.add(branch)
        db.session.flush()

        ops_user = User(
            branch_id=branch.id,
            full_name=f"Ops Test {suffix}",
            username=f"ops_{suffix}",
            password_hash=generate_password_hash("password123"),
            role="ADMIN_OPERASIONAL",
            is_active=True,
        )
        db.session.add(ops_user)
        db.session.commit()
        ops_user_id = ops_user.id

    _login_user_id(client, ops_user_id)

    pages = [
        "/dashboard/ops",
        "/operational/orders",
        "/portal/admin/order-drafts",
        "/operational/order-qty-changes",
        "/operational/menu-schedule",
        "/production/",
        "/operational/kitchen-recap",
        "/delivery/today",
        "/delivery/receiving",
        "/delivery/history",
        "/delivery/scan",
        "/settings/account",
        "/settings/notifications",
        "/sop/admin",
    ]
    for page in pages:
        res = client.get(page, follow_redirects=True)
        assert res.status_code == 200, f"Halaman {page} gagal dimuat (status {res.status_code})"
        text = res.get_data(as_text=True)
        assert "ops-mobile-shell" in text, f"Halaman {page} tidak memakai ops-mobile-shell"


def test_ops_door_can_be_opened_by_owner_and_admin(app, client):
    """Pintu masuk /ops bisa dibuka oleh OWNER dan ADMIN, mengarah ke beranda ops mobile."""
    with app.app_context():
        suffix = uuid4().hex[:6]
        branch = Branch(code=f"BR-DOOR-{suffix}", name="Branch Door Test", is_active=True)
        db.session.add(branch)
        db.session.flush()

        owner_user = User(
            branch_id=branch.id,
            full_name=f"Owner Test {suffix}",
            username=f"owner_{suffix}",
            password_hash=generate_password_hash("password123"),
            role="OWNER",
            is_active=True,
        )
        admin_user = User(
            branch_id=branch.id,
            full_name=f"Admin Test {suffix}",
            username=f"admin_{suffix}",
            password_hash=generate_password_hash("password123"),
            role="ADMIN",
            is_active=True,
        )
        db.session.add_all([owner_user, admin_user])
        db.session.commit()
        owner_id = owner_user.id
        admin_id = admin_user.id

    # Tes untuk OWNER
    _login_user_id(client, owner_id)
    res_owner = client.get("/ops", follow_redirects=True)
    assert res_owner.status_code == 200
    assert "ops-mobile-shell" in res_owner.get_data(as_text=True)

    # Tes untuk ADMIN
    _login_user_id(client, admin_id)
    res_admin = client.get("/ops", follow_redirects=True)
    assert res_admin.status_code == 200
    assert "ops-mobile-shell" in res_admin.get_data(as_text=True)


def test_owner_ops_mode_and_exit(app, client):
    """OWNER setelah membuka /ops mendapat ops-mobile-shell di /operational/orders dan /delivery/today; setelah POST /ops/exit kembali ke layout desktop."""
    app.config["WTF_CSRF_ENABLED"] = False  # tes ini menguji izin role, bukan CSRF
    with app.app_context():
        suffix = uuid4().hex[:6]
        branch = Branch(code=f"BR-MODE-{suffix}", name="Branch Mode Test", is_active=True)
        db.session.add(branch)
        db.session.flush()

        owner_user = User(
            branch_id=branch.id,
            full_name=f"Owner Mode {suffix}",
            username=f"ownermode_{suffix}",
            password_hash=generate_password_hash("password123"),
            role="OWNER",
            is_active=True,
        )
        db.session.add(owner_user)
        db.session.commit()
        owner_id = owner_user.id

    _login_user_id(client, owner_id)

    # 1. Buka /ops -> mengaktifkan session["ops_mode"]
    res_ops = client.get("/ops", follow_redirects=True)
    assert res_ops.status_code == 200
    assert "ops-mobile-shell" in res_ops.get_data(as_text=True)

    # 2. Halaman /operational/orders dan /delivery/today harus menggunakan layout ops-mobile-shell
    res_orders = client.get("/operational/orders", follow_redirects=True)
    assert res_orders.status_code == 200
    assert "ops-mobile-shell" in res_orders.get_data(as_text=True)

    res_delivery = client.get("/delivery/today", follow_redirects=True)
    assert res_delivery.status_code == 200
    assert "ops-mobile-shell" in res_delivery.get_data(as_text=True)

    # 3. POST /ops/exit -> menghapus session["ops_mode"] dan kembali ke desktop
    res_exit = client.post("/ops/exit", follow_redirects=True)
    assert res_exit.status_code == 200

    # 4. Setelah exit, /operational/orders dan /delivery/today tidak lagi memakai ops-mobile-shell
    res_orders_desktop = client.get("/operational/orders", follow_redirects=True)
    assert res_orders_desktop.status_code == 200
    assert "ops-mobile-shell" not in res_orders_desktop.get_data(as_text=True)

    res_delivery_desktop = client.get("/delivery/today", follow_redirects=True)
    assert res_delivery_desktop.status_code == 200
    assert "ops-mobile-shell" not in res_delivery_desktop.get_data(as_text=True)


def test_form_parity_between_original_and_ops_templates():
    """Untuk tiap pasangan template di bagian A, semua action/url_for form di template asli ada di template ops (kecuali yang dikecualikan)."""
    import re
    from pathlib import Path

    base_templates_dir = Path(__file__).resolve().parent.parent / "app" / "templates"

    pairs = [
        ("delivery/today.html", "ops/today.html"),
        ("operational/orders.html", "ops/orders.html"),
        ("operational/order_detail.html", "ops/order_detail.html"),
        ("delivery/detail.html", "ops/delivery_detail.html"),
        ("operational/menu_schedule.html", "ops/menu_schedule.html"),
        ("operational/order_qty_changes.html", "ops/order_qty_changes.html"),
        ("production/detail.html", "ops/production_detail.html"),
        ("delivery/receive.html", "ops/receive.html"),
        ("delivery/receiving.html", "ops/receiving.html"),
        ("portal/admin_order_drafts.html", "ops/drafts.html"),
        ("operational/order_form.html", "ops/order_form.html"),
        ("operational/revision_form.html", "ops/revision_form.html"),
    ]

    excluded_patterns = [
        "costing.",
        "owner_override",
        "finance.",
        "settings.approvals",
        "hpp",
        "stock",
    ]

    for orig_rel, ops_rel in pairs:
        orig_file = base_templates_dir / orig_rel
        ops_file = base_templates_dir / ops_rel

        orig_content = orig_file.read_text(encoding="utf-8")
        ops_content = ops_file.read_text(encoding="utf-8")

        # Cari semua form action url_for(...)
        form_actions = re.findall(
            r'<form\b[^>]*\baction=["\']\{\{\s*url_for\(([\'"][^\'"]+[\'"])',
            orig_content,
            re.IGNORECASE,
        )

        for action_endpoint in form_actions:
            endpoint_clean = action_endpoint.strip("\"'")
            if any(exc in endpoint_clean.lower() for exc in excluded_patterns):
                continue
            assert endpoint_clean in ops_content, (
                f"Form action '{endpoint_clean}' dari {orig_rel} tidak ditemukan di {ops_rel}"
            )


def test_photo_and_attachment_links_in_ops_templates():
    """Tautan location_photos.view dan delivery.view_attachment ada di template ops terkait."""
    from pathlib import Path

    base_templates_dir = Path(__file__).resolve().parent.parent / "app" / "templates"

    receiving_ops = (base_templates_dir / "ops/receiving.html").read_text(encoding="utf-8")
    assert "location_photos.view" in receiving_ops, "Tautan location_photos.view hilang di ops/receiving.html"

    delivery_detail_ops = (base_templates_dir / "ops/delivery_detail.html").read_text(encoding="utf-8")
    assert "location_photos.view" in delivery_detail_ops, "Tautan location_photos.view hilang di ops/delivery_detail.html"
    assert "delivery.view_attachment" in delivery_detail_ops, "Tautan delivery.view_attachment hilang di ops/delivery_detail.html"


def test_order_qty_changes_filter_parity():
    """Filter form di ops/order_qty_changes.html memiliki class app-filter dan mencakup field source, mandor_id, start_date, end_date."""
    from pathlib import Path

    base_templates_dir = Path(__file__).resolve().parent.parent / "app" / "templates"
    content = (base_templates_dir / "ops/order_qty_changes.html").read_text(encoding="utf-8")

    assert 'class="app-filter' in content
    assert 'name="source"' in content
    assert 'name="mandor_id"' in content
    assert 'name="start_date"' in content
    assert 'name="end_date"' in content


def test_production_detail_delivery_type_and_blocking_reason():
    """ops/production_detail.html memakai production_delivery_action.delivery_type dan menampilkan blocking_reason."""
    from pathlib import Path

    base_templates_dir = Path(__file__).resolve().parent.parent / "app" / "templates"
    content = (base_templates_dir / "ops/production_detail.html").read_text(encoding="utf-8")

    assert "production_delivery_action.delivery_type" in content
    assert "production_delivery_action.blocking_reason" in content



def test_ops_form_field_names_match_original_templates():
    """Nama field form versi HP harus sama dengan versi desktop (field yang terbuang = data hilang diam-diam)."""
    import re
    from pathlib import Path

    base = Path(__file__).resolve().parent.parent / "app" / "templates"
    pairs = [
        ("operational/order_form.html", "ops/order_form.html"),
        ("operational/revision_form.html", "ops/revision_form.html"),
        ("operational/order_detail.html", "ops/order_detail.html"),
        ("operational/menu_schedule.html", "ops/menu_schedule.html"),
        ("delivery/receive.html", "ops/receive.html"),
        ("delivery/detail.html", "ops/delivery_detail.html"),
    ]
    # Sengaja tidak ada di versi HP: isian default HPP (di luar lingkup operasional) dan override OWNER.
    excluded = {"default_lunch_menu_id", "default_dinner_menu_id", "default_packaging_profile_id",
                "default_overhead_profile_id", "owner_override"}
    for orig_rel, ops_rel in pairs:
        orig = set(re.findall(r'name="([^"{]+)"', (base / orig_rel).read_text(encoding="utf-8")))
        ops = set(re.findall(r'name="([^"{]+)"', (base / ops_rel).read_text(encoding="utf-8")))
        missing = sorted(orig - ops - excluded)
        assert missing == [], f"{ops_rel} kehilangan field {missing}"
