"""PPh 21 karyawan terintegrasi modul pajak pusat (PP 58/2023, PMK 168/2023, UU HPP).

Dikunci:
1. kategori TER dari status PTKP;
2. titik uji tabel TER A/B/C sesuai Lampiran PP 58/2023;
3. Desember dihitung tahunan (biaya jabatan, PTKP, PKP dibulatkan ribuan, Pasal 17) dikurangi Jan–Nov;
4. karyawan keluar (disetujui) = masa terakhir tahunan; pengajuan yang belum disetujui tidak;
5. alur penuh: buat penggajian → PPh 21 TER → jurnal 5004/2003/2011 seimbang; ditanggung perusahaan 5015;
6. PPh 21 nonaktif = gaji sama persis seperti sebelumnya;
7. batas 50% denda dari upah setelah PPh 21;
8. setoran PPH21 mendebit 2011; build_tax_month menghitung terutang/disetor/sisa;
9. slip memuat baris PPh 21; 1721-A1 tahunan.
"""
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from tests.test_workforce_module import _contract, _setup, ctx  # noqa: F401


def _tax(db, branch_id, **values):
    """Tulis pengaturan pajak langsung (tanpa form) untuk tes."""
    from app.models.master import BranchSetting

    for key, value in values.items():
        key = "tax." + key
        row = BranchSetting.query.filter_by(branch_id=branch_id, setting_key=key).first()
        if row:
            row.setting_value = value
        else:
            db.session.add(BranchSetting(branch_id=branch_id, setting_key=key, setting_value=value))
    db.session.flush()


def _lines(reference_type, reference_id):
    from app.models.accounting import Account, Journal, JournalDetail

    journal = Journal.query.filter_by(reference_type=reference_type, reference_id=reference_id).one()
    totals = {}
    for row in JournalDetail.query.filter_by(journal_id=journal.id).all():
        code = Account.query.get(row.account_id).account_code
        debit, credit = totals.get(code, (Decimal("0"), Decimal("0")))
        totals[code] = (debit + Decimal(str(row.debit)), credit + Decimal(str(row.credit)))
    return totals


def _history(db, s, employee, months, gross, tax, year=2026):
    from app.models.hr import Payroll, PayrollDetail

    for month in months:
        payroll = Payroll(branch_id=s.branch.id, period_month=month, period_year=year, status="POSTED", created_by=s.admin.id)
        db.session.add(payroll)
        db.session.flush()
        db.session.add(PayrollDetail(
            payroll_id=payroll.id, employee_id=employee.id, base_salary=gross, bonus=0, deduction=0,
            tax_bruto=gross, pph21_amount=tax, pph21_method="TER", pph21_borne_by="KARYAWAN",
            final_salary=gross - tax,
        ))
    db.session.flush()


def test_kategori_ter_dari_ptkp():
    from app.services.tax_pph21_service import get_ter_category

    assert [get_ter_category(x) for x in ("TK/0", "TK/1", "K/0")] == ["A"] * 3
    assert [get_ter_category(x) for x in ("TK/2", "TK/3", "K/1", "K/2")] == ["B"] * 4
    assert get_ter_category("K/3") == "C"
    assert get_ter_category(None) == "A" and get_ter_category("ngawur") == "A"


def test_titik_uji_tabel_ter_pp58():
    """Baris dari Lampiran PP 58/2023 (TER A/B/C)."""
    from app.services.tax_pph21_service import TER_TABLE_A, TER_TABLE_B, TER_TABLE_C, lookup_ter_rate

    assert (len(TER_TABLE_A), len(TER_TABLE_B), len(TER_TABLE_C)) == (44, 40, 41)
    cases = [
        ("A", "5400000", "0"), ("A", "5400001", "0.25"), ("A", "8000000", "1.50"),  # A: 7.500.001–8.550.000 = 1,5%
        ("A", "10000000", "2.00"), ("A", "1400000001", "34"),
        ("B", "6200000", "0"), ("B", "8000000", "1.00"),  # B: 7.300.001–9.200.000 = 1%
        ("B", "9200001", "1.50"), ("B", "21850001", "9.00"), ("B", "1405000001", "34"),
        ("C", "6600000", "0"), ("C", "9000000", "1.25"),  # C: 8.850.001–9.800.000 = 1,25%
        ("C", "24000000", "9.00"), ("C", "965000001", "33"),
    ]
    for category, gross, rate in cases:
        assert lookup_ter_rate(category, Decimal(gross)) == Decimal(rate), (category, gross)


