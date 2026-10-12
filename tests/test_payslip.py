"""Slip gaji & kwitansi (keputusan owner 2026-10-11).

Dikunci:
- slip memuat rekap apel, pendapatan, potongan hari tanpa keterangan, tiap denda + dasar pasal,
  sisa piutang, gaji bersih + terbilang, dan kode verifikasi;
- kwitansi hanya setelah hutang gaji dicatat, sekali per karyawan, tidak untuk gaji Rp 0;
  TTD digital wajib ketik nama persis; TTD kertas boleh tanpa scan;
- link WhatsApp hanya setelah dikunci, dibuka PIN 4 angka terakhir NIK, slip konsep tidak bisa dibuka;
- halaman slip/kwitansi tidak membuka data cabang lain.
"""
from datetime import date
from decimal import Decimal

import pytest

from tests.test_workforce_module import _contract, _login, _setup, _signature, ctx  # noqa: F401


def test_terbilang():
    from app.utils.terbilang import terbilang

    assert terbilang(0) == "Nol rupiah"
    assert terbilang(1_000) == "Seribu rupiah"
    assert terbilang(11_500) == "Sebelas ribu lima ratus rupiah"
    assert terbilang(4_400_000) == "Empat juta empat ratus ribu rupiah"
    assert terbilang(1_250_175) == "Satu juta dua ratus lima puluh ribu seratus tujuh puluh lima rupiah"


def _payroll_with_charge(ctx, s):
    from app.models.hr import EmployeeAttendance
    from app.services.employee_charge_service import approve_charge, create_charge
    from app.services.hr_service import generate_payroll

    _contract(s, s.budi, salary="3100000")
    for day, status in ((3, "HADIR"), (4, "IZIN"), (5, "ALPA"), (6, "ALPA")):
        ctx.session.add(EmployeeAttendance(branch_id=s.branch.id, attendance_date=date(2026, 8, day),
                                           employee_id=s.budi.id, status=status, created_by=s.admin.id))
    charge = create_charge(employee=s.budi, charge_type="DENDA", amount=2000000, clause="Kontrak Pasal 5",
                           description="Keluar lokasi malam", created_by=s.admin.id)
    approve_charge(charge, s.owner)
    ok, message, payroll = generate_payroll(s.branch.id, 8, 2026, s.admin.id)
    assert ok, message
    detail = next(d for d in payroll.details if d.employee_id == s.budi.id)
    return payroll, detail, charge


def test_slip_memuat_rincian_lengkap(ctx):
    from app.services.payslip_service import build_payslip, slip_number

    s = _setup(ctx)
    payroll, detail, charge = _payroll_with_charge(ctx, s)
    slip = build_payslip(detail)

    assert slip["number"] == slip_number(detail) and slip["period"] == "Agustus 2026"
    assert slip["attendance"] == {"HADIR": 1, "IZIN": 1, "SAKIT": 0, "CUTI": 0, "ALPA": 2}
    assert slip["contract"].contract_number.startswith("PKWT-")
    labels = [row["label"] for row in slip["deductions"]]
    assert "Hari tidak bekerja · 3 hari (izin 1, tanpa ket. 2)" in labels
    assert any("Keluar lokasi malam" in label for label in labels)
    assert slip["charge_lines"][0]["note"] == "Kontrak Pasal 5"
    # Aturan bawaan: izin + tanpa keterangan dipotong. 3,1 jt - 3/31 hari = 2,8 jt;
    # potongan denda maks 50% = 1.400.000; sisa 600.000 dibawa ke bulan berikutnya.
    assert slip["net"] == Decimal("1400000") and slip["outstanding"] == Decimal("600000")
    assert slip["gross"] - slip["total_deduction"] == slip["net"]
    assert slip["net_words"] == "Satu juta empat ratus ribu rupiah"
    assert slip["is_draft"] and len(slip["verification"]) == 14


