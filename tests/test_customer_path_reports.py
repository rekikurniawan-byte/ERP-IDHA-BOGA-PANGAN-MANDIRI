"""Dua jalur transaksi, tahap 4: pendapatan dan laporan per jalur.

Keputusan owner 2026-09-27 yang dikunci di sini:
- jalur dikunci di invoice saat dibuat; client pindah jalur tidak mengubahnya;
- pendapatan catering: Kontrak -> 4001, Umum -> 4002, apa pun jenis invoicenya;
  invoice tanpa jalur memakai aturan lama (periode 4001, harian 4002);
- daftar invoice, piutang, dan dashboard OWNER bisa dipisah per jalur.
"""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.accounting_service import resolve_invoice_catering_revenue_account
from app.services.pricing_service import PATH_CONTRACT, PATH_GENERAL, invoice_path_breakdown

TODAY = date.today()


@pytest.fixture
def ctx(app, monkeypatch):
    app.config["WTF_CSRF_ENABLED"] = False
    with app.app_context():
        from app.extensions import db

        monkeypatch.setattr(db.session, "commit", db.session.flush)
        try:
            yield db
        finally:
            db.session.rollback()


def _branch_with_clients(db):
    from app.models.master import Branch, Client, User

    branch = Branch(code=f"RPT-{uuid4().hex[:8]}", name="Cabang Uji Laporan", is_active=True)
    contract = Client(name=f"Kontrak {uuid4().hex[:6]}", is_active=True, customer_path=PATH_CONTRACT)
    general = Client(name=f"Umum {uuid4().hex[:6]}", is_active=True, customer_path=PATH_GENERAL)
    db.session.add_all([branch, contract, general])
    db.session.flush()
    owner = User(
        branch_id=branch.id, full_name="Owner Laporan", username=f"rpt-{uuid4().hex[:8]}",
        password_hash="x", role="OWNER", is_active=True,
    )
    db.session.add(owner)
    db.session.flush()
    return branch, contract, general, owner


def _invoice(db, branch, client, owner, total, paid=0, status="SENT", source="DAILY_ORDER"):
    from app.models.finance import Invoice

    invoice = Invoice(
        branch_id=branch.id, invoice_number=f"INV-RPT-{uuid4().hex[:8]}", invoice_date=TODAY, due_date=TODAY,
        bill_to_type="CLIENT", client_id=client.id, source_type=source, total_amount=total, paid_amount=paid,
        remaining_amount=total - paid, status=status, created_by=owner.id,
    )
    db.session.add(invoice)
    db.session.flush()
    return invoice


# --- jalur dikunci di invoice --------------------------------------------

def test_invoice_baru_mencatat_jalur_client(ctx):
    branch, contract, general, owner = _branch_with_clients(ctx)

    assert _invoice(ctx, branch, contract, owner, 100).customer_path == PATH_CONTRACT
    assert _invoice(ctx, branch, general, owner, 100).customer_path == PATH_GENERAL


def test_client_pindah_jalur_tidak_mengubah_invoice_lama(ctx):
    branch, contract, _, owner = _branch_with_clients(ctx)
    invoice = _invoice(ctx, branch, contract, owner, 100)

    contract.customer_path = PATH_GENERAL
    ctx.session.flush()
    ctx.session.refresh(invoice)

    assert invoice.customer_path == PATH_CONTRACT


# --- akun pendapatan ------------------------------------------------------

@pytest.mark.parametrize("path, source, expected", [
    ("KONTRAK", "DAILY_ORDER", "4001"),
    ("UMUM", "PERIOD_INVOICE", "4002"),
    (None, "PERIOD_INVOICE", "4001"),
    (None, "DAILY_ORDER", "4002"),
])
def test_pendapatan_mengikuti_jalur_lalu_aturan_lama(path, source, expected):
    invoice = SimpleNamespace(customer_path=path, source_type=source, period_start=None, period_end=None, items=[])

    assert resolve_invoice_catering_revenue_account(invoice)["account_code"] == expected


# --- ringkasan ------------------------------------------------------------

