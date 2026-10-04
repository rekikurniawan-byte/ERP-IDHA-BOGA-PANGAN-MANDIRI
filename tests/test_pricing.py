"""Dua jalur transaksi, tahap 1: jalur pelanggan dan harga per porsi.

Keputusan owner 2026-09-27 yang dikunci di sini:
- satu harga per porsi (siang = malam); harga kontrak per client menang atas
  harga standar cabang;
- harga bisa diubah kapan saja dengan tanggal berlaku, baris lama tidak diubah;
- admin tidak menentukan harga; OWNER boleh mengubah harga satu pesanan;
- pelanggan UMUM tanpa minimal porsi bawaan (bisa diatur per cabang).
"""
from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from app.services.pricing_service import (
    DEFAULT_MIN_PORTIONS,
    PATH_CONTRACT,
    PATH_GENERAL,
    SOURCE_CONTRACT,
    SOURCE_OWNER,
    SOURCE_STANDARD,
    PricingError,
    min_portion_error,
    price_quotes_by_mandor,
    quote_price,
    resolve_order_price,
    set_general_min_portions,
    set_portion_price,
)

TODAY = date.today()


@pytest.fixture
def ctx(app, monkeypatch):
    """Tanpa commit ke test_db: layanan harga di-flush saja, lalu di-rollback."""
    with app.app_context():
        from app.extensions import db

        monkeypatch.setattr(db.session, "commit", db.session.flush)
        try:
            yield db
        finally:
            db.session.rollback()


def _setup(db, path=PATH_CONTRACT):
    from app.models.master import Branch, Client, Mandor, User

    branch = Branch(code=f"PRC-{uuid4().hex[:8]}", name="Cabang Uji Harga", is_active=True)
    client = Client(name=f"Client Uji Harga {uuid4().hex[:6]}", is_active=True, customer_path=path)
    db.session.add_all([branch, client])
    db.session.flush()
    mandor = Mandor(branch_id=branch.id, client_id=client.id, name="Sub Uji Harga", is_active=True)
    owner = User(
        branch_id=branch.id, full_name="Owner Uji Harga", username=f"prc-{uuid4().hex[:10]}",
        password_hash="x", role="OWNER", is_active=True,
    )
    db.session.add_all([mandor, owner])
    db.session.flush()
    return branch, client, mandor, owner


def _price(branch, owner, amount, client=None, start=TODAY):
    return set_portion_price(
        branch_id=branch.id, client_id=client.id if client else None,
        price=amount, effective_from=start, created_by=owner.id,
    )


# --- daftar harga ---------------------------------------------------------

def test_tanpa_harga_tidak_ada_penawaran(ctx):
    branch, client, _, _ = _setup(ctx)

    assert quote_price(branch.id, client.id) is None


def test_harga_kontrak_menang_atas_harga_standar(ctx):
    branch, client, _, owner = _setup(ctx)
    _price(branch, owner, 25000)
    _price(branch, owner, 22000, client=client)

    standard = quote_price(branch.id, None)
    contract = quote_price(branch.id, client.id)

    assert (standard.price, standard.source) == (Decimal("25000.00"), SOURCE_STANDARD)
    assert (contract.price, contract.source) == (Decimal("22000.00"), SOURCE_CONTRACT)


def test_harga_terjadwal_belum_berlaku_sampai_tanggalnya(ctx):
    branch, client, _, owner = _setup(ctx)
    _price(branch, owner, 25000)
    _price(branch, owner, 28000, start=TODAY + timedelta(days=3))

    assert quote_price(branch.id, client.id).price == Decimal("25000.00")
    assert quote_price(branch.id, client.id, on_date=TODAY + timedelta(days=3)).price == Decimal("28000.00")


def test_perubahan_harga_menambah_baris_tanpa_mengubah_yang_lama(ctx):
    from app.models.pricing import PortionPrice

    branch, _, _, owner = _setup(ctx)
    first = _price(branch, owner, 25000)
    _price(branch, owner, 27000)

    rows = PortionPrice.query.filter_by(branch_id=branch.id).all()
    assert len(rows) == 2
    assert Decimal(first.price_per_portion) == Decimal("25000.00")
    assert quote_price(branch.id).price == Decimal("27000.00")


def test_harga_nol_atau_bukan_angka_ditolak(ctx):
    branch, _, _, owner = _setup(ctx)

    for bad in ("0", "-5", "abc"):
        with pytest.raises(PricingError):
            _price(branch, owner, bad)


def test_perubahan_harga_tercatat_di_audit_log(ctx):
    from app.models.system import AuditLog

    branch, _, _, owner = _setup(ctx)
    _price(branch, owner, 25000)
    row = _price(branch, owner, 30000)

    log = AuditLog.query.filter_by(event_type="PORTION_PRICE_SET", record_id=row.id).one()
    assert "Rp 30,000" in log.description and "sebelumnya Rp 25,000" in log.description


# --- harga di pesanan -----------------------------------------------------

def test_admin_tidak_bisa_menentukan_harga_sendiri(ctx):
    branch, _, mandor, owner = _setup(ctx)
    _price(branch, owner, 25000)

    price, source, error = resolve_order_price(
        branch_id=branch.id, mandor_id=mandor.id, actor_role="ADMIN", requested_price="1000",
    )

    assert error is None
    assert (price, source) == (Decimal("25000.00"), SOURCE_STANDARD)


