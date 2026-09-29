"""Saldo awal satu pintu.

Keputusan owner 2026-09-28 (poin 1-5) yang dikunci di sini:
- satu halaman: kas & bank, piutang lama per nota, hutang supplier lama, stok
  dengan harga, aset dengan akumulasi penyusutan, hutang lain; modal otomatis;
- "Kunci" membuat semua buku pembantu dan satu jurnal dari angka yang sama,
  jadi buku pembantu = buku besar;
- piutang lama bisa dibayar seperti invoice biasa tapi bukan pendapatan;
- stok awal ikut harga rata-rata; aset lama melanjutkan penyusutan dari akumulasinya;
- "Buka Kembali" hanya selama belum ada transaksi sejak tanggal mulai;
  sesudahnya koreksi beralasan (OWNER) yang mengubah buku pembantu + jurnalnya.
"""
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from werkzeug.security import generate_password_hash

TODAY = date.today()
START = TODAY - timedelta(days=3)
PASSWORD = "Rahasia#2026"


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


def _setup(db):
    from app.models.finance import BankAccount
    from app.models.master import Branch, Client, Item, Mandor, Supplier, User
    from app.services.bootstrap_service import ensure_chart_of_accounts

    ensure_chart_of_accounts()
    branch = Branch(code=f"SA-{uuid4().hex[:8]}", name="Cabang Uji Saldo Awal", is_active=True)
    db.session.add(branch)
    db.session.flush()
    users = {
        role: User(branch_id=branch.id, full_name=f"{role} Uji", username=f"sa-{role.lower()}-{uuid4().hex[:8]}",
                   password_hash=generate_password_hash(PASSWORD), role=role, is_active=True)
        for role in ("OWNER", "ADMIN")
    }
    client = Client(name=f"PT Lama {uuid4().hex[:6]}", phone="0811", is_active=True, customer_path="KONTRAK")
    item = Item(item_code=f"SA-{uuid4().hex[:8]}", item_name="Beras Awal", category="RAW_MATERIAL", unit="kg",
                is_stock_tracked=True, is_active=True)
    bank = BankAccount(branch_id=branch.id, account_name="PT Uji", bank_name="BCA", account_number=uuid4().hex[:12], is_active=True)
    supplier = Supplier(branch_id=branch.id, supplier_code=f"SUP-{uuid4().hex[:8]}", supplier_name=f"Toko Lama {uuid4().hex[:6]}",
                        supplier_type="GENERAL", is_active=True)
    db.session.add_all([*users.values(), client, item, bank, supplier])
    db.session.flush()
    mandor = Mandor(branch_id=branch.id, client_id=client.id, name=f"Mandor {uuid4().hex[:6]}", is_active=True)
    db.session.add(mandor)
    db.session.flush()
    return SimpleNamespace(branch=branch, client=client, mandor=mandor, item=item, bank=bank, supplier=supplier,
                           **{role.lower(): user for role, user in users.items()})


def _fill(s):
    """Draf lengkap: harta 5.000.000 + 20.000.000 + 1.500.000 + 1.400.000 + (12.000.000 - 2.000.000);
    hutang 2.000.000 + 3.000.000 -> modal 32.900.000 (neraca 39.900.000)."""
    from app.services.opening_balance_service import change_line, get_or_create_opening, set_start_date

    opening = get_or_create_opening(s.branch.id, s.owner.id)
    set_start_date(opening, START.isoformat())
    for raw in (
        {"account_type": "CASH", "amount": "5.000.000"},
        {"account_type": "BANK", "bank_account_id": s.bank.id, "amount": "20000000"},
    ):
        change_line(opening, "cashbank", None, raw, user=s.owner)
    change_line(opening, "receivables", None, {"client_id": s.client.id, "mandor_id": s.mandor.id, "reference": "NOTA-77",
                                               "invoice_date": (START - timedelta(days=20)).isoformat(), "amount": "1500000"}, user=s.owner)
    change_line(opening, "payables", None, {"supplier_id": s.supplier.id, "reference": "F-9",
                                            "bill_date": (START - timedelta(days=5)).isoformat(), "amount": "2000000"}, user=s.owner)
    change_line(opening, "stock", None, {"item_id": s.item.id, "qty": "100", "unit_cost": "14000"}, user=s.owner)
    change_line(opening, "assets", None, {"name": "Kompor Besar", "category": "KITCHEN_EQUIPMENT", "purchase_date": "2024-01-10",
                                          "purchase_value": "12000000", "accumulated": "2000000", "useful_life_years": "5"}, user=s.owner)
    change_line(opening, "liabilities", None, {"account_code": "2001", "description": "Pinjaman koperasi", "amount": "3000000"}, user=s.owner)
    return opening


