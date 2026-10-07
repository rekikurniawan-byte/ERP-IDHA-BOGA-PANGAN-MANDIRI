from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from flask import url_for
from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models.delivery import Delivery, DeliveryDetail, DeliveryReceipt
from app.models.master import Branch, Client, DeliveryLocation, Driver, Mandor, User
from app.models.operational import DailyOrder, DailyOrderDetail
from app.services.kitchen_recap_service import build_container_labels_data
from app.services.user_management_service import (
    ROLE_ADMIN,
    ROLE_OWNER,
    ROLE_PENGANTAR,
    ROLE_PORTAL_CUSTOMER,
)


def _login_user_id(client, user_id):
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def _create_test_env():
    suffix = uuid4().hex[:6]
    branch = Branch(code=f"BR-{suffix}", name="Branch Test Scan", is_active=True)
    other_branch = Branch(code=f"BR2-{suffix}", name="Branch Other", is_active=True)
    db.session.add_all([branch, other_branch])
    db.session.flush()

    admin = User(
        branch_id=branch.id,
        full_name=f"Admin Scan {suffix}",
        username=f"admin_{suffix}",
        password_hash=generate_password_hash("password123"),
        role=ROLE_ADMIN,
        is_active=True,
    )
    driver_user = User(
        branch_id=branch.id,
        full_name=f"Driver Scan {suffix}",
        username=f"driver_{suffix}",
        password_hash=generate_password_hash("password123"),
        role=ROLE_PENGANTAR,
        is_active=True,
    )
    portal_user = User(
        branch_id=branch.id,
        full_name=f"Portal Customer {suffix}",
        username=f"portal_{suffix}",
        password_hash=generate_password_hash("password123"),
        role=ROLE_PORTAL_CUSTOMER,
        is_active=True,
    )
    db.session.add_all([admin, driver_user, portal_user])
    db.session.flush()

    client_item = Client(name=f"PT Klien Scan {suffix}", customer_path="KONTRAK", is_active=True)
    db.session.add(client_item)
    db.session.flush()

    mandor = Mandor(
        branch_id=branch.id,
        client_id=client_item.id,
        name=f"Mandor Agus {suffix}",
        phone="081234567890",
        is_active=True,
    )
    db.session.add(mandor)
    db.session.flush()

    location = DeliveryLocation(
        mandor_id=mandor.id,
        location_name="Proyek Gedung A Lt. 2",
        description="Masuk lewat pintu timur pos satpam",
        is_active=True,
    )
    driver = Driver(branch_id=branch.id, name=f"Pak Supir {suffix}", phone="0899999999", is_active=True)
    db.session.add_all([location, driver])
    db.session.flush()

    order_date = date.today()
    daily_order = DailyOrder(
        branch_id=branch.id,
        order_number=f"ORD-SCAN-{suffix}",
        order_date=order_date,
        status="LOCKED",
        is_locked=True,
        locked_at=datetime.utcnow(),
        created_by=admin.id,
    )
    db.session.add(daily_order)
    db.session.flush()

    detail = DailyOrderDetail(
        daily_order_id=daily_order.id,
        mandor_id=mandor.id,
        delivery_location_id=location.id,
        price_per_portion=Decimal("25000"),
        lunch_qty=15,
        dinner_qty=0,
        total_qty=15,
    )
    db.session.add(detail)
    db.session.flush()

    delivery = Delivery(
        branch_id=branch.id,
        delivery_number=f"DLV-SCAN-{suffix}",
        delivery_date=order_date,
        driver_id=driver.id,
        status="DISPATCHED",
        notes="delivery_type=LUNCH",
        created_by=admin.id,
    )
    db.session.add(delivery)
    db.session.flush()

    delivery_detail = DeliveryDetail(
        delivery_id=delivery.id,
        daily_order_detail_id=detail.id,
        mandor_id=mandor.id,
        delivery_location_id=location.id,
        planned_qty=15,
        delivered_qty=0,
    )
    db.session.add(delivery_detail)
    db.session.commit()

    return {
        "branch_id": branch.id,
        "other_branch_id": other_branch.id,
        "admin_id": admin.id,
        "driver_user_id": driver_user.id,
        "portal_user_id": portal_user.id,
        "client_name": client_item.name,
        "mandor_name": mandor.name,
        "location_name": location.location_name,
        "order_id": daily_order.id,
        "detail_id": detail.id,
        "delivery_id": delivery.id,
        "delivery_detail_id": delivery_detail.id,
    }


