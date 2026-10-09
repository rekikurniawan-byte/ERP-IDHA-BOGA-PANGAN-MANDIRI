"""Fase 8: pajak. Keputusan owner 2026-10-09 yang dikunci di sini:

- semua pajak mati bawaan; PBJT baru dipungut setelah NPWPD + tanggal mulai diisi;
- PBJT ditambahkan DI ATAS harga, dijurnal ke 2010 Hutang PBJT (bukan pendapatan);
- rezim PPh dipilih di pengaturan; PP 55 untuk PT maks. 3 tahun pajak lalu normal;
- potongan PPh oleh pelanggan = pintu pelunasan ketiga (sisa invoice, jurnal, janji bayar);
- setoran pajak: kas/bank keluar + jurnal sesuai jenis + NTPN wajib.
"""
from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.accounting import Account
from app.models.credit import PARTY_CLIENT
from app.models.finance import CashBankTransaction, Invoice, InvoiceItem
from app.models.tax import WITHHOLDING_PPH23, WITHHOLDING_PPH_FINAL
from app.services import tax_service
from app.services.accounting_service import post_invoice_journal_or_raise
from app.services.credit_control_service import broken_promises
from app.services.invoice_payment_history_service import payment_events
from app.services.tax_service import (
    REGIME_NORMAL,
    REGIME_PP55,
    TaxError,
    apply_pbjt_to_invoice,
    build_tax_month,
    effective_regime,
    get_tax_settings,
    record_tax_payment,
    record_withholding,
    save_tax_settings,
    tax_print_note,
)
from app.utils.clock import today_wib

from tests.test_sharia_credit import _file, _fixtures, _journal_lines, _promise, ctx  # noqa: F401

TODAY = today_wib()


def _ensure_tax_accounts():
    for code, name, kind in (
        ("1001", "Kas", "ASSET"), ("1004", "Piutang Usaha", "ASSET"), ("1009", "Pajak Dibayar di Muka", "ASSET"),
        ("2010", "Hutang PBJT", "LIABILITY"), ("4001", "Pendapatan Catering Proyek", "REVENUE"),
        ("5014", "Beban PPh Final", "EXPENSE"),
    ):
        if not Account.query.filter_by(account_code=code).first():
            db.session.add(Account(account_code=code, account_name=name, account_type=kind, is_active=True))
    db.session.flush()


def _settings(f, **values):
    form = {
        "tax.regime": "", "tax.pp55_first_year": "", "tax.pp55_certificate_number": "",
        "tax.pp55_certificate_valid_until": "", "tax.pbjt_rate": "10", "tax.pbjt_region": "Kab. Ogan Komering Ilir",
        "tax.npwpd": "", "tax.pbjt_effective_from": "", "tax.pbjt_due_day": "15",
    }
    form.update(values)
    return save_tax_settings(f.branch.id, form, f.owner)


def _sales_invoice(f, *, amount=Decimal("1000000"), invoice_date=None, with_pbjt=True):
    invoice_date = invoice_date or TODAY
    invoice = Invoice(
        branch_id=f.branch.id, invoice_number=f"INV-TX-{uuid4().hex[:10]}", invoice_date=invoice_date,
        due_date=invoice_date + timedelta(days=7), bill_to_type="CLIENT", client_id=f.client.id,
        total_amount=amount, paid_amount=0, remaining_amount=amount, status="DRAFT",
        source_type="PERIOD_INVOICE", created_by=f.owner.id,
    )
    db.session.add(invoice)
    db.session.flush()
    db.session.add(InvoiceItem(invoice_id=invoice.id, item_type="CATERING", description="Porsi", qty=40,
                               unit_price=amount / 40, subtotal=amount, source_type="ORDER_DETAIL",
                               source_id=int(uuid4().int % 10**8)))
    db.session.flush()
    if with_pbjt:
        apply_pbjt_to_invoice(invoice)
    post_invoice_journal_or_raise(invoice, f.owner.id)
    return invoice


