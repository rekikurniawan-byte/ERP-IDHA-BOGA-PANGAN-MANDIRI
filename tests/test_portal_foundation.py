from uuid import uuid4
from datetime import date, timedelta

from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models.delivery import Delivery, DeliveryDetail
from app.models.finance import Invoice, Payment, SupplierBill
from app.models.logistics import Procurement, ProcurementItem, StockMovement, StockOpeningBalance
from app.models.master import Branch, Client, ClientPic, DeliveryLocation, Driver, Item, Mandor, Supplier, User
from app.models.operational import DailyOrder, DailyOrderDetail
from app.models.production import Production, ProductionDetail
from app.services.portal_access_service import (
    build_portal_access_scope,
    build_portal_delivery_visibility,
    build_portal_financial_visibility,
    build_portal_inventory_visibility,
    build_portal_ownership_analysis,
    build_portal_order_status_visibility,
    build_portal_procurement_visibility,
    build_portal_production_visibility,
    build_portal_status_shell,
)


def _create_test_user(role="OWNER"):
    suffix = uuid4().hex[:10]
    branch = Branch(
        code=f"T-PORTAL-{suffix}",
        name="Test Portal Branch",
        address="Test",
        phone="0800000000",
        is_active=True,
    )
    user = User(
        branch=branch,
        full_name=f"Test Portal {role}",
        username=f"portal-{role.lower()}-{suffix}",
        password_hash=generate_password_hash("portal-test-password"),
        role=role,
        is_active=True,
    )
    db.session.add(branch)
    db.session.add(user)
    db.session.flush()
    return user


def _login(client, user):
    with client.session_transaction() as session:
        session["_user_id"] = str(user.id)
        session["_fresh"] = True


def _create_scope_master_data(user):
    client = Client(
        client_code=f"T-PORTAL-CLIENT-{uuid4().hex[:8]}",
        name="AAA Test Portal Client",
        address="Test",
        phone="0800000001",
        is_active=True,
    )
    db.session.add(client)
    db.session.flush()

    client_pic = ClientPic(
        client_id=client.id,
        name="AAA Test Portal PIC",
        phone="0800000002",
        email="portal@example.test",
        position="PIC",
        is_active=True,
    )
    mandor = Mandor(
        branch_id=user.branch_id,
        client_id=client.id,
        name="AAA Test Portal Mandor",
        phone="0800000003",
        is_active=True,
    )
    db.session.add(client_pic)
    db.session.add(mandor)
    db.session.flush()

    location = DeliveryLocation(
        mandor_id=mandor.id,
        location_name="AAA Test Portal Location",
        description="Test location",
        is_active=True,
    )
    db.session.add(location)
    db.session.flush()
    return client, client_pic, mandor, location


def _create_other_branch_scope_data():
    branch = Branch(
        code=f"T-PORTAL-OTHER-{uuid4().hex[:8]}",
        name="Other Portal Branch",
        address="Other",
        phone="0800000099",
        is_active=True,
    )
    client = Client(
        client_code=f"T-PORTAL-OTHER-CLIENT-{uuid4().hex[:8]}",
        name="ZZZ Other Branch Client",
        address="Other",
        phone="0800000098",
        is_active=True,
    )
    db.session.add(branch)
    db.session.add(client)
    db.session.flush()
    mandor = Mandor(
        branch_id=branch.id,
        client_id=client.id,
        name="ZZZ Other Branch Mandor",
        phone="0800000097",
        is_active=True,
    )
    db.session.add(mandor)
    db.session.flush()
    location = DeliveryLocation(
        mandor_id=mandor.id,
        location_name="ZZZ Other Branch Location",
        description="Other",
        is_active=True,
    )
    db.session.add(location)
    db.session.flush()
    return branch, client, mandor, location


