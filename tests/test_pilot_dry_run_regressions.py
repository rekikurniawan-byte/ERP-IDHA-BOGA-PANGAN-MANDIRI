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


# --- portal: pelanggan umum tidak melihat label PT/Mandor --------------------

def test_halaman_pesan_pelanggan_umum_tanpa_label_pt_mandor(app, ctx):
    from app.models.master import User

    s = _setup(ctx)
    username = f"cust-{uuid4().hex[:8]}"
    app.test_client().post("/portal/register", data={
        "full_name": "Ibu Uji", "phone": "081570000999", "username": username, "branch_id": s.branch.id,
        "password": "PilotUser#2026", "password_confirmation": "PilotUser#2026", "location_name": "Rumah Uji",
        "delivery_zone_id": s.zone.id, "address": "Jl. Uji No. 1",
    })
    customer = User.query.filter_by(username=username).one()

    page = _login(app, customer).get("/portal/orders/draft").get_data(as_text=True)

    assert "Rumah Uji" in page
    assert "<span>Perusahaan</span>" not in page
    assert "<dt>Mandor</dt>" not in page and "<dt>Sub Client</dt>" not in page


def test_daftar_dengan_titik_gps_tanpa_zona(app, ctx):
    """Keputusan owner 2026-10-04: titik GPS disimpan sejak mendaftar."""
    from app.models.master import User
    from app.models.system import PortalUserMapping

    s = _setup(ctx)
    base = {
        "full_name": "Pak GPS", "phone": "081570000998", "branch_id": s.branch.id,
        "password": "PilotUser#2026", "password_confirmation": "PilotUser#2026",
        "location_name": "Mes Proyek", "address": "Jl. Lintas Timur Km 3",
    }
    tanpa_titik = app.test_client().post("/portal/register", data={**base, "username": f"gps-{uuid4().hex[:8]}"})
    assert tanpa_titik.status_code == 400

    username = f"gps-{uuid4().hex[:8]}"
    app.test_client().post("/portal/register", data={
        **base, "username": username, "latitude": "-2,9612345", "longitude": "105.7512345", "gps_accuracy": "12.4",
    })
    user = User.query.filter_by(username=username).one()
    location = PortalUserMapping.query.filter_by(user_id=user.id).one().delivery_location

    assert str(location.latitude) == "-2.9612345" and str(location.longitude) == "105.7512345"
    assert location.gps_accuracy_m == 12 and location.gps_updated_at is not None
    assert location.delivery_zone_id is None


# --- warung: cicil hutang pekerja crash (Decimal - float) --------------------

def test_cicil_hutang_warung_pekerja_setelah_dibaca_ulang(ctx):
    from app.models.canteen import CanteenSale, WorkerDebt
    from app.models.master import Worker
    from app.services.canteen_service import pay_worker_debt

    s = _setup(ctx)
    worker = Worker(mandor_id=s.mandor.id, full_name="Pekerja Cicil", status="ACTIVE")
    sale = CanteenSale(
        branch_id=s.branch.id, sale_date=TODAY, sale_type="DEBT", total_amount=15000,
        payment_method="DEBT", buyer_type="REGISTERED_WORKER", created_by=s.admin.id,
    )
    ctx.session.add_all([worker, sale])
    ctx.session.flush()
    debt = WorkerDebt(branch_id=s.branch.id, worker_id=worker.id, sale_id=sale.id, debt_amount=15000, status="UNPAID")
    ctx.session.add(debt)
    ctx.session.flush()
    ctx.session.expire_all()  # debt_amount terbaca sebagai Decimal

    ok, message = pay_worker_debt(
        worker_debt=WorkerDebt.query.get(debt.id), payment_date=TODAY, amount="5000",
        notes=None, created_by=s.admin.id,
    )

    assert ok, message
    assert WorkerDebt.query.get(debt.id).status == "PARTIAL"


# --- SDM: bayar gaji hanya menjurnal, buku bank tidak tercatat ---------------