def _lines(journal):
    from app.models.accounting import Account, JournalDetail

    return {
        Account.query.get(row.account_id).account_code: Decimal(str(row.debit)) - Decimal(str(row.credit))
        for row in JournalDetail.query.filter_by(journal_id=journal.id).all()
    }


def _gaps():
    from app.services.subledger_check_service import subledger_lines

    return {line.label: line.difference for line in subledger_lines()}


def _login(app, user):
    client = app.test_client()
    with client.session_transaction() as session:
        session["_user_id"] = str(user.id)
        session["_fresh"] = True
    return client


# --- draf dan penguncian --------------------------------------------------

def test_neraca_draf_menghitung_modal_otomatis(ctx):
    from app.services.opening_balance_service import balance_preview, load_payload

    s = _setup(ctx)
    preview = balance_preview(load_payload(_fill(s)))

    assert preview["equity"] == Decimal("32900000")
    assert preview["total_debit"] == preview["total_credit"] == Decimal("39900000")
    assert not preview["problems"]


def test_kunci_membuat_semua_buku_dan_satu_jurnal_yang_sama(ctx):
    from app.models.accounting import FixedAsset, FixedAssetDepreciation
    from app.models.finance import CashBankTransaction, Invoice, SupplierBill
    from app.models.logistics import StockOpeningBalance
    from app.services.opening_balance_service import lock_opening

    before = _gaps()
    s = _setup(ctx)
    opening = _fill(s)

    journal = lock_opening(opening, user=s.owner)

    assert opening.status == "LOCKED"
    assert _lines(journal) == {
        "1001": Decimal("5000000"), "1002": Decimal("20000000"), "1004": Decimal("1500000"), "1006": Decimal("1400000"),
        "1101": Decimal("12000000"), "2101": Decimal("-2000000"), "2001": Decimal("-3000000"), "2002": Decimal("-2000000"),
        "3001": Decimal("-32900000"),
    }
    assert CashBankTransaction.query.filter_by(branch_id=s.branch.id, reference_type="OPENING_BALANCE").count() == 2
    invoice = Invoice.query.filter_by(branch_id=s.branch.id, source_type="OPENING_BALANCE").one()
    assert (invoice.mandor_id, Decimal(str(invoice.remaining_amount))) == (s.mandor.id, Decimal("1500000"))
    bill = SupplierBill.query.filter_by(branch_id=s.branch.id).one()
    assert bill.procurement_id is None and Decimal(str(bill.remaining_amount)) == Decimal("2000000")
    assert Decimal(str(StockOpeningBalance.query.filter_by(branch_id=s.branch.id).one().unit_cost)) == Decimal("14000")
    asset = FixedAsset.query.filter_by(branch_id=s.branch.id).one()
    assert Decimal(str(asset.book_value)) == Decimal("10000000")
    assert FixedAssetDepreciation.query.filter_by(fixed_asset_id=asset.id).one().journal_id == journal.id
    assert _gaps() == before


def test_kunci_ditolak_tanpa_tanggal_mulai_atau_kalau_modal_minus(ctx):
    from app.services.opening_balance_service import OpeningBalanceError, change_line, get_or_create_opening, lock_opening, set_start_date

    s = _setup(ctx)
    opening = get_or_create_opening(s.branch.id, s.owner.id)
    change_line(opening, "cashbank", None, {"account_type": "CASH", "amount": "100000"}, user=s.owner)
    with pytest.raises(OpeningBalanceError, match="tanggal mulai"):
        lock_opening(opening, user=s.owner)

    set_start_date(opening, START.isoformat())
    change_line(opening, "liabilities", None, {"account_code": "2006", "amount": "500000"}, user=s.owner)
    with pytest.raises(OpeningBalanceError, match="modal pemilik jadi minus"):
        lock_opening(opening, user=s.owner)


# --- sesudah dikunci ------------------------------------------------------

