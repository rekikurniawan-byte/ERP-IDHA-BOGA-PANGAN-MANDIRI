"""Bug yang ditemukan gladi pilot satu cabang (2026-09-28), dikunci di sini.

Gladi menjalankan runbook deployment/PILOT_SATU_CABANG.md dari database kosong
lewat halaman-halaman aslinya. Setiap tes di bawah gagal sebelum perbaikannya.
"""
import json
from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from app.services.pricing_service import PricingError, set_delivery_fee, set_portion_price
from tests.test_prepaid_orders import _draft, _pay, _payment_gate, _setup, ctx  # noqa: F401 - fixture

TODAY = date.today()


def _login(app, user):
    client = app.test_client()
    with client.session_transaction() as session:
        session["_user_id"] = str(user.id)
        session["_fresh"] = True
    return client


# --- master: tambah mandor/pengantar crash (NameError _clean_client_code) ----

def test_admin_bisa_tambah_mandor_dan_pengantar_lewat_halaman(app, ctx):
    from app.models.master import Driver, Mandor

    s = _setup(ctx)
    client = _login(app, s.admin)
    name = f"Mandor Gladi {uuid4().hex[:6]}"

    response = client.post("/master/mandors/create", data={"client_id": s.client.id, "name": name, "is_active": "on"})

    assert response.status_code == 302
    assert Mandor.query.filter_by(name=name, branch_id=s.branch.id).count() == 1

    driver_name = f"Pengantar Gladi {uuid4().hex[:6]}"
    response = client.post("/master/drivers/create", data={"name": driver_name, "is_active": "on"})

    assert response.status_code == 302
    assert Driver.query.filter_by(name=driver_name).count() == 1


# --- operasional: mengunci order crash (Decimal tidak bisa jadi JSON) ---------

def test_kunci_order_setelah_dibaca_ulang_dari_database(ctx):
    from app.models.operational import DailyOrder, DailyOrderDetail, OrderSnapshot
    from app.services.operational_service import lock_daily_order

    s = _setup(ctx)
    order = DailyOrder(
        branch_id=s.branch.id, order_number=f"ORD-GLADI-{uuid4().hex[:6]}", order_date=TODAY + timedelta(days=3),
        status="DRAFT", created_by=s.admin.id,
    )
    ctx.session.add(order)
    ctx.session.flush()
    ctx.session.add(DailyOrderDetail(
        daily_order_id=order.id, mandor_id=s.mandor.id, delivery_location_id=s.location.id,
        price_per_portion=Decimal("18000"), lunch_qty=12, dinner_qty=0, total_qty=12,
        lunch_delivery_fee=Decimal("15000"),
    ))
    ctx.session.flush()
    ctx.session.expire_all()  # seperti request baru: kolom Numeric terbaca sebagai Decimal

    ok, message = lock_daily_order(DailyOrder.query.get(order.id), s.admin.id)

    assert ok, message
    snapshot = json.loads(OrderSnapshot.query.filter_by(daily_order_id=order.id).one().snapshot_data)
    assert Decimal(snapshot[0]["price_per_portion"]) == Decimal("18000")
    assert Decimal(snapshot[0]["lunch_delivery_fee"]) == Decimal("15000")


# --- portal: kurang bayar disebut "menunggu Finance" -------------------------

def test_kurang_bayar_yang_sudah_dicatat_disebut_kurang_bayar(ctx):
    from app.models.system import DigitalAttachment

    s = _setup(ctx)
    draft = _draft(ctx, s)  # total 315.000
    _pay(s, draft, 200000)
    ctx.session.add(DigitalAttachment(
        branch_id=s.branch.id, module="PORTAL_PAYMENT", reference_type="PORTAL_ORDER_DRAFT", reference_id=draft.id,
        attachment_type="PAYMENT_PROOF_PAYMENT_CREATED", original_filename="bukti.png", stored_filename=f"{uuid4().hex}.png",
        file_path="x", file_size=1, sha256_hash="0" * 64, uploaded_by=s.portal_customer.id,
    ))
    ctx.session.flush()

    gate = _payment_gate(draft)

    assert gate["status"] == "BLOCKED"
    assert gate["label"] == "Kurang Bayar"
    assert "kurang Rp 115.000" in gate["message"]


# --- invoice order memakai nama sumber yang sama dengan invoice periode ------

def test_item_invoice_order_bersumber_order_detail(ctx):
    from app.models.operational import DailyOrder, DailyOrderDetail
    from app.services.order_invoice_service import build_order_invoice_lines

    s = _setup(ctx)
    order = DailyOrder(
        branch_id=s.branch.id, order_number=f"ORD-GLADI-{uuid4().hex[:6]}", order_date=TODAY,
        status="LOCKED", is_locked=True, created_by=s.admin.id,
    )
    ctx.session.add(order)
    ctx.session.flush()
    detail = DailyOrderDetail(
        daily_order_id=order.id, mandor_id=s.mandor.id, delivery_location_id=s.location.id,
        price_per_portion=Decimal("25000"), lunch_qty=12, dinner_qty=0, total_qty=12,
    )
    ctx.session.add(detail)
    ctx.session.flush()

    lines = build_order_invoice_lines(order, s.mandor.id)

    catering = [line for line in lines if line.get("source_id") == detail.id]
    assert catering and all(line["source_type"] == "ORDER_DETAIL" for line in catering)


