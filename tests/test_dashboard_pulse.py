"""Dashboard Owner/Admin & 360° Pelanggan (UI desktop internal, 2026-10-13).

Dikunci di sini karena versi sebelumnya mengarang angka (tren "+15.7%" tertulis
mati, grafik dari rumus, nilai cadangan Rp128.450.000):
- KPI hanya dari tabel asli; tanpa pembanding -> delta None, bukan persen karangan;
- kas masuk dari usaha tidak menghitung saldo awal, modal owner, koreksi, pindah buku;
- Saran Sistem & Peringatan hanya muncul kalau kondisinya terjadi;
- 360° dan pencarian global dibatasi cabang pengguna.
"""
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from app.utils.clock import today_wib
from tests.test_prepaid_orders import _setup, ctx  # noqa: F401 - fixture


def _client(app, user):
    client = app.test_client()
    with client.session_transaction() as session:
        session["_user_id"] = str(user.id)
        session["_fresh"] = True
    return client


def _invoice(db, s, total, remaining=None, days_ago=0, due_in=7, status="UNPAID", branch_id=None):
    from app.models.finance import Invoice

    day = today_wib() - timedelta(days=days_ago)
    invoice = Invoice(
        branch_id=branch_id or s.branch.id, invoice_number=f"INV-PULSE-{uuid4().hex[:8]}", invoice_date=day,
        due_date=day + timedelta(days=due_in), bill_to_type="CLIENT", client_id=s.client.id,
        client_name_snapshot=s.client.name, total_amount=total,
        remaining_amount=total if remaining is None else remaining, status=status, created_by=s.owner.id,
    )
    db.session.add(invoice)
    db.session.flush()
    return invoice


def _cash_in(db, s, amount, reference_type, days_ago=0):
    from app.models.finance import CashBankTransaction

    db.session.add(CashBankTransaction(
        branch_id=s.branch.id, transaction_date=today_wib() - timedelta(days=days_ago), account_type="CASH",
        transaction_type="IN", amount=amount, description=f"Uji {reference_type}", reference_type=reference_type,
        created_by=s.owner.id,
    ))
    db.session.flush()


def test_kpi_dari_data_asli_tanpa_tren_karangan(ctx):
    from app.services.dashboard_pulse_service import build_owner_pulse

    s = _setup(ctx)
    _invoice(ctx, s, 500000)
    _invoice(ctx, s, 250000, status="CANCELLED")
    _cash_in(ctx, s, 300000, "PAYMENT")
    _cash_in(ctx, s, 30000000, "OPENING_BALANCE")
    _cash_in(ctx, s, 2000000, "OWNER_CAPITAL")

    pulse = build_owner_pulse(s.branch.id, {"reminders": []})
    kpis = {k["key"]: k for k in pulse["kpis"]}

    assert kpis["omzet"]["value"] == 500000.0
    assert kpis["kas"]["value"] == 300000.0
    assert kpis["omzet"]["delta"] is None and kpis["kas"]["delta"] is None
    assert kpis["piutang"]["value"] == 500000.0
    assert pulse["trend"]["series"][0]["data"][-1] == 500000.0


def test_cabang_kosong_tidak_memunculkan_saran_atau_angka_palsu(ctx):
    from app.services.dashboard_pulse_service import build_owner_pulse

    s = _setup(ctx)
    pulse = build_owner_pulse(s.branch.id, {"reminders": []})

    assert all(k["value"] == 0 for k in pulse["kpis"])
    assert pulse["suggestions"] == []
    assert pulse["alerts"] == []


def test_tunggakan_lebih_14_hari_jadi_saran_dan_peringatan(ctx):
    from app.services.dashboard_pulse_service import build_owner_pulse

    s = _setup(ctx)
    _invoice(ctx, s, 400000, days_ago=40, due_in=7)  # lewat tempo 33 hari

    pulse = build_owner_pulse(s.branch.id, {"reminders": []})

    assert pulse["aging"]["overdue_count"] == 1
    assert pulse["aging"]["late14"][0]["days"] == 33
    assert any(row["endpoint"] == "credit.overview" for row in pulse["suggestions"])
    assert any(row["endpoint"] == "finance.receivables" for row in pulse["alerts"])


def test_dashboard_owner_dan_admin_tampil(app, ctx):
    from app.models.master import User

    s = _setup(ctx)
    _invoice(ctx, s, 500000)
    admin = User.query.get(s.admin.id)

    owner_html = _client(app, s.owner).get("/dashboard/owner").get_data(as_text=True)
    assert "Ringkasan Bisnis" in owner_html and "Dua Jalur Transaksi" in owner_html
    assert "+15.7%" not in owner_html and "Klien Menunggak" not in owner_html

    admin_res = _client(app, admin).get("/dashboard/admin")
    assert admin_res.status_code == 200
    assert "Kendali Hari Ini" in admin_res.get_data(as_text=True)


def test_360_pelanggan_hanya_data_cabang_sendiri(app, ctx):
    from app.models.master import Branch
    from app.services.client_360_service import build_client_360

    s = _setup(ctx)
    other = Branch(code=f"OTH-{uuid4().hex[:6]}", name="Cabang Lain", is_active=True)
    ctx.session.add(other)
    ctx.session.flush()
    _invoice(ctx, s, 400000)
    _invoice(ctx, s, 900000, branch_id=other.id)

    data = build_client_360(s.client.id, s.branch.id)
    assert data["stats"]["receivable"] == 400000.0
    assert [inv.total_amount for inv in data["invoices"]] == [Decimal("400000.00")]

    page = _client(app, s.owner).get(f"/master/clients/{s.client.id}")
    assert page.status_code == 200
    assert s.client.name in page.get_data(as_text=True)


def test_pencarian_global_dibatasi_cabang_dan_label_indonesia(app, ctx):
    from app.models.master import Branch

    s = _setup(ctx)
    other = Branch(code=f"OTH-{uuid4().hex[:6]}", name="Cabang Lain", is_active=True)
    ctx.session.add(other)
    ctx.session.flush()
    mine = _invoice(ctx, s, 100000)
    theirs = _invoice(ctx, s, 100000, branch_id=other.id)

    data = _client(app, s.owner).get("/search?q=INV-PULSE").get_json()
    numbers = [item["title"] for group in data["results"] if group["category"] == "Invoice" for item in group["items"]]

    assert mine.invoice_number in numbers and theirs.invoice_number not in numbers
    badges = [item["badge"] for group in data["results"] for item in group["items"]]
    assert "UNPAID" not in badges