def test_desember_dihitung_tahunan(ctx):
    from app.models.hr import Payroll, PayrollDetail
    from app.services.tax_pph21_service import compute_payroll_detail_pph21

    s = _setup(ctx)
    _tax(ctx, s.branch.id, pph21_enabled="1", pph21_borne_by="KARYAWAN", pph21_effective_from="2026-01-01")
    s.budi.ptkp_status = "TK/0"
    _history(ctx, s, s.budi, range(1, 12), Decimal("8000000"), Decimal("120000"))  # TER A 1,5%
    december = Payroll(branch_id=s.branch.id, period_month=12, period_year=2026, status="DRAFT", created_by=s.admin.id)
    ctx.session.add(december)
    ctx.session.flush()
    detail = PayrollDetail(payroll_id=december.id, employee_id=s.budi.id, base_salary=Decimal("8000000"), bonus=0, deduction=0, final_salary=0)
    ctx.session.add(detail)
    ctx.session.flush()

    # 96 jt - biaya jabatan 4,8 jt - PTKP 54 jt = PKP 37,2 jt x 5% = 1.860.000; sudah dipotong 11 x 120.000.
    assert compute_payroll_detail_pph21(detail, december) == Decimal("540000")
    assert detail.pph21_method == "TAHUNAN" and detail.tax_bruto == Decimal("8000000")


def test_keluar_disetujui_masa_terakhir_pengajuan_tidak(ctx):
    from app.models.hr import Payroll, PayrollDetail
    from app.services.employee_exit_service import approve_exit, create_exit
    from app.services.tax_pph21_service import compute_payroll_detail_pph21

    s = _setup(ctx)
    _tax(ctx, s.branch.id, pph21_enabled="1")
    _contract(s, s.budi, start=date(2026, 1, 1), end=date(2026, 12, 31))
    june = Payroll(branch_id=s.branch.id, period_month=6, period_year=2026, status="DRAFT", created_by=s.admin.id)
    ctx.session.add(june)
    ctx.session.flush()
    detail = PayrollDetail(payroll_id=june.id, employee_id=s.budi.id, base_salary=Decimal("3000000"), bonus=0, deduction=0, final_salary=0)
    ctx.session.add(detail)
    ctx.session.flush()

    row = create_exit(s.budi, exit_type="RESIGN", reason_code="KELUARGA", notice_date=date(2026, 5, 20),
                      effective_date=date(2026, 6, 19), user_id=s.admin.id)
    compute_payroll_detail_pph21(detail, june)
    assert detail.pph21_method == "TER"  # pengajuan belum disetujui
    approve_exit(row, s.owner, handover_done=True)
    compute_payroll_detail_pph21(detail, june)
    assert detail.pph21_method == "TAHUNAN" and detail.pph21_amount == 0  # di bawah PTKP


def test_alur_penuh_penggajian_ter_dan_jurnal(ctx):
    from app.services.accounting_service import create_payroll_journal_for_payroll
    from app.services.hr_service import generate_payroll
    from app.services.payslip_service import build_payslip

    s = _setup(ctx)
    _tax(ctx, s.branch.id, pph21_enabled="1", pph21_borne_by="KARYAWAN", pph21_effective_from="2026-01-01")
    s.budi.ptkp_status = "K/1"  # kategori B
    _contract(s, s.budi, salary="8000000")
    ok, message, payroll = generate_payroll(s.branch.id, 8, 2026, s.admin.id)
    assert ok, message
    detail = next(d for d in payroll.details if d.employee_id == s.budi.id)
    # TER B 8 jt = 1% -> 80.000
    assert (detail.ter_category, detail.ter_rate, detail.pph21_amount) == ("B", Decimal("1.00"), Decimal("80000"))
    assert detail.final_salary == Decimal("7920000")
    slip = build_payslip(detail)
    assert any(row["label"].startswith("PPh 21 (TER kategori B") for row in slip["deductions"])
    assert slip["gross"] - slip["total_deduction"] == slip["net"]

    payroll.status = "FINAL"
    ok, message, _ = create_payroll_journal_for_payroll(payroll, s.admin.id)
    assert ok, message
    lines = _lines("PAYROLL", payroll.id)
    debit = sum(d for d, _ in lines.values())
    credit = sum(c for _, c in lines.values())
    assert debit == credit
    assert lines["2011"] == (0, Decimal("80000"))
    assert lines["5004"][0] == Decimal("8000000") + Decimal(str(sum(d.final_salary for d in payroll.details if d.employee_id != s.budi.id)))


def test_ditanggung_perusahaan_gaji_utuh_dan_beban_5015(ctx):
    from app.services.accounting_service import create_payroll_journal_for_payroll
    from app.services.hr_service import generate_payroll

    s = _setup(ctx)
    _tax(ctx, s.branch.id, pph21_enabled="1", pph21_borne_by="PERUSAHAAN")
    _contract(s, s.budi, salary="8000000")  # TK/0 bawaan -> TER A 1,5% = 120.000
    ok, message, payroll = generate_payroll(s.branch.id, 8, 2026, s.admin.id)
    assert ok, message
    detail = next(d for d in payroll.details if d.employee_id == s.budi.id)
    assert detail.pph21_amount == Decimal("120000") and detail.final_salary == Decimal("8000000")
    assert "TK/0" in (detail.pph21_note or "")  # PTKP kosong -> peringatan
    payroll.status = "FINAL"
    ok, message, _ = create_payroll_journal_for_payroll(payroll, s.admin.id)
    assert ok, message
    lines = _lines("PAYROLL", payroll.id)
    assert lines["5015"] == (Decimal("120000"), 0) and lines["2011"] == (0, Decimal("120000"))
    assert sum(d for d, _ in lines.values()) == sum(c for _, c in lines.values())