def test_everything_is_off_by_default(ctx):
    _ensure_tax_accounts()
    f = _fixtures()
    settings = get_tax_settings(f.branch.id)
    assert settings["regime"] == "" and settings["pbjt_enabled"] is False
    invoice = _sales_invoice(f)
    assert invoice.total_amount == Decimal("1000000")
    assert InvoiceItem.query.filter_by(invoice_id=invoice.id, item_type="PBJT").count() == 0
    assert tax_print_note(invoice) is None


def test_settings_guard_owner_npwpd_and_rate(ctx):
    _ensure_tax_accounts()
    f = _fixtures()
    with pytest.raises(TaxError, match="OWNER"):
        save_tax_settings(f.branch.id, {"tax.regime": REGIME_PP55}, f.admin)
    with pytest.raises(TaxError, match="NPWPD"):
        _settings(f, **{"tax.pbjt_enabled": "1", "tax.pbjt_effective_from": TODAY.isoformat()})
    with pytest.raises(TaxError, match="10 persen"):
        _settings(f, **{"tax.pbjt_rate": "12"})
    with pytest.raises(TaxError, match="tahun pertama"):
        _settings(f, **{"tax.regime": REGIME_PP55})


def test_pbjt_added_on_top_and_booked_as_liability_not_revenue(ctx):
    _ensure_tax_accounts()
    f = _fixtures()
    _settings(f, **{"tax.pbjt_enabled": "1", "tax.npwpd": "P.2.000123.OKI", "tax.pbjt_effective_from": TODAY.isoformat()})

    before = _sales_invoice(f, invoice_date=TODAY - timedelta(days=1))   # sebelum tanggal mulai: tidak berubah
    assert before.total_amount == Decimal("1000000")

    invoice = _sales_invoice(f)
    assert invoice.total_amount == Decimal("1100000") and invoice.remaining_amount == Decimal("1100000")
    assert InvoiceItem.query.filter_by(invoice_id=invoice.id, item_type="PBJT").one().subtotal == Decimal("100000")
    lines = _journal_lines("INVOICE", invoice.id)
    assert lines["1004"] == (Decimal("1100000"), Decimal("0"))
    assert lines["4001"] == (Decimal("0"), Decimal("1000000"))          # pendapatan tetap
    assert lines["2010"] == (Decimal("0"), Decimal("100000"))           # PBJT = hutang
    assert apply_pbjt_to_invoice(invoice) == 0                          # tidak dobel


def test_pp55_ends_after_three_tax_years():
    settings = {"regime": REGIME_PP55, "pp55_last_year": 2028}
    assert effective_regime(settings, date(2028, 12, 31)) == REGIME_PP55
    assert effective_regime(settings, date(2029, 1, 1)) == REGIME_NORMAL
    assert effective_regime({"regime": "", "pp55_last_year": None}, date(2026, 10, 1)) == ""


def test_pp55_withholding_is_third_payment_door(ctx):
    _ensure_tax_accounts()
    f = _fixtures()
    _settings(f, **{"tax.regime": REGIME_PP55, "tax.pp55_first_year": "2026", "tax.pp55_certificate_number": "KET-PP55-001"})
    invoice = _sales_invoice(f, invoice_date=TODAY - timedelta(days=10))
    invoice.due_date = TODAY - timedelta(days=3)
    _promise(f, invoice, TODAY - timedelta(days=1), TODAY - timedelta(days=2))
    assert "Surat Keterangan No. KET-PP55-001" in tax_print_note(invoice)

    suggestion = tax_service.suggest_withholding(invoice)
    assert suggestion["type"] == WITHHOLDING_PPH_FINAL and suggestion["amount"] == Decimal("5000")

    with pytest.raises(TaxError, match="bukti potong"):
        record_withholding(invoice, {"withholding_type": WITHHOLDING_PPH_FINAL, "amount": "5000"}, None, f.admin)
    with pytest.raises(TaxError, match="melebihi"):
        record_withholding(invoice, {"withholding_type": WITHHOLDING_PPH_FINAL, "amount": "2000000",
                                     "certificate_number": "BP-1"}, None, f.admin)

    row = record_withholding(invoice, {
        "withholding_type": WITHHOLDING_PPH_FINAL, "amount": "5000", "certificate_number": "BP-0001",
        "withheld_on": (TODAY - timedelta(days=1)).isoformat(),
    }, _file("bukti_potong.png"), f.admin)
    assert row.attachment_id is not None
    assert invoice.remaining_amount == Decimal("995000") and invoice.status == "PARTIAL"
    lines = _journal_lines("TAX_WITHHOLDING", row.id)
    assert lines["5014"] == (Decimal("5000"), Decimal("0")) and lines["1004"] == (Decimal("0"), Decimal("5000"))
    assert [e["payment_method"] for e in payment_events([invoice.id])] == ["POTONG_PPH_FINAL_05"]
    assert broken_promises(f.branch.id, PARTY_CLIENT, f.client.id, TODAY) == []


