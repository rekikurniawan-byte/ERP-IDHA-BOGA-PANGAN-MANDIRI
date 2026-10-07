from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from flask import url_for
from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models.delivery import Delivery, DeliveryDetail
from app.models.master import Branch, Client, DeliveryLocation, Driver, Mandor, User
from app.models.operational import DailyOrder, DailyOrderDetail
from app.services.kitchen_recap_service import (
    calculate_order_session_hash,
    get_session_print_history,
    record_print_event,
    split_containers,
)
from app.services.user_management_service import (
    ROLE_ADMIN,
    ROLE_DAPUR,
    ROLE_PENGANTAR,
    ROLE_PORTAL_CUSTOMER,
)


def _login_user_id(client, user_id):
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def _create_test_env():
    suffix = uuid4().hex[:6]
    branch = Branch(code=f"BR-{suffix}", name="Branch Test Dapur", is_active=True)
    db.session.add(branch)
    db.session.flush()

    admin = User(
        branch_id=branch.id,
        full_name=f"Admin {suffix}",
        username=f"admin_{suffix}",
        password_hash=generate_password_hash("password123"),
        role=ROLE_ADMIN,
        is_active=True,
    )
    dapur = User(
        branch_id=branch.id,
        full_name=f"Dapur {suffix}",
        username=f"dapur_{suffix}",
        password_hash=generate_password_hash("password123"),
        role=ROLE_DAPUR,
        is_active=True,
    )
    driver_user = User(
        branch_id=branch.id,
        full_name=f"Driver User {suffix}",
        username=f"driver_{suffix}",
        password_hash=generate_password_hash("password123"),
        role=ROLE_PENGANTAR,
        is_active=True,
    )
    customer_user = User(
        branch_id=branch.id,
        full_name=f"Pelanggan {suffix}",
        username=f"pelanggan_{suffix}",
        password_hash=generate_password_hash("password123"),
        role=ROLE_PORTAL_CUSTOMER,
        is_active=True,
    )
    db.session.add_all([admin, dapur, driver_user, customer_user])
    db.session.flush()

    # 1. Contract client
    contract_client = Client(
        name=f"PT Kontrak {suffix}",
        customer_path="KONTRAK",
        is_active=True,
    )
    # 2. General prepaid client
    prepaid_client = Client(
        name=f"Pelanggan Prabayar {suffix}",
        customer_path="UMUM",
        is_active=True,
    )
    db.session.add_all([contract_client, prepaid_client])
    db.session.flush()

    mandor_contract = Mandor(
        branch_id=branch.id,
        client_id=contract_client.id,
        name=f"Mandor Kontrak {suffix}",
        phone="081234567890",
        is_active=True,
    )
    mandor_prepaid = Mandor(
        branch_id=branch.id,
        client_id=prepaid_client.id,
        name=f"Pelanggan Prabayar {suffix}",
        phone="081987654321",
        is_active=True,
    )
    db.session.add_all([mandor_contract, mandor_prepaid])
    db.session.flush()

    loc_contract = DeliveryLocation(
        mandor_id=mandor_contract.id,
        location_name="Proyek Site A",
        description="Pintu Biru Depan Pos",
        is_active=True,
    )
    loc_prepaid = DeliveryLocation(
        mandor_id=mandor_prepaid.id,
        location_name="Ruko Mawar",
        description="Sebelah Apotek Mawar",
        is_active=True,
    )
    db.session.add_all([loc_contract, loc_prepaid])
    db.session.commit()

    return {
        "branch_id": branch.id,
        "admin_id": admin.id,
        "dapur_id": dapur.id,
        "driver_user_id": driver_user.id,
        "customer_user_id": customer_user.id,
        "mandor_contract_id": mandor_contract.id,
        "mandor_prepaid_id": mandor_prepaid.id,
        "loc_contract_id": loc_contract.id,
        "loc_prepaid_id": loc_prepaid.id,
        "contract_client_name": contract_client.name,
        "prepaid_client_name": prepaid_client.name,
    }


