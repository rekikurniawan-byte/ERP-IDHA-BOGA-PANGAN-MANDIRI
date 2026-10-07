"""Tests for Jadwal Menu Harian dan Foto (Bagian 2).

Memastikan:
1. CRUD jadwal menu + unique constraint per sesi (branch_id + menu_date + meal_type).
2. "Salin minggu lalu" (copy_previous_week_schedule) menyalin jadwal antar minggu.
3. Halaman pesan portal menampilkan menu terjadwal / teks "Menu akan diinformasikan".
4. Landing page publik hanya menampilkan menu aktif yang dijadwalkan.
5. Total harga draft pesanan TIDAK BERUBAH dengan ada / tidaknya jadwal menu.
6. Role portal (CUSTOMER, SUBCLIENT, CLIENT) tidak bisa mengubah menu atau jadwal.
"""
from datetime import date, timedelta
from decimal import Decimal
import io
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from werkzeug.datastructures import FileStorage
from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models.master import Branch, Client, DeliveryLocation, Mandor, Menu, MenuSchedule, User
from app.models.system import DigitalAttachment, PortalUserMapping
from app.services.menu_schedule_service import (
    MenuScheduleError,
    add_menu_photos,
    build_menu_schedule_json_for_order,
    copy_previous_week_schedule,
    get_customer_today_tomorrow_menu,
    get_menu_photos,
    get_monday_of_week,
    get_public_weekly_menu,
    get_scheduled_menu,
    save_menu_schedule,
)
from app.services.portal_mapping_service import ACCESS_DRAFT_ORDER, PRINCIPAL_DELEGATE
from app.services.portal_order_draft_service import (
    build_portal_draft_order_context,
    create_portal_order_draft,
)


def _fake_image_file(filename="menu.jpg"):
    content = (
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05"
        b"\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c"
        b" $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4"
        b"\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05"
        b"\x06\x07\x08\t\n\x0b\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xbf\x00\xff\xd9"
    )
    return FileStorage(stream=io.BytesIO(content), filename=filename, content_type="image/jpeg")


def _setup_test_environment():
    uid = uuid4().hex[:6]
    branch = Branch(
        code=f"BR_{uid}",
        name=f"Cabang {uid}",
        address="Jl. Uji No. 1",
        phone="0812345678",
        is_active=True,
    )
    db.session.add(branch)
    db.session.flush()

    admin_user = User(
        branch_id=branch.id,
        full_name=f"Admin {uid}",
        username=f"admin_{uid}",
        password_hash=generate_password_hash("Password123!"),
        role="ADMIN",
        is_active=True,
    )
    dapur_user = User(
        branch_id=branch.id,
        full_name=f"Dapur {uid}",
        username=f"dapur_{uid}",
        password_hash=generate_password_hash("Password123!"),
        role="DAPUR",
        is_active=True,
    )
    customer_user = User(
        branch_id=branch.id,
        full_name=f"Customer {uid}",
        username=f"cust_{uid}",
        email=f"cust_{uid}@test.id",
        password_hash=generate_password_hash("Password123!"),
        role="PORTAL_CUSTOMER",
        is_active=True,
    )
    db.session.add_all([admin_user, dapur_user, customer_user])
    db.session.flush()

    menu1 = Menu(
        branch_id=branch.id,
        menu_code=f"MN1_{uid}",
        menu_name=f"Nasi Ayam Goreng {uid}",
        menu_type="LUNCH",
        default_selling_price=Decimal("20000.00"),
        description="Ayam goreng rempah lezat dengan lalap segar.",
        is_active=True,
    )
    menu2 = Menu(
        branch_id=branch.id,
        menu_code=f"MN2_{uid}",
        menu_name=f"Nasi Telur Balado {uid}",
        menu_type="DINNER",
        default_selling_price=Decimal("18000.00"),
        description="Telur balado bumbu cabai segar pedas manis.",
        is_active=True,
    )
    menu_inactive = Menu(
        branch_id=branch.id,
        menu_code=f"MN3_{uid}",
        menu_name=f"Nasi Ikan Nonaktif {uid}",
        menu_type="LUNCH",
        default_selling_price=Decimal("22000.00"),
        description="Menu nonaktif untuk pengujian filter publik.",
        is_active=False,
    )
    db.session.add_all([menu1, menu2, menu_inactive])
    db.session.commit()

    return {
        "branch": branch,
        "admin": admin_user,
        "dapur": dapur_user,
        "customer": customer_user,
        "menu1": menu1,
        "menu2": menu2,
        "menu_inactive": menu_inactive,
    }


