"""Fase 5: pesanan otomatis client/sub client kontrak dan perubahan porsi.

Semua data dibuat per test dan di-rollback di akhir (commit diganti flush).
Waktu dikunci dengan time_machine: WIB = UTC+7.
"""
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
import time_machine

from app.extensions import db
from app.models.contract import ContractHoliday
from app.models.credit import BILLING_CASH, BILLING_DIRECT, PARTY_MANDOR, STATUS_HOLD, CreditAccount
from app.models.delivery import Delivery, DeliveryDetail
from app.models.master import Branch, Client, DeliveryLocation, Driver, Mandor, User
from app.models.operational import DailyOrder, DailyOrderDetail, OrderQtyChange, StandingOrderState
from app.models.pricing import PortionPrice
from app.models.system import Notification, PortalUserMapping
from app.services.auto_order_service import (
    PORTION_ZERO_REASONS,
    build_portal_today_tomorrow_orders_context,
    get_last_working_day,
    is_delivery_in_transit_or_delivered,
    resolve_auto_order_qty,
    run_auto_daily_orders,
    update_order_qty_from_admin,
    update_order_qty_from_portal,
)
from app.services.customer_contract_service import CONTRACT_STATUS_ACTIVE, create_customer_contract
from app.services.portal_mapping_service import ACCESS_DRAFT_ORDER, PRINCIPAL_MANDOR
from app.services.user_management_service import ROLE_PORTAL_SUBCLIENT


def _wib(year, month, day, hour=0, minute=0):
    """Waktu WIB -> waktu UTC untuk time_machine (now_wib = utcnow + 7 jam)."""
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc) - timedelta(hours=7)


@pytest.fixture
def ctx(app, monkeypatch):
    with app.app_context():
        monkeypatch.setattr(db.session, "commit", db.session.flush)
        try:
            yield db
        finally:
            db.session.rollback()


def _fixtures(prefix="F5", weekly_holidays=None):
    suffix = uuid4().hex[:6]
    branch = Branch(code=f"{prefix}-{suffix}", name=f"Cabang {prefix} {suffix}", is_active=True)
    client = Client(name=f"PT Kontrak {prefix} {suffix}", is_active=True)  # customer_path bawaan KONTRAK
    db.session.add_all([branch, client])
    db.session.flush()

    def user(role, name):
        row = User(
            branch_id=branch.id, full_name=name, username=f"{name.lower()}_{suffix}",
            password_hash="hash", role=role, is_active=True,
        )
        db.session.add(row)
        return row

    owner = user("OWNER", "Owner")
    admin = user("ADMIN", "Admin")
    portal_user = user(ROLE_PORTAL_SUBCLIENT, "Mandorportal")
    mandor = Mandor(branch_id=branch.id, client_id=client.id, name=f"Mandor {suffix}", is_active=True)
    db.session.add(mandor)
    db.session.flush()

    location = DeliveryLocation(mandor_id=mandor.id, location_name=f"Lokasi {suffix}", is_active=True)
    db.session.add(location)
    db.session.flush()

    db.session.add(PortalUserMapping(
        user_id=portal_user.id, principal_type=PRINCIPAL_MANDOR, mandor_id=mandor.id,
        access_level=ACCESS_DRAFT_ORDER, is_active=True,
    ))
    db.session.add(PortionPrice(
        branch_id=branch.id, price_per_portion=Decimal("25000"),
        effective_from=date(2026, 1, 1), created_by=admin.id,
    ))
    db.session.flush()

    contract = create_customer_contract(
        branch_id=branch.id, client_id=client.id, title="Kontrak Uji", start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31), payment_terms="Net 7", status=CONTRACT_STATUS_ACTIVE,
        created_by=owner.id, weekly_holidays=weekly_holidays or [],
    )
    return dict(branch=branch, client=client, owner=owner, admin=admin, portal_user=portal_user,
                mandor=mandor, location=location, contract=contract)


def _order(f, on_date, lunch, dinner, *, locked=False):
    order = DailyOrder.query.filter_by(branch_id=f["branch"].id, order_date=on_date).first()
    if order is None:
        order = DailyOrder(
            order_number=f"DO-{uuid4().hex[:10]}", branch_id=f["branch"].id, order_date=on_date,
            status="LOCKED" if locked else "DRAFT", is_locked=locked, created_by=f["admin"].id,
        )
        db.session.add(order)
        db.session.flush()
    detail = DailyOrderDetail(
        daily_order_id=order.id, mandor_id=f["mandor"].id, delivery_location_id=f["location"].id,
        price_per_portion=Decimal("25000"), price_source="STANDARD",
        lunch_qty=lunch, dinner_qty=dinner, total_qty=lunch + dinner,
        lunch_delivery_fee=Decimal("0"), dinner_delivery_fee=Decimal("0"),
    )
    db.session.add(detail)
    db.session.flush()
    return order, detail