def test_split_containers_unit():
    """Unit test fungsi murni split_containers untuk berbagai skenario porsi."""
    # max 20 cases from prompt
    assert split_containers(45, 20) == [15, 15, 15]
    assert split_containers(50, 20) == [17, 17, 16]
    assert split_containers(12, 20) == [12]
    assert split_containers(1, 20) == [1]
    assert split_containers(15, 20) == [15]
    assert split_containers(20, 20) == [20]
    assert split_containers(21, 20) == [11, 10]
    assert split_containers(40, 20) == [20, 20]

    # Edge cases
    assert split_containers(0, 20) == []
    assert split_containers(-5, 20) == []


def test_print_buttons_and_routes_locked_vs_unlocked(app, client):
    """Tombol cetak dan route rekap/label ditolak sebelum lock, dan diizinkan setelah lock."""
    with app.app_context():
        env = _create_test_env()
        order_date = date.today()

        daily_order = DailyOrder(
            branch_id=env["branch_id"],
            order_number=f"ORD-TEST-{uuid4().hex[:6]}",
            order_date=order_date,
            status="DRAFT",
            is_locked=False,
            created_by=env["admin_id"],
        )
        db.session.add(daily_order)
        db.session.flush()

        detail = DailyOrderDetail(
            daily_order_id=daily_order.id,
            mandor_id=env["mandor_contract_id"],
            delivery_location_id=env["loc_contract_id"],
            price_per_portion=Decimal("25000"),
            lunch_qty=20,
            dinner_qty=0,
            total_qty=20,
        )
        db.session.add(detail)
        db.session.commit()
        order_id = daily_order.id

    _login_user_id(client, env["admin_id"])

    # 1. Saat belum di-lock: halaman order_detail tidak punya panel cetak
    res = client.get(f"/operational/orders/{order_id}")
    assert res.status_code == 200
    assert b'data-kitchen-print-panel="true"' not in res.data

    # Route cetak ditolak bila belum lock
    with app.test_request_context():
        recap_url = url_for("operational.kitchen_recap", order_id=order_id, sesi="LUNCH")
        labels_url = url_for("operational.container_labels", order_id=order_id, sesi="LUNCH")

    res_recap = client.get(recap_url, follow_redirects=True)
    assert res_recap.status_code == 200
    assert "Hanya" in res_recap.get_data(as_text=True) or "dikunci" in res_recap.get_data(as_text=True)

    res_labels = client.get(labels_url, follow_redirects=True)
    assert res_labels.status_code == 200
    assert "Hanya" in res_labels.get_data(as_text=True) or "dikunci" in res_labels.get_data(as_text=True)

    # 2. Sekarang kunci (lock) order
    with app.app_context():
        order_to_lock = DailyOrder.query.get(order_id)
        order_to_lock.is_locked = True
        order_to_lock.status = "LOCKED"
        order_to_lock.locked_at = datetime.utcnow()
        db.session.commit()

    # Panel cetak muncul
    res = client.get(f"/operational/orders/{order_id}")
    assert res.status_code == 200
    assert b'data-kitchen-print-panel="true"' in res.data
    assert "Cetak Rekap Dapur" in res.get_data(as_text=True)
    assert "Cetak Label Wadah" in res.get_data(as_text=True)

    # Route rekap & label bisa diakses setelah lock
    res_recap = client.get(recap_url)
    assert res_recap.status_code == 200
    assert "REKAP OPERASIONAL DAPUR" in res_recap.get_data(as_text=True)

    res_labels = client.get(labels_url + "?size=58mm")
    assert res_labels.status_code == 200
    assert "Label Wadah" in res_labels.get_data(as_text=True)
    assert "<svg" in res_labels.get_data(as_text=True)  # Inline QR SVG from segno