def _create_financial_visibility_data(user):
    client, _, mandor, _ = _create_scope_master_data(user)
    invoice = Invoice(
        branch_id=user.branch_id,
        invoice_number=f"T-PORTAL-INV-{uuid4().hex[:8]}",
        invoice_date=date.today(),
        due_date=date.today() + timedelta(days=7),
        bill_to_type="CLIENT",
        client_id=client.id,
        mandor_id=mandor.id,
        client_name_snapshot="AAA Test Portal Client",
        total_amount=150000,
        paid_amount=50000,
        remaining_amount=100000,
        status="PARTIAL",
        created_by=user.id,
    )
    db.session.add(invoice)
    db.session.flush()
    payment = Payment(
        branch_id=user.branch_id,
        payment_number=f"T-PORTAL-PAY-{uuid4().hex[:8]}",
        payment_date=date.today(),
        invoice_id=invoice.id,
        payment_method="TRANSFER",
        amount=50000,
        reference_number="T-PORTAL-REF",
        received_by=user.id,
    )
    db.session.add(payment)
    db.session.flush()
    return invoice, payment


def _create_other_branch_financial_data(user):
    branch, client, mandor, _ = _create_other_branch_scope_data()
    invoice = Invoice(
        branch_id=branch.id,
        invoice_number=f"T-PORTAL-OTHER-INV-{uuid4().hex[:8]}",
        invoice_date=date.today(),
        due_date=date.today() + timedelta(days=7),
        bill_to_type="CLIENT",
        client_id=client.id,
        mandor_id=mandor.id,
        client_name_snapshot="ZZZ Other Branch Client",
        total_amount=990000,
        paid_amount=0,
        remaining_amount=990000,
        status="OPEN",
        created_by=user.id,
    )
    db.session.add(invoice)
    db.session.flush()
    return invoice


def _create_order_status_data(user):
    _, _, mandor, location = _create_scope_master_data(user)
    order = DailyOrder(
        order_number=f"T-PORTAL-ORD-{uuid4().hex[:8]}",
        branch_id=user.branch_id,
        order_date=date.today(),
        status="LOCKED",
        is_locked=True,
        created_by=user.id,
    )
    db.session.add(order)
    db.session.flush()
    detail = DailyOrderDetail(
        daily_order_id=order.id,
        mandor_id=mandor.id,
        delivery_location_id=location.id,
        price_per_portion=10000,
        lunch_qty=10,
        dinner_qty=0,
        total_qty=10,
    )
    production = Production(
        branch_id=user.branch_id,
        production_date=order.order_date,
        production_type="LUNCH",
        status="COMPLETED",
        created_by=user.id,
    )
    db.session.add(detail)
    db.session.add(production)
    db.session.flush()
    return order, detail, production


def _create_other_branch_order_status_data(user):
    branch, client, mandor, location = _create_other_branch_scope_data()
    order = DailyOrder(
        order_number=f"T-PORTAL-OTHER-ORD-{uuid4().hex[:8]}",
        branch_id=branch.id,
        order_date=date.today(),
        status="LOCKED",
        is_locked=True,
        created_by=user.id,
    )
    db.session.add(order)
    db.session.flush()
    detail = DailyOrderDetail(
        daily_order_id=order.id,
        mandor_id=mandor.id,
        delivery_location_id=location.id,
        price_per_portion=10000,
        lunch_qty=99,
        dinner_qty=0,
        total_qty=99,
    )
    db.session.add(detail)
    db.session.flush()
    return order


def _create_delivery_visibility_data(user):
    order, detail, _ = _create_order_status_data(user)
    driver = Driver(
        branch_id=user.branch_id,
        name="AAA Test Portal Driver",
        phone="0800000044",
        is_active=True,
    )
    db.session.add(driver)
    db.session.flush()

    delivery = Delivery(
        delivery_number=f"T-PORTAL-DLV-{uuid4().hex[:8]}",
        branch_id=user.branch_id,
        delivery_date=order.order_date,
        driver_id=driver.id,
        status="DELIVERED",
        created_by=user.id,
    )
    db.session.add(delivery)
    db.session.flush()

    delivery_detail = DeliveryDetail(
        delivery_id=delivery.id,
        daily_order_detail_id=detail.id,
        mandor_id=detail.mandor_id,
        delivery_location_id=detail.delivery_location_id,
        planned_qty=10,
        delivered_qty=8,
        shortage_qty=2,
    )
    db.session.add(delivery_detail)
    db.session.flush()
    return delivery


