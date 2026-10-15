# Tugas: PPh 21 karyawan, terintegrasi penuh dengan MODUL PAJAK PUSAT (Fase 8)

Kamu bekerja di ERP Flask (Flask + Jinja2 + SQLAlchemy + Alembic + PostgreSQL) milik PT Idha Boga Pangan Mandiri. Balas dan tulis label UI dalam **Bahasa Indonesia**. Baca dulu `RENCANA_PENGEMBANGAN_ERP.md` (sumber kebenaran; entri "Riwayat perubahan" 2026-10-11 tentang Modul Tenaga Kerja, Slip Gaji, Aturan Potongan).

## Prinsip utama (wajib)
**Aturan & tarif pajak hanya ada di modul pajak pusat**, bukan di modul HR. Modul HR/penggajian *memanggil* modul pajak.
- Tarif, PTKP, kategori TER, tabel TER, tarif Pasal 17, biaya jabatan, tanggal berlaku, siapa penanggung PPh 21 → di `app/services/tax_service.py` (atau file baru `app/services/tax_pph21_service.py` **di bawah modul pajak** yang di-import oleh `tax_service`), pengaturannya di halaman pengaturan pajak yang sudah ada (`/finance/tax/settings`, template `app/templates/finance/tax_settings.html`, `SETTING_DEFAULTS` + `get_tax_settings`/`save_tax_settings` di `tax_service.py`).
- Laporan masa pajak, pengingat jatuh tempo, dan setoran memakai mesin yang sudah ada: `build_tax_month`, `tax_warnings`, `run_tax_reminders`, `record_tax_payment`, `TAX_PAYMENT_TYPES`/`TAX_PAYMENT_LABELS`/`TAX_PAYMENT_DEBIT` di `tax_service.py`; model `app/models/tax.py`; halaman `/finance/tax` (`app/templates/finance/tax.html`, route `app/routes/finance/tax_routes.py`).

## Kondisi kode penggajian sekarang (jangan dirusak)
- Buat penggajian: `hr_service.generate_payroll` → `workforce_payroll_service.sync_payroll_workforce` (karyawan keluar + potongan denda/ganti rugi).
- Baris gaji `PayrollDetail` (`app/models/hr.py`): `base_salary`, `bonus`, `deduction` (prorata + hari tidak bekerja), `exit_compensation`, `charge_deduction` (denda/ganti rugi), `unpaid_absence_days`, `final_salary`. Rumus di `employee_charge_service.recalculate_detail`: `final = base + bonus + exit_compensation − deduction − charge_deduction`. Batas potongan denda 50% di `allocate_detail_deductions` memakai `payroll_detail_gross`.
- Jurnal penggajian: `accounting_service.create_payroll_journal_for_payroll` → Dr 5004 (bruto) / Cr 2003 (neto) / Cr 1005 (denda); `finalize_payroll_workforce` dipanggil di situ. Pembayaran: `create_payroll_payment_journal_for_payroll` (Dr 2003 / Cr kas-bank).
- Slip: `app/services/payslip_service.py::build_payslip`, template `app/templates/hr/_payslip_sheet.html`; rincian penggajian `app/templates/hr/payroll_detail.html`.
- Tenaga `CADANGAN` (harian lepas) **tidak** ikut penggajian bulanan — di luar lingkup tugas ini.
- Head migrasi Alembic sekarang: `m1b2c3d4e5f6`.