def test_pengantar_dashboard_and_receiving_have_scan_buttons(app, client):
    """Dashboard pengantar dan halaman receiving memuat tombol Scan Label Wadah dan link ke /delivery/scan."""
    with app.app_context():
        env = _create_test_env()

    _login_user_id(client, env["driver_user_id"])

    # 1. Dashboard pengantar
    res_dash = client.get("/dashboard/pengantar")
    assert res_dash.status_code == 200
    text_dash = res_dash.get_data(as_text=True)
    assert "Scan Label Wadah" in text_dash
    assert "/delivery/scan" in text_dash

    # 2. Halaman Receiving
    res_rec = client.get("/delivery/receiving")
    assert res_rec.status_code == 200
    text_rec = res_rec.get_data(as_text=True)
    assert "Scan Label Wadah" in text_rec
    assert "/delivery/scan" in text_rec


def test_delivery_scan_page_permissions(app, client):
    """GET /delivery/scan bisa dibuka PENGANTAR/ADMIN, ditolak unauthenticated & role portal."""
    with app.app_context():
        env = _create_test_env()

    # 1. Unauthenticated -> 302 login
    res_anon = client.get("/delivery/scan")
    assert res_anon.status_code == 302
    assert "/auth/login" in res_anon.headers["Location"]

    # 2. Portal customer -> ditolak
    _login_user_id(client, env["portal_user_id"])
    res_portal = client.get("/delivery/scan")
    assert res_portal.status_code in (302, 403)

    # 3. Pengantar -> 200 OK
    _login_user_id(client, env["driver_user_id"])
    res_driver = client.get("/delivery/scan")
    assert res_driver.status_code == 200
    text_driver = res_driver.get_data(as_text=True)
    assert "Scan Label Wadah" in text_driver
    assert "Pilih dari Daftar" in text_driver
    # Header keamanan harus mengizinkan kamera untuk situs sendiri, kalau tidak
    # pemindai tidak bisa membuka kamera sama sekali.
    assert "camera=(self)" in res_driver.headers.get("Permissions-Policy", "")

    # 4. Admin -> 200 OK
    _login_user_id(client, env["admin_id"])
    res_admin = client.get("/delivery/scan")
    assert res_admin.status_code == 200


def test_scan_qr_route_redirects_to_receive_with_container_details(app, client):
    """Route scan QR redirect ke receive, header jelas nomor wadah, realisasi porsi & kamera terisi."""
    with app.app_context():
        env = _create_test_env()

    _login_user_id(client, env["driver_user_id"])

    # Hit scan QR dengan param w=2&n=3
    res_scan = client.get(f"/delivery/scan/{env['detail_id']}/LUNCH?w=2&n=3")
    assert res_scan.status_code == 302
    target_location = res_scan.headers["Location"]
    assert f"/delivery/details/{env['delivery_detail_id']}/receive" in target_location
    assert "w=2" in target_location
    assert "n=3" in target_location
    assert "from_scan=1" in target_location

    # Follow redirect ke halaman receive
    res_receive = client.get(target_location)
    assert res_receive.status_code == 200
    body = res_receive.get_data(as_text=True)

    # Header jelas
    assert env["client_name"] in body
    assert env["location_name"] in body
    assert "15 porsi dipesan" in body
    assert "Wadah 2/3 — pesanan ini punya 3 wadah" in body

    # Form serah terima cepat
    assert 'value="15"' in body  # realisasi porsi default dipesan
    assert 'capture="environment"' in body  # langsung kamera
    assert "Selesai Diantar" in body


