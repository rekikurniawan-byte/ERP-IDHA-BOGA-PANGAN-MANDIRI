"""Modul Tenaga Kerja (keputusan owner 2026-10-11).

Dikunci di sini:
- kontrak PKWT/PKWTT: aturan jangka waktu, TTD karyawan (gores + KTP + ketik nama)
  membekukan isi surat, TTD owner mengaktifkan, PKWT wajib dicatat Disnaker 3 hari kerja;
- apel: tanpa keterangan membuka kasus mangkir + memberi tahu owner, kembali = denda diusulkan;
- izin: dicatat Admin Operasional menunggu persetujuan, dicatat ADMIN langsung disetujui,
  telat kembali = denda per hari;
- denda/ganti rugi: hanya OWNER yang memutuskan, dijurnal 1005/4004, batal sisa dibalik;
- penggajian: hari tanpa keterangan tidak dibayar, potongan maks 50% upah, jurnal
  5004 bruto / 2003 neto / 1005 potongan, sisanya tetap piutang;
- keluar: resign kurang pemberitahuan kena denda + ganti rugi sisa PKWT, kompensasi PKWT
  dibayar lewat penggajian, setelah dijurnal karyawan nonaktif & kontrak berakhir;
- mangkir baru bisa dikualifikasikan mengundurkan diri setelah 2 panggilan + 5 hari;
- kebutuhan orang per sesi dari porsi pesanan besok.
"""
from __future__ import annotations

import io
import os
import struct
import zlib
from datetime import date, timedelta
from decimal import ROUND_DOWN, Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from werkzeug.datastructures import FileStorage


@pytest.fixture
def ctx(app, monkeypatch, tmp_path):
    """Tanpa commit ke test_db: semua di-flush lalu di-rollback. Lampiran ke folder sementara."""
    app.config["WTF_CSRF_ENABLED"] = False  # tes ini menguji alur bisnis, bukan CSRF
    app.config["DIGITAL_ATTACHMENT_UPLOAD_DIR"] = str(tmp_path)
    with app.app_context():
        from app.extensions import db

        monkeypatch.setattr(db.session, "commit", db.session.flush)
        try:
            yield db
        finally:
            db.session.rollback()


def _png(size: int = 40) -> bytes:
    """PNG acak kecil (cukup besar untuk lolos pemeriksaan goresan)."""
    raw = b"".join(b"\x00" + os.urandom(size * 3) for _ in range(size))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def _signature() -> str:
    import base64

    return "data:image/png;base64," + base64.b64encode(_png()).decode("ascii")


def _ktp() -> FileStorage:
    return FileStorage(stream=io.BytesIO(_png(32)), filename="ktp.png", content_type="image/png")


def _setup(db):
    from app.models.master import Branch, BranchSetting, Employee, User
    from app.services.bootstrap_service import ensure_chart_of_accounts

    ensure_chart_of_accounts()
    branch = Branch(code=f"SDM-{uuid4().hex[:8]}", name="Cabang Uji SDM", is_active=True)
    db.session.add(branch)
    db.session.flush()
    users = {
        role: User(branch_id=branch.id, full_name=f"{role.title()} Uji", username=f"sdm-{role.lower()}-{uuid4().hex[:8]}",
                   password_hash="x", role=role, is_active=True)
        for role in ("OWNER", "ADMIN", "ADMIN_OPERASIONAL")
    }
    db.session.add_all(users.values())
    for key, value in {
        "hr.fine_absent_per_day": "50000",
        "hr.fine_leave_site": "100000",
        "hr.fine_late_return_per_day": "40000",
        "hr.fine_short_notice": "200000",
        "hr.portions_per_worker": "60",
        "hr.employer_signer_name": "Bu Idha",
    }.items():
        db.session.add(BranchSetting(branch_id=branch.id, setting_key=key, setting_value=value))
    employees = [
        Employee(branch_id=branch.id, full_name=name, phone="0812", status="ACTIVE", employee_type="KARYAWAN",
                 join_date=date(2026, 1, 1), nik="1601" + uuid4().hex[:8])
        for name in ("Budi Santoso", "Sari Wulan")
    ]
    reserve = Employee(branch_id=branch.id, full_name="Joko Cadangan", phone="0813", status="ACTIVE", employee_type="CADANGAN")
    db.session.add_all([*employees, reserve])
    db.session.flush()
    return SimpleNamespace(branch=branch, budi=employees[0], sari=employees[1], reserve=reserve,
                           **{role.lower(): user for role, user in users.items()})