def test_normal_regime_pph23_is_tax_credit(ctx):
    _ensure_tax_accounts()
    f = _fixtures()
    _settings(f, **{"tax.regime": REGIME_NORMAL})
    invoice = _sales_invoice(f)
    suggestion = tax_service.suggest_withholding(invoice)
    assert suggestion["type"] == WITHHOLDING_PPH23 and suggestion["amount"] == Decimal("20000")
    row = record_withholding(invoice, {"withholding_type": WITHHOLDING_PPH23, "amount": "20000",
                                       "certificate_number": "BP-23-1"}, None, f.owner)
    lines = _journal_lines("TAX_WITHHOLDING", row.id)
    assert lines["1009"] == (Decimal("20000"), Decimal("0"))


def test_tax_payment_needs_ntpn_and_posts_cash_out(ctx):
    _ensure_tax_accounts()
    f = _fixtures()
    db.session.add(CashBankTransaction(branch_id=f.branch.id, transaction_date=TODAY, account_type="CASH",
                                       transaction_type="IN", amount=500000, description="Saldo uji", created_by=f.owner.id))
    db.session.flush()
    form = {"tax_type": "PBJT", "amount": "100000", "paid_on": TODAY.isoformat(), "period_year": TODAY.year,
            "period_month": TODAY.month, "account_type": "CASH"}
    with pytest.raises(TaxError, match="NTPN"):
        record_tax_payment(f.branch.id, form, None, f.admin)
    row = record_tax_payment(f.branch.id, {**form, "reference_number": "NTPN-123"}, None, f.admin)
    ledger = db.session.get(CashBankTransaction, row.cash_bank_transaction_id)
    assert ledger.transaction_type == "OUT"
    lines = _journal_lines("TAX_PAYMENT", row.id)
    assert lines["2010"] == (Decimal("100000"), Decimal("0")) and lines["1001"] == (Decimal("0"), Decimal("100000"))


def test_monthly_report_pp55_due_minus_withheld_and_paid(ctx):
    _ensure_tax_accounts()
    f = _fixtures()
    _settings(f, **{"tax.regime": REGIME_PP55, "tax.pp55_first_year": "2026", "tax.pp55_certificate_number": "KET-1",
                    "tax.pbjt_enabled": "1", "tax.npwpd": "NPWPD-1", "tax.pbjt_effective_from": TODAY.replace(day=1).isoformat()})
    before = build_tax_month(f.branch.id, TODAY.year, TODAY.month)
    invoice = _sales_invoice(f, amount=Decimal("2000000"))
    record_withholding(invoice, {"withholding_type": WITHHOLDING_PPH_FINAL, "amount": "3000",
                                 "certificate_number": "BP-X"}, None, f.owner)
    report = build_tax_month(f.branch.id, TODAY.year, TODAY.month)

    assert report["gross"] - before["gross"] == Decimal("2000000")              # PBJT tidak masuk omzet
    assert report["pph_final_due"] - before["pph_final_due"] == Decimal("10000")
    assert report["withheld_final"] - before["withheld_final"] == Decimal("3000")
    assert report["pbjt_collected"] - before["pbjt_collected"] == Decimal("200000")
    row = next(r for r in report["reconciliation"] if r["invoice"].id == invoice.id)
    assert row["pbjt"] == Decimal("200000") and row["withheld"] == Decimal("3000")


def test_tax_reminders_job_registered_at_0830(ctx):
    from app.services.scheduler_service import get_job

    job = get_job("tax_reminders")
    assert job is not None and job["schedule"] == {"type": "daily", "time": "08:30"}
