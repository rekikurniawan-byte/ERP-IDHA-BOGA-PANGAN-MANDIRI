# Tugas Gemini: Gladi pilot ulang end-to-end (Fase 3–7 + audit integrasi)

Jalankan SETELAH tugas `PROMPT_GEMINI_JAM_WIB.md` selesai dan di-commit pemilik.
Baca dulu `RENCANA_PENGEMBANGAN_ERP.md` (bagian 1, Fase 3–7, dan "Riwayat perubahan" 2026-10-09).

## Tujuan
Membuktikan semua fitur baru jalan sebagai SATU sistem lewat halaman aslinya, bukan cuma lulus unit test. Skrip gladi yang sudah ada: `tools/pilot_dry_run.py` (stage: setup → orders → operations → billing → one_step → contracts → checks; laporan ke `instance/gladi_pilot_hasil.md`). Baca skripnya sendiri dan **tambahkan stage baru**, jangan tulis ulang yang sudah ada.

## Stage baru yang ditambahkan (lewat test client Flask + login per peran, seperti stage lama)
1. **Pengaturan kontrak (Fase 3)**: buat kontrak aktif dengan jam lock, libur rutin + 1 libur khusus, siklus 14 hari, tempo 7 hari, ta'zir Rp100.000, pengadilan.
2. **Pesanan otomatis (Fase 5)**: jalankan tugas `auto_daily_orders` untuk tanggal tertentu lewat `scheduler_service.run_job_now(...)`; cek pesanan besok terbentuk dari porsi hari kerja terakhir, hari libur dilewati, porsi 0 wajib alasan.
3. **Dapur → kirim → scan terima**: pakai alur yang sudah ada di stage operations.
4. **Invoice otomatis (Fase 6)**: jalankan `auto_invoice_preview` (H-1) lalu `auto_period_invoices` di hari potong; cek: hanya pengiriman yang diterima ditagih, pengiriman belum diterima ikut invoice berikutnya, jurnal piutang ada, notifikasi pihak ditagih + salinan.
5. **Bayar 3 jalur**: (a) bayar manual sebagian, (b) bukti transfer portal → verifikasi → pembayaran, (c) potong DP/deposit. Cek sisa invoice, buku kas, jurnal, log penagihan, dan riwayat bayar portal semuanya cocok.
6. **Kredit syariah (Fase 7)**: buat invoice lewat jatuh tempo + janji bayar yang meleset → jalankan `credit_daily_sweep`; cek status naik, notifikasi portal, usulan ta'zir muncul; Owner "Kenakan" → tagihan ta'zir terpisah, jurnal ke 2009 (bukan pendapatan); kelonggaran menahan status di Tahan; catat penyaluran Dana Sosial (hanya dari dana yang sudah dibayar).
7. **Cek tagihan dobel**: coba buat invoice per pesanan untuk pesanan yang sudah masuk invoice otomatis → harus ditolak.
8. **Pemeriksaan akhir** (stage checks yang sudah ada + tambahan): buku besar = buku pembantu (`subledger_check_service.subledger_lines()` selisih 0), tidak ada invoice tanpa jurnal (kecuali OPENING_BALANCE), tidak ada jurnal tidak seimbang, `paid_amount` = pembayaran + potongan DP/deposit per invoice.

Tanggal dalam gladi: pakai tanggal tetap yang dihitung dari `today_wib()`, jangan bergantung jam server.

## Database (WAJIB)
- Hanya database gladi BARU: `idha_boga_gladi_20261009` (nama wajib mengandung "gladi"). Buat dengan `createdb` (tools Laragon: `/c/laragon/bin/postgresql/postgresql-11.0-1/bin`), lalu `flask --app run db upgrade` dan `flask --app run bootstrap ...` dengan `DATABASE_URL` mengarah ke DB gladi itu (salin URL dari `.env`, ganti nama DB; **jangan ubah `.env`**).
- **Dilarang** `dropdb`/DROP/TRUNCATE apa pun, dan **dilarang** menyentuh `idha_boga_staging` (DB dev) atau `test_db`.
- `--backup` butuh `PG_DUMP_PATH=<bin laragon>/pg_dump.exe`.

## Aturan keras
- **Dilarang** `git clean`, `git checkout -- .`, `git reset --hard`, menghapus file belum di-commit, `Stop-Process`.
- Jangan ubah kode aplikasi (`app/`) kecuali bug nyata yang ditemukan gladi — kalau ketemu, **jangan perbaiki sendiri bagian uang/jurnal/kredit/pajak**; tulis di laporan (langkah, data, hasil vs harapan) untuk Claude.
- Jangan sentuh `.env`, `storage/`, `instance/` (kecuali file laporan gladi), `app.zip`, `tools/reset_staging_demo.py`, tabel `ml_*`/`research_dataset_*`.
- Tidak `git add -A`, tidak commit, tidak push. Jangan jalankan pytest.

## Laporan akhir (singkat)
1. Jumlah langkah & cek: lulus/gagal (dari `instance/gladi_pilot_hasil.md`).
2. Setiap kegagalan: stage, langkah, hasil vs harapan, dugaan file penyebab.
3. File yang diubah.
4. Command untuk pemilik mengulang gladi:
```
# Git Bash, DATABASE_URL diarahkan ke idha_boga_gladi_20261009
PYTHONIOENCODING=utf-8 venv/Scripts/python.exe tools/pilot_dry_run.py --db idha_boga_gladi_20261009 --backup
```