def _contract(s, employee, *, contract_type="PKWT", start=date(2026, 1, 1), end=date(2026, 12, 31), salary="3000000", sign=True):
    from app.services.workforce_service import ContractInput, create_contract, sign_contract_employee, sign_contract_employer

    contract = create_contract(employee, ContractInput(
        contract_type=contract_type, position="Juru masak", start_date=start, end_date=end,
        probation_months=0, monthly_salary=Decimal(salary),
    ), s.admin.id)
    if sign:
        sign_contract_employee(contract, typed_name=employee.full_name, agreed=True, signature_data=_signature(),
                               ktp_file=_ktp(), user_id=s.admin.id)
        sign_contract_employer(contract, signature_data=_signature(), user=s.owner)
    return contract


def _lines(reference_type, reference_id):
    from app.models.accounting import Account, Journal, JournalDetail

    journal = Journal.query.filter_by(reference_type=reference_type, reference_id=reference_id).one()
    return {
        Account.query.get(row.account_id).account_code: (Decimal(str(row.debit)), Decimal(str(row.credit)))
        for row in JournalDetail.query.filter_by(journal_id=journal.id).all()
    }


class _As:
    """Klien uji per pengguna. Fixture memegang satu app context, jadi flask-login
    menyimpan pengguna di `g` yang sama; dibersihkan sebelum tiap permintaan."""

    def __init__(self, app, user):
        self.client = app.test_client()
        with self.client.session_transaction() as session:
            session["_user_id"] = str(user.id)
            session["_fresh"] = True

    def _call(self, method, *args, **kwargs):
        from flask import g

        g.pop("_login_user", None)
        return getattr(self.client, method)(*args, **kwargs)

    def get(self, *args, **kwargs):
        return self._call("get", *args, **kwargs)

    def post(self, *args, **kwargs):
        return self._call("post", *args, **kwargs)


def _login(app, user):
    return _As(app, user)


# --- kontrak ---------------------------------------------------------------


def test_aturan_jangka_waktu_kontrak(ctx):
    from app.services.workforce_service import ContractInput, WorkforceError, create_contract

    s = _setup(ctx)
    base = dict(position="Juru masak", monthly_salary=Decimal("3000000"))
    with pytest.raises(WorkforceError, match="tanggal selesai"):
        create_contract(s.budi, ContractInput(contract_type="PKWT", start_date=date(2026, 1, 1), end_date=None, probation_months=0, **base), s.admin.id)
    with pytest.raises(WorkforceError, match="masa percobaan"):
        create_contract(s.budi, ContractInput(contract_type="PKWT", start_date=date(2026, 1, 1), end_date=date(2026, 6, 30), probation_months=1, **base), s.admin.id)
    with pytest.raises(WorkforceError, match="5 tahun"):
        create_contract(s.budi, ContractInput(contract_type="PKWT", start_date=date(2026, 1, 1), end_date=date(2031, 6, 30), probation_months=0, **base), s.admin.id)
    with pytest.raises(ValueError):
        create_contract(s.budi, ContractInput(contract_type="PKWTT", start_date=date(2026, 1, 1), end_date=None, probation_months=4, **base), s.admin.id)

    pkwtt = create_contract(s.sari, ContractInput(contract_type="PKWTT", start_date=date(2026, 1, 1), end_date=date(2027, 1, 1), probation_months=3, **base), s.admin.id)
    assert pkwtt.end_date is None and pkwtt.probation_months == 3
    assert pkwtt.fine_absent_per_day == Decimal("50000")  # dari Pengaturan Perusahaan
    with pytest.raises(WorkforceError, match="belum selesai ditandatangani"):
        create_contract(s.sari, ContractInput(contract_type="PKWTT", start_date=date(2026, 2, 1), end_date=None, probation_months=0, **base), s.admin.id)