def test_menu_schedule_crud_and_unique_constraint(client, app):
    """Test CRUD jadwal menu dan penegakan unique constraint per sesi."""
    with app.app_context():
        env = _setup_test_environment()
        branch = env["branch"]
        menu1 = env["menu1"]
        menu2 = env["menu2"]
        target_date = date(2026, 10, 12)

        # 1. CREATE schedule
        sched = save_menu_schedule(
            branch_id=branch.id,
            menu_date=target_date,
            meal_type="LUNCH",
            menu_id=menu1.id,
            notes="Catatan porsi pedas",
            acted_by=env["admin"].id,
            commit=True,
        )
        assert sched is not None
        assert sched.menu_id == menu1.id
        assert sched.notes == "Catatan porsi pedas"

        # 2. READ schedule
        loaded = get_scheduled_menu(branch.id, target_date, "LUNCH")
        assert loaded is not None
        assert loaded.menu.menu_name == menu1.menu_name

        # 3. UPDATE schedule (same branch + date + session)
        updated = save_menu_schedule(
            branch_id=branch.id,
            menu_date=target_date,
            meal_type="LUNCH",
            menu_id=menu2.id,
            notes="Diubah ke telur balado",
            acted_by=env["admin"].id,
            commit=True,
        )
        assert updated.id == sched.id
        assert updated.menu_id == menu2.id
        assert updated.notes == "Diubah ke telur balado"

        # Verify only 1 row exists
        count = MenuSchedule.query.filter_by(
            branch_id=branch.id, menu_date=target_date, meal_type="LUNCH"
        ).count()
        assert count == 1

        # 4. Enforce unique constraint at database level
        duplicate = MenuSchedule(
            branch_id=branch.id,
            menu_date=target_date,
            meal_type="LUNCH",
            menu_id=menu1.id,
        )
        db.session.add(duplicate)
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()

        # 5. DELETE schedule (menu_id=None)
        cleared = save_menu_schedule(
            branch_id=branch.id,
            menu_date=target_date,
            meal_type="LUNCH",
            menu_id=None,
            commit=True,
        )
        assert cleared is None
        assert get_scheduled_menu(branch.id, target_date, "LUNCH") is None


def test_menu_schedule_copy_previous_week(client, app):
    """Test salin jadwal menu dari minggu sebelumnya."""
    with app.app_context():
        env = _setup_test_environment()
        branch = env["branch"]
        menu1 = env["menu1"]
        menu2 = env["menu2"]

        # Week 1: Senin 2026-10-12 s/d Minggu 2026-10-18
        mon_w1 = date(2026, 10, 12)
        wed_w1 = date(2026, 10, 14)
        fri_w1 = date(2026, 10, 16)

        save_menu_schedule(branch.id, mon_w1, "LUNCH", menu1.id, notes="W1 Mon Lunch", commit=True)
        save_menu_schedule(branch.id, wed_w1, "DINNER", menu2.id, notes="W1 Wed Dinner", commit=True)
        save_menu_schedule(branch.id, fri_w1, "LUNCH", menu1.id, notes="W1 Fri Lunch", commit=True)

        # Target Week 2: Senin 2026-10-19
        mon_w2 = date(2026, 10, 19)
        wed_w2 = date(2026, 10, 21)
        fri_w2 = date(2026, 10, 23)

        # Copy without overwrite
        copied = copy_previous_week_schedule(
            branch_id=branch.id,
            target_monday=mon_w2,
            acted_by=env["admin"].id,
            commit=True,
        )
        assert copied == 3

        s_mon2 = get_scheduled_menu(branch.id, mon_w2, "LUNCH")
        s_wed2 = get_scheduled_menu(branch.id, wed_w2, "DINNER")
        s_fri2 = get_scheduled_menu(branch.id, fri_w2, "LUNCH")

        assert s_mon2 is not None and s_mon2.menu_id == menu1.id
        assert s_wed2 is not None and s_wed2.menu_id == menu2.id
        assert s_fri2 is not None and s_fri2.menu_id == menu1.id


