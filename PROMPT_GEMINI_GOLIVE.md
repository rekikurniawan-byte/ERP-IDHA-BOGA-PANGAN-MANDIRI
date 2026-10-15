# Tugas: siap go-live pilot (dokumen + SOP SDM + 2 rapikan kecil)

ERP Flask (Flask/Jinja/SQLAlchemy/Alembic/PostgreSQL) PT Idha Boga Pangan Mandiri. Bahasa Indonesia untuk semua teks. Baca dulu `RENCANA_PENGEMBANGAN_ERP.md` bagian "Riwayat perubahan" 2026-10-11 s/d 2026-10-12 (modul SDM, slip, kasbon, PPh 21, Peraturan Perusahaan). Kerjakan per bagian, file kecil, jangan riset web.

## A. Daftar periksa go-live → `deployment/GO_LIVE_PILOT.md`
Satu dokumen langkah-demi-langkah untuk owner (bukan programmer), berupa checklist `[ ]`:
1. **Server**: rujuk `deployment/README_PRODUCTION_SERVER.md`, `deployment/nginx`, `deployment/systemd`, `deployment/gunicorn.conf.py`, `deployment/logrotate` — HTTPS/domain, `flask db upgrade`, `flask --app run ops-check` (harus 0 FAIL), backup harian + uji restore (`deployment/BACKUP_RESTORE_RECOVERY_SOP.md`), penjadwal `flask jobs` jalan (halaman Pengaturan → Tugas Otomatis), Gmail PT + App Password di `.env` (JANGAN tulis isinya), log error.
2. **Urutan isi data asli** (urutan penting, sebutkan menu persisnya): Pengaturan Perusahaan (logo, alamat, rekening) → Pengaturan Pajak → Saldo Awal (wizard) → pelanggan/client + sub client + lokasi + kontrak → harga → menu & jadwal menu → user per role → SDM: Aturan Gaji & Potongan → data karyawan (NIK, PTKP, kontak darurat) → kontrak kerja ditandatangani → cetak & ajukan Peraturan Perusahaan → apel hari pertama.
3. **Hari pertama & minggu pertama**: siapa melakukan apa (OWNER, ADMIN, ADMIN_OPERASIONAL, DAPUR, PENGANTAR), cek harian (Ringkasan SDM, Pembayaran Masuk, Tutup Harian, Cek Kesehatan Data harus 0 RISIKO).
4. Tambah satu baris di tabel fase RENCANA: `| Go-live | Daftar periksa go-live | Gemini | ✅ deployment/GO_LIVE_PILOT.md |` dan satu entri Riwayat perubahan bertanggal hari ini.

## B. SOP SDM di halaman SOP per role
SOP ada di `app/routes/sop_routes.py` (`SOP_LIBRARY`, slug per role, ditampilkan `sop.role_sop`). Tambahkan/ubah isi (bukan kode baru) supaya mencakup modul SDM, mengikuti struktur entri yang sudah ada (langkah, kesalahan umum, `work_links` endpoint yang benar):
- **ADMIN/HR**: tambah karyawan (`hr.create_employee`), buat & tanda tangan kontrak (`workforce.contract_create`), catat izin (`workforce.leave_create`), mangkir & surat panggilan (`workforce.cases`), denda (`workforce.charges`), kasbon (`workforce.advances`), karyawan keluar (`workforce.exits`), penggajian bulanan: Buat → Hitung Ulang → Kunci → Catat Hutang Gaji → Bayar (`hr.payrolls`), slip/WA/kwitansi.
- **OWNER**: keputusan di Ringkasan SDM (`workforce.index`), Aturan Gaji & Potongan (`workforce.rules`), tanda tangan kontrak, setujui denda & kasbon, aktifkan PPh 21 di pengaturan pajak (`finance.tax_settings`).
- **ADMIN_OPERASIONAL**: apel harian di HP (Dapur → Apel Tim, `workforce.attendance`), centang "Surat dokter" untuk sakit, catat izin.
- Gunakan hanya endpoint yang ada (cek dengan `grep "def <nama>" app/routes`). Tes `tests/test_route_endpoint_references.py` harus tetap lulus.

## C. Dua rapikan kecil
1. **Isian Peraturan Perusahaan**: di `app/services/workforce_service.py` tambah kunci ke `HR_SETTING_DEFAULTS`: `"hr.working_hours": ""` dan `"hr.fine_fund_usage": ""`; tampilkan sebagai 2 isian teks di kartu "4. Kontrak & operasional" pada `app/templates/workforce/rules.html` (label: "Jam kerja (untuk Peraturan Perusahaan)", "Penggunaan uang denda"); di `app/templates/workforce/company_regulation_print.html` pakai nilai itu menggantikan placeholder `[isi: ...]` bila terisi (bila kosong placeholder tetap). Nilai diteruskan lewat `settings["raw"]` dari route `workforce.company_regulation` di `app/routes/workforce_routes.py`.
2. **Tes rapuh** `tests/test_scheduler_service.py::test_scheduled_jobs_page_and_heartbeat_alert`: lulus di run penuh tapi gagal bila dijalankan sendiri karena bergantung pada data heartbeat penjadwal yang tersisa di DB tes. Buat tes itu menyiapkan sendiri kondisi heartbeat-nya (hapus/atur baris heartbeat di dalam tes sebelum mengecek pesan peringatan) supaya hasilnya sama baik dijalankan sendiri maupun bersama. Jangan ubah perilaku aplikasi.

## Larangan keras
- JANGAN `git clean`, `git checkout -- .`, `git reset --hard`, `git add -A`, commit, push; jangan hapus file untracked.
- JANGAN sentuh `.env`, `storage/`, `instance/`, `app.zip`, `tools/reset_staging_demo.py`, tabel `ml_*`/`research_dataset_*`.
- JANGAN jalankan pytest, `flask db ...`, job, atau skrip apa pun ke database dev.
- Jangan mengubah logika uang/jurnal/penggajian.

## Selesai → laporkan singkat
Daftar file yang diubah + perintah untuk owner:
```
venv\Scripts\python.exe -m pytest -q tests/test_scheduler_service.py tests/test_route_endpoint_references.py tests/test_employee_advance.py tests/test_workforce_module.py
```