def test_ttd_karyawan_membekukan_isi_lalu_owner_mengaktifkan(ctx):
    from app.models.hr import EmployeeSalaryHistory
    from app.models.master import BranchSetting
    from app.models.system import Notification
    from app.services.workforce_service import (
        WorkforceError, add_working_days, disnaker_due_date, record_disnaker,
        sign_contract_employee, sign_contract_employer,
    )

    s = _setup(ctx)
    contract = _contract(s, s.budi, sign=False)
    with pytest.raises(WorkforceError, match="Nama yang diketik"):
        sign_contract_employee(contract, typed_name="Orang Lain", agreed=True, signature_data=_signature(), ktp_file=_ktp(), user_id=s.admin.id)
    with pytest.raises(WorkforceError, match="KTP"):
        sign_contract_employee(contract, typed_name="budi  santoso", agreed=True, signature_data=_signature(), ktp_file=None, user_id=s.admin.id)
    with pytest.raises(WorkforceError, match="belum digores"):
        sign_contract_employee(contract, typed_name="Budi Santoso", agreed=True, signature_data="", ktp_file=_ktp(), user_id=s.admin.id)

    sign_contract_employee(contract, typed_name="budi santoso", agreed=True, signature_data=_signature(), ktp_file=_ktp(), user_id=s.admin.id)
    assert contract.status == "MENUNGGU_TTD_PERUSAHAAN"
    assert "Rp 50.000" in contract.html_snapshot and contract.ktp_attachment_id
    snapshot = contract.html_snapshot

    # Pengaturan berubah sesudah ditandatangani: surat tetap seperti yang disetujui karyawan.
    BranchSetting.query.filter_by(branch_id=s.branch.id, setting_key="hr.fine_absent_per_day").one().setting_value = "999000"
    ctx.session.flush()

    with pytest.raises(WorkforceError, match="OWNER"):
        sign_contract_employer(contract, signature_data=_signature(), user=s.admin)
    sign_contract_employer(contract, signature_data=_signature(), user=s.owner)
    assert contract.status == "AKTIF" and contract.html_snapshot == snapshot
    assert contract.employer_signer_name == "Bu Idha"
    assert s.budi.position == "Juru masak"
    assert EmployeeSalaryHistory.query.filter_by(employee_id=s.budi.id).one().salary_amount == Decimal("3000000")

    due = disnaker_due_date(contract)
    note = Notification.query.filter_by(branch_id=s.branch.id, notification_type="HR_PKWT_DISNAKER").one()
    assert note.due_date == due and note.target_role == "OWNER"
    assert add_working_days(date(2026, 10, 9), 3) == date(2026, 10, 14)  # Jumat + 3 hari kerja = Rabu

    record_disnaker(contract, registered_at=date(2026, 1, 5), reference="DISNAKER/OKI/123")
    assert contract.disnaker_reference == "DISNAKER/OKI/123"


def test_karyawan_tanpa_kontrak_berlaku_ditandai(ctx):
    from app.services.workforce_service import contract_alerts

    s = _setup(ctx)
    _contract(s, s.budi)
    alerts = contract_alerts(s.branch.id, today=date(2026, 3, 1))
    flagged = {row["employee"].id for row in alerts["without_contract"]}
    assert s.sari.id in flagged and s.budi.id not in flagged and s.reserve.id not in flagged
    assert [row["contract"].employee_id for row in alerts["disnaker"]] == [s.budi.id]


# --- apel, izin, mangkir ----------------------------------------------------


