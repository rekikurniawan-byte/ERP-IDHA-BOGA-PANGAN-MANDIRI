from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models.delivery import Delivery, DeliveryDetail, DeliveryReceipt
from app.models.finance import CashBankTransaction, Invoice, SupplierBill
from app.models.logistics import Procurement
from app.models.master import Branch, Client, DeliveryLocation, Driver, Item, Mandor, Supplier, User
from app.models.operational import DailyOrder, DailyOrderDetail
from app.services.live_reminder_service import (
    SECTION_LABELS,
    allowed_reminder_sections,
    build_empty_live_reminder_center,
    build_live_reminder_badge_summary,
    build_live_reminder_center,
)
from app.services.user_management_service import (
    ROLE_ADMIN,
    ROLE_DAPUR,
    ROLE_OWNER,
    ROLE_PENGANTAR,
    ROLE_PORTAL_CLIENT,
    ROLE_PORTAL_CUSTOMER,
    ROLE_PORTAL_SUBCLIENT,
)


def _setup_branch(code_prefix="RMS"):
    suffix = uuid4().hex[:6]
    branch = Branch(code=f"{code_prefix}-{suffix}", name=f"Branch Reminder {suffix}", is_active=True)
    db.session.add(branch)
    db.session.flush()
    return branch


def _create_user(branch, role, username_prefix="u_rm", full_name=None, driver_id=None):
    suffix = uuid4().hex[:6]
    name = full_name or f"User {role} {suffix}"
    user = User(
        branch_id=branch.id,
        full_name=name,
        username=f"{username_prefix}_{role.lower()}_{suffix}",
        password_hash=generate_password_hash("password123"),
        role=role,
        is_active=True,
    )
    if driver_id is not None:
        user.driver_id = driver_id
    db.session.add(user)
    db.session.flush()
    return user


def _login_user_id(client, user_id):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True


def test_allowed_reminder_sections_contract():
    """Verify single source of truth for allowed reminder sections across all roles."""
    all_sections = set(SECTION_LABELS.keys())

    # OWNER & ADMIN (and retired roles mapped to ADMIN) see all sections
    assert allowed_reminder_sections(ROLE_OWNER) == all_sections
    assert allowed_reminder_sections(ROLE_ADMIN) == all_sections
    assert allowed_reminder_sections("FINANCE") == all_sections
    assert allowed_reminder_sections("ACCOUNTING") == all_sections
    assert allowed_reminder_sections("LOGISTICS") == all_sections
    assert allowed_reminder_sections("HR") == all_sections
    assert allowed_reminder_sections("CUSTOMER_SUCCESS") == all_sections

    # DAPUR sees only stock and hpp_order
    assert allowed_reminder_sections(ROLE_DAPUR) == {"stock", "hpp_order"}

    # PENGANTAR sees only delivery and digital_proof
    assert allowed_reminder_sections(ROLE_PENGANTAR) == {"delivery", "digital_proof"}

    # Portal roles see NO internal reminders
    assert allowed_reminder_sections(ROLE_PORTAL_CUSTOMER) == set()
    assert allowed_reminder_sections(ROLE_PORTAL_CLIENT) == set()
    assert allowed_reminder_sections(ROLE_PORTAL_SUBCLIENT) == set()
    assert allowed_reminder_sections("PORTAL_MANDOR") == set()
    assert allowed_reminder_sections("PORTAL_PT") == set()

    # None defaults to all (for system sync / fallback)
    assert allowed_reminder_sections(None) == all_sections