def test_recap_and_labels_contain_contract_and_prepaid(app, client):
    """Rekap dan label memuat pesanan pelanggan kontrak dan pelanggan umum/prabayar."""
    with app.app_context():
        env = _create_test_env()
        order_date = date.today()

        daily_order = DailyOrder(
            branch_id=env["branch_id"],
            order_number=f"ORD-MIX-{uuid4().hex[:6]}",
            order_date=order_date,
            status="LOCKED",
            is_locked=True,
            locked_at=datetime.utcnow(),
            created_by=env["admin_id"],
        )
        db.session.add(daily_order)
        db.session.flush()

        detail_contract = DailyOrderDetail(
            daily_order_id=daily_order.id,
            mandor_id=env["mandor_contract_id"],
            delivery_location_id=env["loc_contract_id"],
            price_per_portion=Decimal("25000"),
            lunch_qty=25,
            dinner_qty=0,
            total_qty=25,
        )
        detail_prepaid = DailyOrderDetail(
            daily_order_id=daily_order.id,
            mandor_id=env["mandor_prepaid_id"],
            delivery_location_id=env["loc_prepaid_id"],
            price_per_portion=Decimal("30000"),
            lunch_qty=15,
            dinner_qty=0,
            total_qty=15,
        )
        db.session.add_all([detail_contract, detail_prepaid])
        db.session.commit()
        order_id = daily_order.id

    _login_user_id(client, env["admin_id"])

    with app.test_request_context():
        recap_url = url_for("operational.kitchen_recap", order_id=order_id, sesi="LUNCH")
        labels_url = url_for("operational.container_labels", order_id=order_id, sesi="LUNCH")

    # Rekap
    res_recap = client.get(recap_url)
    assert res_recap.status_code == 200
    body_recap = res_recap.get_data(as_text=True)
    assert env["contract_client_name"] in body_recap
    assert env["prepaid_client_name"] in body_recap
    # Total portion 25 + 15 = 40
    assert "40" in body_recap

    # Label (80mm)
    res_label = client.get(labels_url + "?size=80mm")
    assert res_label.status_code == 200
    body_label = res_label.get_data(as_text=True)
    assert env["contract_client_name"] in body_label
    assert env["prepaid_client_name"] in body_label
    assert "Wadah 1/2" in body_label  # 25 porsi with max 20 -> 2 containers
    assert "Wadah 1/1" in body_label  # 15 porsi with max 20 -> 1 container


def test_reprint_warning_triggers_on_portion_change(app, client):
    """Tanda 'Cetak ulang — data berubah sejak dicetak' muncul bila porsi berubah setelah cetak."""
    with app.app_context():
        env = _create_test_env()
        order_date = date.today()

        daily_order = DailyOrder(
            branch_id=env["branch_id"],
            order_number=f"ORD-WARN-{uuid4().hex[:6]}",
            order_date=order_date,
            status="LOCKED",
            is_locked=True,
            locked_at=datetime.utcnow(),
            created_by=env["admin_id"],
        )
        db.session.add(daily_order)
        db.session.flush()

        detail = DailyOrderDetail(
            daily_order_id=daily_order.id,
            mandor_id=env["mandor_contract_id"],
            delivery_location_id=env["loc_contract_id"],
            price_per_portion=Decimal("25000"),
            lunch_qty=12,
            dinner_qty=0,
            total_qty=12,
        )
        db.session.add(detail)
        db.session.commit()
        order_id = daily_order.id
        detail_id = detail.id

    _login_user_id(client, env["admin_id"])

    with app.test_request_context():
        recap_url = url_for("operational.kitchen_recap", order_id=order_id, sesi="LUNCH")
        labels_url = url_for("operational.container_labels", order_id=order_id, sesi="LUNCH")

    # 1. Cetak pertama (merekam audit print untuk rekap & label)
    res_recap1 = client.get(recap_url)
    assert res_recap1.status_code == 200
    assert "data-stale-warning" not in res_recap1.get_data(as_text=True)

    res_labels1 = client.get(labels_url)
    assert res_labels1.status_code == 200
    assert "CETAK ULANG" not in res_labels1.get_data(as_text=True)

    res_detail1 = client.get(f"/operational/orders/{order_id}")
    assert "Sudah dicetak" in res_detail1.get_data(as_text=True)
    assert "Cetak ulang — data berubah sejak dicetak" not in res_detail1.get_data(as_text=True)

    # 2. Ubah porsi pesanan
    with app.app_context():
        d = DailyOrderDetail.query.get(detail_id)
        d.lunch_qty = 20
        d.total_qty = 20
        db.session.commit()

    # 3. Halaman order_detail, rekap, dan label sekarang harus mendeteksi perubahan
    res_detail2 = client.get(f"/operational/orders/{order_id}")
    assert "Cetak ulang — data berubah sejak dicetak" in res_detail2.get_data(as_text=True)

    res_recap2 = client.get(recap_url)
    assert "Cetak ulang — data berubah sejak dicetak" in res_recap2.get_data(as_text=True)

    res_labels2 = client.get(labels_url)
    assert "Cetak ulang — data berubah sejak dicetak" in res_labels2.get_data(as_text=True)
    assert "CETAK ULANG" in res_labels2.get_data(as_text=True)