def test_apel_tanpa_keterangan_membuka_kasus_dan_kembali_mengusulkan_denda(ctx):
    from app.models.system import Notification
    from app.models.workforce import EmployeeAbsenceCase, EmployeeCharge
    from app.services.workforce_attendance_service import absent_days, roll_call, save_roll_call
    from app.utils.clock import today_wib

    s = _setup(ctx)
    _contract(s, s.budi, end=today_wib() + timedelta(days=200))
    today = today_wib()
    d1, d2 = today - timedelta(days=3), today - timedelta(days=2)

    summary = save_roll_call(s.branch.id, d1, {str(s.budi.id): "ALPA", str(s.sari.id): "HADIR"}, {}, s.admin_operasional.id)
    case = summary["opened"][0]
    assert case.employee_id == s.budi.id and case.status == "TERBUKA"
    assert Notification.query.filter_by(branch_id=s.branch.id, generated_key=f"hr-case-{case.id}").one().target_role == "OWNER"

    # Hari berikutnya apel menyarankan ALPA untuk yang masih mangkir.
    suggestion = {row["employee"].id: row["status"] for row in roll_call(s.branch.id, d2)["rows"]}
    assert suggestion[s.budi.id] == "ALPA" and suggestion[s.reserve.id] == ""
    save_roll_call(s.branch.id, d2, {str(s.budi.id): "ALPA"}, {}, s.admin_operasional.id)
    assert absent_days(case) == 2

    back = save_roll_call(s.branch.id, today - timedelta(days=1), {str(s.budi.id): "HADIR"}, {}, s.admin_operasional.id)
    assert back["proposals"] == 2 and case.status == "KEMBALI"
    amounts = sorted(c.amount for c in EmployeeCharge.query.filter_by(employee_id=s.budi.id).all())
    assert amounts == [Decimal("100000"), Decimal("100000")]  # 2 hari x 50rb + keluar lokasi 100rb
    assert all(c.status == "DIUSULKAN" for c in EmployeeCharge.query.filter_by(employee_id=s.budi.id))

    # Koreksi di hari yang sama: ALPA lalu diubah HADIR = kasus dihapus.
    save_roll_call(s.branch.id, today, {str(s.sari.id): "ALPA"}, {}, s.admin_operasional.id)
    save_roll_call(s.branch.id, today, {str(s.sari.id): "HADIR"}, {}, s.admin_operasional.id)
    assert EmployeeAbsenceCase.query.filter_by(employee_id=s.sari.id).count() == 0


def test_izin_admin_operasional_menunggu_dan_telat_kembali_didenda(ctx):
    from app.models.workforce import EmployeeCharge
    from app.services.workforce_attendance_service import (
        WorkforceError, create_leave, decide_leave, roll_call, save_roll_call,
    )
    from app.utils.clock import today_wib

    s = _setup(ctx)
    _contract(s, s.sari, end=today_wib() + timedelta(days=200))
    today = today_wib()
    leave = create_leave(s.sari, leave_type="PULANG_KAMPUNG", start_date=today - timedelta(days=6),
                         expected_return_date=today - timedelta(days=4), reason="Keluarga sakit", user=s.admin_operasional)
    assert leave.status == "DIAJUKAN"
    with pytest.raises(WorkforceError):
        decide_leave(leave, approve=True, user=s.admin_operasional)
    decide_leave(leave, approve=True, user=s.admin)
    assert leave.status == "DISETUJUI"

    during = {row["employee"].id: row["status"] for row in roll_call(s.branch.id, today - timedelta(days=5))["rows"]}
    after = {row["employee"].id: row["status"] for row in roll_call(s.branch.id, today - timedelta(days=3))["rows"]}
    assert during[s.sari.id] == "IZIN" and after[s.sari.id] == "ALPA"

    save_roll_call(s.branch.id, today - timedelta(days=3), {str(s.sari.id): "ALPA"}, {}, s.admin.id)
    save_roll_call(s.branch.id, today - timedelta(days=2), {str(s.sari.id): "ALPA"}, {}, s.admin.id)
    save_roll_call(s.branch.id, today - timedelta(days=1), {str(s.sari.id): "HADIR"}, {}, s.admin.id)
    assert leave.status == "KEMBALI" and leave.actual_return_date == today - timedelta(days=1)
    charge = EmployeeCharge.query.filter_by(employee_id=s.sari.id).one()
    assert charge.amount == Decimal("80000") and "Terlambat kembali 2 hari" in charge.description

    direct = create_leave(s.budi, leave_type="IZIN_KELUAR", start_date=today, expected_return_date=today,
                          reason="Ke pasar", user=s.admin)
    assert direct.status == "DISETUJUI"