def test_reminder_role_scope_isolation_and_badge_consistency(app):
    """Seed data triggering every section and verify scope isolation & badge consistency."""
    with app.app_context():
        today = date.today()
        branch = _setup_branch()

        # 1. Setup Drivers and Users
        driver1 = Driver(
            branch_id=branch.id,
            name=f"Driver Satu {uuid4().hex[:4]}",
            phone="0811111111",
            license_number="B1111XX",
            is_active=True,
        )
        driver2 = Driver(
            branch_id=branch.id,
            name=f"Driver Dua {uuid4().hex[:4]}",
            phone="0822222222",
            license_number="B2222XX",
            is_active=True,
        )
        db.session.add_all([driver1, driver2])
        db.session.flush()

        admin = _create_user(branch, ROLE_ADMIN, "admin")
        owner = _create_user(branch, ROLE_OWNER, "owner")
        dapur = _create_user(branch, ROLE_DAPUR, "dapur")
        pengantar1 = _create_user(branch, ROLE_PENGANTAR, "p1", full_name=driver1.name, driver_id=driver1.id)
        pengantar2 = _create_user(branch, ROLE_PENGANTAR, "p2", full_name=driver2.name, driver_id=driver2.id)
        portal_user = _create_user(branch, ROLE_PORTAL_CUSTOMER, "portal")

        # 2. Trigger Section: receivable (Overdue Invoice)
        client_obj = Client(name=f"Client {uuid4().hex[:4]}", is_active=True)
        db.session.add(client_obj)
        db.session.flush()
        inv = Invoice(
            branch_id=branch.id,
            invoice_number=f"INV-{uuid4().hex[:6]}",
            invoice_date=today - timedelta(days=10),
            due_date=today - timedelta(days=2),
            bill_to_type="CLIENT",
            client_id=client_obj.id,
            total_amount=Decimal("1500000.00"),
            paid_amount=Decimal("500000.00"),
            remaining_amount=Decimal("1000000.00"),
            status="UNPAID",
            created_by=admin.id,
        )
        db.session.add(inv)

        # 3. Trigger Section: payable (Overdue Supplier Bill)
        supplier = Supplier(
            branch_id=branch.id,
            supplier_code=f"SUP-{uuid4().hex[:6]}",
            supplier_name="Supplier Sayur",
            is_active=True,
        )
        db.session.add(supplier)
        db.session.flush()
        bill = SupplierBill(
            branch_id=branch.id,
            bill_number=f"BILL-{uuid4().hex[:6]}",
            supplier_id=supplier.id,
            supplier_name=supplier.supplier_name,
            bill_date=today - timedelta(days=8),
            due_date=today - timedelta(days=1),
            total_amount=Decimal("750000.00"),
            paid_amount=Decimal("0.00"),
            remaining_amount=Decimal("750000.00"),
            status="OPEN",
            created_by=admin.id,
        )
        db.session.add(bill)

        # 4. Trigger Section: stock (Active Item with 0 stock -> OUT)
        item = Item(
            item_code=f"ITM-{uuid4().hex[:6]}",
            item_name="Beras Ramos",
            category="RAW_MATERIAL",
            unit="kg",
            minimum_stock=Decimal("20.0"),
            is_active=True,
            is_stock_tracked=True,
        )
        db.session.add(item)

        # 5. Trigger Section: hpp_order (DailyOrder locked without HPP snapshot)
        mandor = Mandor(branch_id=branch.id, client_id=client_obj.id, name="Mandor Proyek", is_active=True)
        db.session.add(mandor)
        db.session.flush()
        order = DailyOrder(
            branch_id=branch.id,
            order_number=f"ORD-{uuid4().hex[:6]}",
            order_date=today,
            status="CONFIRMED",
            is_locked=True,
            created_by=admin.id,
        )
        db.session.add(order)
        db.session.flush()
        location = DeliveryLocation(
            mandor_id=mandor.id,
            location_name="Site Proyek A",
            is_active=True,
        )
        db.session.add(location)
        db.session.flush()
        order_detail = DailyOrderDetail(
            daily_order_id=order.id,
            mandor_id=mandor.id,
            delivery_location_id=location.id,
            lunch_qty=10,
            dinner_qty=0,
        )
        db.session.add(order_detail)
        db.session.flush()

        # 6. Trigger Section: delivery (Delivery without receipt)
        # - deliv1 assigned to driver1 (Pengantar 1)
        deliv1 = Delivery(
            delivery_number=f"DLV-P1-{uuid4().hex[:6]}",
            branch_id=branch.id,
            delivery_date=today,
            driver_id=driver1.id,
            status="ON_THE_WAY",
            created_by=admin.id,
        )
        db.session.add(deliv1)
        db.session.flush()
        detail1 = DeliveryDetail(
            delivery_id=deliv1.id,
            daily_order_detail_id=order_detail.id,
            mandor_id=mandor.id,
            delivery_location_id=location.id,
            planned_qty=10,
        )
        db.session.add(detail1)

        # - deliv2 assigned to driver2 (Pengantar 2)
        deliv2 = Delivery(
            delivery_number=f"DLV-P2-{uuid4().hex[:6]}",
            branch_id=branch.id,
            delivery_date=today,
            driver_id=driver2.id,
            status="ON_THE_WAY",
            created_by=admin.id,
        )
        db.session.add(deliv2)
        db.session.flush()
        detail2 = DeliveryDetail(
            delivery_id=deliv2.id,
            daily_order_detail_id=order_detail.id,
            mandor_id=mandor.id,
            delivery_location_id=location.id,
            planned_qty=10,
        )
        db.session.add(detail2)

        # 7. Trigger Section: digital_proof
        # - Procurement without digital invoice attachment
        proc = Procurement(
            branch_id=branch.id,
            procurement_number=f"PROC-{uuid4().hex[:6]}",
            procurement_date=today,
            purchase_type="MARKET",
            supplier_name="Toko Pasar Baru",
            total_amount=Decimal("350000.00"),
            created_by=admin.id,
        )
        db.session.add(proc)

        # - Delivery 3 (driver1) with receipt but without digital proof attachment
        deliv3 = Delivery(
            delivery_number=f"DLV-P1-REC-{uuid4().hex[:6]}",
            branch_id=branch.id,
            delivery_date=today,
            driver_id=driver1.id,
            status="DELIVERED",
            created_by=admin.id,
        )
        db.session.add(deliv3)
        db.session.flush()
        detail3 = DeliveryDetail(
            delivery_id=deliv3.id,
            daily_order_detail_id=order_detail.id,
            mandor_id=mandor.id,
            delivery_location_id=location.id,
            planned_qty=10,
            delivered_qty=10,
        )
        db.session.add(detail3)
        db.session.flush()
        receipt3 = DeliveryReceipt(
            delivery_detail_id=detail3.id,
            receiver_name="Penerima A",
            receive_time=today,
        )
        db.session.add(receipt3)

        # - Delivery 4 (driver2) with receipt but without digital proof attachment
        deliv4 = Delivery(
            delivery_number=f"DLV-P2-REC-{uuid4().hex[:6]}",
            branch_id=branch.id,
            delivery_date=today,
            driver_id=driver2.id,
            status="DELIVERED",
            created_by=admin.id,
        )
        db.session.add(deliv4)
        db.session.flush()
        detail4 = DeliveryDetail(
            delivery_id=deliv4.id,
            daily_order_detail_id=order_detail.id,
            mandor_id=mandor.id,
            delivery_location_id=location.id,
            planned_qty=10,
            delivered_qty=10,
        )
        db.session.add(detail4)
        db.session.flush()
        receipt4 = DeliveryReceipt(
            delivery_detail_id=detail4.id,
            receiver_name="Penerima B",
            receive_time=today,
        )
        db.session.add(receipt4)

        # 8. Trigger Section: cash_bank (Unreconciled Transaction)
        trx = CashBankTransaction(
            branch_id=branch.id,
            transaction_date=today,
            transaction_type="DEBIT",
            account_type="KAS_KECIL",
            amount=Decimal("120000.00"),
            is_reconciled=False,
            description="Beli bensin operasional",
            created_by=admin.id,
        )
        db.session.add(trx)
        db.session.flush()

        # ========================================================
        # TEST SCOPE 1: OWNER & ADMIN see ALL sections
        # ========================================================
        owner_center = build_live_reminder_center(branch.id, user=owner)
        admin_center = build_live_reminder_center(branch.id, user=admin)

        owner_sections = {s["key"] for s in owner_center["sections"]}
        admin_sections = {s["key"] for s in admin_center["sections"]}

        assert owner_sections == set(SECTION_LABELS.keys())
        assert admin_sections == set(SECTION_LABELS.keys())

        # Badge total matches center total
        owner_badge = build_live_reminder_badge_summary(branch.id, user=owner)
        admin_badge = build_live_reminder_badge_summary(branch.id, user=admin)
        assert owner_badge["total"] == owner_center["summary"]["total"]
        assert admin_badge["total"] == admin_center["summary"]["total"]
        assert owner_badge["total"] > 0

        # ========================================================
        # TEST SCOPE 2: DAPUR sees ONLY stock + hpp_order
        # ========================================================
        dapur_center = build_live_reminder_center(branch.id, user=dapur)
        dapur_sections = {s["key"] for s in dapur_center["sections"]}

        assert dapur_sections == {"stock", "hpp_order"}
        assert "receivable" not in dapur_sections
        assert "payable" not in dapur_sections
        assert "delivery" not in dapur_sections
        assert "digital_proof" not in dapur_sections
        assert "cash_bank" not in dapur_sections

        dapur_badge = build_live_reminder_badge_summary(branch.id, user=dapur)
        assert dapur_badge["total"] == dapur_center["summary"]["total"]

        # Number of items equals sum of stock and hpp_order
        dapur_items_sum = sum(s["count"] for s in dapur_center["sections"])
        assert dapur_badge["total"] == dapur_items_sum
        assert dapur_badge["total"] < owner_badge["total"]

        # ========================================================
        # TEST SCOPE 3: PENGANTAR 1 sees ONLY their own delivery & digital_proof
        # ========================================================
        p1_center = build_live_reminder_center(branch.id, user=pengantar1)
        p1_sections = {s["key"] for s in p1_center["sections"]}

        assert p1_sections == {"delivery", "digital_proof"}
        assert "stock" not in p1_sections
        assert "hpp_order" not in p1_sections
        assert "receivable" not in p1_sections
        assert "payable" not in p1_sections
        assert "cash_bank" not in p1_sections

        p1_delivery_refs = [
            item["reference_label"]
            for s in p1_center["sections"] if s["key"] == "delivery"
            for item in s["items"]
        ]
        assert deliv1.delivery_number in p1_delivery_refs
        assert deliv2.delivery_number not in p1_delivery_refs, "Pengantar 1 must NOT see Pengantar 2 delivery"

        p1_proof_refs = [
            item["reference_label"]
            for s in p1_center["sections"] if s["key"] == "digital_proof"
            for item in s["items"]
        ]
        assert deliv3.delivery_number in p1_proof_refs
        assert deliv4.delivery_number not in p1_proof_refs, "Pengantar 1 must NOT see Pengantar 2 receipt proof"
        assert proc.procurement_number not in p1_proof_refs, "Pengantar must NOT see procurement proof reminders"

        p1_badge = build_live_reminder_badge_summary(branch.id, user=pengantar1)
        assert p1_badge["total"] == p1_center["summary"]["total"]
        assert p1_badge["total"] == len(p1_delivery_refs) + len(p1_proof_refs)

        # ========================================================
        # TEST SCOPE 4: PENGANTAR 2 sees ONLY their own delivery & digital_proof
        # ========================================================
        p2_center = build_live_reminder_center(branch.id, user=pengantar2)
        p2_delivery_refs = [
            item["reference_label"]
            for s in p2_center["sections"] if s["key"] == "delivery"
            for item in s["items"]
        ]
        assert deliv2.delivery_number in p2_delivery_refs
        assert deliv1.delivery_number not in p2_delivery_refs, "Pengantar 2 must NOT see Pengantar 1 delivery"

        p2_proof_refs = [
            item["reference_label"]
            for s in p2_center["sections"] if s["key"] == "digital_proof"
            for item in s["items"]
        ]
        assert deliv4.delivery_number in p2_proof_refs
        assert deliv3.delivery_number not in p2_proof_refs, "Pengantar 2 must NOT see Pengantar 1 receipt proof"

        p2_badge = build_live_reminder_badge_summary(branch.id, user=pengantar2)
        assert p2_badge["total"] == p2_center["summary"]["total"]

        # ========================================================
        # TEST SCOPE 5: PORTAL accounts have 0 reminders
        # ========================================================
        portal_center = build_live_reminder_center(branch.id, user=portal_user)
        assert portal_center["sections"] == []
        assert portal_center["summary"]["total"] == 0

        portal_badge = build_live_reminder_badge_summary(branch.id, user=portal_user)
        assert portal_badge["total"] == 0


