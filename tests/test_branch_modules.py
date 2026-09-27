"""Modul per cabang: Warung dan Hutang Pekerja.

Keputusan owner 2026-09-27 yang dikunci di sini:
- dua saklar terpisah; Hutang Pekerja hanya bisa nyala kalau Warung nyala;
- cabang baru (tanpa pengaturan) = mati;
- modul tidak bisa dimatikan selama masih ada uang terbuka di dalamnya;
- modul mati = halaman ditolak dengan pesan, menu hilang, data tetap.
"""
from datetime import date
from uuid import uuid4

import pytest

from app.services.branch_module_service import (
    WARUNG,
    WORKER_DEBT,
    enable_modules_for_branch,
    module_blockers,
    module_change_errors,
    module_enabled,
)

ON = {"module_warung": "1", "module_worker_debt": "1"}


@pytest.fixture
def ctx(app):
    """Tanpa commit ke test_db: semua data uji cukup di-flush lalu di-rollback."""
    app.config["WTF_CSRF_ENABLED"] = False
    with app.app_context():
        from app.extensions import db
        from app.services.ttl_cache_service import clear_cache

        clear_cache("company_settings")
        try:
            yield db
        finally:
            db.session.rollback()
            clear_cache("company_settings")


def _branch(db, *names):
    from app.models.master import Branch

    branch = Branch(code=f"MOD-{uuid4().hex[:8]}", name="Cabang Uji Modul", is_active=True)
    db.session.add(branch)
    db.session.flush()
    if names:
        enable_modules_for_branch(branch.id, names)
        db.session.flush()
    return branch


def _user(db, branch, role="OWNER"):
    from app.models.master import User

    user = User(
        branch_id=branch.id,
        full_name=f"Uji Modul {role}",
        username=f"modul-{uuid4().hex[:10]}",
        password_hash="x",
        role=role,
        is_active=True,
    )
    db.session.add(user)
    db.session.flush()
    return user


def _worker_debt(db, branch, user, status="UNPAID"):
    from app.models.canteen import CanteenSale, WorkerDebt
    from app.models.master import Client, Mandor, Worker

    client = Client(name="Client Uji Modul", is_active=True)
    db.session.add(client)
    db.session.flush()
    mandor = Mandor(branch_id=branch.id, client_id=client.id, name="Sub Uji Modul", is_active=True)
    db.session.add(mandor)
    db.session.flush()
    worker = Worker(mandor_id=mandor.id, full_name="Pekerja Uji Modul", status="ACTIVE")
    sale = CanteenSale(
        branch_id=branch.id, sale_date=date.today(), sale_type="DEBT", total_amount=15000,
        payment_method="DEBT", buyer_type="REGISTERED_WORKER", created_by=user.id,
    )
    db.session.add_all([worker, sale])
    db.session.flush()
    debt = WorkerDebt(branch_id=branch.id, worker_id=worker.id, sale_id=sale.id, debt_amount=15000, status=status)
    db.session.add(debt)
    db.session.flush()
    return debt


def _invoice_with_debt(db, branch, user, debt, status):
    from app.models.finance import Invoice, InvoiceItem

    invoice = Invoice(
        branch_id=branch.id, invoice_number=f"INV-MOD-{uuid4().hex[:8]}", invoice_date=date.today(),
        due_date=date.today(), bill_to_type="MANDOR", total_amount=15000, remaining_amount=15000,
        status=status, created_by=user.id,
    )
    db.session.add(invoice)
    db.session.flush()
    db.session.add(InvoiceItem(
        invoice_id=invoice.id, item_type="WARUNG_DEBT", description="Hutang warung uji",
        qty=1, unit_price=15000, subtotal=15000, source_type="WORKER_DEBT", source_id=debt.id,
    ))
    db.session.flush()
    return invoice


def _login(client, user):
    with client.session_transaction() as session:
        session["_user_id"] = str(user.id)
        session["_fresh"] = True


# --- saklar ---------------------------------------------------------------

def test_cabang_baru_tanpa_pengaturan_semua_modul_mati(ctx):
    branch = _branch(ctx)

    assert not module_enabled(WARUNG, branch.id)
    assert not module_enabled(WORKER_DEBT, branch.id)


def test_hutang_pekerja_ikut_mati_kalau_warung_mati(ctx):
    branch = _branch(ctx, WORKER_DEBT)

    assert not module_enabled(WORKER_DEBT, branch.id)

    enable_modules_for_branch(branch.id, [WARUNG])
    ctx.session.flush()

    assert module_enabled(WARUNG, branch.id)
    assert module_enabled(WORKER_DEBT, branch.id)


def test_hutang_pekerja_tanpa_warung_ditolak(ctx):
    branch = _branch(ctx)

    errors = module_change_errors(branch.id, {"module_worker_debt": "1"})

    assert any("hanya bisa nyala kalau Warung" in error for error in errors)


# --- pengaman: tidak boleh mati selama ada uang terbuka -------------------

def test_hutang_pekerja_belum_ditagih_menahan_saklar(ctx):
    branch = _branch(ctx, WARUNG, WORKER_DEBT)
    _worker_debt(ctx, branch, _user(ctx, branch))

    errors = module_change_errors(branch.id, {"module_warung": "1"})

    assert len(errors) == 1
    assert "1 hutang" in errors[0] and "belum masuk invoice" in errors[0]