def test_bayar_gaji_transfer_tercatat_di_buku_bank_rekening_yang_dipilih(ctx):
    from app.models.accounting import Account, Journal, JournalDetail
    from app.models.finance import BankAccount, CashBankTransaction
    from app.models.hr import Payroll, PayrollDetail
    from app.models.master import Employee
    from app.services.accounting_service import create_payroll_payment_journal_for_payroll

    s = _setup(ctx)
    for code, name, kind in (("1003", "Bank 2", "ASSET"), ("2003", "Hutang Gaji", "LIABILITY")):
        if not Account.query.filter_by(account_code=code).first():
            ctx.session.add(Account(account_code=code, account_name=name, account_type=kind, is_active=True))
    ctx.session.flush()
    bank = BankAccount(branch_id=s.branch.id, account_name="Rekening Gaji", bank_name="Mandiri",
                       account_number=f"GJ-{uuid4().hex[:10]}", coa_account_code="1003", is_active=True)
    funding = Journal(journal_number=f"JU-GJ-{uuid4().hex[:6]}", journal_date=TODAY, reference_type="TEST",
                      reference_id=0, description="Saldo uji", created_by=s.owner.id)
    employee = Employee(branch_id=s.branch.id, full_name="Karyawan Uji Gaji", status="ACTIVE")
    ctx.session.add_all([bank, funding, employee])
    ctx.session.flush()
    ctx.session.add(JournalDetail(journal_id=funding.id, account_id=Account.query.filter_by(account_code="1003").one().id,
                                  debit=Decimal("50000000"), credit=0))
    payroll = Payroll(branch_id=s.branch.id, period_month=1, period_year=2000 + int(uuid4().hex[:3], 16) % 900,
                      status="POSTED", created_by=s.owner.id)
    ctx.session.add(payroll)
    ctx.session.flush()
    ctx.session.add(PayrollDetail(payroll_id=payroll.id, employee_id=employee.id, base_salary=3200000, final_salary=3200000))
    ctx.session.flush()

    ok, message, journal = create_payroll_payment_journal_for_payroll(
        payroll=payroll, payment_method="TRANSFER", bank_account_id=bank.id, created_by=s.owner.id)

    assert ok, message
    movement = CashBankTransaction.query.filter_by(reference_type="PAYROLL_PAYMENT", reference_id=payroll.id).one()
    assert (movement.account_type, movement.bank_account_id, movement.transaction_type) == ("BANK", bank.id, "OUT")
    assert movement.amount == Decimal("3200000")
    credited = [d for d in journal.details if d.credit]
    assert [d.account.account_code for d in credited] == ["1003"]


# --- cek buku pembantu: piutang warung eksternal juga ada di 1004 ------------

def test_buku_pembantu_piutang_menghitung_piutang_warung_eksternal(ctx):
    from app.models.canteen import CanteenExternalReceivable, CanteenSale
    from app.services.subledger_check_service import _receivables

    s = _setup(ctx)
    before = _receivables()
    sale = CanteenSale(
        branch_id=s.branch.id, sale_date=TODAY, sale_type="DEBT", total_amount=15000,
        payment_method="DEBT", buyer_type="EXTERNAL_COMPANY_WORKER", created_by=s.admin.id,
    )
    ctx.session.add(sale)
    ctx.session.flush()
    ctx.session.add(CanteenExternalReceivable(
        branch_id=s.branch.id, sale_id=sale.id, buyer_name="Pak Rudi", receivable_amount=15000,
        paid_amount=0, remaining_amount=15000, status="UNPAID", created_by=s.admin.id,
    ))
    ctx.session.flush()

    assert _receivables() - before == Decimal("15000")


# --- tutup buku: laba-rugi bulan yang ditutup tidak boleh jadi nol -----------