def test_kualifikasi_mengundurkan_diri_butuh_dua_panggilan_dan_lima_hari(ctx):
    from app.models.hr import EmployeeAttendance
    from app.models.workforce import EmployeeCharge
    from app.services.employee_exit_service import exit_for_absconding
    from app.services.workforce_attendance_service import WorkforceError, issue_summons, open_absence_case
    from app.utils.clock import today_wib

    s = _setup(ctx)
    today = today_wib()
    contract = _contract(s, s.budi, start=today - timedelta(days=100), end=today + timedelta(days=200))
    start = today - timedelta(days=6)
    case = open_absence_case(s.budi, start, s.admin.id)
    for offset in range(6):
        ctx.session.add(EmployeeAttendance(branch_id=s.branch.id, attendance_date=start + timedelta(days=offset),
                                           employee_id=s.budi.id, status="ALPA", created_by=s.admin.id))
    ctx.session.flush()

    with pytest.raises(WorkforceError, match="2 kali"):
        exit_for_absconding(case, s.owner)
    issue_summons(case, 1, today - timedelta(days=4))
    with pytest.raises(WorkforceError, match="sehari setelah"):
        issue_summons(case, 2, today - timedelta(days=4))
    issue_summons(case, 2, today - timedelta(days=2))
    with pytest.raises(WorkforceError, match="OWNER"):
        exit_for_absconding(case, s.admin)

    row = exit_for_absconding(case, s.owner)
    assert case.status == "MENGUNDURKAN_DIRI" and row.exit_type == "MANGKIR" and row.status == "DISETUJUI"
    assert row.last_work_date == start - timedelta(days=1)
    charges = {c.charge_type: c for c in EmployeeCharge.query.filter_by(employee_id=s.budi.id).all()}
    assert charges["GANTI_RUGI"].status == "AKTIF"  # owner memutuskan langsung
    assert charges["GANTI_RUGI"].amount == Decimal(3000000 * 200 / 30).quantize(Decimal("1"))
    assert charges["DENDA"].amount == Decimal("400000")  # 6 hari x 50rb + 100rb
    assert contract.ended_at == today and s.budi.exit_date == today


# --- denda, jurnal, penggajian ---------------------------------------------


def test_hanya_owner_memutuskan_denda_dan_jurnalnya(ctx):
    from app.services.employee_charge_service import approve_charge, cancel_charge, create_charge
    from app.services.workforce_service import WorkforceError

    s = _setup(ctx)
    _contract(s, s.budi)
    with pytest.raises(WorkforceError, match="kontrak"):
        create_charge(employee=s.sari, charge_type="DENDA", amount=10000, clause="x", description="y", created_by=s.admin.id)
    with pytest.raises(WorkforceError, match="PKWT"):
        _contract(s, s.sari, contract_type="PKWTT", end=None)
        create_charge(employee=s.sari, charge_type="GANTI_RUGI", amount=10000, clause="x", description="y", created_by=s.admin.id)

    charge = create_charge(employee=s.budi, charge_type="DENDA", amount=150000, clause="Pasal 5", description="Keluar lokasi", created_by=s.admin.id)
    with pytest.raises(WorkforceError, match="OWNER"):
        approve_charge(charge, s.admin)
    with pytest.raises(WorkforceError, match="tidak melebihi"):
        approve_charge(charge, s.owner, amount="200000")
    approve_charge(charge, s.owner, amount="120000")
    assert charge.status == "AKTIF" and charge.amount == Decimal("120000")
    assert _lines("EMPLOYEE_CHARGE", charge.id) == {"1005": (Decimal("120000"), 0), "4004": (0, Decimal("120000"))}

    cancel_charge(charge, s.owner, "Dimaafkan")
    assert charge.status == "BATAL" and charge.cancelled_amount == Decimal("120000")
    assert _lines("EMPLOYEE_CHARGE_CANCEL", charge.id) == {"4004": (Decimal("120000"), 0), "1005": (0, Decimal("120000"))}