# --- cek kesehatan data: pelunasan dari uang muka dihitung -------------------

def test_cek_kesehatan_data_menghitung_pelunasan_dari_uang_muka(ctx):
    from app.models.finance import AdvanceSettlement, Invoice
    from app.services.data_health_service import _invoice_rows

    s = _setup(ctx)
    invoice = Invoice(
        branch_id=s.branch.id, invoice_number=f"INV-GLADI-{uuid4().hex[:6]}", invoice_date=TODAY, due_date=TODAY,
        bill_to_type="CLIENT", client_id=s.client.id, mandor_id=s.mandor.id,
        total_amount=Decimal("315000"), paid_amount=Decimal("315000"),
        remaining_amount=Decimal("0"), status="PAID", source_type="DAILY_ORDER", created_by=s.admin.id,
    )
    ctx.session.add(invoice)
    ctx.session.flush()
    advance = _pay(s, _draft(ctx, s), 315000)
    ctx.session.add(AdvanceSettlement(
        branch_id=s.branch.id, settlement_number=f"ADVS-GLADI-{uuid4().hex[:6]}", advance_id=advance.id,
        settlement_date=TODAY, settlement_type="CLIENT_INVOICE", reference_type="invoices", reference_id=invoice.id,
        amount=Decimal("315000"), created_by=s.admin.id,
    ))
    ctx.session.flush()

    rows = [row for row in _invoice_rows(s.branch.id) if row["check"] == "Payment total vs paid_amount invoice"]

    assert [row["status"] for row in rows] == ["AMAN"]


# --- harga: simpan ulang tidak menumpuk, alasan masuk audit -------------------

def test_simpan_ulang_harga_sama_ditolak_dan_alasan_tercatat(ctx):
    from app.models.pricing import PortionPrice
    from app.models.system import AuditLog

    s = _setup(ctx)  # harga standar 25.000 mulai hari ini
    before = PortionPrice.query.filter_by(branch_id=s.branch.id).count()

    with pytest.raises(PricingError, match="tidak ada yang diubah"):
        set_portion_price(branch_id=s.branch.id, price=25000, effective_from=TODAY, created_by=s.owner.id)
    with pytest.raises(PricingError, match="tidak ada yang diubah"):
        set_delivery_fee(branch_id=s.branch.id, zone_id=s.zone.id, fee=15000, effective_from=TODAY, created_by=s.owner.id)
    assert PortionPrice.query.filter_by(branch_id=s.branch.id).count() == before

    row = set_portion_price(branch_id=s.branch.id, price=27000, effective_from=TODAY, created_by=s.owner.id, notes="harga beras naik")

    log = AuditLog.query.filter_by(event_type="PORTION_PRICE_SET", record_id=row.id).one()
    assert json.loads(log.metadata_json)["reason"] == "harga beras naik"


# --- ops-check: PIC kontrak dan buku kas/bank --------------------------------

def test_ops_check_memperingatkan_client_kontrak_tanpa_pic(ctx):
    from app.services.pricing_service import PATH_CONTRACT
    from app.services.readiness_service import WARN, _contract_pic_check

    s = _setup(ctx, path=PATH_CONTRACT)

    check = _contract_pic_check()

    assert check.status == WARN
    assert s.client.name in check.message or "client kontrak belum punya PIC" in check.message


# --- database baru: COA, cabang, OWNER pertama (flask bootstrap) -------------

def test_bootstrap_aman_diulang_dan_tidak_membuat_owner_kedua(ctx):
    from app.models.accounting import Account
    from app.models.master import Branch, User
    from app.services.bootstrap_service import DEFAULT_CHART_OF_ACCOUNTS, bootstrap_company, ensure_chart_of_accounts
    from app.services.readiness_service import REQUIRED_ACCOUNTS

    ensure_chart_of_accounts()
    assert ensure_chart_of_accounts() == []
    assert set(REQUIRED_ACCOUNTS) <= {code for code, _name, _kind in DEFAULT_CHART_OF_ACCOUNTS}
    assert Account.query.filter(Account.account_code.in_(list(REQUIRED_ACCOUNTS))).count() == len(REQUIRED_ACCOUNTS)

    code = f"BOOT-{uuid4().hex[:6]}"
    owners_before = User.query.filter_by(role="OWNER").count()
    kwargs = dict(branch_code=code, branch_name="Cabang Baru", owner_username=f"own-{uuid4().hex[:6]}",
                  owner_full_name="Owner Baru", owner_password="Rahasia#2026")

    first = bootstrap_company(**kwargs)
    second = bootstrap_company(**kwargs)

    assert first["branch_created"] and not second["branch_created"]
    assert Branch.query.filter_by(code=code).count() == 1
    assert not first["owner_created"] or owners_before == 0
    assert User.query.filter_by(role="OWNER").count() == max(owners_before, 1)