def _create_other_branch_delivery_visibility_data(user):
    branch, _, mandor, location = _create_other_branch_scope_data()
    order = DailyOrder(
        order_number=f"T-PORTAL-OTHER-DLV-ORD-{uuid4().hex[:8]}",
        branch_id=branch.id,
        order_date=date.today(),
        status="LOCKED",
        is_locked=True,
        created_by=user.id,
    )
    db.session.add(order)
    db.session.flush()
    order_detail = DailyOrderDetail(
        daily_order_id=order.id,
        mandor_id=mandor.id,
        delivery_location_id=location.id,
        price_per_portion=10000,
        lunch_qty=90,
        dinner_qty=0,
        total_qty=90,
    )
    driver = Driver(
        branch_id=branch.id,
        name="ZZZ Other Portal Driver",
        phone="0800000094",
        is_active=True,
    )
    db.session.add(order_detail)
    db.session.add(driver)
    db.session.flush()

    delivery = Delivery(
        delivery_number=f"T-PORTAL-OTHER-DLV-{uuid4().hex[:8]}",
        branch_id=branch.id,
        delivery_date=order.order_date,
        driver_id=driver.id,
        status="DELIVERED",
        created_by=user.id,
    )
    db.session.add(delivery)
    db.session.flush()
    db.session.add(
        DeliveryDetail(
            delivery_id=delivery.id,
            daily_order_detail_id=order_detail.id,
            mandor_id=mandor.id,
            delivery_location_id=location.id,
            planned_qty=90,
            delivered_qty=90,
            shortage_qty=0,
        )
    )
    db.session.flush()
    return delivery


def _create_production_visibility_data(user):
    item = Item(
        item_code=f"T-PORTAL-PROD-ITEM-{uuid4().hex[:8]}",
        item_name="AAA Test Portal Production Item",
        category="RAW_MATERIAL",
        unit="KG",
        minimum_stock=0,
        selling_price=0,
        is_stock_tracked=True,
        is_active=True,
    )
    production = Production(
        branch_id=user.branch_id,
        production_date=date.today(),
        production_type="LUNCH",
        status="COMPLETED",
        created_by=user.id,
    )
    db.session.add(item)
    db.session.add(production)
    db.session.flush()
    db.session.add(
        ProductionDetail(
            production_id=production.id,
            item_id=item.id,
            planned_qty=12,
            actual_qty=10,
            unit="KG",
        )
    )
    db.session.flush()
    return production, item


def _create_other_branch_production_visibility_data(user):
    branch = Branch(
        code=f"T-PORTAL-OTHER-PROD-{uuid4().hex[:8]}",
        name="Other Production Branch",
        address="Other",
        phone="0800000088",
        is_active=True,
    )
    item = Item(
        item_code=f"T-PORTAL-OTHER-PROD-ITEM-{uuid4().hex[:8]}",
        item_name="ZZZ Other Portal Production Item",
        category="RAW_MATERIAL",
        unit="KG",
        minimum_stock=0,
        selling_price=0,
        is_stock_tracked=True,
        is_active=True,
    )
    db.session.add(branch)
    db.session.add(item)
    db.session.flush()
    production = Production(
        branch_id=branch.id,
        production_date=date.today(),
        production_type="DINNER",
        status="COMPLETED",
        created_by=user.id,
    )
    db.session.add(production)
    db.session.flush()
    db.session.add(
        ProductionDetail(
            production_id=production.id,
            item_id=item.id,
            planned_qty=99,
            actual_qty=99,
            unit="KG",
        )
    )
    db.session.flush()
    return production, item


