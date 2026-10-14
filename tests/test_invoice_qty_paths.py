"""Uji jalur perubahan porsi terhadap perhitungan invoice (Task A).

Menguji dua jalur ubah porsi:
1. Jalur lama: revise_order_detail (menghasilkan OrderRevision)
2. Jalur baru: update_order_qty_from_admin (menghasilkan OrderQtyChange)
dan kombinasinya pada order TERKUNCI, lalu menghitung total porsi yang ditagih oleh plan_invoices.
"""
from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.accounting import Account
from app.models.delivery import Delivery, DeliveryDetail, DeliveryReceipt
from app.models.master import Branch, Client, DeliveryLocation, Driver, Mandor, User
from app.models.operational import DailyOrder, DailyOrderDetail
from app.models.pricing import PortionPrice
from app.services.auto_invoice_service import plan_invoices
from app.services.auto_order_service import update_order_qty_from_admin
from app.services.customer_contract_service import CONTRACT_STATUS_ACTIVE, create_customer_contract
from app.services.operational_service import revise_order_detail

ANCHOR = date(2026, 10, 1)
CUTOFF = date(2026, 10, 15)
ORDER_DATE = date(2026, 10, 5)


@pytest.fixture
def ctx(app, monkeypatch):
    """Tanpa commit ke db: semua di-flush lalu di-rollback."""
    app.config["WTF_CSRF_ENABLED"] = False
    with app.app_context():
        monkeypatch.setattr(db.session, "commit", db.session.flush)
        try:
            yield db
        finally:
            db.session.rollback()


def _ensure_accounts():
    for code, name, kind in (
        ("1004", "Piutang Usaha", "ASSET"),
        ("1005", "Piutang Karyawan", "ASSET"),
        ("4001", "Pendapatan Catering Proyek", "REVENUE"),
        ("4002", "Pendapatan Catering Harian", "REVENUE"),
        ("4003", "Pendapatan Warung", "REVENUE"),
        ("4004", "Pendapatan Lain-Lain", "REVENUE"),
        ("4005", "Pendapatan Ongkos Kirim", "REVENUE"),
    ):
        if not Account.query.filter_by(account_code=code).first():
            db.session.add(Account(account_code=code, account_name=name, account_type=kind, is_active=True))
    db.session.flush()


def _setup(db):
    _ensure_accounts()
    suffix = uuid4().hex[:6]
    branch = Branch(code=f"TQ-{suffix}", name=f"Cabang Uji Qty {suffix}", is_active=True)
    client = Client(name=f"PT Klien Uji {suffix}", is_active=True)
    db.session.add_all([branch, client])
    db.session.flush()

    owner = User(
        branch_id=branch.id,
        full_name="Owner Uji",
        username=f"owner_{suffix}",
        password_hash="x",
        role="OWNER",
        is_active=True,
    )
    admin = User(
        branch_id=branch.id,
        full_name="Admin Uji",
        username=f"admin_{suffix}",
        password_hash="x",
        role="ADMIN",
        is_active=True,
    )
    mandor = Mandor(branch_id=branch.id, client_id=client.id, name=f"Mandor {suffix}", is_active=True)
    db.session.add_all([owner, admin, mandor])
    db.session.flush()

    location = DeliveryLocation(mandor_id=mandor.id, location_name=f"Lokasi {suffix}", is_active=True)
    driver = Driver(branch_id=branch.id, name=f"Driver {suffix}", is_active=True)
    price = PortionPrice(
        branch_id=branch.id,
        price_per_portion=Decimal("25000"),
        effective_from=date(2026, 1, 1),
        created_by=owner.id,
    )
    db.session.add_all([location, driver, price])
    db.session.flush()

    contract = create_customer_contract(
        branch_id=branch.id,
        client_id=client.id,
        title="Kontrak Biweekly Uji",
        start_date=ANCHOR,
        end_date=date(2026, 12, 31),
        payment_terms="Net 7",
        status=CONTRACT_STATUS_ACTIVE,
        created_by=owner.id,
        billing_cycle="BIWEEKLY",
        billing_anchor_date=ANCHOR,
        due_days=7,
    )

    # Order awal 10 porsi siang, terkunci
    order = DailyOrder(
        order_number=f"DO-{suffix}",
        branch_id=branch.id,
        order_date=ORDER_DATE,
        status="LOCKED",
        is_locked=True,
        created_by=owner.id,
    )
    db.session.add(order)
    db.session.flush()

    detail = DailyOrderDetail(
        daily_order_id=order.id,
        mandor_id=mandor.id,
        delivery_location_id=location.id,
        price_per_portion=Decimal("25000"),
        price_source="CONTRACT",
        lunch_qty=10,
        dinner_qty=0,
        total_qty=10,
        lunch_delivery_fee=Decimal("0"),
        dinner_delivery_fee=Decimal("0"),
    )
    db.session.add(detail)
    db.session.flush()

    return {
        "branch": branch,
        "client": client,
        "owner": owner,
        "admin": admin,
        "mandor": mandor,
        "contract": contract,
        "order": order,
        "detail": detail,
        "driver": driver,
        "location": location,
        "suffix": suffix,
    }


