"""Kurang kirim yang tidak diganti tidak ditagih; kelebihan uang muka dikembalikan.

Keputusan owner 2026-09-28 (gladi pilot). Ikut dikunci: pesanan portal siang
dan malam untuk lokasi yang sama digabung ke satu baris order.
"""
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from app.services.mandor_invoice_helper_service import billable_base_quantities, is_after_lock_increase_revision
from tests.test_prepaid_orders import TODAY, _draft, _pay, _setup, ctx  # noqa: F401 - fixture


def _order(db, s, lunch=20, dinner=0):
    from app.models.operational import DailyOrder, DailyOrderDetail

    order = DailyOrder(branch_id=s.branch.id, order_number=f"ORD-KK-{uuid4().hex[:6]}", order_date=TODAY,
                       status="LOCKED", is_locked=True, created_by=s.admin.id)
    db.session.add(order)
    db.session.flush()
    detail = DailyOrderDetail(daily_order_id=order.id, mandor_id=s.mandor.id, delivery_location_id=s.location.id,
                              price_per_portion=Decimal("25000"), lunch_qty=lunch, dinner_qty=dinner,
                              total_qty=lunch + dinner, lunch_delivery_fee=Decimal("15000"))
    db.session.add(detail)
    db.session.flush()
    return order, detail


def _deliver(db, s, detail, planned, received, *, replacement=False):
    from app.models.delivery import Delivery, DeliveryDetail, DeliveryReceipt
    from app.models.master import Driver

    driver = Driver(branch_id=s.branch.id, name=f"Pengantar {uuid4().hex[:4]}", is_active=True)
    db.session.add(driver)
    db.session.flush()
    notes = "delivery_type=LUNCH; batch=" + ("SHORTAGE_REPLACEMENT; shortage_source_detail_id=0" if replacement else "MAIN")
    delivery = Delivery(delivery_number=f"DLV-KK-{uuid4().hex[:8]}", branch_id=s.branch.id, delivery_date=TODAY,
                        driver_id=driver.id, status="DELIVERED", notes=notes, created_by=s.admin.id)
    db.session.add(delivery)
    db.session.flush()
    row = DeliveryDetail(delivery_id=delivery.id, daily_order_detail_id=detail.id, mandor_id=detail.mandor_id,
                         delivery_location_id=detail.delivery_location_id, planned_qty=planned,
                         delivered_qty=received, shortage_qty=planned - received)
    db.session.add(row)
    db.session.flush()
    db.session.add(DeliveryReceipt(delivery_detail_id=row.id, receiver_name="Penerima", receive_time=datetime.utcnow()))
    db.session.flush()
    return row


def test_kurang_kirim_tercatat_tidak_ditagih_sampai_diganti(ctx):
    s = _setup(ctx)
    _order_row, detail = _order(ctx, s, lunch=20)

    assert billable_base_quantities(detail, is_after_lock_increase_revision) == (20, 0, 0)  # belum diterima: tagih penuh

    _deliver(ctx, s, detail, planned=20, received=17)
    assert billable_base_quantities(detail, is_after_lock_increase_revision) == (17, 0, 3)

    _deliver(ctx, s, detail, planned=3, received=2, replacement=True)
    assert billable_base_quantities(detail, is_after_lock_increase_revision) == (19, 0, 1)


def test_invoice_menagih_porsi_diterima_dan_menulis_kekurangannya(ctx):
    from app.services.order_invoice_service import build_order_invoice_lines

    s = _setup(ctx)
    order, detail = _order(ctx, s, lunch=20)
    _deliver(ctx, s, detail, planned=20, received=18)

    catering = [line for line in build_order_invoice_lines(order, s.mandor.id) if line["item_type"] == "CATERING"]

    assert [line["qty"] for line in catering] == [18]
    assert catering[0]["subtotal"] == Decimal("450000")
    assert "Kurang kirim 2 porsi (tidak ditagih)" in catering[0]["description"]