def test_reminder_route_access_and_portal_rejection(app, client):
    """Verify route /settings/reminders rejects portal users and shows filtered sections per role."""
    with app.app_context():
        branch = _setup_branch("RTR")
        admin = _create_user(branch, ROLE_ADMIN, "rt_admin")
        dapur = _create_user(branch, ROLE_DAPUR, "rt_dapur")
        portal = _create_user(branch, ROLE_PORTAL_CUSTOMER, "rt_portal")
        db.session.commit()
        portal_id = portal.id
        dapur_id = dapur.id
        admin_id = admin.id

    # 1. Portal user is rejected (redirected with warning / 403)
    _login_user_id(client, portal_id)
    res_portal = client.get("/settings/reminders")
    assert res_portal.status_code in (302, 403)

    # 2. Dapur user is allowed (200 OK) and gets only dapur sections
    _login_user_id(client, dapur_id)
    res_dapur = client.get("/settings/reminders")
    assert res_dapur.status_code == 200
    html_dapur = res_dapur.get_data(as_text=True)
    assert "Stok &amp; Bahan" in html_dapur or "Stok & Bahan" in html_dapur
    assert "Order &amp; HPP" in html_dapur or "Order & HPP" in html_dapur
    # Disallowed sections must not be present in card headers
    assert "Invoice &amp; Piutang" not in html_dapur and "Invoice & Piutang" not in html_dapur
    assert "Hutang Supplier" not in html_dapur
    assert "Kas/Bank" not in html_dapur

    # 3. Admin user is allowed (200 OK) and gets all sections
    _login_user_id(client, admin_id)
    res_admin = client.get("/settings/reminders")
    assert res_admin.status_code == 200
    html_admin = res_admin.get_data(as_text=True)
    assert "Stok &amp; Bahan" in html_admin or "Stok & Bahan" in html_admin
    assert "Hutang Supplier" in html_admin
    assert "Kas/Bank" in html_admin