def test_scan_qr_order_already_received_shows_status_not_form(app, client):
    """Kalau order sudah diterima: jangan tampilkan form; tampilkan info diterima + foto + tombol Scan berikutnya."""
    with app.app_context():
        env = _create_test_env()
        # Tambahkan DeliveryReceipt
        rcpt = DeliveryReceipt(
            delivery_detail_id=env["delivery_detail_id"],
            receiver_name="Pak Satpam Joko",
            receive_time=datetime(2026, 10, 7, 12, 15, 0),
            notes="Diterima lengkap dan hangat",
        )
        deliv_det = db.session.get(DeliveryDetail, env["delivery_detail_id"])
        deliv_det.delivered_qty = 15
        db.session.add(rcpt)
        db.session.commit()

    _login_user_id(client, env["driver_user_id"])

    res = client.get(f"/delivery/details/{env['delivery_detail_id']}/receive?from_scan=1")
    assert res.status_code == 200
    body = res.get_data(as_text=True)

    # Menampilkan status penerimaan
    assert "Sudah diantar jam" in body
    assert "Scan Berikutnya" in body or "Scan berikutnya" in body
    assert "Pak Satpam Joko" in body

    # Form serah terima TIDAK ditampilkan
    assert "Selesai Diantar" not in body
    assert 'action="/delivery/details/' not in body or 'Form Serah Terima' not in body


def test_save_receive_from_scan_redirects_to_scan_with_success_message(app, client):
    """Simpan serah terima dari halaman hasil scan → redirect ke /delivery/scan dengan pesan sukses."""
    app.config["WTF_CSRF_ENABLED"] = False
    with app.app_context():
        env = _create_test_env()

    _login_user_id(client, env["driver_user_id"])

    res_post = client.post(
        f"/delivery/details/{env['delivery_detail_id']}/receive",
        data={
            "delivered_qty": "15",
            "receiver_name": "Ibu Mandor Siti",
            "notes": "Diterima lengkap tanpa kendala",
            "from_scan": "1",
        },
    )
    assert res_post.status_code == 302
    assert "/delivery/scan" in res_post.headers["Location"]

    res_after = client.get(res_post.headers["Location"])
    assert res_after.status_code == 200
    body = res_after.get_data(as_text=True)
    assert "Tersimpan. Scan label berikutnya." in body


def test_container_labels_contain_qr_with_container_numbers(app, client):
    """Label yang dicetak memuat URL QR dengan nomor wadah (w & n)."""
    with app.app_context():
        env = _create_test_env()
        # Buat order dengan 35 porsi (maks 20 per wadah -> terbagi jadi 2 wadah: 20 dan 15)
        order = db.session.get(DailyOrder, env["order_id"])
        det = db.session.get(DailyOrderDetail, env["detail_id"])
        det.lunch_qty = 35
        det.total_qty = 35
        db.session.commit()

        with app.test_request_context():
            labels_data = build_container_labels_data(order, "LUNCH")

        labels = labels_data["labels"]
        assert len(labels) == 2

        # Cek nomor wadah pada URL scan
        assert "w=1" in labels[0]["scan_url"]
        assert "n=2" in labels[0]["scan_url"]
        assert labels[0]["container_label"] == "Wadah 1/2"

        assert "w=2" in labels[1]["scan_url"]
        assert "n=2" in labels[1]["scan_url"]
        assert labels[1]["container_label"] == "Wadah 2/2"


def test_scan_qr_order_delivery_not_created_yet(app, client):
    """Kalau pengiriman belum dibuat admin: pesan jelas + tombol/redirect."""
    with app.app_context():
        env = _create_test_env()
        # DailyOrder baru tanpa pengiriman
        order_unassigned = DailyOrder(
            branch_id=env["branch_id"],
            order_number=f"ORD-NODLV-{uuid4().hex[:6]}",
            order_date=date.today(),
            status="LOCKED",
            is_locked=True,
            locked_at=datetime.utcnow(),
            created_by=env["admin_id"],
        )
        db.session.add(order_unassigned)
        db.session.flush()

        detail_unassigned = DailyOrderDetail(
            daily_order_id=order_unassigned.id,
            mandor_id=db.session.get(DailyOrderDetail, env["detail_id"]).mandor_id,
            delivery_location_id=db.session.get(DailyOrderDetail, env["detail_id"]).delivery_location_id,
            price_per_portion=Decimal("25000"),
            lunch_qty=10,
            dinner_qty=0,
            total_qty=10,
        )
        db.session.add(detail_unassigned)
        db.session.commit()
        unassigned_id = detail_unassigned.id

    _login_user_id(client, env["driver_user_id"])

    res = client.get(f"/delivery/scan/{unassigned_id}/LUNCH", follow_redirects=True)
    assert res.status_code == 200
    body = res.get_data(as_text=True)
    assert "Pengiriman untuk pesanan ini belum dibuat" in body
