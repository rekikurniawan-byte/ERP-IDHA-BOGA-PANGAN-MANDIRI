"""Kasir cepat warung (keputusan owner 2026-10-13).

- satu layar: pilih orang -> ketuk barang -> TUNAI / QRIS / HUTANG;
- harga selalu dari master barang di server, bukan dari browser;
- ketuk dobel / kirim ulang tidak menyimpan dua kali;
- batas hutang per pekerja = peringatan saja (tetap tersimpan);
- pekerja bisa cicil langsung di kasir, dialokasikan ke hutang terlama;
- hutang yang sudah masuk invoice mandor tidak bisa dibayar di warung (cegah tagih dobel);
- ADMIN_OPERASIONAL boleh membuka kasir, tapi bukan ringkasan/daftar hutang warung.
"""
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from tests.test_prepaid_orders import _setup, ctx  # noqa: F401 - fixture


def _warung(db, s, limit="50000"):
    from app.models.finance import BankAccount
    from app.models.accounting import Account
    from app.models.master import BranchSetting, Item, User, Worker
    from app.services.branch_module_service import WARUNG, WORKER_DEBT, enable_modules_for_branch
    from app.services.ttl_cache_service import clear_cache

    if not Account.query.filter_by(account_code="1002").first():
        db.session.add(Account(account_code="1002", account_name="Bank", account_type="ASSET", is_active=True))
    enable_modules_for_branch(s.branch.id, [WARUNG, WORKER_DEBT])
    db.session.add(BranchSetting(branch_id=s.branch.id, setting_key="warung.worker_debt_limit", setting_value=limit))
    suffix = uuid4().hex[:6].upper()
    kopi = Item(item_code=f"POS-K-{suffix}", item_name=f"Kopi Uji {suffix}", category="MERCHANDISE", unit="PCS",
                selling_price=5000, is_stock_tracked=False, is_active=True)
    mie = Item(item_code=f"POS-M-{suffix}", item_name=f"Mie Uji {suffix}", category="MERCHANDISE", unit="PCS",
               selling_price=8000, is_stock_tracked=False, is_active=True)
    worker = Worker(mandor_id=s.mandor.id, full_name=f"Budi Uji {suffix}", status="ACTIVE")
    bank = BankAccount(branch_id=s.branch.id, account_name="PT Uji", bank_name="BSI", account_number=f"POS{suffix}", is_active=True)
    ops = User(branch_id=s.branch.id, full_name="Ops Uji", username=f"pos-ops-{uuid4().hex[:8]}",
               password_hash="x", role="ADMIN_OPERASIONAL", is_active=True)
    db.session.add_all([kopi, mie, worker, bank, ops])
    db.session.flush()
    clear_cache("company_settings")
    return kopi, mie, worker, ops


def _client(app, user):
    client = app.test_client()
    with client.session_transaction() as session:
        session["_user_id"] = str(user.id)
        session["_fresh"] = True
    return client


def _checkout(client, **body):
    body.setdefault("key", uuid4().hex)
    return client.post("/canteen/quick/checkout", json=body)


def test_harga_dari_master_bukan_dari_browser(app, ctx):
    from app.models.canteen import CanteenSale

    s = _setup(ctx)
    kopi, mie, worker, ops = _warung(ctx, s)
    res = _checkout(_client(app, ops), method="CASH", cash_received=50000,
                    cart=[{"item_id": kopi.id, "qty": 2, "price": 1}, {"item_id": mie.id, "qty": 1}])

    data = res.get_json()
    assert res.status_code == 200 and data["ok"], data
    assert data["total"] == 18000 and data["change"] == 32000
    sale = CanteenSale.query.get(data["sale_id"])
    assert sale.total_amount == Decimal("18000.00") and sale.payment_method == "CASH"
    assert sale.branch_id == s.branch.id


def test_kirim_ulang_kunci_sama_tidak_menyimpan_dua_kali(app, ctx):
    from app.models.canteen import CanteenSale

    s = _setup(ctx)
    kopi, _, worker, ops = _warung(ctx, s)
    client = _client(app, ops)
    key = uuid4().hex
    first = _checkout(client, key=key, method="DEBT", worker_id=worker.id, cart=[{"item_id": kopi.id, "qty": 1}]).get_json()
    second = _checkout(client, key=key, method="DEBT", worker_id=worker.id, cart=[{"item_id": kopi.id, "qty": 1}]).get_json()

    assert first["ok"] and second["ok"] and second.get("replayed")
    assert first["sale_id"] == second["sale_id"]
    assert CanteenSale.query.filter_by(branch_id=s.branch.id).count() == 1