def _create_inventory_visibility_data(user):
    item = Item(
        item_code=f"T-PORTAL-STOCK-ITEM-{uuid4().hex[:8]}",
        item_name="AAA Test Portal Stock Item",
        category="RAW_MATERIAL",
        unit="KG",
        minimum_stock=5,
        selling_price=0,
        is_stock_tracked=True,
        is_active=True,
    )
    db.session.add(item)
    db.session.flush()
    opening = StockOpeningBalance(
        branch_id=user.branch_id,
        item_id=item.id,
        opening_date=date.today(),
        qty=5,
        notes="Portal inventory test opening",
        created_by=user.id,
    )
    in_movement = StockMovement(
        branch_id=user.branch_id,
        item_id=item.id,
        movement_date=date.today(),
        movement_type="IN",
        reference_type="PORTAL_TEST",
        reference_id=1,
        qty=10,
        notes="Portal inventory test in",
        created_by=user.id,
    )
    out_movement = StockMovement(
        branch_id=user.branch_id,
        item_id=item.id,
        movement_date=date.today(),
        movement_type="OUT",
        reference_type="PORTAL_TEST",
        reference_id=2,
        qty=3,
        notes="Portal inventory test out",
        created_by=user.id,
    )
    db.session.add(opening)
    db.session.add(in_movement)
    db.session.add(out_movement)
    db.session.flush()
    return item


def _create_other_branch_inventory_visibility_data(user):
    branch = Branch(
        code=f"T-PORTAL-OTHER-STOCK-{uuid4().hex[:8]}",
        name="Other Stock Branch",
        address="Other",
        phone="0800000077",
        is_active=True,
    )
    item = Item(
        item_code=f"T-PORTAL-OTHER-STOCK-ITEM-{uuid4().hex[:8]}",
        item_name="ZZZ Other Portal Stock Item",
        category="RAW_MATERIAL",
        unit="KG",
        minimum_stock=1,
        selling_price=0,
        is_stock_tracked=True,
        is_active=True,
    )
    db.session.add(branch)
    db.session.add(item)
    db.session.flush()
    db.session.add(
        StockMovement(
            branch_id=branch.id,
            item_id=item.id,
            movement_date=date.today(),
            movement_type="IN",
            reference_type="PORTAL_TEST_OTHER",
            reference_id=9,
            qty=99,
            notes="Other branch inventory test",
            created_by=user.id,
        )
    )
    db.session.flush()
    return item


def _create_procurement_visibility_data(user):
    supplier = Supplier(
        branch_id=user.branch_id,
        supplier_code=f"T-PORTAL-SUP-{uuid4().hex[:8]}",
        supplier_name="AAA Test Portal Supplier",
        supplier_type="GENERAL",
        is_active=True,
    )
    item = Item(
        item_code=f"T-PORTAL-PROC-ITEM-{uuid4().hex[:8]}",
        item_name="AAA Test Portal Procurement Item",
        category="RAW_MATERIAL",
        unit="KG",
        minimum_stock=0,
        selling_price=0,
        is_stock_tracked=True,
        is_active=True,
    )
    db.session.add(supplier)
    db.session.add(item)
    db.session.flush()
    procurement = Procurement(
        procurement_number=f"T-PORTAL-PROC-{uuid4().hex[:8]}",
        branch_id=user.branch_id,
        supplier_id=supplier.id,
        procurement_date=date.today(),
        purchase_type="CREDIT",
        supplier_name=supplier.supplier_name,
        total_amount=75000,
        created_by=user.id,
    )
    db.session.add(procurement)
    db.session.flush()
    db.session.add(
        ProcurementItem(
            procurement_id=procurement.id,
            item_id=item.id,
            qty=5,
            unit_price=15000,
            subtotal=75000,
        )
    )
    db.session.flush()
    bill = SupplierBill(
        branch_id=user.branch_id,
        bill_number=f"T-PORTAL-BILL-{uuid4().hex[:8]}",
        supplier_id=supplier.id,
        procurement_id=procurement.id,
        bill_date=date.today(),
        due_date=date.today() + timedelta(days=7),
        supplier_name=supplier.supplier_name,
        total_amount=75000,
        paid_amount=25000,
        remaining_amount=50000,
        status="PARTIAL",
        created_by=user.id,
    )
    db.session.add(bill)
    db.session.flush()
    return procurement, bill, supplier