## Aturan PPh 21 yang dipakai (PP 58/2023 + PMK 168/2023, tarif Pasal 17 UU HPP)
1. **Masa Januari–November**: PPh 21 = **TER bulanan** × penghasilan bruto bulan itu. Kategori TER dari status PTKP: **A** = TK/0, TK/1, K/0; **B** = TK/2, TK/3, K/1, K/2; **C** = K/3.
2. **Masa Desember atau masa terakhir karyawan keluar**: hitung setahun — bruto setahun − biaya jabatan (5%, maks Rp 6.000.000/tahun; disetahunkan proporsional bila bekerja < 12 bulan sesuai PMK 168/2023) − PTKP → PKP dibulatkan ke bawah ribuan → tarif Pasal 17 (5% s/d 60 jt; 15% >60–250 jt; 25% >250–500 jt; 30% >500 jt–5 M; 35% >5 M) → dikurangi PPh 21 yang sudah dipotong Jan–Nov. Lebih bayar → tampilkan sebagai pengembalian ke karyawan di masa itu (nilai negatif boleh, tapi neto tidak boleh di bawah 0; sisanya catat sebagai catatan).
3. **PTKP**: TK/0 Rp 54.000.000; tambahan kawin Rp 4.500.000; tanggungan Rp 4.500.000/orang (maks 3).
4. **Bruto** = upah yang benar-benar dibayar (gaji setelah prorata & potongan hari tidak bekerja) + bonus + `exit_compensation`. **Denda/ganti rugi TIDAK mengurangi bruto.** Tulis di RENCANA bahwa perlakuan kompensasi akhir PKWT perlu dikonfirmasi konsultan.
5. **Tabel TER A/B/C**: salin **persis** dari Lampiran PP 58/2023 ke satu struktur data dengan tanggal berlaku (`effective_from`) supaya bisa diganti bila aturan berubah. Jangan mengarang angka. Cantumkan sumber di docstring. Tampilkan banner di pengaturan pajak: "Tabel TER wajib dicek dengan Lampiran PP 58/2023 sebelum dipakai" sampai OWNER mencentang "Tabel TER sudah diverifikasi".
6. **Penanggung PPh 21** (pengaturan pajak, OWNER): `KARYAWAN` (dipotong dari gaji, bawaan) atau `PERUSAHAAN` (ditanggung, tidak mengurangi gaji; tanpa gross-up).
7. Saklar **"PPh 21 aktif mulai tanggal"** di pengaturan pajak. Sebelum aktif / tidak aktif → tidak ada perhitungan (perilaku lama tetap).

## Yang harus dibangun
1. **Data karyawan** (modul HR hanya menyimpan identitas, bukan tarif): kolom `ptkp_status` (TK/0…K/3) dan `npwp` (opsional; kosong = NIK dipakai sebagai NPWP) di `employees`; field di `app/templates/hr/employee_form.html` + `hr_service._apply_profile`/`PROFILE_FIELDS`. Karyawan aktif tanpa status PTKP → peringatan di Ringkasan SDM (`app/templates/workforce/index.html`, daftar "Perlu Tindakan") dan di rincian penggajian; hitung sementara dengan TK/0.
2. **Snapshot per baris gaji** (migrasi baru, revisi turunan `m1b2c3d4e5f6`): di `payroll_details` simpan `tax_bruto`, `pph21_amount`, `pph21_method` (TER/TAHUNAN), `ter_category`, `ter_rate`, `pph21_borne_by`. Dihitung oleh fungsi di modul pajak, mis. `tax_pph21_service.compute_payroll_detail_pph21(detail, payroll)`, dipanggil dari `generate_payroll`/`sync_payroll_workforce`/`update_payroll_detail_record` hanya saat penggajian DRAFT. Rumus neto baru: `final = bruto_dibayar − pph21 (bila KARYAWAN) − charge_deduction`. Batas 50% denda dihitung dari upah **setelah** PPh 21.
3. **Akuntansi**: akun baru lewat `app/services/bootstrap_service.py`: `2011 Hutang PPh 21` (LIABILITY) dan `5015 Beban PPh 21 Ditanggung Perusahaan` (EXPENSE). Jurnal penggajian: PPh 21 dipotong → tambah Cr 2011 (5004 tetap bruto); ditanggung perusahaan → tambah Dr 5015 / Cr 2011. Jurnal harus seimbang; tes jurnal yang ada tetap lulus bila PPh 21 tidak aktif.
4. **Setoran & laporan di modul pajak**: tambah `TAX_PAYMENT_PPH21 = "PPH21"` ke `TAX_PAYMENT_TYPES`, label "PPh Pasal 21 (karyawan)", debit `2011`. `build_tax_month` menampilkan PPh 21 terutang (jumlah `pph21_amount` dari penggajian yang sudah dicatat hutangnya pada masa itu), sudah disetor, selisih; jatuh tempo setor tgl 15 bulan berikutnya ikut `tax_warnings`/`run_tax_reminders`. Halaman `/finance/tax` menampilkan baris PPh 21 dengan tautan ke penggajian masa itu.
5. **Slip gaji**: baris "PPh 21 (TER kategori X, Y%)" atau "PPh 21 ditanggung perusahaan" + status PTKP; Desember/masa terakhir tampilkan "perhitungan tahunan". Rincian penggajian: kolom PPh 21 + total.
6. **Bukti potong tahunan 1721-A1** (cetak A4, gaya sama dengan `app/templates/hr/_doc_styles.html`): per karyawan per tahun, data dari snapshot penggajian; tombol cetak di profil karyawan (`app/templates/workforce/employee_detail.html`, kartu "Slip Gaji") dan cetak semua dari halaman pajak. Label jelas bahwa bukti potong resmi tetap dibuat di Coretax.