def test_owner_boleh_mengubah_harga_satu_pesanan(ctx):
    branch, _, mandor, owner = _setup(ctx)
    _price(branch, owner, 25000)

    price, source, _ = resolve_order_price(
        branch_id=branch.id, mandor_id=mandor.id, actor_role="OWNER", requested_price="30000",
    )
    same, same_source, _ = resolve_order_price(
        branch_id=branch.id, mandor_id=mandor.id, actor_role="OWNER", requested_price="25000",
    )

    assert (price, source) == (Decimal("30000.00"), SOURCE_OWNER)
    assert same_source == SOURCE_STANDARD


def test_pesanan_ditolak_kalau_harga_belum_diatur(ctx):
    branch, _, mandor, _ = _setup(ctx)

    price, _, error = resolve_order_price(branch_id=branch.id, mandor_id=mandor.id, actor_role="ADMIN")

    assert price is None
    assert "belum diatur" in error


def test_harga_di_form_order_mengikuti_client_tiap_sub_client(ctx):
    from app.models.master import Client, Mandor

    branch, client, mandor, owner = _setup(ctx)
    other_client = Client(name=f"Client Lain {uuid4().hex[:6]}", is_active=True)
    ctx.session.add(other_client)
    ctx.session.flush()
    other = Mandor(branch_id=branch.id, client_id=other_client.id, name="Sub Lain", is_active=True)
    ctx.session.add(other)
    ctx.session.flush()
    _price(branch, owner, 25000)
    _price(branch, owner, 21000, client=client)

    quotes = price_quotes_by_mandor(branch.id, [mandor, other])

    assert quotes[mandor.id].price == Decimal("21000.00")
    assert quotes[other.id].price == Decimal("25000.00")


# --- minimal porsi pelanggan umum -----------------------------------------

def test_pelanggan_umum_tanpa_minimal_bawaan_tapi_bisa_diatur(ctx):
    branch, client, _, owner = _setup(ctx, path=PATH_GENERAL)

    assert DEFAULT_MIN_PORTIONS == 1
    assert min_portion_error(branch.id, client, [("siang", 1), ("malam", 0)]) is None
    set_general_min_portions(branch.id, "10", owner.id)
    error = min_portion_error(branch.id, client, [("siang", 12), ("malam", 4)])
    assert "minimal 10 porsi" in error and "malam: 4" in error


def test_client_kontrak_tidak_dibatasi_minimal(ctx):
    branch, client, _, _ = _setup(ctx, path=PATH_CONTRACT)

    assert min_portion_error(branch.id, client, [("siang", 1)]) is None


def test_minimal_porsi_bisa_diubah_per_cabang(ctx):
    branch, client, _, owner = _setup(ctx, path=PATH_GENERAL)

    set_general_min_portions(branch.id, "20", owner.id)

    assert "minimal 20 porsi" in min_portion_error(branch.id, client, [("siang", 15)])
    with pytest.raises(PricingError):
        set_general_min_portions(branch.id, "0", owner.id)


# --- rute input order admin -----------------------------------------------

def _admin_order_setup(db, path):
    from app.models.master import DeliveryLocation, User

    branch, client, mandor, owner = _setup(db, path=path)
    location = DeliveryLocation(mandor_id=mandor.id, location_name="Lokasi Uji Harga", is_active=True)
    admin = User(
        branch_id=branch.id, full_name="Admin Uji Harga", username=f"prc-adm-{uuid4().hex[:8]}",
        password_hash="x", role="ADMIN", is_active=True,
    )
    db.session.add_all([location, admin])
    db.session.flush()
    _price(branch, owner, 25000)
    return mandor, location, admin


def _post_order(app, admin, mandor, location, lunch_qty, price="1"):
    client = app.test_client()
    with client.session_transaction() as session:
        session["_user_id"] = str(admin.id)
        session["_fresh"] = True
    return client.post("/operational/orders/create", data={
        "order_date": (TODAY + timedelta(days=30)).isoformat(),
        "mandor_id": mandor.id,
        "delivery_location_id": location.id,
        "price_per_portion": price,
        "lunch_qty": lunch_qty,
        "dinner_qty": 0,
    })


def test_rute_order_admin_memakai_harga_daftar_bukan_ketikan(app, ctx):
    from app.models.operational import DailyOrderDetail

    app.config["WTF_CSRF_ENABLED"] = False
    mandor, location, admin = _admin_order_setup(ctx, PATH_CONTRACT)

    response = _post_order(app, admin, mandor, location, lunch_qty=5, price="1")

    detail = DailyOrderDetail.query.filter_by(mandor_id=mandor.id).one()
    assert response.status_code == 302
    assert (detail.price_per_portion, detail.price_source) == (Decimal("25000.00"), SOURCE_STANDARD)


def test_rute_order_menolak_pelanggan_umum_di_bawah_minimal(app, ctx):
    from app.models.operational import DailyOrderDetail

    app.config["WTF_CSRF_ENABLED"] = False
    mandor, location, admin = _admin_order_setup(ctx, PATH_GENERAL)

    _post_order(app, admin, mandor, location, lunch_qty=5)

    assert DailyOrderDetail.query.filter_by(mandor_id=mandor.id).count() == 0