def test_kwitansi_hanya_setelah_hutang_dicatat_dan_sekali(ctx):
    from app.services.accounting_service import create_payroll_journal_for_payroll
    from app.services.payslip_service import build_receipt, record_manual_receipt, sign_receipt
    from app.services.workforce_service import WorkforceError

    s = _setup(ctx)
    payroll, detail, _ = _payroll_with_charge(ctx, s)
    with pytest.raises(WorkforceError, match="hutang gaji dicatat"):
        sign_receipt(detail, typed_name=s.budi.full_name, signature_data=_signature(), user=s.admin)

    payroll.status = "FINAL"
    ok, message, _ = create_payroll_journal_for_payroll(payroll, s.admin.id)
    assert ok, message
    with pytest.raises(WorkforceError, match="Nama"):
        sign_receipt(detail, typed_name="Orang Lain", signature_data=_signature(), user=s.admin)
    receipt, attachments = sign_receipt(detail, typed_name="budi santoso", signature_data=_signature(), user=s.admin)
    assert receipt.method == "DIGITAL" and receipt.amount == Decimal("1400000") and attachments
    assert receipt.receipt_number.startswith("KW-GJ/202608/")
    with pytest.raises(WorkforceError, match="sudah ditandatangani"):
        record_manual_receipt(detail, user=s.admin)
    data = build_receipt(detail)
    assert data["amount_words"] == "Satu juta empat ratus ribu rupiah" and data["signature"].startswith("data:image/png")

    zero = next(d for d in payroll.details if d.employee_id == s.sari.id)
    assert zero.final_salary == 0
    with pytest.raises(WorkforceError, match="Rp 0"):
        record_manual_receipt(zero, user=s.admin)


def test_link_whatsapp_dikunci_pin_nik(app, ctx):
    from app.services.payslip_service import ensure_slip_token, slip_pin, whatsapp_url
    from app.services.workforce_service import WorkforceError

    s = _setup(ctx)
    s.budi.nik = "1601020304057731"
    payroll, detail, _ = _payroll_with_charge(ctx, s)
    with pytest.raises(WorkforceError, match="dikunci"):
        ensure_slip_token(detail)
    payroll.status = "FINAL"
    token = ensure_slip_token(detail)
    assert ensure_slip_token(detail) == token and len(token) >= 30
    assert slip_pin(s.budi) == "7731"
    url = whatsapp_url(s.budi, f"https://erp.contoh/slip/{token}", payroll)
    assert url.startswith("https://wa.me/62812?text=") and "PIN%204%20angka%20terakhir%20NIK" in url

    public = app.test_client()
    page = public.get(f"/slip/{token}").get_data(as_text=True)
    assert "4 angka terakhir NIK" in page and "Gaji bersih" not in page
    assert "PIN salah" in public.post(f"/slip/{token}", data={"pin": "0000"}).get_data(as_text=True)
    public.post(f"/slip/{token}", data={"pin": s.budi.nik[-4:]})
    page = public.get(f"/slip/{token}").get_data(as_text=True)
    assert "SLIP GAJI" in page and "Rp 1.400.000" in page and "Disetujui," not in page
    assert public.get("/slip/token-palsu-yang-tidak-ada-di-sistem").status_code == 404

    payroll.status = "DRAFT"
    assert app.test_client().get(f"/slip/{token}").status_code == 404


def test_halaman_slip_dan_kwitansi_dalam_cabang(app, ctx):
    from app.models.master import Branch, User
    from uuid import uuid4

    s = _setup(ctx)
    payroll, detail, _ = _payroll_with_charge(ctx, s)
    owner = _login(app, s.owner)
    for url in (f"/hr/slip/{detail.id}", f"/hr/slip/penggajian/{payroll.id}", f"/hr/slip/{detail.id}/kwitansi",
                f"/hr/slip/penggajian/{payroll.id}/kwitansi", f"/hr/slip/{detail.id}/kwitansi/ttd", f"/hr/payrolls/{payroll.id}"):
        assert owner.get(url).status_code == 200, url
    assert "KONSEP" in owner.get(f"/hr/slip/{detail.id}").get_data(as_text=True)

    other = Branch(code=f"LAIN-{uuid4().hex[:6]}", name="Cabang Lain", is_active=True)
    ctx.session.add(other)
    ctx.session.flush()
    stranger = User(branch_id=other.id, full_name="Owner Lain", username=f"lain-{uuid4().hex[:8]}",
                    password_hash="x", role="OWNER", is_active=True)
    ctx.session.add(stranger)
    ctx.session.flush()
    outsider = _login(app, stranger)
    assert outsider.get(f"/hr/slip/{detail.id}").status_code == 404
    assert outsider.get(f"/hr/slip/penggajian/{payroll.id}").status_code == 404