def _create_other_branch_procurement_visibility_data(user):
    branch = Branch(
        code=f"T-PORTAL-OTHER-PROC-{uuid4().hex[:8]}",
        name="Other Procurement Branch",
        address="Other",
        phone="0800000066",
        is_active=True,
    )
    db.session.add(branch)
    db.session.flush()
    supplier = Supplier(
        branch_id=branch.id,
        supplier_code=f"T-PORTAL-OTHER-SUP-{uuid4().hex[:8]}",
        supplier_name="ZZZ Other Portal Supplier",
        supplier_type="GENERAL",
        is_active=True,
    )
    item = Item(
        item_code=f"T-PORTAL-OTHER-PROC-ITEM-{uuid4().hex[:8]}",
        item_name="ZZZ Other Portal Procurement Item",
        category="RAW_MATERIAL",
        unit="KG",
        minimum_stock=0,
        selling_price=0,
        is_stock_tracked=True,
        is_active=True,
    )
    db.session.add(supplier)
    db.session.add(item)
    db.session.flush()
    procurement = Procurement(
        procurement_number=f"T-PORTAL-OTHER-PROC-{uuid4().hex[:8]}",
        branch_id=branch.id,
        supplier_id=supplier.id,
        procurement_date=date.today(),
        purchase_type="CREDIT",
        supplier_name=supplier.supplier_name,
        total_amount=99000,
        created_by=user.id,
    )
    db.session.add(procurement)
    db.session.flush()
    db.session.add(
        ProcurementItem(
            procurement_id=procurement.id,
            item_id=item.id,
            qty=9,
            unit_price=11000,
            subtotal=99000,
        )
    )
    db.session.flush()
    bill = SupplierBill(
        branch_id=branch.id,
        bill_number=f"T-PORTAL-OTHER-BILL-{uuid4().hex[:8]}",
        supplier_id=supplier.id,
        procurement_id=procurement.id,
        bill_date=date.today(),
        due_date=date.today() + timedelta(days=7),
        supplier_name=supplier.supplier_name,
        total_amount=99000,
        paid_amount=0,
        remaining_amount=99000,
        status="OPEN",
        created_by=user.id,
    )
    db.session.add(bill)
    db.session.flush()
    return procurement, bill, supplier


def test_portal_feature_flag_off_returns_404_for_authenticated_owner(app):
    app.config["PORTAL_ENABLED"] = False

    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_test_user("OWNER")
            with app.test_client() as client:
                _login(client, user)
                assert client.get("/portal").status_code == 404
                assert client.get("/portal/dashboard").status_code == 404
        finally:
            transaction.rollback()


def test_portal_enabled_requires_login(app):
    app.config["PORTAL_ENABLED"] = True

    with app.test_client() as client:
        response = client.get("/portal/dashboard")

    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


def test_portal_enabled_allows_owner_and_admin_preview(app):
    app.config["PORTAL_ENABLED"] = True

    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            users = [_create_test_user("OWNER"), _create_test_user("ADMIN")]
            for user in users:
                with app.test_client() as client:
                    _login(client, user)
                    response = client.get("/portal/dashboard")
                    html = response.get_data(as_text=True)

                assert response.status_code == 200
                assert "Portal Pelanggan" in html
                assert "Preview internal" in html
                assert "Scope read-only dari master client" in html
                assert "Role eksternal dan mapping portal masih ditunda sampai approval owner." in html
        finally:
            transaction.rollback()


def test_portal_navigation_is_hidden_when_feature_flag_off(app):
    app.config["PORTAL_ENABLED"] = False

    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_test_user("OWNER")
            with app.test_client() as client:
                _login(client, user)
                response = client.get("/settings/change-password")

            html = response.get_data(as_text=True)
            assert response.status_code == 200
            assert 'href="/portal' not in html
            assert "Portal Pelanggan" not in html
        finally:
            transaction.rollback()


def test_portal_navigation_is_visible_when_feature_flag_on_for_owner(app):
    app.config["PORTAL_ENABLED"] = True

    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_test_user("OWNER")
            with app.test_client() as client:
                _login(client, user)
                response = client.get("/settings/change-password")

            html = response.get_data(as_text=True)
            assert response.status_code == 200
            assert 'href="/portal/dashboard"' in html
            assert 'href="/portal/customers"' in html
            assert 'href="/portal/mandors"' in html
            assert 'href="/portal/status"' in html
            assert 'href="/portal/ownership"' in html
            assert 'href="/portal/financial"' in html
            assert 'href="/portal/orders"' in html
            assert 'href="/portal/deliveries"' in html
            assert 'href="/portal/productions"' in html
            assert 'href="/portal/inventory"' in html
            assert 'href="/portal/procurement"' in html
        finally:
            transaction.rollback()