def test_piutang_lama_dibayar_seperti_invoice_biasa_tanpa_pendapatan(app, ctx):
    from app.models.accounting import Journal
    from app.models.finance import Invoice, Payment
    from app.services.opening_balance_service import lock_opening

    s = _setup(ctx)
    opening_journal = lock_opening(_fill(s), user=s.owner)
    invoice = Invoice.query.filter_by(branch_id=s.branch.id, source_type="OPENING_BALANCE").one()

    _login(app, s.admin).post(f"/finance/invoices/{invoice.id}/payments/create", data={
        "idempotency_key": uuid4().hex, "payment_date": TODAY.isoformat(), "payment_method": "CASH", "amount": "1500000", "notes": "lunas",
    })

    payment = Payment.query.filter_by(invoice_id=invoice.id).one()
    journal = Journal.query.filter_by(reference_type="PAYMENT", reference_id=payment.id).one()
    assert _lines(journal) == {"1001": Decimal("1500000"), "1004": Decimal("-1500000")}
    assert invoice.status == "PAID"
    assert not any(code.startswith("4") for code in _lines(opening_journal))  # bukan pendapatan


def test_hutang_lama_dibayar_dari_daftar_hutang_supplier(app, ctx):
    from app.models.accounting import Journal
    from app.models.finance import SupplierBill, SupplierPayment
    from app.services.opening_balance_service import lock_opening

    s = _setup(ctx)
    lock_opening(_fill(s), user=s.owner)
    bill = SupplierBill.query.filter_by(branch_id=s.branch.id).one()

    _login(app, s.owner).post(f"/finance/supplier-bills/{bill.id}/payments/create", data={
        "idempotency_key": uuid4().hex, "payment_date": TODAY.isoformat(), "payment_method": "CASH", "amount": "500000",
    })

    payment = SupplierPayment.query.filter_by(supplier_bill_id=bill.id).one()
    assert _lines(Journal.query.filter_by(reference_type="SUPPLIER_PAYMENT", reference_id=payment.id).one()) == {
        "2002": Decimal("500000"), "1001": Decimal("-500000")}
    assert Decimal(str(bill.remaining_amount)) == Decimal("1500000")


def test_stok_awal_ikut_harga_rata_rata(ctx):
    from app.services.opening_balance_service import lock_opening
    from app.services.stock_journal_service import item_average_cost
    from app.services.stock_service import create_stock_movement, get_item_stock

    s = _setup(ctx)
    lock_opening(_fill(s), user=s.owner)

    assert get_item_stock(s.branch.id, s.item.id) == Decimal("100")
    assert item_average_cost(s.item.id) == Decimal("14000")
    ok, message, _ = create_stock_movement(branch_id=s.branch.id, item_id=s.item.id, movement_date=TODAY, movement_type="OUT",
                                           reference_type="PEMAKAIAN_PRODUKSI", qty=10, notes="uji", created_by=s.owner.id)
    assert ok, message


def test_aset_lama_melanjutkan_penyusutan_sampai_batasnya(ctx):
    from app.models.accounting import FixedAsset
    from app.services.fixed_asset_depreciation_service import configure_asset_depreciation, post_asset_depreciation
    from app.services.opening_balance_service import change_line, get_or_create_opening, lock_opening, set_start_date

    s = _setup(ctx)
    opening = get_or_create_opening(s.branch.id, s.owner.id)
    set_start_date(opening, START.isoformat())
    change_line(opening, "assets", None, {"name": "Freezer", "category": "KITCHEN_EQUIPMENT", "purchase_date": "2023-01-01",
                                          "purchase_value": "12000000", "accumulated": "11900000"}, user=s.owner)
    lock_opening(opening, user=s.owner)
    asset = FixedAsset.query.filter_by(branch_id=s.branch.id).one()
    configure_asset_depreciation(branch_id=s.branch.id, asset_id=asset.id, depreciation_start_date=START, useful_life_months=12,
                                 residual_value=0, accumulated_account_code="2101", status="CONFIGURED", notes=None, created_by=s.owner.id)
    period_end = START.replace(day=28) + timedelta(days=4)

    entry = post_asset_depreciation(branch_id=s.branch.id, asset_id=asset.id, period_year=period_end.year,
                                    period_month=period_end.month, created_by=s.owner.id)

    assert Decimal(str(entry.amount)) == Decimal("100000")  # sisa 12 jt - 11,9 jt, bukan 1 jt/bulan
    assert Decimal(str(asset.accumulated_depreciation)) == Decimal("12000000")


def test_buka_kembali_menghapus_semua_dan_kunci_ulang(ctx):
    from app.models.accounting import FixedAsset, Journal
    from app.models.finance import Invoice
    from app.services.opening_balance_service import lock_opening, reopen_opening

    before = _gaps()
    s = _setup(ctx)
    opening = _fill(s)
    lock_opening(opening, user=s.owner)

    reopen_opening(opening, user=s.owner, reason="salah ketik saldo bank")

    assert opening.status == "DRAFT"
    assert Invoice.query.filter_by(branch_id=s.branch.id).count() == 0
    assert FixedAsset.query.filter_by(branch_id=s.branch.id).count() == 0
    assert Journal.query.filter_by(reference_type="SALDO_AWAL", reference_id=opening.id).count() == 0
    assert _gaps() == before
    lock_opening(opening, user=s.owner)
    assert opening.status == "LOCKED"
    assert _gaps() == before