def _tomorrow_detail(f, on_date):
    order = DailyOrder.query.filter_by(branch_id=f["branch"].id, order_date=on_date).first()
    if order is None:
        return None
    return DailyOrderDetail.query.filter_by(
        daily_order_id=order.id, mandor_id=f["mandor"].id, delivery_location_id=f["location"].id
    ).first()


def _run(f, period_date):
    return run_auto_daily_orders(
        branch_id=f["branch"].id, period_key=period_date.isoformat(),
        now=datetime.combine(period_date, time(18, 0)), commit=False,
    )


def _delivery_on_the_way(f, detail, meal="LUNCH"):
    driver = Driver(branch_id=f["branch"].id, name=f"Driver {uuid4().hex[:5]}", is_active=True)
    db.session.add(driver)
    db.session.flush()
    delivery = Delivery(
        delivery_number=f"DEL-{uuid4().hex[:10]}", branch_id=f["branch"].id,
        delivery_date=detail.daily_order.order_date, driver_id=driver.id, status="ON_THE_WAY",
        notes=f"delivery_type={meal}", created_by=f["admin"].id,
    )
    db.session.add(delivery)
    db.session.flush()
    db.session.add(DeliveryDetail(
        delivery_id=delivery.id, daily_order_detail_id=detail.id, mandor_id=f["mandor"].id,
        delivery_location_id=f["location"].id, planned_qty=detail.lunch_qty,
    ))
    db.session.flush()


# --- 1. Pesanan otomatis 18.00 -------------------------------------------------

def test_creates_tomorrow_from_last_working_day(ctx):
    f = _fixtures("LWD")
    _order(f, date(2026, 10, 7), 40, 35)

    summary = _run(f, date(2026, 10, 7))

    assert summary["created_orders_count"] == 1
    assert summary["created_portions_total"] == 75
    detail = _tomorrow_detail(f, date(2026, 10, 8))
    assert (detail.lunch_qty, detail.dinner_qty, detail.total_qty) == (40, 35, 75)
    assert detail.price_per_portion == Decimal("25000")
    changes = OrderQtyChange.query.filter_by(daily_order_detail_id=detail.id).all()
    assert {(c.meal_type, c.source, c.new_qty) for c in changes} == {("LUNCH", "AUTO", 40), ("DINNER", "AUTO", 35)}


def test_holiday_skipped_and_monday_uses_last_working_day(ctx):
    f = _fixtures("HOL", weekly_holidays=["7"])  # Minggu libur rutin
    db.session.add(ContractHoliday(contract_id=f["contract"].id, holiday_date=date(2026, 10, 10), note="Cuti"))
    _order(f, date(2026, 10, 9), 50, 45)  # Jumat

    saturday = _run(f, date(2026, 10, 9))  # untuk Sabtu = libur khusus
    assert saturday["created_orders_count"] == 0
    assert _tomorrow_detail(f, date(2026, 10, 10)) is None

    sunday = _run(f, date(2026, 10, 10))  # untuk Minggu = libur rutin
    assert sunday["created_orders_count"] == 0
    assert get_last_working_day(f["client"].id, date(2026, 10, 12), branch_id=f["branch"].id) == date(2026, 10, 9)

    monday = _run(f, date(2026, 10, 11))  # untuk Senin: ambil Jumat
    assert monday["created_portions_total"] == 95
    detail = _tomorrow_detail(f, date(2026, 10, 12))
    assert (detail.lunch_qty, detail.dinner_qty) == (50, 45)


def test_existing_order_untouched_and_rerun_is_idempotent(ctx):
    f = _fixtures("IDEM")
    _order(f, date(2026, 10, 7), 30, 30)
    _order(f, date(2026, 10, 8), 60, 0)  # besok sudah dipesan manual, malam sengaja kosong

    _run(f, date(2026, 10, 7))
    detail = _tomorrow_detail(f, date(2026, 10, 8))
    assert (detail.lunch_qty, detail.dinner_qty) == (60, 0)

    g = _fixtures("RERUN")
    _order(g, date(2026, 10, 7), 20, 10)
    _run(g, date(2026, 10, 7))
    _run(g, date(2026, 10, 7))
    detail = _tomorrow_detail(g, date(2026, 10, 8))
    assert (detail.lunch_qty, detail.dinner_qty) == (20, 10)
    assert OrderQtyChange.query.filter_by(daily_order_detail_id=detail.id).count() == 2


def test_skipped_without_history_or_price(ctx):
    f = _fixtures("NOHIST")
    summary = _run(f, date(2026, 10, 7))
    assert summary["created_orders_count"] == 0

    g = _fixtures("NOPRICE")
    _order(g, date(2026, 10, 7), 20, 20)
    PortionPrice.query.filter_by(branch_id=g["branch"].id).delete()
    db.session.flush()
    summary = _run(g, date(2026, 10, 7))
    assert summary["created_orders_count"] == 0
    assert any("Harga per porsi belum diatur" in row["reason"] for row in summary["skipped_records"])


