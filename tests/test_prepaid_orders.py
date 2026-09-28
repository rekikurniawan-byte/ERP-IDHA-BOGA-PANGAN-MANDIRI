"""Dua jalur transaksi, tahap 3: pelanggan umum bayar di muka.

Keputusan owner 2026-09-27 yang dikunci di sini:
- uang muka yang dicatat Finance = Uang Muka Pelanggan (2008) + jurnal otomatis;
- pesanan umum baru boleh diproses kalau uang muka >= total; OWNER boleh
  meloloskan dengan alasan;
- setelah semua pengiriman diterima, invoice dibuat otomatis dan dilunasi dari
  uang mukanya;
- pengembalian uang muka hanya OWNER;
- pesanan umum yang diinput admin dibayar saat input.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.pricing_service import (
    PATH_CONTRACT,
    PATH_GENERAL,
    create_delivery_zone,
    set_delivery_fee,
    set_portion_price,
)

TODAY = date.today()


@pytest.fixture
def ctx(app, monkeypatch):
    """Tanpa commit ke test_db: semua di-flush lalu di-rollback."""
    app.config["WTF_CSRF_ENABLED"] = False
    with app.app_context():
        from app.extensions import db

        monkeypatch.setattr(db.session, "commit", db.session.flush)
        try:
            yield db
        finally:
            db.session.rollback()


def _ensure_accounts(db):
    from app.models.accounting import Account

    for code, name, kind in (
        ("1001", "Kas", "ASSET"), ("1004", "Piutang Usaha", "ASSET"), ("1005", "Piutang Karyawan", "ASSET"),
        ("2008", "Uang Muka Pelanggan", "LIABILITY"), ("4001", "Pendapatan Catering Proyek", "REVENUE"),
        ("4002", "Pendapatan Catering Harian", "REVENUE"), ("4003", "Pendapatan Warung", "REVENUE"),
        ("4004", "Pendapatan Lain-Lain", "REVENUE"), ("4005", "Pendapatan Ongkos Kirim", "REVENUE"),
    ):
        if not Account.query.filter_by(account_code=code).first():
            db.session.add(Account(account_code=code, account_name=name, account_type=kind, is_active=True))
    db.session.flush()


def _setup(db, path=PATH_GENERAL):
    from app.models.master import Branch, Client, DeliveryLocation, Mandor, User

    _ensure_accounts(db)
    branch = Branch(code=f"PRE-{uuid4().hex[:8]}", name="Cabang Uji Bayar Muka", is_active=True)
    client = Client(name=f"Pelanggan Uji {uuid4().hex[:6]}", phone="0811", is_active=True, customer_path=path)
    db.session.add_all([branch, client])
    db.session.flush()
    users = {
        role: User(
            branch_id=branch.id, full_name=f"{role} Uji", username=f"pre-{role.lower()}-{uuid4().hex[:8]}",
            password_hash="x", role=role, is_active=True,
        )
        for role in ("OWNER", "ADMIN", "PORTAL_CUSTOMER")
    }
    mandor = Mandor(branch_id=branch.id, client_id=client.id, name=client.name, is_active=True)
    db.session.add_all([mandor, *users.values()])
    db.session.flush()
    owner = users["OWNER"]
    zone = create_delivery_zone(branch.id, "Dalam Kota", owner.id)
    set_delivery_fee(branch_id=branch.id, zone_id=zone.id, fee=15000, effective_from=TODAY, created_by=owner.id)
    set_portion_price(branch_id=branch.id, price=25000, effective_from=TODAY, created_by=owner.id)
    location = DeliveryLocation(mandor_id=mandor.id, location_name="Rumah", is_active=True, delivery_zone_id=zone.id)
    db.session.add(location)
    db.session.flush()
    return SimpleNamespace(branch=branch, client=client, mandor=mandor, location=location, zone=zone, **{
        role.lower(): user for role, user in users.items()
    })


def _draft(db, s, qty=12, meal="LUNCH"):
    from app.models.system import PortalOrderDraft

    draft = PortalOrderDraft(
        user_id=s.portal_customer.id, branch_id=s.branch.id, client_id=s.client.id, mandor_id=s.mandor.id,
        delivery_location_id=s.location.id, order_date=TODAY + timedelta(days=2), meal_type=meal,
        portion_qty=qty, price_per_portion=Decimal("25000"), price_source="STANDAR",
        delivery_fee=Decimal("15000"), idempotency_key=uuid4().hex,
    )
    db.session.add(draft)
    db.session.flush()
    return draft  # total = 12 × 25.000 + 15.000 = 315.000


def _pay(s, draft, amount):
    from app.services.prepaid_order_service import record_draft_prepayment

    return record_draft_prepayment(draft=draft, amount=amount, payment_method="CASH", created_by=s.admin.id)


def _payment_gate(draft, **kwargs):
    from app.services.portal_order_draft_service import evaluate_portal_order_draft_gate

    gate = evaluate_portal_order_draft_gate(draft, **kwargs)
    return next(item for item in gate["gates"] if item["key"] == "PAYMENT")


# --- uang muka dan gerbang ------------------------------------------------

def test_uang_muka_dijurnal_ke_2008_dan_terhubung_ke_draft(ctx):
    from app.models.accounting import Account, JournalDetail

    s = _setup(ctx)
    draft = _draft(ctx, s)

    advance = _pay(s, draft, 315000)

    assert advance.portal_order_draft_id == draft.id
    lines = {
        Account.query.get(row.account_id).account_code: (Decimal(str(row.debit)), Decimal(str(row.credit)))
        for row in JournalDetail.query.filter_by(journal_id=advance.journal_id).all()
    }
    assert lines == {"1001": (Decimal("315000"), Decimal("0")), "2008": (Decimal("0"), Decimal("315000"))}


def test_pembayaran_melebihi_sisa_ditolak(ctx):
    from app.services.prepaid_order_service import PrepaymentError

    s = _setup(ctx)
    draft = _draft(ctx, s)
    _pay(s, draft, 300000)

    with pytest.raises(PrepaymentError, match="melebihi sisa"):
        _pay(s, draft, 20000)


def test_draft_umum_tertahan_sampai_lunas(ctx):
    s = _setup(ctx)
    draft = _draft(ctx, s)

    assert _payment_gate(draft)["status"] == "BLOCKED"
    _pay(s, draft, 300000)
    assert _payment_gate(draft)["status"] == "BLOCKED"
    _pay(s, draft, 15000)
    assert _payment_gate(draft)["status"] == "OK"


def test_owner_boleh_meloloskan_dengan_alasan(ctx):
    from app.services.portal_order_draft_service import confirm_portal_order_draft

    s = _setup(ctx)
    draft = _draft(ctx, s)

    _, converted, error = confirm_portal_order_draft(draft.id, s.owner, review_note="", prepayment_override=True)
    assert not converted and "alasan" in error

    _, converted, error = confirm_portal_order_draft(draft.id, s.admin, review_note="x", prepayment_override=True)
    assert not converted  # override hanya berlaku untuk OWNER

    assert _payment_gate(draft, owner_override=True)["status"] == "OVERRIDE"


def test_draft_kontrak_tidak_wajib_bayar_di_muka(ctx):
    from app.models.system import PortalOrderDraft

    s = _setup(ctx, path=PATH_CONTRACT)
    draft = _draft(ctx, s)
    draft.user_id = s.admin.id  # bukan akun pelanggan umum
    ctx.session.flush()
    ctx.session.expire(draft)
    draft = PortalOrderDraft.query.get(draft.id)

    assert _payment_gate(draft)["status"] == "NOT_REQUIRED"


# --- setelah terkirim: invoice otomatis lunas -----------------------------

def _locked_order_with_detail(db, s, lunch_qty=12, lunch_fee=Decimal("15000")):
    from app.models.operational import DailyOrder, DailyOrderDetail

    order = DailyOrder(
        order_number=f"ORD-PRE-{uuid4().hex[:8]}", branch_id=s.branch.id, order_date=TODAY,
        status="LOCKED", is_locked=True, created_by=s.admin.id,
    )
    db.session.add(order)
    db.session.flush()
    detail = DailyOrderDetail(
        daily_order_id=order.id, mandor_id=s.mandor.id, delivery_location_id=s.location.id,
        price_per_portion=Decimal("25000"), price_source="STANDAR", lunch_qty=lunch_qty, dinner_qty=0,
        total_qty=lunch_qty, lunch_delivery_fee=lunch_fee, dinner_delivery_fee=0,
    )
    db.session.add(detail)
    db.session.flush()
    return order, detail


def _deliver(db, s, detail, received=True):
    from app.models.delivery import Delivery, DeliveryDetail, DeliveryReceipt
    from app.models.master import Driver

    driver = Driver(branch_id=s.branch.id, name="Driver Uji", is_active=True)
    db.session.add(driver)
    db.session.flush()
    delivery = Delivery(
        delivery_number=f"DLV-PRE-{uuid4().hex[:8]}", branch_id=s.branch.id, delivery_date=TODAY,
        driver_id=driver.id, status="DELIVERED" if received else "PREPARING",
        notes="delivery_type=LUNCH", created_by=s.admin.id,
    )
    db.session.add(delivery)
    db.session.flush()
    row = DeliveryDetail(
        delivery_id=delivery.id, daily_order_detail_id=detail.id, mandor_id=detail.mandor_id,
        delivery_location_id=detail.delivery_location_id, planned_qty=detail.lunch_qty,
        delivered_qty=detail.lunch_qty if received else 0,
    )
    db.session.add(row)
    db.session.flush()
    if received:
        db.session.add(DeliveryReceipt(delivery_detail_id=row.id, receiver_name="Penerima", receive_time=datetime.utcnow()))
        db.session.flush()
    return row


def test_invoice_otomatis_lunas_dari_uang_muka_setelah_terkirim(ctx):
    from app.models.accounting import Account, JournalDetail
    from app.models.finance import AdvanceSettlement
    from app.services.prepaid_order_service import invoice_prepaid_order, record_detail_prepayment

    s = _setup(ctx)
    order, detail = _locked_order_with_detail(ctx, s)
    advance = record_detail_prepayment(detail=detail, amount=315000, payment_method="CASH", created_by=s.admin.id)
    _deliver(ctx, s, detail)

    invoice = invoice_prepaid_order(order, s.mandor, s.admin.id)

    assert invoice is not None
    assert Decimal(str(invoice.total_amount)) == Decimal("315000")
    assert invoice.status == "PAID" and Decimal(str(invoice.remaining_amount)) == 0
    assert advance.status == "SETTLED"
    settlement = AdvanceSettlement.query.filter_by(advance_id=advance.id).one()
    lines = {
        Account.query.get(row.account_id).account_code: (Decimal(str(row.debit)), Decimal(str(row.credit)))
        for row in JournalDetail.query.filter_by(journal_id=settlement.journal_id).all()
    }
    assert lines == {"2008": (Decimal("315000"), Decimal("0")), "1004": (Decimal("0"), Decimal("315000"))}


def test_belum_terkirim_belum_ada_invoice(ctx):
    from app.services.prepaid_order_service import invoice_prepaid_order

    s = _setup(ctx)
    order, detail = _locked_order_with_detail(ctx, s)
    _deliver(ctx, s, detail, received=False)

    assert invoice_prepaid_order(order, s.mandor, s.admin.id) is None


def test_pesanan_kontrak_tidak_diinvoice_otomatis(ctx):
    from app.services.prepaid_order_service import invoice_prepaid_order

    s = _setup(ctx, path=PATH_CONTRACT)
    order, detail = _locked_order_with_detail(ctx, s)
    _deliver(ctx, s, detail)

    assert invoice_prepaid_order(order, s.mandor, s.admin.id) is None


def test_diloloskan_owner_sisa_jadi_piutang(ctx):
    from app.services.prepaid_order_service import invoice_prepaid_order, record_detail_prepayment

    s = _setup(ctx)
    order, detail = _locked_order_with_detail(ctx, s)
    record_detail_prepayment(detail=detail, amount=200000, payment_method="CASH", created_by=s.admin.id)
    _deliver(ctx, s, detail)

    invoice = invoice_prepaid_order(order, s.mandor, s.admin.id)

    assert invoice.status == "PARTIAL"
    assert Decimal(str(invoice.remaining_amount)) == Decimal("115000")


# --- pengembalian ---------------------------------------------------------

def test_pengembalian_uang_muka_hanya_owner_dan_dijurnal(ctx):
    # Jalur yang dipakai halaman Finance > Uang Muka & Refund (advance_settle).
    from app.models.accounting import Account, JournalDetail
    from app.models.finance import AdvanceSettlement
    from app.services.advance_service import CLIENT_DP_REFUND, create_advance_settlement

    s = _setup(ctx)
    draft = _draft(ctx, s)
    advance = _pay(s, draft, 315000)
    refund = dict(advance=advance, settlement_date=TODAY, settlement_type=CLIENT_DP_REFUND, amount=Decimal("315000"),
                  notes="ditolak", payment_method="CASH", commit=False)

    with pytest.raises(Exception, match="OWNER"):
        create_advance_settlement(created_by=s.admin.id, **refund)

    create_advance_settlement(created_by=s.owner.id, **refund)

    assert Decimal(str(advance.remaining_amount)) == Decimal("0.00")
    settlement = AdvanceSettlement.query.filter_by(advance_id=advance.id).one()
    lines = {
        Account.query.get(row.account_id).account_code: (Decimal(str(row.debit)), Decimal(str(row.credit)))
        for row in JournalDetail.query.filter_by(journal_id=settlement.journal_id).all()
    }
    assert lines == {"2008": (Decimal("315000"), Decimal("0")), "1001": (Decimal("0"), Decimal("315000"))}


# --- input admin ----------------------------------------------------------

def _post_order(app, user, s, **extra):
    client = app.test_client()
    with client.session_transaction() as session:
        session["_user_id"] = str(user.id)
        session["_fresh"] = True
    return client.post("/operational/orders/create", data={
        "order_date": (TODAY + timedelta(days=30)).isoformat(),
        "mandor_id": s.mandor.id,
        "delivery_location_id": s.location.id,
        "lunch_qty": 12,
        "dinner_qty": 0,
        **extra,
    })


def test_admin_input_pesanan_umum_wajib_lunas(app, ctx):
    from app.models.operational import DailyOrderDetail

    s = _setup(ctx)

    _post_order(app, s.admin, s, prepayment_amount="100000", prepayment_method="CASH")

    assert DailyOrderDetail.query.filter_by(mandor_id=s.mandor.id).count() == 0


def test_admin_input_pesanan_umum_lunas_tercatat_uang_muka(app, ctx):
    from app.models.operational import DailyOrderDetail
    from app.services.prepaid_order_service import available_amount, detail_prepayments

    s = _setup(ctx)

    _post_order(app, s.admin, s, prepayment_amount="315000", prepayment_method="CASH")

    detail = DailyOrderDetail.query.filter_by(mandor_id=s.mandor.id).one()
    assert available_amount(detail_prepayments(detail)) == Decimal("315000.00")


def test_invoice_pelanggan_umum_tanpa_pic(ctx):
    from app.services.invoice_identity_service import invoice_contact_snapshot

    s = _setup(ctx)

    contact, error = invoice_contact_snapshot(s.client, s.mandor, None, "CLIENT")

    assert error is None
    assert contact["client_pic_name_snapshot"] == s.client.name


def test_tanda_terima_memicu_invoice_otomatis(ctx):
    from app.services.prepaid_order_service import invoice_after_delivery_receipt, record_detail_prepayment

    s = _setup(ctx)
    order, detail = _locked_order_with_detail(ctx, s)
    record_detail_prepayment(detail=detail, amount=315000, payment_method="CASH", created_by=s.admin.id)
    delivery_row = _deliver(ctx, s, detail)

    invoice, error = invoice_after_delivery_receipt(delivery_row, s.admin.id)

    assert error is None
    assert invoice is not None and invoice.status == "PAID"
    # Tanda terima kedua (mis. dibuka ulang) tidak membuat invoice ganda.
    assert invoice_after_delivery_receipt(delivery_row, s.admin.id) == (None, None)