def test_order_draft_shows_scheduled_menu_and_unscheduled_text(client, app):
    """Test halaman draft pesan menampilkan menu terjadwal dan teks 'akan diinformasikan'."""
    with app.app_context():
        env = _setup_test_environment()
        branch = env["branch"]
        menu1 = env["menu1"]
        customer = env["customer"]

        # Upload photo to menu1
        photo_file = _fake_image_file("ayam.jpg")
        add_menu_photos(menu1, [photo_file], acted_by=env["admin"].id, commit=True)

        target_date = date.today() + timedelta(days=2)
        # Schedule LUNCH, leave DINNER unscheduled
        save_menu_schedule(branch.id, target_date, "LUNCH", menu1.id, commit=True)

        # Test context helper
        schedule_json = build_menu_schedule_json_for_order(branch.id)
        lunch_key = f"{target_date.strftime('%Y-%m-%d')}_LUNCH"
        dinner_key = f"{target_date.strftime('%Y-%m-%d')}_DINNER"

        assert lunch_key in schedule_json
        assert schedule_json[lunch_key]["menu_name"] == menu1.menu_name
        assert schedule_json[lunch_key]["description"] == menu1.description
        assert schedule_json[lunch_key]["photo_id"] is not None

        assert dinner_key not in schedule_json

        # Test draft order context
        ctx = build_portal_draft_order_context(customer)
        assert "menu_schedules" in ctx
        assert lunch_key in ctx["menu_schedules"]


def test_landing_page_only_shows_active_menus(client, app):
    """Test landing page publik hanya menampilkan menu aktif yang dijadwalkan."""
    with app.app_context():
        env = _setup_test_environment()
        branch = env["branch"]
        from app.services.public_site_service import _main_branch
        target_branch = _main_branch() or branch
        ref_date = date.today()
        monday = get_monday_of_week(ref_date)

        menu_active = Menu(
            branch_id=target_branch.id,
            menu_code=f"ACT_{uuid4().hex[:6]}",
            menu_name=f"Menu Aktif Publik {uuid4().hex[:6]}",
            menu_type="LUNCH",
            is_active=True,
        )
        menu_inactive = Menu(
            branch_id=target_branch.id,
            menu_code=f"INACT_{uuid4().hex[:6]}",
            menu_name=f"Menu Nonaktif {uuid4().hex[:6]}",
            menu_type="DINNER",
            is_active=False,
        )
        db.session.add_all([menu_active, menu_inactive])
        db.session.flush()

        # Schedule active menu and inactive menu
        save_menu_schedule(target_branch.id, monday, "LUNCH", menu_active.id, commit=True)
        save_menu_schedule(target_branch.id, monday, "DINNER", menu_inactive.id, commit=True)

        weekly_menus = get_public_weekly_menu(target_branch.id, ref_date)
        names = [m["menu_name"] for m in weekly_menus]
        assert menu_active.menu_name in names
        assert menu_inactive.menu_name not in names

    # Public landing page response
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert menu_active.menu_name in html
    assert menu_inactive.menu_name not in html


def test_draft_total_price_unaffected_by_menu(client, app):
    """Test harga draft pesanan per porsi murni mengikuti lokasi dan tidak terpengaruh jadwal menu."""
    with app.app_context():
        env = _setup_test_environment()
        branch = env["branch"]
        customer = env["customer"]
        menu1 = env["menu1"]

        # Create Client, Mandor, and Location
        cl = Client(
            name="Client Testing Draft",
            customer_path="KONTRAK",
            is_active=True,
        )
        db.session.add(cl)
        db.session.flush()

        mandor = Mandor(
            branch_id=branch.id,
            client_id=cl.id,
            name="Mandor Testing Draft",
            is_active=True,
        )
        db.session.add(mandor)
        db.session.flush()

        loc = DeliveryLocation(
            mandor_id=mandor.id,
            location_name="Lokasi Uji Pesan",
            is_active=True,
        )
        db.session.add(loc)
        db.session.flush()

        # Add PortionPrice for branch
        from app.models.pricing import PortionPrice
        pp = PortionPrice(
            branch_id=branch.id,
            client_id=cl.id,
            price_per_portion=Decimal("25000.00"),
            effective_from=date(2026, 1, 1),
            created_by=customer.id,
        )
        db.session.add(pp)

        mapping = PortalUserMapping(
            user_id=customer.id,
            principal_type=PRINCIPAL_DELEGATE,
            client_id=cl.id,
            mandor_id=mandor.id,
            delivery_location_id=loc.id,
            access_level=ACCESS_DRAFT_ORDER,
            is_active=True,
        )
        db.session.add(mapping)
        db.session.commit()

        date_with_menu = date.today() + timedelta(days=2)
        date_without_menu = date.today() + timedelta(days=3)

        # Schedule menu only on date_with_menu LUNCH
        save_menu_schedule(branch.id, date_with_menu, "LUNCH", menu1.id, commit=True)

        # Draft 1: dengan menu
        form_with = {
            "order_date": date_with_menu.strftime("%Y-%m-%d"),
            "meal_type": "LUNCH",
            "delivery_location_id": str(loc.id),
            "portion_qty": "10",
            "idempotency_key": uuid4().hex,
        }
        draft_with, created_with, err_with = create_portal_order_draft(customer, form_with)
        assert err_with is None
        assert draft_with is not None

        # Draft 2: tanpa menu
        form_without = {
            "order_date": date_without_menu.strftime("%Y-%m-%d"),
            "meal_type": "LUNCH",
            "delivery_location_id": str(loc.id),
            "portion_qty": "10",
            "idempotency_key": uuid4().hex,
        }
        draft_without, created_without, err_without = create_portal_order_draft(customer, form_without)
        assert err_without is None
        assert draft_without is not None

        # Verify price per portion and total amount are identical!
        total_with = draft_with.price_per_portion * draft_with.portion_qty + (draft_with.delivery_fee or Decimal("0.00"))
        total_without = draft_without.price_per_portion * draft_without.portion_qty + (draft_without.delivery_fee or Decimal("0.00"))
        assert draft_with.price_per_portion == draft_without.price_per_portion
        assert total_with == total_without
        assert draft_with.price_per_portion == Decimal("25000.00")
        assert total_with == Decimal("250000.00")