def test_skipped_for_stopped_paused_cash_and_credit_hold(ctx):
    f = _fixtures("SKIP")
    _order(f, date(2026, 10, 7), 20, 20)
    states = {
        meal: StandingOrderState(
            branch_id=f["branch"].id, mandor_id=f["mandor"].id, delivery_location_id=f["location"].id,
            meal_type=meal, status="STOPPED", last_nonzero_qty=20,
        )
        for meal in ("LUNCH", "DINNER")
    }
    db.session.add_all(states.values())
    db.session.flush()
    args = (f["branch"].id, f["client"].id, f["mandor"].id, f["location"].id)

    qty, can_create, reason = resolve_auto_order_qty(*args, "LUNCH", date(2026, 10, 8))
    assert (qty, can_create) == (0, False) and "STOPPED" in reason

    states["LUNCH"].status = "PAUSED_UNTIL"
    states["LUNCH"].resume_date = date(2026, 10, 10)
    db.session.flush()
    assert resolve_auto_order_qty(*args, "LUNCH", date(2026, 10, 8))[1] is False
    assert resolve_auto_order_qty(*args, "LUNCH", date(2026, 10, 10))[:2] == (20, True)

    # Bayar di muka -> tidak dibuat otomatis
    for state in states.values():
        state.status = "ACTIVE"
        state.resume_date = None
    account = CreditAccount(
        branch_id=f["branch"].id, party_type=PARTY_MANDOR, party_id=f["mandor"].id,
        billing_mode=BILLING_CASH, credit_limit=Decimal("0"), payment_terms_days=0,
        deposit_percent=Decimal("0"),
    )
    db.session.add(account)
    db.session.flush()
    summary = _run(f, date(2026, 10, 7))
    assert summary["created_orders_count"] == 0
    assert any("bayar di muka" in row["reason"].lower() for row in summary["skipped_records"])

    # Kredit langsung berstatus TAHAN -> tidak dibuat, admin diberi tahu
    account.billing_mode = BILLING_DIRECT
    account.credit_limit = Decimal("10000000")
    account.payment_terms_days = 7
    account.status = STATUS_HOLD
    db.session.flush()
    summary = _run(f, date(2026, 10, 7))
    assert summary["created_orders_count"] == 0
    assert any("status kredit" in row["reason"] for row in summary["skipped_records"])
    assert Notification.query.filter_by(
        branch_id=f["branch"].id, notification_type="CREDIT_AUTO_ORDER_BLOCKED", target_role="ADMIN"
    ).count() >= 1
    assert Notification.query.filter_by(
        notification_type="CREDIT_AUTO_ORDER_BLOCKED", target_user_id=f["portal_user"].id
    ).count() >= 1


# --- 2. Porsi 0 wajib alasan -------------------------------------------------

def test_six_zero_reasons_drive_next_day(ctx):
    f = _fixtures("ZERO")
    _, detail = _order(f, date(2026, 10, 7), 40, 35)
    args = (f["branch"].id, f["client"].id, f["mandor"].id, f["location"].id, "LUNCH", date(2026, 10, 8))

    def set_zero(code, resume=None):
        detail.lunch_qty = 40
        db.session.flush()
        ok, msg, _ = update_order_qty_from_admin(
            f["admin"], detail.id, "LUNCH", 0, reason=f"alasan {code}", reason_code=code,
            resume_date=resume, commit=False,
        )
        assert ok, msg
        return StandingOrderState.query.filter_by(
            branch_id=f["branch"].id, mandor_id=f["mandor"].id, meal_type="LUNCH"
        ).first()

    for code in ("OFF_TODAY", "NO_WORKERS", "OTHER"):
        state = set_zero(code)
        assert state.status == "ACTIVE"
        assert resolve_auto_order_qty(*args)[:2] == (40, True)

    state = set_zero("OFF_UNTIL", resume=date(2026, 10, 10))
    assert (state.status, state.resume_date) == ("PAUSED_UNTIL", date(2026, 10, 10))
    assert resolve_auto_order_qty(*args)[1] is False

    state = set_zero("PAUSE")
    assert state.status == "STOPPED"
    assert resolve_auto_order_qty(*args)[1] is False

    state = set_zero("PROJECT_DONE")
    assert state.status == "STOPPED"
    assert Notification.query.filter(
        Notification.branch_id == f["branch"].id,
        Notification.notification_type == "CONTRACT_REVIEW_REQUIRED",
    ).count() >= 1
    assert set(PORTION_ZERO_REASONS) == {"OFF_TODAY", "OFF_UNTIL", "PAUSE", "PROJECT_DONE", "NO_WORKERS", "OTHER"}