def test_penggajian_potong_maks_50_persen_dan_hari_alpa_tidak_dibayar(ctx):
    from app.models.hr import EmployeeAttendance, PayrollDetail
    from app.models.workforce import PayrollDeductionItem
    from app.services.accounting_service import create_payroll_journal_for_payroll
    from app.services.employee_charge_service import approve_charge, charge_remaining, create_charge
    from app.services.hr_service import generate_payroll, update_payroll_detail_record

    s = _setup(ctx)
    _contract(s, s.budi, salary="3100000")
    _contract(s, s.sari, salary="3100000")
    for day in (5, 6):
        ctx.session.add(EmployeeAttendance(branch_id=s.branch.id, attendance_date=date(2026, 8, day),
                                           employee_id=s.sari.id, status="ALPA", created_by=s.admin.id))
    charge = create_charge(employee=s.budi, charge_type="GANTI_RUGI", amount=2000000, clause="Pasal 7", description="Uji", created_by=s.admin.id)
    approve_charge(charge, s.owner)

    ok, message, payroll = generate_payroll(s.branch.id, 8, 2026, s.admin.id)
    assert ok, message
    details = {d.employee_id: d for d in PayrollDetail.query.filter_by(payroll_id=payroll.id).all()}
    sari, budi = details[s.sari.id], details[s.budi.id]
    assert sari.unpaid_absence_days == 2 and sari.final_salary == Decimal("2900000")  # 3,1jt - 2/31 x 3,1jt
    assert budi.charge_deduction == Decimal("1550000") and budi.final_salary == Decimal("1550000")  # 50%

    # Bonus naik -> batas potongan ikut naik.
    update_payroll_detail_record(budi, base_salary=budi.base_salary, bonus=200000, deduction=budi.deduction)
    assert budi.charge_deduction == Decimal("1650000")
    assert PayrollDeductionItem.query.filter_by(payroll_detail_id=budi.id).one().amount == Decimal("1650000")

    payroll.status = "FINAL"
    ok, message, journal = create_payroll_journal_for_payroll(payroll, s.admin.id)
    assert ok, message
    lines = _lines("PAYROLL", payroll.id)
    net = sari.final_salary + budi.final_salary
    assert lines["2003"] == (0, net)
    assert lines["1005"] == (0, Decimal("1650000"))
    assert lines["5004"] == (net + Decimal("1650000"), 0)
    assert charge.deducted_amount == Decimal("1650000") and charge_remaining(charge) == Decimal("350000")
    assert charge.status == "AKTIF"  # sisa jadi piutang, dipotong periode berikutnya


def test_resign_kurang_pemberitahuan_dan_penyelesaian_lewat_penggajian(ctx):
    from app.models.hr import PayrollDetail
    from app.models.workforce import EmployeeCharge
    from app.services.accounting_service import create_payroll_journal_for_payroll
    from app.services.employee_exit_service import approve_exit, create_exit, settlement_preview
    from app.services.hr_service import generate_payroll
    from app.services.workforce_service import WorkforceError

    s = _setup(ctx)
    contract = _contract(s, s.budi, start=date(2026, 1, 1), end=date(2026, 12, 31), salary="3000000")
    row = create_exit(s.budi, exit_type="RESIGN", reason_code="PEKERJAAN_LAIN", notice_date=date(2026, 9, 1),
                      effective_date=date(2026, 9, 10), user_id=s.admin.id)
    assert row.short_notice_days == 21
    preview = settlement_preview(row)
    assert preview["employee_damages"] == Decimal(3000000 * 112 / 30).quantize(Decimal("1"))
    assert preview["short_notice_fine"] == Decimal("200000")
    assert preview["compensation"] == Decimal(3000000 * (253 / 30.4375) / 12).quantize(Decimal("1"))
    assert preview["deduct_now"] <= preview["gross"] * Decimal("0.5")

    with pytest.raises(WorkforceError, match="serah terima"):
        approve_exit(row, s.owner, handover_done=False)
    approve_exit(row, s.owner, handover_done=True)
    assert row.status == "DISETUJUI" and contract.ended_at == date(2026, 9, 10)
    assert {c.charge_type for c in EmployeeCharge.query.filter_by(employee_id=s.budi.id, status="AKTIF")} == {"GANTI_RUGI", "DENDA"}

    ok, message, payroll = generate_payroll(s.branch.id, 9, 2026, s.admin.id)
    assert ok, message
    detail = PayrollDetail.query.filter_by(payroll_id=payroll.id, employee_id=s.budi.id).one()
    assert row.payroll_detail_id == detail.id
    assert detail.exit_compensation == preview["compensation"]
    gross = Decimal("1000000") + preview["compensation"]  # 10/30 hari September
    assert detail.charge_deduction == (gross * Decimal("0.5")).quantize(Decimal("1"), rounding=ROUND_DOWN)

    payroll.status = "FINAL"
    ok, message, _ = create_payroll_journal_for_payroll(payroll, s.admin.id)
    assert ok, message
    assert row.status == "SELESAI" and s.budi.status == "INACTIVE" and contract.status == "BERAKHIR"