def test_portal_roles_cannot_modify_menu_or_schedule(app):
    """Test role portal (CUSTOMER, SUBCLIENT, CLIENT) tidak diizinkan mengubah menu atau jadwal."""
    with app.app_context():
        env = _setup_test_environment()
        customer = env["customer"]

        uid = uuid4().hex[:6]
        mandor_user = User(
            branch_id=env["branch"].id,
            full_name=f"Mandor Test {uid}",
            username=f"mandor_{uid}",
            password_hash=generate_password_hash("Password123!"),
            role="PORTAL_SUBCLIENT",
            is_active=True,
        )
        client_user = User(
            branch_id=env["branch"].id,
            full_name=f"Client Test {uid}",
            username=f"client_{uid}",
            password_hash=generate_password_hash("Password123!"),
            role="PORTAL_CLIENT",
            is_active=True,
        )
        db.session.add_all([mandor_user, client_user])
        db.session.commit()

        portal_user_ids = [customer.id, mandor_user.id, client_user.id]

    for uid in portal_user_ids:
        test_client = app.test_client()
        with test_client.session_transaction() as sess:
            sess["_user_id"] = str(uid)
            sess["_fresh"] = True

        # 1. Operational menu schedule GET
        r1 = test_client.get("/operational/menu-schedule")
        assert r1.status_code in (302, 400, 403)

        # 2. Operational menu schedule POST save
        r2 = test_client.post("/operational/menu-schedule/save", data={
            "menu_date": "2026-10-25",
            "meal_type": "LUNCH",
            "menu_id": "1",
        })
        assert r2.status_code in (302, 400, 403)

        # 3. Operational menu schedule POST copy
        r3 = test_client.post("/operational/menu-schedule/copy-last-week", data={
            "target_week": "2026-10-26",
        })
        assert r3.status_code in (302, 400, 403)

        # 4. Costing menu create GET
        r4 = test_client.get("/costing/menus/create")
        assert r4.status_code in (302, 400, 403)

        # 5. Costing menu create POST
        r5 = test_client.post("/costing/menus/create", data={
            "menu_name": "Hack Menu",
            "menu_type": "LUNCH",
            "default_selling_price": "20000",
        })
        assert r5.status_code in (302, 400, 403)


def test_staff_roles_can_access_menu_schedule_and_costing(app):
    """Test role staf (ADMIN, DAPUR, OWNER) dapat mengakses menu dan jadwal."""
    with app.app_context():
        env = _setup_test_environment()
        staff_user_ids = [env["admin"].id, env["dapur"].id]

    for uid in staff_user_ids:
        test_client = app.test_client()
        with test_client.session_transaction() as sess:
            sess["_user_id"] = str(uid)
            sess["_fresh"] = True

        # Menu schedule page
        resp = test_client.get("/operational/menu-schedule")
        assert resp.status_code == 200
        assert "Jadwal Menu" in resp.get_data(as_text=True)

        # Costing menus page
        resp_cost = test_client.get("/costing/menus")
        assert resp_cost.status_code == 200
