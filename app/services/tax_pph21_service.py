"""Modul Pajak Pusat: Perhitungan PPh Pasal 21 Karyawan (Fase 8).

Dasar hukum (sumber kebenaran):
- PP Nomor 58 Tahun 2023: Tarif Pemotongan PPh Pasal 21 atas Penghasilan Sehubungan dengan
  Pekerjaan, Jasa, atau Kegiatan Wajib Pajak Orang Pribadi (Tarif Efektif Rata-rata / TER).
- PMK Nomor 168 Tahun 2023: Petunjuk Pelaksanaan Pemotongan Pajak atas Penghasilan Sehubungan
  dengan Pekerjaan, Jasa, atau Kegiatan Orang Pribadi.
- UU Nomor 7 Tahun 2021 tentang Harmonisasi Peraturan Perpajakan (UU HPP): Tarif Pasal 17 ayat (1) huruf a
  dan ketentuan PTKP.

Prinsip:
1. Seluruh tarif, PTKP, tabel TER, dan logika perhitungan PPh 21 hanya berada di modul pajak pusat ini.
2. Modul HR/penggajian hanya memanggil fungsi di modul ini untuk menghitung dan mencatat snapshot.
3. Karyawan aktif tanpa PTKP dihitung sementara dengan TK/0 + diberi peringatan.
4. Masa Januari-November (bukan keluar): TER bulanan x bruto bulan itu.
5. Masa Desember atau masa terakhir karyawan keluar: perhitungan tahunan (tarif Pasal 17 UU HPP).
6. Bruto pajak = upah yang benar-benar dibayar (base_salary + bonus + exit_compensation - deduction).
   Denda/ganti rugi TIDAK mengurangi bruto pajak.
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date
from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN
from typing import Optional

from app.extensions import db
from app.models.hr import Payroll, PayrollDetail
from app.models.master import Employee
from app.models.workforce import EmployeeExit

ZERO = Decimal("0")
ONE_HUNDRED = Decimal("100")

# PTKP Tahunan sesuai UU HPP
# TK/0 Rp 54.000.000; tambahan kawin Rp 4.500.000; tanggungan Rp 4.500.000/orang (maks 3)
PTKP_RATES: dict[str, Decimal] = {
    "TK/0": Decimal("54000000"),
    "TK/1": Decimal("58500000"),
    "TK/2": Decimal("63000000"),
    "TK/3": Decimal("67500000"),
    "K/0": Decimal("58500000"),
    "K/1": Decimal("63000000"),
    "K/2": Decimal("67500000"),
    "K/3": Decimal("72000000"),
}

DEFAULT_PTKP = "TK/0"

# Kategori TER berdasarkan status PTKP (PP 58/2023 Pasal 2 ayat 2)
# Kategori A: TK/0, TK/1, K/0
# Kategori B: TK/2, TK/3, K/1, K/2
# Kategori C: K/3
TER_CATEGORIES: dict[str, str] = {
    "TK/0": "A",
    "TK/1": "A",
    "K/0": "A",
    "TK/2": "B",
    "TK/3": "B",
    "K/1": "B",
    "K/2": "B",
    "K/3": "C",
}

# Biaya Jabatan (PMK 168/2023 Pasal 10 ayat 2)
# 5% dari penghasilan bruto, maks Rp 500.000/bulan atau Rp 6.000.000/tahun
BIAYA_JABATAN_RATE = Decimal("0.05")
MAX_BIAYA_JABATAN_MONTHLY = Decimal("500000")
MAX_BIAYA_JABATAN_ANNUAL = Decimal("6000000")

# Tabel TER Bulanan PP 58/2023 Lampiran (diverifikasi Claude 2026-10-11 terhadap salinan Lampiran;
# owner tetap wajib mencentang verifikasi di Pengaturan Pajak sebelum dipakai).
# Struktur: list tuple (batas_atas_bruto_inklusif, tarif_persen)
# Batas atas None menandakan lapisan tertinggi (> batas sebelumnya)
TER_TABLE_A: list[tuple[Optional[Decimal], Decimal]] = [
    (Decimal("5400000"), Decimal("0")),
    (Decimal("5650000"), Decimal("0.25")),
    (Decimal("5950000"), Decimal("0.50")),
    (Decimal("6300000"), Decimal("0.75")),
    (Decimal("6750000"), Decimal("1.00")),
    (Decimal("7500000"), Decimal("1.25")),
    (Decimal("8550000"), Decimal("1.50")),
    (Decimal("9650000"), Decimal("1.75")),
    (Decimal("10050000"), Decimal("2.00")),
    (Decimal("10350000"), Decimal("2.25")),
    (Decimal("10700000"), Decimal("2.50")),
    (Decimal("11050000"), Decimal("3.00")),
    (Decimal("11600000"), Decimal("3.50")),
    (Decimal("12500000"), Decimal("4.00")),
    (Decimal("13750000"), Decimal("5.00")),
    (Decimal("15100000"), Decimal("6.00")),
    (Decimal("16950000"), Decimal("7.00")),
    (Decimal("19750000"), Decimal("8.00")),
    (Decimal("24150000"), Decimal("9.00")),
    (Decimal("26450000"), Decimal("10.00")),
    (Decimal("28000000"), Decimal("11.00")),
    (Decimal("30050000"), Decimal("12.00")),
    (Decimal("32400000"), Decimal("13.00")),
    (Decimal("35400000"), Decimal("14.00")),
    (Decimal("39100000"), Decimal("15.00")),
    (Decimal("43850000"), Decimal("16.00")),
    (Decimal("47800000"), Decimal("17.00")),
    (Decimal("51400000"), Decimal("18.00")),
    (Decimal("56300000"), Decimal("19.00")),
    (Decimal("62200000"), Decimal("20.00")),
    (Decimal("68600000"), Decimal("21.00")),
    (Decimal("77500000"), Decimal("22.00")),
    (Decimal("89000000"), Decimal("23.00")),
    (Decimal("103000000"), Decimal("24.00")),
    (Decimal("125000000"), Decimal("25.00")),
    (Decimal("157000000"), Decimal("26.00")),
    (Decimal("206000000"), Decimal("27.00")),
    (Decimal("337000000"), Decimal("28.00")),
    (Decimal("454000000"), Decimal("29.00")),
    (Decimal("550000000"), Decimal("30.00")),
    (Decimal("695000000"), Decimal("31.00")),
    (Decimal("910000000"), Decimal("32.00")),
    (Decimal("1400000000"), Decimal("33.00")),
    (None, Decimal("34.00")),
]

TER_TABLE_B: list[tuple[Optional[Decimal], Decimal]] = [  # Lampiran PP 58/2023 Kategori B (40 lapisan)
    (Decimal("6200000"), Decimal("0")),
    (Decimal("6500000"), Decimal("0.25")),
    (Decimal("6850000"), Decimal("0.50")),
    (Decimal("7300000"), Decimal("0.75")),
    (Decimal("9200000"), Decimal("1.00")),
    (Decimal("10750000"), Decimal("1.50")),
    (Decimal("11250000"), Decimal("2.00")),
    (Decimal("11600000"), Decimal("2.50")),
    (Decimal("12600000"), Decimal("3.00")),
    (Decimal("13600000"), Decimal("4.00")),
    (Decimal("14950000"), Decimal("5.00")),
    (Decimal("16400000"), Decimal("6.00")),
    (Decimal("18450000"), Decimal("7.00")),
    (Decimal("21850000"), Decimal("8.00")),
    (Decimal("26000000"), Decimal("9.00")),
    (Decimal("27700000"), Decimal("10.00")),
    (Decimal("29350000"), Decimal("11.00")),
    (Decimal("31450000"), Decimal("12.00")),
    (Decimal("33950000"), Decimal("13.00")),
    (Decimal("37100000"), Decimal("14.00")),
    (Decimal("41100000"), Decimal("15.00")),
    (Decimal("45800000"), Decimal("16.00")),
    (Decimal("49500000"), Decimal("17.00")),
    (Decimal("53800000"), Decimal("18.00")),
    (Decimal("58500000"), Decimal("19.00")),
    (Decimal("64000000"), Decimal("20.00")),
    (Decimal("71000000"), Decimal("21.00")),
    (Decimal("80000000"), Decimal("22.00")),
    (Decimal("93000000"), Decimal("23.00")),
    (Decimal("109000000"), Decimal("24.00")),
    (Decimal("129000000"), Decimal("25.00")),
    (Decimal("163000000"), Decimal("26.00")),
    (Decimal("211000000"), Decimal("27.00")),
    (Decimal("374000000"), Decimal("28.00")),
    (Decimal("459000000"), Decimal("29.00")),
    (Decimal("555000000"), Decimal("30.00")),
    (Decimal("704000000"), Decimal("31.00")),
    (Decimal("957000000"), Decimal("32.00")),
    (Decimal("1405000000"), Decimal("33.00")),
    (None, Decimal("34.00")),
]

TER_TABLE_C: list[tuple[Optional[Decimal], Decimal]] = [  # Lampiran PP 58/2023 Kategori C (41 lapisan)
    (Decimal("6600000"), Decimal("0")),
    (Decimal("6950000"), Decimal("0.25")),
    (Decimal("7350000"), Decimal("0.50")),
    (Decimal("7800000"), Decimal("0.75")),
    (Decimal("8850000"), Decimal("1.00")),
    (Decimal("9800000"), Decimal("1.25")),
    (Decimal("10950000"), Decimal("1.50")),
    (Decimal("11200000"), Decimal("1.75")),
    (Decimal("12050000"), Decimal("2.00")),
    (Decimal("12950000"), Decimal("3.00")),
    (Decimal("14150000"), Decimal("4.00")),
    (Decimal("15550000"), Decimal("5.00")),
    (Decimal("17050000"), Decimal("6.00")),
    (Decimal("19500000"), Decimal("7.00")),
    (Decimal("22700000"), Decimal("8.00")),
    (Decimal("26600000"), Decimal("9.00")),
    (Decimal("28100000"), Decimal("10.00")),
    (Decimal("30100000"), Decimal("11.00")),
    (Decimal("32600000"), Decimal("12.00")),
    (Decimal("35400000"), Decimal("13.00")),
    (Decimal("38900000"), Decimal("14.00")),
    (Decimal("43000000"), Decimal("15.00")),
    (Decimal("47400000"), Decimal("16.00")),
    (Decimal("51200000"), Decimal("17.00")),
    (Decimal("55800000"), Decimal("18.00")),
    (Decimal("60400000"), Decimal("19.00")),
    (Decimal("66700000"), Decimal("20.00")),
    (Decimal("74500000"), Decimal("21.00")),
    (Decimal("83200000"), Decimal("22.00")),
    (Decimal("95600000"), Decimal("23.00")),
    (Decimal("110000000"), Decimal("24.00")),
    (Decimal("134000000"), Decimal("25.00")),
    (Decimal("169000000"), Decimal("26.00")),
    (Decimal("221000000"), Decimal("27.00")),
    (Decimal("390000000"), Decimal("28.00")),
    (Decimal("463000000"), Decimal("29.00")),
    (Decimal("561000000"), Decimal("30.00")),
    (Decimal("709000000"), Decimal("31.00")),
    (Decimal("965000000"), Decimal("32.00")),
    (Decimal("1419000000"), Decimal("33.00")),
    (None, Decimal("34.00")),
]

TER_TABLES_REGISTRY: dict[str, list[tuple[Optional[Decimal], Decimal]]] = {
    "A": TER_TABLE_A,
    "B": TER_TABLE_B,
    "C": TER_TABLE_C,
}

# Lapisan Tarif Pasal 17 ayat (1) huruf a UU HPP
PASAL_17_BRACKETS: list[tuple[Optional[Decimal], Decimal]] = [
    (Decimal("60000000"), Decimal("0.05")),       # s.d. 60 juta: 5%
    (Decimal("250000000"), Decimal("0.15")),      # > 60 jt s.d. 250 jt: 15%
    (Decimal("500000000"), Decimal("0.25")),      # > 250 jt s.d. 500 jt: 25%
    (Decimal("5000000000"), Decimal("0.30")),     # > 500 jt s.d. 5 M: 30%
    (None, Decimal("0.35")),                      # > 5 M: 35%
]


def _money(value) -> Decimal:
    if value is None:
        return ZERO
    return Decimal(str(value)).quantize(Decimal("0.01"))


def _round_rupiah(value: Decimal) -> Decimal:
    """Pembulatan rupiah utuh setengah ke atas."""
    return Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def get_ter_category(ptkp_status: Optional[str]) -> str:
    """Mengembalikan kategori TER (A, B, atau C) berdasarkan status PTKP.

    Bila status belum diisi, dikembalikan kategori A (default TK/0).
    """
    clean_status = str(ptkp_status or "").strip().upper()
    return TER_CATEGORIES.get(clean_status, "A")


def lookup_ter_rate(ter_category: str, monthly_gross: Decimal) -> Decimal:
    """Mencari persentase tarif TER (PP 58/2023) untuk kategori dan nominal bruto bulanan."""
    table = TER_TABLES_REGISTRY.get(ter_category, TER_TABLE_A)
    gross = Decimal(str(monthly_gross or 0))
    if gross <= ZERO:
        return ZERO

    for upper_limit, rate in table:
        if upper_limit is None or gross <= upper_limit:
            return rate
    return Decimal("34.00")


def calculate_pasal_17_tax(pkp: Decimal) -> Decimal:
    """Menghitung pajak terutang setahun berdasarkan tarif progresif Pasal 17 ayat (1) huruf a UU HPP."""
    pkp_val = max(ZERO, Decimal(str(pkp or 0)))
    if pkp_val <= ZERO:
        return ZERO

    tax = ZERO
    prev_limit = ZERO
    for upper_limit, rate in PASAL_17_BRACKETS:
        if upper_limit is None:
            taxable_in_bracket = pkp_val - prev_limit
            tax += taxable_in_bracket * rate
            break
        elif pkp_val > upper_limit:
            taxable_in_bracket = upper_limit - prev_limit
            tax += taxable_in_bracket * rate
            prev_limit = upper_limit
        else:
            taxable_in_bracket = pkp_val - prev_limit
            tax += taxable_in_bracket * rate
            break

    return _round_rupiah(tax)


def calculate_taxable_gross(detail: PayrollDetail) -> Decimal:
    """Menghitung bruto kena pajak untuk satu baris penggajian.

    Aturan:
    Bruto = upah yang benar-benar dibayar (setelah prorata & potongan hari tidak bekerja)
            + bonus + kompensasi akhir PKWT.
    Rumus: base_salary + bonus + exit_compensation - deduction.
    Denda/ganti rugi TIDAK mengurangi bruto pajak.
    """
    base = Decimal(str(detail.base_salary or 0))
    bonus = Decimal(str(detail.bonus or 0))
    compensation = Decimal(str(detail.exit_compensation or 0))
    deduction = Decimal(str(detail.deduction or 0))
    gross = base + bonus + compensation - deduction
    return max(ZERO, _money(gross))


def is_final_tax_period(payroll: Payroll, employee_id: int) -> bool:
    """Menentukan apakah periode penggajian ini adalah masa pajak terakhir karyawan.

    Masa terakhir adalah:
    1. Bulan Desember (period_month == 12); ATAU
    2. Karyawan berhenti/keluar pada bulan tersebut (ada EmployeeExit terkait detail payroll ini).
    """
    if payroll.period_month == 12:
        return True

    last_day = monthrange(payroll.period_year, payroll.period_month)[1]
    period_start = date(payroll.period_year, payroll.period_month, 1)
    period_end = date(payroll.period_year, payroll.period_month, last_day)

    # Cek apakah karyawan memiliki pencatatan keluar yang berlaku di bulan ini
    # Hanya keluar yang sudah disetujui/selesai; pengajuan atau yang dibatalkan bukan masa terakhir.
    exit_record = EmployeeExit.query.filter(
        EmployeeExit.employee_id == employee_id,
        EmployeeExit.status.in_(("DISETUJUI", "SELESAI")),
        EmployeeExit.last_work_date >= period_start,
        EmployeeExit.last_work_date <= period_end,
    ).first()

    return exit_record is not None


def get_ytd_prior_payroll_history(branch_id: int, employee_id: int, year: int, current_month: int) -> dict:
    """Mengambil riwayat bruto pajak dan PPh 21 yang sudah dipotong di masa pajak sebelumnya

    pada tahun pajak yang sama (Januari s.d. bulan sebelum current_month).
    Hanya memperhitungkan penggajian yang sudah FINAL, POSTED, atau PAID (bukan DRAFT masa lain).
    """
    prior_details = (
        PayrollDetail.query
        .join(Payroll, Payroll.id == PayrollDetail.payroll_id)
        .filter(
            Payroll.branch_id == branch_id,
            PayrollDetail.employee_id == employee_id,
            Payroll.period_year == year,
            Payroll.period_month < current_month,
            Payroll.status.in_(("FINAL", "POSTED", "PAID")),
        )
        .order_by(Payroll.period_month.asc())
        .all()
    )

    total_gross = ZERO
    total_tax_paid = ZERO
    months_worked = set()

    for d in prior_details:
        gross = d.tax_bruto if d.tax_bruto is not None else calculate_taxable_gross(d)
        total_gross += Decimal(str(gross or 0))
        total_tax_paid += Decimal(str(d.pph21_amount or 0))
        months_worked.add(d.payroll.period_month)

    return {
        "prior_gross": _money(total_gross),
        "prior_tax": _money(total_tax_paid),
        "months_count": len(months_worked),
    }


def compute_annual_tax_reconciliation(
    detail: PayrollDetail,
    payroll: Payroll,
    ptkp_status: str,
    months_in_year: int = 12
) -> tuple[Decimal, Decimal, Decimal, str]:
    """Menghitung PPh 21 masa terakhir secara tahunan (Pasal 17 UU HPP).

    Mengembalikan tuple: (pph21_bulan_ini, bruto_setahun, pph21_setahun, catatan)
    """
    history = get_ytd_prior_payroll_history(
        branch_id=payroll.branch_id,
        employee_id=detail.employee_id,
        year=payroll.period_year,
        current_month=payroll.period_month,
    )

    current_gross = calculate_taxable_gross(detail)
    annual_gross = history["prior_gross"] + current_gross

    # Jumlah bulan bekerja dalam tahun berjalan
    # Minimal 1 bulan, maksimal 12 bulan
    months_worked = max(1, min(12, history["months_count"] + 1))

    # Biaya Jabatan 5%, maks Rp 500.000 per bulan bekerja
    max_biaya_jabatan = MAX_BIAYA_JABATAN_MONTHLY * Decimal(months_worked)
    biaya_jabatan = min(annual_gross * BIAYA_JABATAN_RATE, max_biaya_jabatan)
    biaya_jabatan = _round_rupiah(biaya_jabatan)

    netto_annual = max(ZERO, annual_gross - biaya_jabatan)

    # PTKP setahun
    ptkp = PTKP_RATES.get(ptkp_status, PTKP_RATES[DEFAULT_PTKP])

    # PKP = Netto setahun - PTKP, dibulatkan ke bawah ke ribuan penuh
    raw_pkp = max(ZERO, netto_annual - ptkp)
    pkp = (raw_pkp // Decimal("1000")) * Decimal("1000")

    annual_tax = calculate_pasal_17_tax(pkp)

    # PPh 21 masa ini = PPh 21 setahun - PPh 21 Jan s.d. bulan sebelumnya
    tax_due = annual_tax - history["prior_tax"]

    note_parts = []
    if tax_due < ZERO:
        note_parts.append(f"Lebih bayar PPh 21 setahun sebesar Rp{abs(tax_due):,.0f} diperhitungkan sebagai pengembalian.")

    return _round_rupiah(tax_due), annual_gross, annual_tax, "; ".join(note_parts)


def compute_payroll_detail_pph21(detail: PayrollDetail, payroll: Payroll) -> Decimal:
    """Fungsi utama: menghitung PPh 21 untuk satu PayrollDetail dan mengisi snapshot-nya.

    Hanya dijalankan saat penggajian berstatus DRAFT.
    Memeriksa konfigurasi pajak cabang dari modul pajak pusat.
    """
    from app.services.tax_service import get_tax_settings

    settings = get_tax_settings(payroll.branch_id)
    pph21_enabled = settings.get("pph21_enabled", False)
    effective_from = settings.get("pph21_effective_from")
    borne_by = settings.get("pph21_borne_by", "KARYAWAN")

    last_day = monthrange(payroll.period_year, payroll.period_month)[1]
    period_end = date(payroll.period_year, payroll.period_month, last_day)

    # Bila fitur tidak aktif atau tanggal efektif belum tercapai -> tidak dihitung (snapshot kosong)
    if not pph21_enabled or (effective_from and period_end < effective_from):
        detail.tax_bruto = None
        detail.pph21_amount = ZERO
        detail.pph21_method = None
        detail.ter_category = None
        detail.ter_rate = None
        detail.pph21_borne_by = None
        detail.ptkp_status = None
        detail.pph21_note = None
        return ZERO

    employee = detail.employee or db.session.get(Employee, detail.employee_id)
    raw_ptkp = getattr(employee, "ptkp_status", None)
    clean_ptkp = str(raw_ptkp or "").strip().upper()
    ptkp_status = clean_ptkp if clean_ptkp in PTKP_RATES else DEFAULT_PTKP

    notes = []
    if not raw_ptkp:
        notes.append("Status PTKP belum diatur di data karyawan; dihitung sementara dengan TK/0.")

    gross = calculate_taxable_gross(detail)
    detail.tax_bruto = gross
    detail.ptkp_status = ptkp_status
    detail.pph21_borne_by = borne_by

    is_final = is_final_tax_period(payroll, detail.employee_id)

    if is_final:
        # Perhitungan Masa Terakhir / Tahunan (Desember atau Karyawan Keluar)
        tax_amount, annual_gross, annual_tax, recon_note = compute_annual_tax_reconciliation(
            detail=detail,
            payroll=payroll,
            ptkp_status=ptkp_status,
        )
        detail.pph21_amount = tax_amount
        detail.pph21_method = "TAHUNAN"
        detail.ter_category = get_ter_category(ptkp_status)
        detail.ter_rate = ZERO  # Masa tahunan tidak menggunakan persentase tunggal TER
        if recon_note:
            notes.append(recon_note)
    else:
        # Perhitungan Masa Reguler (Januari - November) menggunakan TER Bulanan
        category = get_ter_category(ptkp_status)
        rate = lookup_ter_rate(category, gross)
        tax_amount = _round_rupiah(gross * rate / ONE_HUNDRED)

        detail.pph21_amount = tax_amount
        detail.pph21_method = "TER"
        detail.ter_category = category
        detail.ter_rate = rate

    detail.pph21_note = " | ".join(notes) if notes else None
    return detail.pph21_amount


def compute_annual_1721_a1(employee: Employee, year: int, branch_id: int) -> dict:
    """Menyusun data Bukti Potong 1721-A1 tahunan untuk karyawan."""
    from app.services.company_settings_service import get_company_settings

    details = (
        PayrollDetail.query
        .join(Payroll, Payroll.id == PayrollDetail.payroll_id)
        .filter(
            Payroll.branch_id == branch_id,
            PayrollDetail.employee_id == employee.id,
            Payroll.period_year == year,
            Payroll.status.in_(("POSTED", "PAID", "FINAL")),
        )
        .order_by(Payroll.period_month.asc())
        .all()
    )

    total_gross = ZERO
    total_tax = ZERO
    months_worked = len(details)

    for d in details:
        gross = d.tax_bruto if d.tax_bruto is not None else calculate_taxable_gross(d)
        total_gross += Decimal(str(gross or 0))
        total_tax += Decimal(str(d.pph21_amount or 0))

    clean_ptkp = str(employee.ptkp_status or "").strip().upper()
    ptkp_status = clean_ptkp if clean_ptkp in PTKP_RATES else DEFAULT_PTKP
    ptkp = PTKP_RATES.get(ptkp_status, PTKP_RATES[DEFAULT_PTKP])

    max_biaya_jabatan = MAX_BIAYA_JABATAN_MONTHLY * Decimal(max(1, months_worked))
    biaya_jabatan = min(total_gross * BIAYA_JABATAN_RATE, max_biaya_jabatan)
    biaya_jabatan = _round_rupiah(biaya_jabatan)

    netto = max(ZERO, total_gross - biaya_jabatan)
    raw_pkp = max(ZERO, netto - ptkp)
    pkp = (raw_pkp // Decimal("1000")) * Decimal("1000")
    tax_annual = calculate_pasal_17_tax(pkp)

    company = get_company_settings(branch_id)

    return {
        "year": year,
        "employee": employee,
        "company": company,
        "months_worked": months_worked,
        "gross_salary": total_gross,
        "biaya_jabatan": biaya_jabatan,
        "netto": netto,
        "ptkp_status": ptkp_status,
        "ptkp_amount": ptkp,
        "pkp": pkp,
        "pph21_annual": tax_annual,
        "pph21_withheld": total_tax,
        "difference": tax_annual - total_tax,
    }