def test_kontrak_habis_harus_di_tanggal_selesai(ctx):
    from app.services.employee_exit_service import create_exit
    from app.services.workforce_service import WorkforceError

    s = _setup(ctx)
    _contract(s, s.budi, start=date(2026, 1, 1), end=date(2026, 6, 30))
    with pytest.raises(WorkforceError, match="30-06-2026"):
        create_exit(s.budi, exit_type="HABIS_KONTRAK", reason_code="KONTRAK_HABIS", notice_date=date(2026, 6, 1),
                    effective_date=date(2026, 6, 20), user_id=s.admin.id)
    row = create_exit(s.budi, exit_type="HABIS_KONTRAK", reason_code="KONTRAK_HABIS", notice_date=date(2026, 6, 1),
                      effective_date=date(2026, 6, 30), user_id=s.admin.id)
    assert row.short_notice_days == 0


# --- kebutuhan orang ---------------------------------------------------------


def test_kebutuhan_orang_dari_porsi_besok(ctx):
    from app.models.master import Client, DeliveryLocation, Mandor
    from app.models.operational import DailyOrder, DailyOrderDetail
    from app.services.workforce_attendance_service import create_leave, staffing_forecast
    from app.utils.clock import today_wib

    s = _setup(ctx)
    tomorrow = today_wib() + timedelta(days=1)
    client = Client(name=f"PT Uji {uuid4().hex[:6]}", is_active=True)
    ctx.session.add(client)
    ctx.session.flush()
    mandor = Mandor(branch_id=s.branch.id, client_id=client.id, name="Mandor Uji", is_active=True)
    ctx.session.add(mandor)
    ctx.session.flush()
    location = DeliveryLocation(mandor_id=mandor.id, location_name="Proyek Uji", is_active=True)
    ctx.session.add(location)
    ctx.session.flush()
    order = DailyOrder(order_number=f"DO-{uuid4().hex[:10]}", branch_id=s.branch.id, order_date=tomorrow,
                       status="DRAFT", created_by=s.owner.id)
    ctx.session.add(order)
    ctx.session.flush()
    ctx.session.add(DailyOrderDetail(daily_order_id=order.id, mandor_id=mandor.id, delivery_location_id=location.id,
                                     price_per_portion=Decimal("20000"), lunch_qty=130, dinner_qty=50, total_qty=180))
    ctx.session.flush()
    create_leave(s.sari, leave_type="PULANG_KAMPUNG", start_date=tomorrow, expected_return_date=tomorrow + timedelta(days=3),
                 reason="Mudik", user=s.admin)

    forecast = staffing_forecast(s.branch.id, tomorrow)
    assert [(x["portions"], x["needed"]) for x in forecast["sessions"]] == [(130, 3), (50, 1)]
    assert forecast["available"] == 1 and forecast["shortage"] == 2
    assert [r.id for r in forecast["reserves"]] == [s.reserve.id]


# --- halaman & hak akses -----------------------------------------------------


def test_halaman_sdm_terbuka_dan_admin_operasional_hanya_apel_izin(app, ctx):
    from app.models.workforce import EmployeeAbsenceCase
    from app.services.employee_exit_service import create_exit
    from app.services.workforce_attendance_service import issue_summons, open_absence_case
    from app.utils.clock import today_wib

    s = _setup(ctx)
    contract = _contract(s, s.budi, end=today_wib() + timedelta(days=200))
    draft = _contract(s, s.sari, sign=False)
    case = open_absence_case(s.budi, today_wib() - timedelta(days=2), s.admin.id)
    issue_summons(case, 1, today_wib() - timedelta(days=1))
    row = create_exit(s.budi, exit_type="RESIGN", reason_code="KELUARGA", notice_date=today_wib(),
                      effective_date=today_wib() + timedelta(days=30), user_id=s.admin.id)

    owner = _login(app, s.owner)
    for url in (
        "/sdm/", "/sdm/apel", "/sdm/izin", "/sdm/izin/baru", "/sdm/mangkir", f"/sdm/mangkir/{case.id}",
        f"/sdm/mangkir/{case.id}/panggilan/1/cetak", "/sdm/kontrak", "/sdm/kontrak/baru",
        f"/sdm/kontrak/{contract.id}", f"/sdm/kontrak/{contract.id}/cetak", f"/sdm/kontrak/{draft.id}/ttd-karyawan",
        f"/sdm/karyawan/{s.budi.id}", "/sdm/denda", "/sdm/keluar", "/sdm/keluar/baru", f"/sdm/keluar/{row.id}",
        "/sdm/laporan", f"/sdm/kontrak/{contract.id}/ktp",
    ):
        response = owner.get(url)
        assert response.status_code == 200, url
    assert "Pasal 62" in owner.get(f"/sdm/kontrak/{contract.id}").get_data(as_text=True)

    ops = _login(app, s.admin_operasional)
    apel = ops.get("/sdm/apel")
    assert apel.status_code == 200 and "ops-mobile-shell" in apel.get_data(as_text=True)
    assert "Apel Tim" in apel.get_data(as_text=True)
    assert ops.get("/sdm/izin/baru").status_code == 200
    for url in ("/sdm/", "/sdm/denda", "/sdm/kontrak", f"/sdm/kontrak/{contract.id}/ktp"):
        assert ops.get(url).status_code == 302, url
    response = ops.post("/sdm/apel", data={"tanggal": today_wib().isoformat(), f"status_{s.sari.id}": "ALPA"})
    assert response.status_code == 302
    assert EmployeeAbsenceCase.query.filter_by(employee_id=s.sari.id).count() == 1

    admin = _login(app, s.admin)
    assert admin.post(f"/sdm/kontrak/{draft.id}/ttd-perusahaan", data={"signature_data": _signature()}).status_code == 302
    assert draft.status == "DRAFT"