def test_sesudah_ada_transaksi_hanya_koreksi_beralasan(app, ctx):
    from app.models.accounting import Journal, OpeningBalanceCorrection
    from app.models.finance import CashBankOpeningBalance, Invoice
    from app.services.opening_balance_service import (
        OpeningBalanceError,
        change_line,
        later_activity,
        load_payload,
        lock_opening,
        reopen_opening,
    )

    before = _gaps()
    s = _setup(ctx)
    opening = _fill(s)
    lock_opening(opening, user=s.owner)
    invoice = Invoice.query.filter_by(branch_id=s.branch.id, source_type="OPENING_BALANCE").one()
    _login(app, s.admin).post(f"/finance/invoices/{invoice.id}/payments/create", data={
        "idempotency_key": uuid4().hex, "payment_date": TODAY.isoformat(), "payment_method": "CASH", "amount": "500000",
    })
    assert later_activity(opening)

    with pytest.raises(OpeningBalanceError, match="tidak bisa dibuka kembali"):
        reopen_opening(opening, user=s.owner, reason="coba buka")
    with pytest.raises(OpeningBalanceError, match="hanya bisa dilakukan OWNER"):
        change_line(opening, "cashbank", None, {"account_type": "CASH", "amount": "5200000"}, user=s.admin, reason="kas kurang catat")
    with pytest.raises(OpeningBalanceError, match="alasan koreksi"):
        change_line(opening, "cashbank", None, {"account_type": "CASH", "amount": "5200000"}, user=s.owner)
    receivable_key = load_payload(opening)["receivables"][0]["key"]
    with pytest.raises(OpeningBalanceError, match="sudah dibayar"):
        change_line(opening, "receivables", receivable_key, {"client_id": s.client.id, "mandor_id": s.mandor.id, "reference": "NOTA-77",
                                                             "invoice_date": (START - timedelta(days=20)).isoformat(), "amount": "400000"},
                    user=s.owner, reason="nota ternyata lebih kecil")

    change_line(opening, "cashbank", None, {"account_type": "CASH", "amount": "5200000"}, user=s.owner, reason="kas di brankas belum dihitung")

    correction = OpeningBalanceCorrection.query.filter_by(opening_balance_id=opening.id).one()
    assert _lines(Journal.query.get(correction.journal_id)) == {"1001": Decimal("200000"), "3001": Decimal("-200000")}
    assert Decimal(str(CashBankOpeningBalance.query.filter_by(branch_id=s.branch.id, account_key="CASH").one().amount)) == Decimal("5200000")
    assert _gaps() == before


def test_halaman_saldo_awal_dan_kunci_lewat_password(app, ctx):
    from app.services.opening_balance_service import get_opening

    s = _setup(ctx)
    _fill(s)
    owner = _login(app, s.owner)

    page = owner.get("/accounting/opening-balance")
    assert page.status_code == 200
    assert "NOTA-77" in page.get_data(as_text=True) and "Kompor Besar" in page.get_data(as_text=True)

    owner.post("/accounting/opening-balance/lock", data={"sensitive_reason": "saldo awal sesuai hitung fisik", "confirm_password": "salah"})
    assert get_opening(s.branch.id).status == "DRAFT"
    owner.post("/accounting/opening-balance/lock", data={"sensitive_reason": "saldo awal sesuai hitung fisik", "confirm_password": PASSWORD})
    assert get_opening(s.branch.id).status == "LOCKED"
    assert owner.get("/accounting/opening-balance").status_code == 200


def test_halaman_lama_dialihkan_ke_saldo_awal(app, ctx):
    s = _setup(ctx)
    owner = _login(app, s.owner)

    for path in ("/finance/cash-bank-opening-balances", "/logistics/opening-balances"):
        response = owner.get(path)
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/accounting/opening-balance")


def test_ops_check_gagal_selama_saldo_awal_belum_dikunci(ctx):
    from app.services.opening_balance_service import lock_opening
    from app.services.readiness_service import FAIL, PASS, _branch_checks

    s = _setup(ctx)

    def opening_check():
        return next(check for check in _branch_checks([s.branch.id]) if check.name.endswith("saldo awal"))

    assert opening_check().status == FAIL
    lock_opening(_fill(s), user=s.owner)
    assert opening_check().status == PASS