def test_ringkasan_per_jalur_mengabaikan_invoice_batal():
    invoices = [
        SimpleNamespace(customer_path="KONTRAK", status="SENT", total_amount=100, paid_amount=40, remaining_amount=60),
        SimpleNamespace(customer_path="UMUM", status="PAID", total_amount=50, paid_amount=50, remaining_amount=0),
        SimpleNamespace(customer_path="UMUM", status="CANCELLED", total_amount=999, paid_amount=0, remaining_amount=999),
        SimpleNamespace(customer_path=None, status="SENT", total_amount=10, paid_amount=0, remaining_amount=10),
    ]

    rows = invoice_path_breakdown(invoices)

    assert (rows["KONTRAK"]["count"], rows["KONTRAK"]["remaining"]) == (1, Decimal("60"))
    assert (rows["UMUM"]["count"], rows["UMUM"]["total"]) == (1, Decimal("50"))
    assert rows["TANPA"]["count"] == 1


def test_dashboard_owner_omzet_kas_dan_piutang_per_jalur(ctx):
    from app.models.finance import AdvanceTransaction, Payment
    from app.services.path_report_service import build_path_summary

    branch, contract, general, owner = _branch_with_clients(ctx)
    contract_invoice = _invoice(ctx, branch, contract, owner, Decimal("1000000"), paid=Decimal("400000"), status="PARTIAL")
    _invoice(ctx, branch, general, owner, Decimal("300000"), paid=Decimal("300000"), status="PAID")
    _invoice(ctx, branch, contract, owner, Decimal("777"), status="CANCELLED")
    ctx.session.add(Payment(
        payment_number=f"PAY-RPT-{uuid4().hex[:8]}", branch_id=branch.id, payment_date=TODAY,
        invoice_id=contract_invoice.id, payment_method="CASH", amount=Decimal("400000"), received_by=owner.id,
    ))
    ctx.session.add(AdvanceTransaction(
        branch_id=branch.id, advance_number=f"ADV-RPT-{uuid4().hex[:8]}", advance_date=TODAY,
        advance_type="CLIENT_DP_RECEIVED", party_type="CLIENT", client_id=general.id, account_type="CASH",
        payment_method="CASH", amount=Decimal("300000"), settled_amount=Decimal("300000"),
        remaining_amount=0, status="SETTLED", created_by=owner.id,
    ))
    ctx.session.flush()

    summary = build_path_summary(branch.id)
    rows = {row["path"]: row for row in summary["rows"]}

    assert rows["KONTRAK"]["revenue"] == Decimal("1000000")
    assert rows["KONTRAK"]["cash_in"] == Decimal("400000")
    assert rows["KONTRAK"]["receivable"] == Decimal("600000")
    assert rows["UMUM"]["revenue"] == Decimal("300000")
    assert rows["UMUM"]["cash_in"] == Decimal("300000")  # uang muka, bukan Payment: tidak dobel
    assert rows["UMUM"]["receivable"] == Decimal("0")


def test_halaman_invoice_bisa_difilter_per_jalur(app, ctx):
    branch, contract, general, owner = _branch_with_clients(ctx)
    contract_invoice = _invoice(ctx, branch, contract, owner, 100)
    general_invoice = _invoice(ctx, branch, general, owner, 100)
    client = app.test_client()
    with client.session_transaction() as session:
        session["_user_id"] = str(owner.id)
        session["_fresh"] = True

    html = client.get("/finance/invoices?path=UMUM").get_data(as_text=True)

    assert general_invoice.invoice_number in html
    assert contract_invoice.invoice_number not in html
    assert "Per Jalur Transaksi" in html


def test_halaman_piutang_dan_dashboard_owner_tampil(app, ctx):
    branch, contract, _, owner = _branch_with_clients(ctx)
    _invoice(ctx, branch, contract, owner, 100)
    client = app.test_client()
    with client.session_transaction() as session:
        session["_user_id"] = str(owner.id)
        session["_fresh"] = True

    assert client.get("/finance/receivables?path=KONTRAK").status_code == 200
    dashboard = client.get("/dashboard/owner")
    assert dashboard.status_code == 200
    assert "Dua Jalur Transaksi" in dashboard.get_data(as_text=True)