def test_aturan_potongan_diatur_owner_dan_terkunci_per_kontrak(app, ctx):
    from app.models.hr import EmployeeAttendance
    from app.services.hr_service import generate_payroll
    from app.services.workforce_service import save_hr_settings

    s = _setup(ctx)
    save_hr_settings(s.branch.id, {"hr.unpaid_statuses": "ALPA", "hr.daily_wage_divisor": "30"})
    old = _contract(s, s.budi, salary="3000000")
    # Sakit & cuti selalu ikut aturan UU walau owner hanya mencentang tanpa keterangan.
    assert old.unpaid_statuses == "SAKIT,CUTI,ALPA" and old.daily_wage_divisor == "30"
    assert "sakit tanpa surat keterangan dokter" in old.html_snapshot and "÷ 30 hari" in old.html_snapshot
    assert "cuti tahunan 12 (dua belas) hari kerja" in old.html_snapshot

    # Owner mengubah aturan: semua hari tidak bekerja dipotong. Kontrak lama tidak berubah.
    owner = _login(app, s.owner)
    owner.post("/sdm/aturan", data={"unpaid_status": ["IZIN", "SAKIT", "CUTI", "ALPA"], "hr.daily_wage_divisor": "KALENDER"})
    new = _contract(s, s.sari, salary="3000000")
    assert new.unpaid_statuses == "IZIN,SAKIT,CUTI,ALPA" and old.unpaid_statuses == "SAKIT,CUTI,ALPA"
    admin = _login(app, s.admin)
    admin.post("/sdm/aturan", data={"unpaid_status": [], "hr.daily_wage_divisor": "26"})
    from app.services.workforce_service import hr_settings
    assert hr_settings(s.branch.id)["daily_wage_divisor"] == "KALENDER"  # admin tidak boleh mengubah

    for employee in (s.budi, s.sari):
        for day, status in ((3, "IZIN"), (4, "SAKIT"), (5, "ALPA")):
            ctx.session.add(EmployeeAttendance(branch_id=s.branch.id, attendance_date=date(2026, 9, day),
                                               employee_id=employee.id, status=status, created_by=s.admin.id))
    ok, message, payroll = generate_payroll(s.branch.id, 9, 2026, s.admin.id)
    assert ok, message
    lines = {d.employee_id: d for d in payroll.details}
    assert lines[s.budi.id].unpaid_absence_days == 2 and lines[s.budi.id].final_salary == Decimal("2800000")  # sakit + alpa, izin tidak
    assert lines[s.sari.id].unpaid_absence_days == 3 and lines[s.sari.id].final_salary == Decimal("2700000")  # 3 x 3jt/30 hari
    assert owner.get("/sdm/aturan").status_code == 200


def test_sakit_bersurat_dokter_dan_cuti_tahunan_dibayar_sesuai_uu(ctx):
    from app.models.hr import EmployeeAttendance
    from app.services.workforce_payroll_service import annual_leave_status, unpaid_days_by_status

    s = _setup(ctx)
    budi = s.budi
    budi.join_date = date(2025, 3, 1)  # sudah > 12 bulan pada Sept 2026; tahun cuti 1-3-2026 s/d 28-2-2027
    statuses = ("IZIN", "SAKIT", "CUTI", "ALPA")

    def add(day, status, medical=False):
        ctx.session.add(EmployeeAttendance(branch_id=s.branch.id, attendance_date=day, employee_id=budi.id,
                                           status=status, medical_note=medical, created_by=s.admin.id))

    for day in range(1, 11):  # 10 hari cuti di Agustus (jatah terpakai 10)
        add(date(2026, 8, day), "CUTI")
    for day in range(1, 5):  # 4 hari cuti di September: 2 masih jatah, 2 di luar jatah
        add(date(2026, 9, day), "CUTI")
    add(date(2026, 9, 10), "SAKIT", medical=True)
    add(date(2026, 9, 11), "SAKIT")
    add(date(2026, 9, 12), "IZIN")
    ctx.session.flush()

    counts = unpaid_days_by_status(budi.id, date(2026, 9, 1), date(2026, 9, 30), statuses)
    assert counts == {"IZIN": 1, "SAKIT": 1, "CUTI": 2, "ALPA": 0}
    assert unpaid_days_by_status(budi.id, date(2026, 8, 1), date(2026, 8, 31), statuses)["CUTI"] == 0
    status = annual_leave_status(budi, date(2026, 9, 30))
    assert status["eligible"] and status["used"] == 14 and status["remaining"] == 0

    # Belum 12 bulan bekerja: semua cuti dipotong.
    s.sari.join_date = date(2026, 1, 1)
    for day in (15, 16):
        ctx.session.add(EmployeeAttendance(branch_id=s.branch.id, attendance_date=date(2026, 9, day),
                                           employee_id=s.sari.id, status="CUTI", created_by=s.admin.id))
    ctx.session.flush()
    assert unpaid_days_by_status(s.sari.id, date(2026, 9, 1), date(2026, 9, 30), statuses)["CUTI"] == 2
    assert annual_leave_status(s.sari, date(2026, 9, 30))["eligible_from"] == date(2027, 1, 1)