def test_pph21_nonaktif_gaji_sama_persis(ctx):
    from app.services.hr_service import generate_payroll

    s = _setup(ctx)
    _contract(s, s.budi, salary="8000000")
    ok, message, payroll = generate_payroll(s.branch.id, 8, 2026, s.admin.id)
    assert ok, message
    detail = next(d for d in payroll.details if d.employee_id == s.budi.id)
    assert detail.final_salary == Decimal("8000000") and not detail.pph21_amount and detail.tax_bruto is None


def test_batas_denda_50_persen_dari_upah_setelah_pph21(ctx):
    from app.services.employee_charge_service import approve_charge, create_charge
    from app.services.hr_service import generate_payroll

    s = _setup(ctx)
    _tax(ctx, s.branch.id, pph21_enabled="1", pph21_borne_by="KARYAWAN")
    _contract(s, s.budi, salary="8000000")
    charge = create_charge(employee=s.budi, charge_type="DENDA", amount=9000000, clause="Pasal 5", description="Uji", created_by=s.admin.id)
    approve_charge(charge, s.owner)
    ok, message, payroll = generate_payroll(s.branch.id, 8, 2026, s.admin.id)
    detail = next(d for d in payroll.details if d.employee_id == s.budi.id)
    # (8.000.000 - 120.000) x 50% = 3.940.000
    assert detail.charge_deduction == Decimal("3940000") and detail.final_salary == Decimal("3940000")


def test_setoran_pph21_dan_laporan_masa(ctx):
    from app.models.accounting import Account, Journal, JournalDetail
    from app.models.hr import Payroll, PayrollDetail
    from app.services.owner_capital_service import record_owner_capital
    from app.services.tax_service import TAX_PAYMENT_PPH21, build_tax_month, record_tax_payment

    s = _setup(ctx)
    _tax(ctx, s.branch.id, pph21_enabled="1")
    record_owner_capital(branch_id=s.branch.id, kind="SETOR", transaction_date=date(2026, 8, 1), account_type="CASH",
                         bank_account_id=None, amount=1000000, notes="modal uji", created_by=s.owner.id, actor_role="OWNER")
    payroll = Payroll(branch_id=s.branch.id, period_month=7, period_year=2026, status="POSTED", created_by=s.admin.id)
    ctx.session.add(payroll)
    ctx.session.flush()
    ctx.session.add(PayrollDetail(payroll_id=payroll.id, employee_id=s.budi.id, base_salary=8000000, bonus=0, deduction=0,
                                  pph21_amount=120000, pph21_borne_by="KARYAWAN", final_salary=7880000))
    ctx.session.flush()

    report = build_tax_month(s.branch.id, 2026, 7)
    assert report["pph21_due"] == Decimal("120000") and report["pph21_to_pay"] == Decimal("120000")
    assert report["pph21_due_date"] == date(2026, 8, 15)

    record_tax_payment(s.branch.id, {
        "tax_type": TAX_PAYMENT_PPH21, "amount": "120000", "reference_number": "NTPN-UJI-1", "paid_on": "2026-08-10",
        "period_year": "2026", "period_month": "7", "account_type": "CASH",
    }, None, s.owner)
    report = build_tax_month(s.branch.id, 2026, 7)
    assert report["pph21_paid"] == Decimal("120000") and report["pph21_to_pay"] == 0
    journal = Journal.query.filter_by(reference_type="TAX_PAYMENT").order_by(Journal.id.desc()).first()
    debit = next(row for row in JournalDetail.query.filter_by(journal_id=journal.id).all() if row.debit > 0)
    assert Account.query.get(debit.account_id).account_code == "2011"


def test_bukti_potong_1721_a1(ctx):
    from app.services.tax_pph21_service import compute_annual_1721_a1

    s = _setup(ctx)
    s.budi.ptkp_status = "TK/0"
    _history(ctx, s, s.budi, range(1, 13), Decimal("5000000"), Decimal("0"))
    doc = compute_annual_1721_a1(s.budi, 2026, s.branch.id)
    assert (doc["gross_salary"], doc["biaya_jabatan"], doc["netto"]) == (Decimal("60000000"), Decimal("3000000"), Decimal("57000000"))
    assert (doc["pkp"], doc["pph21_annual"], doc["difference"]) == (Decimal("3000000"), Decimal("150000"), Decimal("150000"))


def test_halaman_pajak_dan_1721_a1_terbuka(app, ctx):
    from tests.test_workforce_module import _login

    s = _setup(ctx)
    _history(ctx, s, s.budi, range(1, 4), Decimal("5000000"), Decimal("0"))
    owner = _login(app, s.owner)
    page = owner.get(f"/sdm/karyawan/{s.budi.id}/bukti-potong-1721a1?year=2026")
    assert page.status_code == 200 and "1721" in page.get_data(as_text=True)
    for url in ("/finance/tax", "/finance/tax/settings", f"/sdm/karyawan/{s.budi.id}", f"/hr/employees/{s.budi.id}/edit"):
        assert owner.get(url).status_code == 200, url
