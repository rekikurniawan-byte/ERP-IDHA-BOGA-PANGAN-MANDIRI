"""Dua jalur transaksi, tahap 2: ongkir.

Keputusan owner 2026-09-27 yang dikunci di sini:
- kontrak: ongkir termasuk harga porsi, kecuali kontraknya punya tarif sendiri;
- umum: tarif zona per pengiriman (siang dan malam = dua kali jalan), gratis
  kalau porsi pengiriman itu mencapai ambang cabang;
- tarif dikunci ke pengiriman saat pesanan dibuat;
- ongkir ditagih sebagai baris invoice sendiri dan dijurnal ke 4005.
"""
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.pricing_service import (
    FEE_SOURCE_CONTRACT,
    FEE_SOURCE_FREE,
    FEE_SOURCE_INCLUDED,
    FEE_SOURCE_ZONE,
    PATH_CONTRACT,
    PATH_GENERAL,
    PricingError,
    create_delivery_zone,
    order_trip_fees,
    quote_trip_fee,
    set_delivery_fee,
    set_free_delivery_min_portions,
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


def _setup(db, path=PATH_GENERAL, zone_fee=15000):
    from app.models.master import Branch, Client, DeliveryLocation, Mandor, User

    branch = Branch(code=f"ONG-{uuid4().hex[:8]}", name="Cabang Uji Ongkir", is_active=True)
    client = Client(name=f"Client Uji Ongkir {uuid4().hex[:6]}", is_active=True, customer_path=path)
    db.session.add_all([branch, client])
    db.session.flush()
    owner = User(
        branch_id=branch.id, full_name="Owner Uji Ongkir", username=f"ong-{uuid4().hex[:10]}",
        password_hash="x", role="OWNER", is_active=True,
    )
    mandor = Mandor(branch_id=branch.id, client_id=client.id, name="Sub Uji Ongkir", is_active=True)
    db.session.add_all([owner, mandor])
    db.session.flush()
    zone = create_delivery_zone(branch.id, "Dalam Kota", owner.id)
    if zone_fee is not None:
        set_delivery_fee(branch_id=branch.id, zone_id=zone.id, fee=zone_fee, effective_from=TODAY, created_by=owner.id)
    location = DeliveryLocation(mandor_id=mandor.id, location_name="Lokasi Uji Ongkir", is_active=True, delivery_zone_id=zone.id)
    db.session.add(location)
    db.session.flush()
    return SimpleNamespace(branch=branch, client=client, owner=owner, mandor=mandor, zone=zone, location=location)


# --- tarif ----------------------------------------------------------------

def test_kontrak_tanpa_tarif_sendiri_ongkirnya_termasuk_harga(ctx):
    s = _setup(ctx, path=PATH_CONTRACT)

    assert quote_trip_fee(s.branch.id, s.client, s.location, 20) == (Decimal("0.00"), FEE_SOURCE_INCLUDED, None)


def test_kontrak_dengan_tarif_ongkir_sendiri(ctx):
    s = _setup(ctx, path=PATH_CONTRACT)
    set_delivery_fee(branch_id=s.branch.id, client_id=s.client.id, fee=40000, effective_from=TODAY, created_by=s.owner.id)

    fee, source, _ = quote_trip_fee(s.branch.id, s.client, s.location, 20)

    assert (fee, source) == (Decimal("40000.00"), FEE_SOURCE_CONTRACT)


def test_pelanggan_umum_kena_tarif_zona(ctx):
    s = _setup(ctx)

    assert quote_trip_fee(s.branch.id, s.client, s.location, 12)[:2] == (Decimal("15000.00"), FEE_SOURCE_ZONE)


def test_gratis_ongkir_mulai_ambang_per_pengiriman(ctx):
    s = _setup(ctx)
    set_free_delivery_min_portions(s.branch.id, 30, s.owner.id)

    assert quote_trip_fee(s.branch.id, s.client, s.location, 30)[:2] == (Decimal("0.00"), FEE_SOURCE_FREE)
    assert quote_trip_fee(s.branch.id, s.client, s.location, 29)[0] == Decimal("15000.00")


def test_siang_dan_malam_dihitung_dua_kali_jalan(ctx):
    s = _setup(ctx)

    lunch, dinner, error = order_trip_fees(s.branch.id, s.client, s.location, 12, 15)
    only_lunch = order_trip_fees(s.branch.id, s.client, s.location, 12, 0)

    assert error is None
    assert (lunch, dinner) == (Decimal("15000.00"), Decimal("15000.00"))
    assert only_lunch[:2] == (Decimal("15000.00"), Decimal("0.00"))


def test_lokasi_umum_tanpa_zona_ditolak(ctx):
    s = _setup(ctx)
    s.location.delivery_zone_id = None

    fee, _, error = quote_trip_fee(s.branch.id, s.client, s.location, 12)

    assert fee is None and "belum punya zona" in error


def test_zona_tanpa_tarif_ditolak(ctx):
    s = _setup(ctx, zone_fee=None)

    assert "belum diatur" in quote_trip_fee(s.branch.id, s.client, s.location, 12)[2]


def test_tarif_baru_terjadwal_tidak_mengubah_tarif_hari_ini(ctx):
    s = _setup(ctx)
    set_delivery_fee(
        branch_id=s.branch.id, zone_id=s.zone.id, fee=20000,
        effective_from=TODAY + timedelta(days=7), created_by=s.owner.id,
    )

    assert quote_trip_fee(s.branch.id, s.client, s.location, 12)[0] == Decimal("15000.00")
    assert quote_trip_fee(s.branch.id, s.client, s.location, 12, TODAY + timedelta(days=7))[0] == Decimal("20000.00")


def test_tarif_minus_atau_target_ganda_ditolak(ctx):
    s = _setup(ctx)

    with pytest.raises(PricingError):
        set_delivery_fee(branch_id=s.branch.id, zone_id=s.zone.id, fee=-1, effective_from=TODAY, created_by=s.owner.id)
    with pytest.raises(PricingError):
        set_delivery_fee(
            branch_id=s.branch.id, zone_id=s.zone.id, client_id=s.client.id, fee=1,
            effective_from=TODAY, created_by=s.owner.id,
        )


# --- order, revisi, invoice, jurnal ---------------------------------------

def _order_with_detail(db, s, lunch_qty, dinner_qty, lunch_fee, dinner_fee, price=Decimal("25000")):
    from app.models.operational import DailyOrder, DailyOrderDetail

    order = DailyOrder(
        order_number=f"ORD-ONG-{uuid4().hex[:8]}", branch_id=s.branch.id, order_date=TODAY,
        status="DRAFT", is_locked=False, created_by=s.owner.id,
    )
    db.session.add(order)
    db.session.flush()
    detail = DailyOrderDetail(
        daily_order_id=order.id, mandor_id=s.mandor.id, delivery_location_id=s.location.id,
        price_per_portion=price, price_source="STANDAR", lunch_qty=lunch_qty, dinner_qty=dinner_qty,
        total_qty=lunch_qty + dinner_qty, lunch_delivery_fee=lunch_fee, dinner_delivery_fee=dinner_fee,
    )
    db.session.add(detail)
    db.session.flush()
    return order, detail


def test_revisi_menambah_pengiriman_baru_mengenakan_ongkirnya(ctx):
    from app.services.operational_service import revise_order_detail

    s = _setup(ctx)
    _, detail = _order_with_detail(ctx, s, 12, 0, Decimal("15000"), 0)

    ok, _ = revise_order_detail(
        detail=detail, revision_type="MANUAL", revision_direction="INCREASE",
        lunch_qty_change=0, dinner_qty_change=12, reason="tambah malam", created_by=s.owner.id, commit=False,
    )

    assert ok
    assert (detail.lunch_delivery_fee, detail.dinner_delivery_fee) == (Decimal("15000"), Decimal("15000.00"))


def test_pengiriman_yang_porsinya_habis_tidak_dikenai_ongkir(ctx):
    from app.services.operational_service import revise_order_detail

    s = _setup(ctx)
    _, detail = _order_with_detail(ctx, s, 12, 12, Decimal("15000"), Decimal("15000"))

    ok, _ = revise_order_detail(
        detail=detail, revision_type="MANUAL", revision_direction="DECREASE",
        lunch_qty_change=0, dinner_qty_change=12, reason="batal malam", created_by=s.owner.id, commit=False,
    )

    assert ok
    assert detail.dinner_delivery_fee == 0
    assert detail.lunch_delivery_fee == Decimal("15000")


def test_baris_invoice_ongkir_satu_per_pengiriman_berbayar(ctx):
    from app.services.mandor_invoice_helper_service import delivery_fee_invoice_lines

    s = _setup(ctx)
    order, detail = _order_with_detail(ctx, s, 12, 40, Decimal("15000"), 0)

    lines = delivery_fee_invoice_lines(order, detail)

    assert len(lines) == 1
    assert lines[0]["item_type"] == "ONGKIR"
    assert lines[0]["source_type"] == "DELIVERY_FEE_LUNCH"
    assert lines[0]["subtotal"] == 15000.0


def test_jurnal_invoice_mencatat_ongkir_di_4005(ctx):
    from app.models.accounting import Account, JournalDetail
    from app.models.finance import Invoice, InvoiceItem
    from app.services.accounting_service import create_invoice_journal_for_invoice

    s = _setup(ctx)
    # test_db tidak membawa COA lengkap; akun yang dipakai jurnal disiapkan di sini.
    for code, name, kind in (
        ("1005", "Piutang Karyawan", "ASSET"), ("4001", "Pendapatan Catering Proyek", "REVENUE"),
        ("4002", "Pendapatan Catering Harian", "REVENUE"), ("4003", "Pendapatan Warung", "REVENUE"),
        ("4004", "Pendapatan Lain-Lain", "REVENUE"),
    ):
        if not Account.query.filter_by(account_code=code).first():
            ctx.session.add(Account(account_code=code, account_name=name, account_type=kind, is_active=True))
    ctx.session.flush()
    invoice = Invoice(
        branch_id=s.branch.id, invoice_number=f"INV-ONG-{uuid4().hex[:8]}", invoice_date=TODAY, due_date=TODAY,
        bill_to_type="MANDOR", source_type="DAILY_ORDER", total_amount=Decimal("315000"),
        remaining_amount=Decimal("315000"), status="SENT", created_by=s.owner.id,
    )
    ctx.session.add(invoice)
    ctx.session.flush()
    ctx.session.add_all([
        InvoiceItem(invoice_id=invoice.id, item_type="CATERING", description="Catering", qty=12,
                    unit_price=25000, subtotal=300000, source_type="ORDER_DETAIL", source_id=1),
        InvoiceItem(invoice_id=invoice.id, item_type="ONGKIR", description="Ongkos kirim siang", qty=1,
                    unit_price=15000, subtotal=15000, source_type="DELIVERY_FEE_LUNCH", source_id=1),
    ])
    ctx.session.flush()

    ok, message, journal = create_invoice_journal_for_invoice(invoice, s.owner.id, commit=False)

    assert ok, message
    credits = {
        Account.query.get(row.account_id).account_code: Decimal(str(row.credit))
        for row in JournalDetail.query.filter_by(journal_id=journal.id).all()
        if row.credit
    }
    assert credits == {"4002": Decimal("300000"), "4005": Decimal("15000")}


def test_hutang_belum_ditagih_ikut_menghitung_ongkir(ctx):
    from app.models.credit import PARTY_MANDOR
    from app.services.credit_control_service import unbilled_delivered

    s = _setup(ctx)
    _order_with_detail(ctx, s, 12, 12, Decimal("15000"), Decimal("15000"))

    assert unbilled_delivered(s.branch.id, PARTY_MANDOR, s.mandor.id) == Decimal("25000") * 24 + Decimal("30000")


def test_rute_order_mengunci_ongkir_pelanggan_umum(app, ctx):
    from app.models.master import User
    from app.models.operational import DailyOrderDetail

    s = _setup(ctx)
    set_portion_price(branch_id=s.branch.id, price=25000, effective_from=TODAY, created_by=s.owner.id)
    admin = User(
        branch_id=s.branch.id, full_name="Admin Uji Ongkir", username=f"ong-adm-{uuid4().hex[:8]}",
        password_hash="x", role="ADMIN", is_active=True,
    )
    ctx.session.add(admin)
    ctx.session.flush()
    client = app.test_client()
    with client.session_transaction() as session:
        session["_user_id"] = str(admin.id)
        session["_fresh"] = True

    client.post("/operational/orders/create", data={
        "order_date": (TODAY + timedelta(days=30)).isoformat(),
        "mandor_id": s.mandor.id,
        "delivery_location_id": s.location.id,
        "lunch_qty": 12,
        "dinner_qty": 10,
    })

    detail = DailyOrderDetail.query.filter_by(mandor_id=s.mandor.id).one()
    assert (detail.lunch_delivery_fee, detail.dinner_delivery_fee) == (Decimal("15000.00"), Decimal("15000.00"))