def test_scan_qr_route_permissions_and_redirect(app, client):
    """Route scan QR: redirect serah terima, role tanpa akses ditolak."""
    with app.app_context():
        env = _create_test_env()
        order_date = date.today()

        daily_order = DailyOrder(
            branch_id=env["branch_id"],
            order_number=f"ORD-SCAN-{uuid4().hex[:6]}",
            order_date=order_date,
            status="LOCKED",
            is_locked=True,
            locked_at=datetime.utcnow(),
            created_by=env["admin_id"],
        )
        db.session.add(daily_order)
        db.session.flush()

        detail = DailyOrderDetail(
            daily_order_id=daily_order.id,
            mandor_id=env["mandor_contract_id"],
            delivery_location_id=env["loc_contract_id"],
            price_per_portion=Decimal("25000"),
            lunch_qty=10,
            dinner_qty=0,
            total_qty=10,
        )
        db.session.add(detail)
        db.session.commit()
        detail_id = detail.id
        daily_order_id = daily_order.id

        driver = Driver(branch_id=env["branch_id"], name="Driver Scan", is_active=True)
        db.session.add(driver)
        db.session.flush()

        delivery = Delivery(
            branch_id=env["branch_id"],
            delivery_number=f"DLV-{uuid4().hex[:6]}",
            delivery_date=order_date,
            driver_id=driver.id,
            status="ASSIGNED",
            notes="delivery_type=LUNCH",
            created_by=env["admin_id"],
        )
        db.session.add(delivery)
        db.session.flush()

        deliv_detail = DeliveryDetail(
            delivery_id=delivery.id,
            daily_order_detail_id=detail.id,
            mandor_id=detail.mandor_id,
            delivery_location_id=detail.delivery_location_id,
            planned_qty=10,
            delivered_qty=0,
        )
        db.session.add(deliv_detail)
        db.session.commit()
        delivery_detail_id = deliv_detail.id

    # 1. Unauthenticated -> 302 login
    res_anon = client.get(f"/delivery/scan/{detail_id}/LUNCH")
    assert res_anon.status_code == 302
    assert "/auth/login" in res_anon.headers["Location"]

    # 2. Portal customer -> access denied (redirects to dashboard)
    _login_user_id(client, env["customer_user_id"])
    res_cust = client.get(f"/delivery/scan/{detail_id}/LUNCH")
    assert res_cust.status_code in (403, 302)

    # 3. Driver/Pengantar -> Redirect to delivery.receive
    _login_user_id(client, env["driver_user_id"])
    res_driver = client.get(f"/delivery/scan/{detail_id}/LUNCH")
    assert res_driver.status_code == 302
    assert f"/delivery/details/{delivery_detail_id}/receive" in res_driver.headers["Location"]

    # 4. Detail yang belum dibuat delivery-nya -> redirect dengan warning
    with app.app_context():
        detail2 = DailyOrderDetail(
            daily_order_id=daily_order_id,
            mandor_id=env["mandor_prepaid_id"],
            delivery_location_id=env["loc_prepaid_id"],
            price_per_portion=Decimal("25000"),
            lunch_qty=10,
            dinner_qty=0,
            total_qty=10,
        )
        db.session.add(detail2)
        db.session.commit()
        detail2_id = detail2.id

    res_no_deliv = client.get(f"/delivery/scan/{detail2_id}/LUNCH", follow_redirects=True)
    assert res_no_deliv.status_code == 200
    assert "Pengiriman untuk pesanan ini belum dibuat" in res_no_deliv.get_data(as_text=True)