def _deliver(db, env):
    """Kirim & terima SETELAH porsi diubah (urutan nyata: porsi tidak bisa diubah setelah makanan berangkat)."""
    detail, branch, owner = env["detail"], env["branch"], env["owner"]
    driver, mandor, location, suffix = env["driver"], env["mandor"], env["location"], env["suffix"]
    delivery = Delivery(
        delivery_number=f"DEL-{suffix}",
        branch_id=branch.id,
        delivery_date=ORDER_DATE,
        driver_id=driver.id,
        status="DELIVERED",
        notes="delivery_type=LUNCH",
        created_by=owner.id,
    )
    db.session.add(delivery)
    db.session.flush()

    delivery_detail = DeliveryDetail(
        delivery_id=delivery.id,
        daily_order_detail_id=detail.id,
        mandor_id=mandor.id,
        delivery_location_id=location.id,
        planned_qty=detail.total_qty,
        delivered_qty=detail.total_qty,
    )
    delivery_detail.receipt = DeliveryReceipt(
        receiver_name="Mandor Penerima",
        receive_time=datetime(2026, 10, 5, 12, 0),
    )
    db.session.add(delivery_detail)
    db.session.flush()


def _total_billed_portions(env, cutoff_date: date) -> int:
    """Hitung total porsi catering + revision increase dari rencana invoice."""
    from app.extensions import db

    _deliver(db, env)
    plans = plan_invoices(env["branch"].id, cutoff_date)
    assert len(plans) == 1, f"Harus ada 1 rencana invoice, dapat {len(plans)}"
    lines = plans[0]["lines"]
    total = sum(
        int(line["qty"])
        for line in lines
        if line.get("item_type") in ("CATERING", "REVISION_INCREASE")
    )
    return total


def test_scenario_1_revisi_tambah_only(ctx):
    """Skenario 1: hanya Revisi tambah +5 -> total ditagih = porsi akhir detail (15)."""
    env = _setup(ctx)
    detail = env["detail"]

    ok, msg = revise_order_detail(
        detail=detail,
        revision_type="AFTER_LOCK",
        revision_direction="INCREASE",
        lunch_qty_change=5,
        dinner_qty_change=0,
        reason="Revisi tambah 5 porsi setelah lock",
        created_by=env["admin"].id,
        commit=False,
    )
    assert ok, msg
    assert detail.total_qty == 15

    total_billed = _total_billed_portions(env, CUTOFF)
    assert total_billed == detail.total_qty, f"Harapan: {detail.total_qty}, Aktual: {total_billed}"


def test_scenario_2_ubah_porsi_naik_only(ctx):
    """Skenario 2: hanya Ubah Porsi (naik +5, dengan alasan) -> total = porsi akhir (15)."""
    env = _setup(ctx)
    detail = env["detail"]

    ok, msg, updated = update_order_qty_from_admin(
        user=env["admin"],
        detail_id=detail.id,
        meal_type="LUNCH",
        new_qty=15,
        reason="Ubah porsi dari 10 ke 15 karena ada tambahan tukang",
        commit=False,
    )
    assert ok, msg
    assert detail.total_qty == 15

    total_billed = _total_billed_portions(env, CUTOFF)
    assert total_billed == detail.total_qty, f"Harapan: {detail.total_qty}, Aktual: {total_billed}"


def test_scenario_3_revisi_lalu_ubah_porsi_turun(ctx):
    """Skenario 3: Revisi +5 lalu Ubah Porsi turun -3 -> total = porsi akhir (12)."""
    env = _setup(ctx)
    detail = env["detail"]

    # 1. Revisi tambah +5 (10 -> 15)
    ok, msg = revise_order_detail(
        detail=detail,
        revision_type="AFTER_LOCK",
        revision_direction="INCREASE",
        lunch_qty_change=5,
        dinner_qty_change=0,
        reason="Revisi tambah 5 porsi",
        created_by=env["admin"].id,
        commit=False,
    )
    assert ok, msg
    assert detail.total_qty == 15

    # 2. Ubah Porsi turun -3 (15 -> 12)
    ok, msg, updated = update_order_qty_from_admin(
        user=env["admin"],
        detail_id=detail.id,
        meal_type="LUNCH",
        new_qty=12,
        reason="Koreksi porsi turun dari 15 ke 12",
        commit=False,
    )
    assert ok, msg
    assert detail.total_qty == 12

    total_billed = _total_billed_portions(env, CUTOFF)
    assert total_billed == detail.total_qty, f"Harapan: {detail.total_qty}, Aktual: {total_billed}"


def test_scenario_4_ubah_porsi_lalu_revisi(ctx):
    """Skenario 4: Ubah Porsi +4 lalu Revisi +2 -> total = porsi akhir (16)."""
    env = _setup(ctx)
    detail = env["detail"]

    # 1. Ubah Porsi naik +4 (10 -> 14)
    ok, msg, updated = update_order_qty_from_admin(
        user=env["admin"],
        detail_id=detail.id,
        meal_type="LUNCH",
        new_qty=14,
        reason="Ubah porsi naik dari 10 ke 14",
        commit=False,
    )
    assert ok, msg
    assert detail.total_qty == 14

    # 2. Revisi tambah +2 (14 -> 16)
    ok, msg = revise_order_detail(
        detail=detail,
        revision_type="AFTER_LOCK",
        revision_direction="INCREASE",
        lunch_qty_change=2,
        dinner_qty_change=0,
        reason="Revisi susulan tambah 2 porsi",
        created_by=env["admin"].id,
        commit=False,
    )
    assert ok, msg
    assert detail.total_qty == 16

    total_billed = _total_billed_portions(env, CUTOFF)
    assert total_billed == detail.total_qty, f"Harapan: {detail.total_qty}, Aktual: {total_billed}"