def test_portal_navigation_is_hidden_for_non_preview_role_even_when_enabled(app):
    app.config["PORTAL_ENABLED"] = True

    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_test_user("FINANCE")
            with app.test_client() as client:
                _login(client, user)
                response = client.get("/settings/change-password")

            html = response.get_data(as_text=True)
            assert response.status_code == 200
            assert 'href="/portal' not in html
            assert "Portal Pelanggan" not in html
        finally:
            transaction.rollback()


def test_portal_enabled_rejects_unauthorized_internal_role(app):
    app.config["PORTAL_ENABLED"] = True

    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_test_user("FINANCE")
            with app.test_client() as client:
                _login(client, user)
                response = client.get("/portal/dashboard")

            assert response.status_code == 302
            assert response.headers["Location"].endswith("/")
        finally:
            transaction.rollback()


def test_portal_route_has_no_session_commit_or_rollback():
    source = open("app/routes/portal_routes.py", encoding="utf-8").read()

    assert "db.session.commit(" not in source
    assert "db.session.rollback(" not in source


def test_portal_access_scope_is_branch_scoped_for_admin(app):
    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_test_user("ADMIN")
            _create_scope_master_data(user)

            scope = build_portal_access_scope(user)

            assert scope["allowed"] is True
            assert scope["scope_mode"] == "ADMIN_BRANCH_PREVIEW"
            assert scope["counts"]["clients"] == 1
            assert scope["counts"]["client_pics"] == 1
            assert scope["counts"]["mandors"] == 1
            assert scope["counts"]["locations"] == 1
            assert scope["active_counts"]["clients"] == 1
            assert scope["active_counts"]["mandors"] == 1
            assert scope["active_counts"]["locations"] == 1
            assert scope["client_preview"][0]["name"] == "AAA Test Portal Client"
            assert scope["mandor_preview"][0]["name"] == "AAA Test Portal Mandor"
            assert scope["location_preview"][0]["name"] == "AAA Test Portal Location"
        finally:
            transaction.rollback()


def test_portal_readonly_directories_are_branch_scoped_for_admin(app):
    app.config["PORTAL_ENABLED"] = True

    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_test_user("ADMIN")
            _create_scope_master_data(user)
            _create_other_branch_scope_data()

            with app.test_client() as client:
                _login(client, user)
                customers_response = client.get("/portal/customers")
                mandors_response = client.get("/portal/mandors")

            customers_html = customers_response.get_data(as_text=True)
            mandors_html = mandors_response.get_data(as_text=True)

            assert customers_response.status_code == 200
            assert mandors_response.status_code == 200
            assert "Client/PT Read-only" in customers_html
            assert "Mandor Read-only" in mandors_html
            assert "AAA Test Portal Client" in customers_html
            assert "AAA Test Portal Mandor" in mandors_html
            assert "ZZZ Other Branch Client" not in customers_html
            assert "ZZZ Other Branch Mandor" not in mandors_html
            assert 'action="/portal' not in customers_html.lower()
            assert 'action="/portal' not in mandors_html.lower()
        finally:
            transaction.rollback()


def test_portal_status_shell_is_read_only_and_shows_approval_gates(app):
    app.config["PORTAL_ENABLED"] = True

    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_test_user("OWNER")
            status = build_portal_status_shell(user)

            with app.test_client() as client:
                _login(client, user)
                response = client.get("/portal/status")

            html = response.get_data(as_text=True)
            assert status["ready_count"] >= 1
            assert status["approval_required_count"] >= 1
            assert response.status_code == 200
            assert "Status Portal Read-only" in html
            assert "Akun eksternal Client/PT/Mandor" in html
            assert "Draft order portal" in html
            assert "Invoice/payment portal" in html
            assert 'action="/portal' not in html.lower()
        finally:
            transaction.rollback()