# --- 3. Ubah porsi dari portal -----------------------------------------------

def _portal(f, day, meal, qty, **kwargs):
    return update_order_qty_from_portal(
        f["portal_user"], f["mandor"].id, f["location"].id, meal, day, qty, commit=False, **kwargs
    )


def test_portal_change_before_lock_and_refusals(ctx):
    f = _fixtures("PORTAL")
    day = date(2026, 10, 8)
    order, detail = _order(f, day, 40, 30)

    with time_machine.travel(_wib(2026, 10, 8, 9, 0), tick=False):
        ok, msg, _ = _portal(f, day, "LUNCH", 32)
        assert ok, msg
        assert detail.lunch_qty == 32
        change = OrderQtyChange.query.filter_by(daily_order_detail_id=detail.id, source="PORTAL").first()
        assert (change.old_qty, change.new_qty) == (40, 32)

        ok, msg, _ = _portal(f, day, "LUNCH", 0)  # porsi 0 tanpa alasan
        assert not ok and "alasan" in msg

    with time_machine.travel(_wib(2026, 10, 8, 10, 30), tick=False):
        ok, msg, _ = _portal(f, day, "LUNCH", 50)  # lewat jam lock 10.00
        assert not ok and "dikunci" in msg.lower()

    with time_machine.travel(_wib(2026, 10, 8, 9, 0), tick=False):
        order.is_locked = True
        db.session.flush()
        ok, msg, _ = _portal(f, day, "LUNCH", 50)
        assert not ok and "dikunci" in msg.lower()
        order.is_locked = False
        db.session.flush()

        _delivery_on_the_way(f, detail, "LUNCH")
        assert is_delivery_in_transit_or_delivered(detail.id, "LUNCH")
        ok, msg, _ = _portal(f, day, "LUNCH", 35)
        assert not ok and "perjalanan" in msg.lower()


def test_portal_cannot_touch_other_accounts_location(ctx):
    f = _fixtures("OWNA")
    g = _fixtures("OWNB")
    day = date(2026, 10, 8)
    _order(g, day, 10, 10)
    with time_machine.travel(_wib(2026, 10, 8, 9, 0), tick=False):
        ok, msg, _ = update_order_qty_from_portal(
            f["portal_user"], g["mandor"].id, g["location"].id, "LUNCH", day, 50, commit=False
        )
    assert not ok and "akses" in msg.lower()


def test_portal_increase_refused_by_credit_control(ctx):
    f = _fixtures("CREDIT")
    day = date(2026, 10, 8)
    _, detail = _order(f, day, 10, 10)
    db.session.add(CreditAccount(
        branch_id=f["branch"].id, party_type=PARTY_MANDOR, party_id=f["mandor"].id,
        billing_mode=BILLING_DIRECT, credit_limit=Decimal("100000"), payment_terms_days=7,
        deposit_percent=Decimal("0"),
    ))
    db.session.flush()
    with time_machine.travel(_wib(2026, 10, 8, 9, 0), tick=False):
        ok, msg, _ = _portal(f, day, "LUNCH", 30)  # +20 porsi = Rp500.000 > limit
    assert not ok and "kredit" in msg.lower()
    assert detail.lunch_qty == 10


def test_portal_card_marks_sessions(ctx):
    f = _fixtures("CARD")
    _order(f, date(2026, 10, 8), 40, 30)
    with time_machine.travel(_wib(2026, 10, 8, 9, 0), tick=False):
        context = build_portal_today_tomorrow_orders_context(f["portal_user"])
    today = context["days"][0]["locations"][0]["sessions"]
    assert context["has_contract"] is True
    assert today[0]["qty"] == 40 and today[0]["can_edit"] is True


# --- 4. Admin --------------------------------------------------------------

def test_admin_after_lock_needs_reason_and_in_transit_blocks_everyone(ctx):
    f = _fixtures("ADM")
    _, detail = _order(f, date(2026, 10, 8), 40, 30, locked=True)

    ok, msg, _ = update_order_qty_from_admin(f["admin"], detail.id, "LUNCH", 45, reason="", commit=False)
    assert not ok and "alasan" in msg.lower()

    ok, msg, _ = update_order_qty_from_admin(
        f["admin"], detail.id, "LUNCH", 45, reason="Tambahan dari mandor via telepon", commit=False
    )
    assert ok, msg
    change = OrderQtyChange.query.filter_by(daily_order_detail_id=detail.id, source="ADMIN").first()
    assert (change.new_qty, change.note) == (45, "Tambahan dari mandor via telepon")

    _delivery_on_the_way(f, detail, "LUNCH")
    ok, msg, _ = update_order_qty_from_admin(f["admin"], detail.id, "LUNCH", 50, reason="coba", commit=False)
    assert not ok and "perjalanan" in msg.lower()