def test_tanda_tangan_tidak_valid_ditolak():
    from app.services.workforce_service import WorkforceError, signature_file

    with pytest.raises(WorkforceError):
        signature_file("data:image/jpeg;base64,AAAA", "x")
    with pytest.raises(WorkforceError):
        signature_file("data:image/png;base64,bukan-base64!!", "x")
    with pytest.raises(WorkforceError, match="terlalu pendek"):
        import base64

        signature_file("data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 10).decode(), "x")
    assert signature_file(_signature(), "ttd").filename == "ttd.png"


# --- navigasi SDM satu pintu & batas cabang ---------------------------------


def test_menu_sdm_empat_dan_tiap_halaman_satu_pintu():
    from app.services.hr_navigation_service import HR_SECTIONS, hr_section_for

    assert [s["label"] for s in HR_SECTIONS] == ["Ringkasan SDM", "Karyawan & Kontrak", "Kehadiran & Disiplin", "Penggajian"]
    seen = [endpoint for s in HR_SECTIONS for tab in s["tabs"] for endpoint in tab["endpoints"]]
    assert len(seen) == len(set(seen)), "satu halaman hanya boleh punya satu pintu"
    assert hr_section_for("hr.payroll_detail")["key"] == "payroll"
    assert hr_section_for("workforce.employee_detail")["key"] == "people"
    templates = [
        "hr/employees.html", "hr/employee_form.html", "hr/payrolls.html", "hr/payroll_detail.html",
        "hr/payroll_generate.html", "hr/payroll_payment_history.html",
    ]
    from pathlib import Path

    for name in templates:
        text = Path("app/templates", name).read_text(encoding="utf-8")
        assert "Aksi SDM" not in text and "Aksi Payroll" not in text and "dropdown" not in text, name


def test_sdm_lama_tidak_membuka_data_cabang_lain_dan_kontrak_menahan_nonaktif(app, ctx):
    from app.models.master import Branch, Employee

    s = _setup(ctx)
    other = Branch(code=f"LAIN-{uuid4().hex[:6]}", name="Cabang Lain", is_active=True)
    ctx.session.add(other)
    ctx.session.flush()
    stranger = Employee(branch_id=other.id, full_name="Orang Cabang Lain", status="ACTIVE", employee_type="KARYAWAN")
    ctx.session.add(stranger)
    ctx.session.flush()
    _contract(s, s.budi)

    owner = _login(app, s.owner)
    assert owner.get(f"/hr/employees/{stranger.id}/edit").status_code == 404
    assert "Orang Cabang Lain" not in owner.get("/hr/employees?status=ALL").get_data(as_text=True)
    assert owner.get("/hr/").headers["Location"].endswith("/sdm/")

    response = owner.post(f"/hr/employees/{s.budi.id}/toggle")
    assert "/sdm/keluar/baru" in response.headers["Location"] and s.budi.status == "ACTIVE"