def test_portal_ownership_analysis_is_read_only_and_branch_scoped(app):
    app.config["PORTAL_ENABLED"] = True

    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_test_user("ADMIN")
            _create_scope_master_data(user)
            _create_other_branch_scope_data()
            analysis = build_portal_ownership_analysis(user)

            with app.test_client() as client:
                _login(client, user)
                response = client.get("/portal/ownership")

            html = response.get_data(as_text=True)
            assert analysis["summary"]["scope_mode"] == "ADMIN_BRANCH_PREVIEW"
            assert analysis["summary"]["clients"] == 1
            assert analysis["summary"]["mandors"] == 1
            assert analysis["summary"]["locations"] == 1
            assert response.status_code == 200
            assert "Ownership Portal" in html
            assert "User.branch_id, User.role" in html
            assert "APPROVAL_REQUIRED" in html
            assert 'action="/portal' not in html.lower()
        finally:
            transaction.rollback()


def test_portal_financial_visibility_is_read_only_and_branch_scoped(app):
    app.config["PORTAL_ENABLED"] = True

    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_test_user("ADMIN")
            _create_financial_visibility_data(user)
            _create_other_branch_financial_data(user)
            financial = build_portal_financial_visibility(user)

            with app.test_client() as client:
                _login(client, user)
                response = client.get("/portal/financial")

            html = response.get_data(as_text=True)
            assert financial["scope_mode"] == "ADMIN_BRANCH_FINANCIAL_PREVIEW"
            assert financial["summary"]["invoice_count"] == 1
            assert int(financial["summary"]["invoice_total"]) == 150000
            assert int(financial["summary"]["invoice_paid"]) == 50000
            assert int(financial["summary"]["invoice_remaining"]) == 100000
            assert financial["summary"]["payment_count"] == 1
            assert response.status_code == 200
            assert "Financial Visibility" in html
            assert "AAA Test Portal Client" in html
            assert "ZZZ Other Branch Client" not in html
            assert 'action="/portal' not in html.lower()
        finally:
            transaction.rollback()


def test_portal_order_status_visibility_is_read_only_and_branch_scoped(app):
    app.config["PORTAL_ENABLED"] = True

    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_test_user("ADMIN")
            order, _, _ = _create_order_status_data(user)
            other_order = _create_other_branch_order_status_data(user)
            orders = build_portal_order_status_visibility(user)

            with app.test_client() as client:
                _login(client, user)
                response = client.get("/portal/orders")

            html = response.get_data(as_text=True)
            assert orders["scope_mode"] == "ADMIN_BRANCH_ORDER_PREVIEW"
            assert orders["summary"]["order_count"] == 1
            assert orders["summary"]["locked_order_count"] == 1
            assert int(orders["summary"]["total_portion"]) == 10
            assert orders["summary"]["production_count"] == 1
            assert response.status_code == 200
            assert "Order Status Visibility" in html
            assert order.order_number in html
            assert other_order.order_number not in html
            assert 'action="/portal' not in html.lower()
        finally:
            transaction.rollback()


def test_portal_delivery_visibility_is_read_only_and_branch_scoped(app):
    app.config["PORTAL_ENABLED"] = True

    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_test_user("ADMIN")
            delivery = _create_delivery_visibility_data(user)
            other_delivery = _create_other_branch_delivery_visibility_data(user)
            deliveries = build_portal_delivery_visibility(user)

            with app.test_client() as client:
                _login(client, user)
                response = client.get("/portal/deliveries")

            html = response.get_data(as_text=True)
            assert deliveries["scope_mode"] == "ADMIN_BRANCH_DELIVERY_PREVIEW"
            assert deliveries["summary"]["delivery_count"] == 1
            assert deliveries["summary"]["delivered_count"] == 1
            assert int(deliveries["summary"]["planned_qty"]) == 10
            assert int(deliveries["summary"]["delivered_qty"]) == 8
            assert int(deliveries["summary"]["shortage_qty"]) == 2
            assert response.status_code == 200
            assert "Delivery Visibility" in html
            assert delivery.delivery_number in html
            assert "AAA Test Portal Driver" in html
            assert other_delivery.delivery_number not in html
            assert "ZZZ Other Portal Driver" not in html
            assert 'action="/portal' not in html.lower()
        finally:
            transaction.rollback()