## Aturan kerja proyek (wajib)
- Service **tidak commit**; route membungkus mutasi dengan `atomic_business_action` (lihat `app/routes/workforce_routes.py::_run`). Uang `db.Numeric(18, 2)`, dihitung `Decimal`, dibulatkan ke rupiah. Tanggal pakai `today_wib()/now_wib()` dari `app/utils/clock.py`.
- Jangan ada `except Exception: pass` (tes `tests/test_exception_hygiene.py`). Filter GET memakai kelas `app-filter`. Kartu ringkasan punya ikon. Tanpa mode gelap. CSS internal di `app/static/css/app/*.css` lalu jalankan `python tools/build_css.py`.
- **Satu pintu per halaman**: jangan menambah menu/tombol yang menduplikasi navigasi (lihat `app/services/hr_navigation_service.py`). Pengaturan PPh 21 hanya di halaman pengaturan pajak.
- Hanya OWNER yang mengubah pengaturan pajak (pakai `_require_role` yang ada).
- Tambah entri **Riwayat perubahan** di `RENCANA_PENGEMBANGAN_ERP.md` (tanggal hari ini) berisi keputusan & batasan.

## Larangan keras
- JANGAN `git clean`, `git checkout -- .`, `git reset --hard`, `git add -A`, commit, push; jangan hapus file untracked.
- JANGAN sentuh `.env`, `storage/`, `instance/`, `app.zip`, `tools/reset_staging_demo.py`, tabel `ml_*`/`research_dataset_*`.
- JANGAN jalankan `flask db upgrade`/job/skrip apa pun ke database dev. Cukup tulis file migrasi.
- JANGAN simpan password Coretax di sistem.
- JANGAN mengarang tarif/tabel; bila ragu, tulis TODO jelas + tampilkan peringatan di layar.

## Tes (tulis, JANGAN jalankan pytest — owner yang menjalankan)
`tests/test_pph21.py`: kategori TER dari PTKP; contoh TER bulanan (ambil 3 titik dari Lampiran PP 58/2023 dan cantumkan barisnya di komentar); perhitungan Desember (biaya jabatan, PTKP, pembulatan PKP, Pasal 17, dikurangi Jan–Nov); karyawan keluar Juni → masa terakhir tahunan; jurnal seimbang untuk KARYAWAN vs PERUSAHAAN; PPh 21 tidak aktif → angka gaji sama persis seperti sebelumnya; batas 50% denda dari upah setelah PPh 21; setoran PPH21 mendebit 2011; `build_tax_month` menampilkan terutang/disetor; slip memuat baris PPh 21.

## Selesai → laporkan singkat
Daftar file yang diubah/dibuat + perintah untuk owner:
```
venv\Scripts\python.exe -m flask db upgrade
venv\Scripts\python.exe -m pytest -q tests/test_pph21.py tests/test_payslip.py tests/test_workforce_module.py tests/test_one_step_journals.py tests/test_hr_service_transactions.py
```