def test_ringkasan_laba_rugi_tetap_benar_setelah_tutup_buku(ctx):
    from app.models.accounting import Account, Journal, JournalDetail
    from app.routes.accounting.report_routes import _build_accounting1b_reports_data
    from app.services.accounting_service import generate_journal_number
    from app.services.period_closing_service import post_period_closing

    s = _setup(ctx)
    cash = Account.query.filter_by(account_code="1001").first()
    revenue = Account.query.filter_by(account_type="REVENUE", is_active=True).order_by(Account.account_code).first()
    retained = Account.query.filter_by(account_code="3002", is_active=True).first()
    if not (cash and revenue and retained):
        pytest.skip("COA dasar belum ada di DB tes.")
    start, end = date(2001, 1, 1), date(2001, 1, 31)
    journal = Journal(journal_number=generate_journal_number(start), journal_date=start, reference_type="TEST_SALE",
                      reference_id=900001, description="Penjualan uji", created_by=s.admin.id)
    ctx.session.add(journal)
    ctx.session.flush()
    ctx.session.add_all([
        JournalDetail(journal_id=journal.id, account_id=cash.id, debit=Decimal("250000"), credit=0),
        JournalDetail(journal_id=journal.id, account_id=revenue.id, debit=0, credit=Decimal("250000")),
    ])
    ctx.session.flush()

    post_period_closing(branch_id=s.branch.id, year=2001, month=1, closing_date=end, notes=None, created_by=s.admin.id)
    ctx.session.flush()
    report = _build_accounting1b_reports_data(start, end)

    assert report["revenue_total"] == 250000
    assert report["net_income"] == 250000
    assert report["is_period_balanced"]


# --- rekening bank: jurnal ke akun COA rekening itu, terkunci setelah dipakai --

def test_rekening_bank_memakai_akun_coa_sendiri_dan_terkunci_setelah_dipakai(ctx):
    from app.models.accounting import Account
    from app.models.finance import BankAccount, CashBankTransaction
    from app.services.accounting_service import bank_coa_code
    from app.services.cash_bank_service import cash_bank_coa_code, validate_bank_coa_code

    s = _setup(ctx)
    if not Account.query.filter_by(account_code="1003", is_active=True).first():
        pytest.skip("Akun 1003 Bank 2 belum ada di DB tes.")
    bank = BankAccount(branch_id=s.branch.id, account_name="PT Uji", bank_name="BRI",
                       account_number=f"77{uuid4().int % 10**9}", is_active=True)
    ctx.session.add(bank)
    ctx.session.flush()
    assert bank_coa_code(bank.id) == "1002"

    bank.coa_account_code = validate_bank_coa_code(bank, "1003")
    ctx.session.flush()
    assert bank_coa_code(bank.id) == "1003"
    assert cash_bank_coa_code("BANK", bank.id) == "1003"
    assert cash_bank_coa_code("CASH", bank.id) == "1001"
    with pytest.raises(Exception, match="bukan akun bank"):
        validate_bank_coa_code(bank, "1004")

    ctx.session.add(CashBankTransaction(
        branch_id=s.branch.id, transaction_date=TODAY, account_type="BANK", bank_account_id=bank.id,
        transaction_type="IN", amount=1000, description="uji", reference_type="TEST", reference_id=1,
        created_by=s.admin.id,
    ))
    ctx.session.flush()
    with pytest.raises(Exception, match="terkunci"):
        validate_bank_coa_code(bank, "1002")
    assert validate_bank_coa_code(bank, "1003") == "1003"


# --- aksi atomik bersarang: yang di dalam tidak boleh menutup transaksi luar --

def test_aksi_atomik_bersarang_tidak_menutup_transaksi_luar(ctx):
    """Dulu bayar piutang/hutang manual gagal: transaksi lapangan turunan
    (aksi atomik di dalam) meng-commit sesi sehingga aksi luar tertutup."""
    from sqlalchemy import text

    from app.services.atomic_transaction_service import atomic_business_action

    with atomic_business_action(module="TEST", action="OUTER", description="luar", audit_success=False):
        with atomic_business_action(module="TEST", action="INNER", description="dalam", audit_success=False):
            ctx.session.execute(text("SELECT 1"))
        assert ctx.session.execute(text("SELECT 1")).scalar() == 1