def test_portal_production_visibility_is_read_only_and_branch_scoped(app):
    app.config["PORTAL_ENABLED"] = True

    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_test_user("ADMIN")
            production, item = _create_production_visibility_data(user)
            other_production, other_item = _create_other_branch_production_visibility_data(user)
            productions = build_portal_production_visibility(user)

            with app.test_client() as client:
                _login(client, user)
                response = client.get("/portal/productions")

            html = response.get_data(as_text=True)
            assert productions["scope_mode"] == "ADMIN_BRANCH_PRODUCTION_PREVIEW"
            assert productions["summary"]["production_count"] == 1
            assert productions["summary"]["completed_count"] == 1
            assert int(productions["summary"]["planned_qty"]) == 12
            assert int(productions["summary"]["actual_qty"]) == 10
            assert int(productions["summary"]["variance_qty"]) == -2
            assert response.status_code == 200
            assert "Production Visibility" in html
            assert production.production_type in html
            assert item.item_name in html
            assert other_production.production_type not in html
            assert other_item.item_name not in html
            assert 'action="/portal' not in html.lower()
        finally:
            transaction.rollback()


def test_portal_inventory_visibility_is_read_only_and_branch_scoped(app):
    app.config["PORTAL_ENABLED"] = True

    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_test_user("ADMIN")
            item = _create_inventory_visibility_data(user)
            other_item = _create_other_branch_inventory_visibility_data(user)
            inventory = build_portal_inventory_visibility(user)

            with app.test_client() as client:
                _login(client, user)
                response = client.get("/portal/inventory")

            html = response.get_data(as_text=True)
            assert inventory["scope_mode"] == "ADMIN_BRANCH_INVENTORY_PREVIEW"
            assert inventory["summary"]["item_count"] == 1
            assert inventory["summary"]["safe_count"] == 1
            assert inventory["summary"]["low_count"] == 0
            assert inventory["summary"]["out_count"] == 0
            assert inventory["summary"]["movement_count"] == 2
            assert int(inventory["stock_rows"][0]["stock_qty"]) == 12
            assert response.status_code == 200
            assert "Inventory Visibility" in html
            assert item.item_name in html
            assert "PORTAL_TEST #2" in html
            assert other_item.item_name not in html
            assert "PORTAL_TEST_OTHER" not in html
            assert 'action="/portal' not in html.lower()
        finally:
            transaction.rollback()


def test_portal_procurement_visibility_is_read_only_and_branch_scoped(app):
    app.config["PORTAL_ENABLED"] = True

    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_test_user("ADMIN")
            procurement, bill, supplier = _create_procurement_visibility_data(user)
            other_procurement, other_bill, other_supplier = _create_other_branch_procurement_visibility_data(user)
            procurement_visibility = build_portal_procurement_visibility(user)

            with app.test_client() as client:
                _login(client, user)
                response = client.get("/portal/procurement")

            html = response.get_data(as_text=True)
            assert procurement_visibility["scope_mode"] == "ADMIN_BRANCH_PROCUREMENT_PREVIEW"
            assert procurement_visibility["summary"]["procurement_count"] == 1
            assert int(procurement_visibility["summary"]["procurement_total"]) == 75000
            assert procurement_visibility["summary"]["procurement_item_count"] == 1
            assert int(procurement_visibility["summary"]["procurement_qty"]) == 5
            assert procurement_visibility["summary"]["supplier_bill_count"] == 1
            assert procurement_visibility["summary"]["open_supplier_bill_count"] == 1
            assert int(procurement_visibility["summary"]["open_supplier_bill_remaining"]) == 50000
            assert response.status_code == 200
            assert "Procurement Visibility" in html
            assert procurement.procurement_number in html
            assert bill.bill_number in html
            assert supplier.supplier_name in html
            assert other_procurement.procurement_number not in html
            assert other_bill.bill_number not in html
            assert other_supplier.supplier_name not in html
            assert 'action="/portal' not in html.lower()
        finally:
            transaction.rollback()


def test_portal_access_service_has_no_session_commit_or_rollback():
    source = open("app/services/portal_access_service.py", encoding="utf-8").read()

    assert "db.session.commit(" not in source
    assert "db.session.rollback(" not in source
