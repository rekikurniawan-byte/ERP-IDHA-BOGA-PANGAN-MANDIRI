"""Kasbon karyawan (keputusan owner 2026-10-12).

Dikunci: persetujuan tertulis karyawan (ketik nama + gores), batas 1x gaji, hanya OWNER mencairkan,
pencairan = buku kas keluar + jurnal 1005/1001 dengan cek saldo, cicilan per gaji ikut batas 50%,
saat keluar dipotong sebanyak batas mengizinkan, pelunasan tunai, hapus sisa = beban 5013.
"""
from datetime import date
from decimal import Decimal

import pytest

from tests.test_workforce_module import _contract, _login, _setup, _signature, ctx  # noqa: F401


def _cash(s, amount=5000000):
    from app.services.owner_capital_service import record_owner_capital

    record_owner_capital(branch_id=s.branch.id, kind="SETOR", transaction_date=date(2026, 8, 1), account_type="CASH",
                         bank_account_id=None, amount=amount, notes="modal uji", created_by=s.owner.id, actor_role="OWNER")


def _lines(reference_type, reference_id):
    from tests.test_pph21 import _lines as lines

    return lines(reference_type, reference_id)


def _request(s, amount="1500000", installment="500000", name=None):
    from app.services.employee_advance_service import request_advance

    charge, _ = request_advance(s.budi, amount=amount, installment=installment, reason="Biaya sekolah", account_type="CASH",
                                bank_account_id=None, typed_name=name or s.budi.full_name, signature_data=_signature(), user=s.admin)
    return charge


def test_pengajuan_kasbon_wajib_persetujuan_dan_batas_satu_gaji(ctx):
    from app.services.workforce_service import WorkforceError

    s = _setup(ctx)
    _contract(s, s.budi, salary="3000000")
    with pytest.raises(WorkforceError, match="mengetik namanya"):
        _request(s, name="Orang Lain")
    with pytest.raises(WorkforceError, match="1x gaji"):
        _request(s, amount="3500000")
    with pytest.raises(WorkforceError, match="Cicilan"):
        _request(s, installment="0")
    charge = _request(s, amount="2000000")
    assert charge.status == "DIUSULKAN" and charge.signature_attachment_id and charge.clause.startswith("Surat pernyataan kasbon KSB/")
    with pytest.raises(WorkforceError, match="1x gaji"):
        _request(s, amount="1500000")  # sisa batas 1 jt


def test_pencairan_hanya_owner_cek_saldo_dan_jurnal(ctx):
    from app.models.finance import CashBankTransaction
    from app.services.employee_charge_service import approve_charge
    from app.services.workforce_service import WorkforceError

    s = _setup(ctx)
    _contract(s, s.budi, salary="3000000")
    charge = _request(s)
    with pytest.raises(WorkforceError, match="OWNER"):
        approve_charge(charge, s.admin)
    with pytest.raises(WorkforceError, match="Saldo kas"):
        approve_charge(charge, s.owner)
    _cash(s)
    approve_charge(charge, s.owner, amount="1200000")
    assert charge.status == "AKTIF" and charge.amount == Decimal("1200000") and charge.disbursed_on
    ledger = CashBankTransaction.query.get(charge.cash_bank_transaction_id)
    assert ledger.transaction_type == "OUT" and Decimal(str(ledger.amount)) == Decimal("1200000")
    assert _lines("EMPLOYEE_ADVANCE", charge.id) == {"1005": (Decimal("1200000"), 0), "1001": (0, Decimal("1200000"))}


def test_cicilan_dari_gaji_dan_saat_keluar_dipotong_maksimal(ctx):
    from app.services.employee_charge_service import approve_charge
    from app.services.employee_exit_service import approve_exit, create_exit
    from app.services.hr_service import generate_payroll

    s = _setup(ctx)
    _contract(s, s.budi, start=date(2026, 1, 1), end=date(2026, 12, 31), salary="3000000")
    _cash(s)
    charge = _request(s, amount="2400000", installment="400000")
    approve_charge(charge, s.owner)
    ok, message, payroll = generate_payroll(s.branch.id, 8, 2026, s.admin.id)
    detail = next(d for d in payroll.details if d.employee_id == s.budi.id)
    assert detail.charge_deduction == Decimal("400000") and detail.final_salary == Decimal("2600000")

    row = create_exit(s.budi, exit_type="HABIS_KONTRAK", reason_code="KONTRAK_HABIS", notice_date=date(2026, 9, 1),
                      effective_date=date(2026, 12, 31), user_id=s.admin.id)
    row.effective_date = row.last_work_date = date(2026, 9, 30)  # paksa keluar September untuk uji batas
    approve_exit(row, s.owner, handover_done=True)
    ok, message, september = generate_payroll(s.branch.id, 9, 2026, s.admin.id)
    detail = next(d for d in september.details if d.employee_id == s.budi.id)
    # Saat keluar cicilan tidak dibatasi 400rb: dipotong sampai 50% upah+kompensasi (sisa 2,4 jt belum dijurnal Agustus).
    assert detail.charge_deduction > Decimal("400000")


def test_pelunasan_tunai_dan_hapus_sisa(ctx):
    from app.services.employee_advance_service import repay_advance_cash
    from app.services.employee_charge_service import approve_charge, cancel_charge, charge_remaining

    s = _setup(ctx)
    _contract(s, s.budi, salary="3000000")
    _cash(s)
    charge = _request(s, amount="1000000", installment="250000")
    approve_charge(charge, s.owner)
    ledger = repay_advance_cash(charge, amount="400000", account_type="CASH", bank_account_id=None, user=s.admin)
    assert charge_remaining(charge) == Decimal("600000")
    assert _lines("EMPLOYEE_ADVANCE_REPAY", ledger.id) == {"1001": (Decimal("400000"), 0), "1005": (0, Decimal("400000"))}
    cancel_charge(charge, s.owner, "Dihapuskan owner")
    assert charge.status == "BATAL"
    assert _lines("EMPLOYEE_CHARGE_CANCEL", charge.id) == {"5013": (Decimal("600000"), 0), "1005": (0, Decimal("600000"))}


def test_halaman_kasbon(app, ctx):
    s = _setup(ctx)
    _contract(s, s.budi, salary="3000000")
    charge = _request(s)
    owner = _login(app, s.owner)
    for url in ("/sdm/kasbon", "/sdm/kasbon/baru", f"/sdm/kasbon/{charge.id}/cetak", "/sdm/"):
        assert owner.get(url).status_code == 200, url
    assert "Biaya sekolah" not in owner.get("/sdm/denda").get_data(as_text=True)  # kasbon tidak dobel di halaman denda
    assert "Biaya sekolah" in owner.get("/sdm/kasbon").get_data(as_text=True)


def test_draf_peraturan_perusahaan_mengikuti_aturan(app, ctx):
    from app.services.workforce_service import save_hr_settings

    s = _setup(ctx)
    save_hr_settings(s.branch.id, {"hr.unpaid_statuses": "ALPA", "hr.fine_absent_per_day": "75000", "hr.notice_days": "30"})
    page = _login(app, s.owner).get("/sdm/aturan/peraturan-perusahaan").get_data(as_text=True)
    assert "PERATURAN PERUSAHAAN" in page and "Rp 75.000 per hari" in page
    assert "tidak masuk tanpa keterangan" in page and "cuti tahunan 12" in page and "paling lambat 30 hari" in page