def test_hutang_yang_sudah_masuk_invoice_aktif_tidak_menahan(ctx):
    branch = _branch(ctx, WARUNG, WORKER_DEBT)
    user = _user(ctx, branch)
    debt = _worker_debt(ctx, branch, user)
    _invoice_with_debt(ctx, branch, user, debt, status="SENT")

    assert module_blockers(WORKER_DEBT, branch.id) == []


def test_invoice_yang_dibatalkan_tidak_dihitung_menagih(ctx):
    branch = _branch(ctx, WARUNG, WORKER_DEBT)
    user = _user(ctx, branch)
    debt = _worker_debt(ctx, branch, user)
    _invoice_with_debt(ctx, branch, user, debt, status="CANCELLED")

    assert len(module_blockers(WORKER_DEBT, branch.id)) == 1


def test_hutang_lunas_tidak_menahan(ctx):
    branch = _branch(ctx, WARUNG, WORKER_DEBT)
    _worker_debt(ctx, branch, _user(ctx, branch), status="PAID")

    assert module_change_errors(branch.id, {}) == []


def test_piutang_warung_dan_kas_harian_open_menahan_warung(ctx):
    from app.models.canteen import CanteenExternalReceivable, CanteenSale, CashDaily

    branch = _branch(ctx, WARUNG)
    user = _user(ctx, branch)
    sale = CanteenSale(
        branch_id=branch.id, sale_date=date.today(), sale_type="DEBT", total_amount=20000,
        payment_method="DEBT", buyer_type="GENERAL_BUYER", created_by=user.id,
    )
    ctx.session.add(sale)
    ctx.session.flush()
    ctx.session.add_all([
        CanteenExternalReceivable(
            branch_id=branch.id, sale_id=sale.id, buyer_name="Pembeli Uji", receivable_amount=20000,
            remaining_amount=20000, status="UNPAID", created_by=user.id,
        ),
        CashDaily(branch_id=branch.id, cash_date=date.today(), status="OPEN", created_by=user.id),
    ])
    ctx.session.flush()

    errors = module_change_errors(branch.id, {})

    assert len(errors) == 2
    assert any("piutang warung" in error for error in errors)
    assert any("kas harian" in error for error in errors)


def test_menyimpan_pengaturan_ditolak_tanpa_menulis_apa_pun(ctx):
    from app.models.master import BranchSetting
    from app.services.branch_module_service import ModuleChangeError
    from app.services.company_settings_service import save_company_settings

    branch = _branch(ctx, WARUNG, WORKER_DEBT)
    _worker_debt(ctx, branch, _user(ctx, branch))

    with pytest.raises(ModuleChangeError):
        save_company_settings(branch.id, {"company_name": "Nama Baru", "module_warung": "1"})

    assert BranchSetting.query.filter_by(branch_id=branch.id, setting_key="company_name").first() is None


# --- halaman --------------------------------------------------------------

def test_halaman_warung_ditolak_dengan_pesan_kalau_modul_mati(app, ctx):
    branch = _branch(ctx)
    client = app.test_client()
    _login(client, _user(ctx, branch))

    response = client.get("/canteen/", follow_redirects=True)

    assert response.status_code == 200
    assert "Modul Warung tidak aktif di cabang ini" in response.get_data(as_text=True)


def test_halaman_warung_terbuka_kalau_modul_nyala(app, ctx):
    branch = _branch(ctx, WARUNG)
    client = app.test_client()
    _login(client, _user(ctx, branch))

    response = client.get("/canteen/")

    assert response.status_code == 200


def test_master_pekerja_butuh_modul_hutang_pekerja(app, ctx):
    branch = _branch(ctx, WARUNG)
    client = app.test_client()
    _login(client, _user(ctx, branch))

    response = client.get("/master/workers")

    assert response.status_code == 302


# Satu pengguna per tes: Flask-Login menyimpan pengguna di g selama konteks app.
def test_menu_warung_dan_pekerja_hilang_kalau_modul_mati(app, ctx):
    client = app.test_client()
    _login(client, _user(ctx, _branch(ctx)))

    html = client.get("/master/").get_data(as_text=True)

    assert "/canteen/" not in html
    assert "/master/workers" not in html


def test_menu_warung_dan_pekerja_tampil_kalau_modul_nyala(app, ctx):
    client = app.test_client()
    _login(client, _user(ctx, _branch(ctx, WARUNG, WORKER_DEBT)))

    html = client.get("/master/").get_data(as_text=True)

    assert "/canteen/" in html
    assert "/master/workers" in html


def test_penjualan_hutang_pekerja_ditolak_di_layanan_kalau_modul_mati(ctx):
    from app.services.canteen_service import create_canteen_sale

    branch = _branch(ctx, WARUNG)

    ok, message, sale = create_canteen_sale(
        branch_id=branch.id, sale_date=date.today(), payment_method="DEBT",
        buyer_type="REGISTERED_WORKER", worker_id=1, item_rows=[], created_by=1,
    )

    assert not ok and sale is None
    assert "tidak aktif" in message