def test_lewat_batas_hutang_hanya_peringatan(app, ctx):
    from app.models.canteen import WorkerDebt

    s = _setup(ctx)
    _, mie, worker, ops = _warung(ctx, s, limit="20000")
    data = _checkout(_client(app, ops), method="DEBT", worker_id=worker.id, cart=[{"item_id": mie.id, "qty": 3}]).get_json()

    assert data["ok"] and data["over_limit"] is True and data["debt_after"] == 24000
    assert WorkerDebt.query.filter_by(worker_id=worker.id).count() == 1


def test_hutang_wajib_pilih_pekerja_atau_nama(app, ctx):
    s = _setup(ctx)
    kopi, _, _, ops = _warung(ctx, s)
    res = _checkout(_client(app, ops), method="DEBT", cart=[{"item_id": kopi.id, "qty": 1}])

    assert res.status_code == 422 and not res.get_json()["ok"]


def test_cicil_hutang_dialokasikan_ke_yang_terlama(app, ctx):
    from app.models.canteen import WorkerDebt

    s = _setup(ctx)
    kopi, mie, worker, ops = _warung(ctx, s)
    client = _client(app, ops)
    _checkout(client, method="DEBT", worker_id=worker.id, cart=[{"item_id": kopi.id, "qty": 1}])  # 5.000
    _checkout(client, method="DEBT", worker_id=worker.id, cart=[{"item_id": mie.id, "qty": 1}])   # 8.000

    paid = client.post("/canteen/quick/pay-debt", json={"key": uuid4().hex, "worker_id": worker.id, "amount": 7000, "method": "CASH"}).get_json()

    assert paid["ok"], paid
    assert paid["remaining"] == 6000
    debts = WorkerDebt.query.filter_by(worker_id=worker.id).order_by(WorkerDebt.id.asc()).all()
    assert [d.status for d in debts] == ["PAID", "PARTIAL"]

    over = client.post("/canteen/quick/pay-debt", json={"key": uuid4().hex, "worker_id": worker.id, "amount": 9000, "method": "CASH"})
    assert over.status_code == 422


def test_hutang_yang_sudah_masuk_invoice_mandor_tidak_bisa_dibayar_di_warung(app, ctx):
    from app.models.canteen import WorkerDebt
    from app.models.finance import Invoice, InvoiceItem
    from app.services.canteen_service import pay_worker_debt

    s = _setup(ctx)
    kopi, _, worker, ops = _warung(ctx, s)
    client = _client(app, ops)
    _checkout(client, method="DEBT", worker_id=worker.id, cart=[{"item_id": kopi.id, "qty": 1}])
    debt = WorkerDebt.query.filter_by(worker_id=worker.id).one()
    invoice = Invoice(branch_id=s.branch.id, invoice_number=f"INV-POS-{uuid4().hex[:8]}", invoice_date=date.today(),
                      due_date=date.today(), bill_to_type="MANDOR", total_amount=5000, remaining_amount=5000,
                      status="UNPAID", created_by=s.admin.id)
    ctx.session.add(invoice)
    ctx.session.flush()
    ctx.session.add(InvoiceItem(invoice_id=invoice.id, item_type="WARUNG_DEBT", description="Hutang warung",
                                qty=1, unit_price=5000, subtotal=5000, source_type="WORKER_DEBT", source_id=debt.id))
    ctx.session.flush()

    ok, message = pay_worker_debt(debt, date.today(), 5000, None, s.admin.id)
    assert not ok and "invoice" in message

    res = client.post("/canteen/quick/pay-debt", json={"key": uuid4().hex, "worker_id": worker.id, "amount": 5000, "method": "CASH"})
    assert res.status_code == 422

    invoice.status = "CANCELLED"
    ctx.session.flush()
    ok, message = pay_worker_debt(debt, date.today(), 5000, None, s.admin.id)
    assert ok, message


def test_admin_operasional_buka_kasir_tapi_bukan_ringkasan_warung(app, ctx):
    s = _setup(ctx)
    _, _, worker, ops = _warung(ctx, s)
    client = _client(app, ops)

    page = client.get("/canteen/quick")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "Kasir Warung" in html and worker.full_name in html
    assert "Warung" in html and "storefront" in html  # tab bawah aplikasi HP
    assert client.get("/canteen/", follow_redirects=False).status_code in (302, 403)