def test_sisa_uang_muka_pesanan_yang_sudah_ditagih_harus_dikembalikan(ctx):
    from app.services.prepaid_order_service import advances_to_refund, invoice_prepaid_order, link_draft_prepayments_to_detail

    s = _setup(ctx)  # pelanggan umum, harga 25.000, ongkir 15.000
    order, detail = _order(ctx, s, lunch=12)
    draft = _draft(ctx, s, qty=12)
    _pay(s, draft, 315000)
    link_draft_prepayments_to_detail(draft, detail)
    _deliver(ctx, s, detail, planned=12, received=11)

    invoice = invoice_prepaid_order(order, s.mandor, s.admin.id)

    assert invoice.total_amount == Decimal("290000.00")  # 11 x 25.000 + ongkir 15.000
    assert invoice.status == "PAID"
    pending = advances_to_refund(s.branch.id)
    assert [(Decimal(str(advance.remaining_amount)), "sudah ditagih" in reason) for advance, reason in pending] == [(Decimal("25000.00"), True)]


def _as_mandor_account(db, s, *drafts):
    """Draft jalur kontrak dikirim akun Portal Mandor (bukan akun pelanggan umum)."""
    from app.models.master import User

    user = User(branch_id=s.branch.id, full_name="Mandor Uji", username=f"mdr-{uuid4().hex[:8]}",
                password_hash="x", role="PORTAL_SUBCLIENT", is_active=True)
    db.session.add(user)
    db.session.flush()
    for draft in drafts:
        draft.user_id = user.id
    db.session.flush()
    db.session.expire_all()


def test_pesanan_portal_siang_dan_malam_digabung_ke_satu_baris(ctx):
    from app.models.operational import DailyOrderDetail
    from app.services.pricing_service import PATH_CONTRACT
    from app.services.portal_order_draft_service import confirm_portal_order_draft

    s = _setup(ctx, path=PATH_CONTRACT)
    lunch = _draft(ctx, s, qty=40, meal="LUNCH")
    dinner = _draft(ctx, s, qty=30, meal="DINNER")
    second_lunch = _draft(ctx, s, qty=10, meal="LUNCH")
    _as_mandor_account(ctx, s, lunch, dinner, second_lunch)

    _draft_row, ok, message = confirm_portal_order_draft(lunch.id, s.admin, review_note="uji")
    assert ok, message
    _draft_row, ok, message = confirm_portal_order_draft(dinner.id, s.admin, review_note="uji")
    assert ok, message
    _draft_row, ok, message = confirm_portal_order_draft(second_lunch.id, s.admin, review_note="uji")
    assert not ok and "sudah ada" in message

    rows = DailyOrderDetail.query.filter_by(mandor_id=s.mandor.id, delivery_location_id=s.location.id).all()
    assert [(row.lunch_qty, row.dinner_qty, row.total_qty) for row in rows] == [(40, 30, 70)]
    assert rows[0].lunch_delivery_fee == rows[0].dinner_delivery_fee == Decimal("15000.00")


def test_pesanan_portal_harga_berbeda_tidak_digabung(ctx):
    from app.services.pricing_service import PATH_CONTRACT
    from app.services.portal_order_draft_service import confirm_portal_order_draft

    s = _setup(ctx, path=PATH_CONTRACT)
    lunch = _draft(ctx, s, qty=40, meal="LUNCH")
    dinner = _draft(ctx, s, qty=30, meal="DINNER")
    dinner.price_per_portion = Decimal("27000")
    ctx.session.flush()
    _as_mandor_account(ctx, s, lunch, dinner)

    assert confirm_portal_order_draft(lunch.id, s.admin, review_note="uji")[1]
    _draft_row, ok, message = confirm_portal_order_draft(dinner.id, s.admin, review_note="uji")

    assert not ok and "berbeda" in message