def test_pengantar_badge_cache_key_isolation(app, client):
    """Verify that live reminder badge cache differentiates by user_id for PENGANTAR."""
    with app.app_context():
        branch = _setup_branch("CKI")
        driver1 = Driver(branch_id=branch.id, name=f"Drv1 {uuid4().hex[:4]}", is_active=True)
        driver2 = Driver(branch_id=branch.id, name=f"Drv2 {uuid4().hex[:4]}", is_active=True)
        db.session.add_all([driver1, driver2])
        db.session.flush()

        p1 = _create_user(branch, ROLE_PENGANTAR, "p1", full_name=driver1.name, driver_id=driver1.id)
        p2 = _create_user(branch, ROLE_PENGANTAR, "p2", full_name=driver2.name, driver_id=driver2.id)
        admin = _create_user(branch, ROLE_ADMIN, "ad")

        # Create 1 unreceived delivery for p1 only
        order = DailyOrder(
            branch_id=branch.id,
            order_number=f"ORD-CK-{uuid4().hex[:6]}",
            order_date=date.today(),
            status="CONFIRMED",
            is_locked=True,
            created_by=admin.id,
        )
        db.session.add(order)
        db.session.flush()

        client_cki = Client(name=f"Client CKI {uuid4().hex[:4]}", is_active=True)
        db.session.add(client_cki)
        db.session.flush()

        mandor = Mandor(branch_id=branch.id, client_id=client_cki.id, name="Mandor CKI", is_active=True)
        db.session.add(mandor)
        db.session.flush()

        loc = DeliveryLocation(mandor_id=mandor.id, location_name="Loc CKI", is_active=True)
        db.session.add(loc)
        db.session.flush()

        order_detail = DailyOrderDetail(
            daily_order_id=order.id,
            mandor_id=mandor.id,
            delivery_location_id=loc.id,
            lunch_qty=5,
            dinner_qty=0,
        )
        db.session.add(order_detail)
        db.session.flush()

        deliv_p1 = Delivery(
            delivery_number=f"DLV-CK1-{uuid4().hex[:6]}",
            branch_id=branch.id,
            delivery_date=date.today(),
            driver_id=driver1.id,
            status="ON_THE_WAY",
            created_by=admin.id,
        )
        db.session.add(deliv_p1)
        db.session.flush()
        db.session.add(DeliveryDetail(
            delivery_id=deliv_p1.id,
            daily_order_detail_id=order_detail.id,
            mandor_id=mandor.id,
            delivery_location_id=loc.id,
            planned_qty=5,
        ))
        db.session.commit()

        p1_id, p2_id = p1.id, p2.id
        branch_id = branch.id

    # Request dashboard/pages for p1
    _login_user_id(client, p1_id)
    res_p1 = client.get("/dashboard/pengantar")
    assert res_p1.status_code == 200

    # Request dashboard/pages for p2
    _login_user_id(client, p2_id)
    res_p2 = client.get("/dashboard/pengantar")
    assert res_p2.status_code == 200

    # Test badge summary calculation for both
    with app.app_context():
        p1_user = db.session.get(User, p1_id)
        p2_user = db.session.get(User, p2_id)
        b1 = build_live_reminder_badge_summary(branch_id, user=p1_user)
        b2 = build_live_reminder_badge_summary(branch_id, user=p2_user)
        assert b1["total"] == 1
        assert b2["total"] == 0

