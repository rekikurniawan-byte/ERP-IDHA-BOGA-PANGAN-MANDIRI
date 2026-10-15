# Tugas Gemini: Semua tanggal bisnis memakai WIB, bukan jam server

Baca dulu `RENCANA_PENGEMBANGAN_ERP.md` bagian 1 (prinsip + aturan teknis). Kerjakan, jangan tanya balik.

## Masalah
Saat online, server biasanya ber-jam UTC. Kode yang memakai `date.today()` / `datetime.now()` untuk **tanggal bisnis** (tanggal pesanan, invoice, jatuh tempo, "hari ini", validasi "tidak boleh tanggal masa depan", laporan harian) akan mundur 1 hari antara 00.00–07.00 WIB.

## Aturan perbaikan
- Pakai helper yang SUDAH ADA di `app/utils/clock.py`: `today_wib()` (date) dan `now_wib()` (datetime naif WIB). Jangan buat helper baru.
- `date.today()` untuk tanggal bisnis → `today_wib()`.
- `datetime.now()` untuk waktu bisnis (jam lock, jam sekarang dibanding jadwal) → `now_wib()`.
- **JANGAN ubah `datetime.utcnow()`** — kolom cap waktu (`created_at`, `changed_at`, dll.) memang disimpan UTC dan ditampilkan lewat filter `|wib` (+7 jam). Mengubahnya membuat tampilan maju 7 jam.
- Default di parameter fungsi (`today = today or date.today()`) ikut diganti ke `today_wib()`.
- Nilai yang disimpan sebagai WIB jangan ditampilkan lewat `|wib` (akan +7 lagi); pakai `strftime`.
- Template: `now().date()` / tanggal default form → kirim `today_wib()` dari route.

## JANGAN sentuh file ini (Claude sedang mengerjakan Fase 8 Pajak di sini)
`app/services/accounting_service.py`, `auto_invoice_service.py`, `order_invoice_service.py`, `customer_payment_service.py`, `portal_payment_creation_service.py`, `invoice_payment_history_service.py`, `sharia_credit_service.py`, `credit_account_service.py`, `credit_control_service.py`, `company_settings_service.py`, `manual_billing_service.py`, `manual_backfill_billing_service.py`, `app/routes/finance/period_invoice_routes.py`, `app/routes/finance/payment_routes.py`, `app/templates/finance/invoice_print.html`.
Kalau di file itu ada `date.today()`/`datetime.now()`, **tulis daftarnya (file:baris) di laporan akhir**, Claude yang ubah.

## Cara kerja
1. `grep -rnE "date\.today\(\)|datetime\.now\(\)" app --include=*.py` → putuskan per baris (bisnis → WIB; log/teknis boleh tetap).
2. Ubah per file, kecil-kecil. Jangan ubah perilaku lain.
3. Test: tambah `tests/test_wib_dates.py` — monkeypatch jam supaya UTC 2026-10-10 18:30 (= WIB 11 Okt 01.30) dan cek minimal: tanggal pesanan otomatis, tanggal default invoice/pembayaran, validasi "tanggal masa depan" memakai 11 Okt. Ikuti pola test yang sudah ada (fixture `ctx` dengan `commit`→`flush`).

## Aturan keras
- **Dilarang** `git clean`, `git checkout -- .`, `git reset --hard`, menghapus file yang belum di-commit, `Stop-Process`.
- **Dilarang** menjalankan `flask db upgrade/downgrade`, `flask jobs ...`, atau skrip apa pun ke database dev (`idha_boga_staging`). Jangan menjalankan pytest (pemilik yang menjalankan).
- Jangan sentuh `.env`, `storage/`, `instance/`, `app.zip`, `tools/reset_staging_demo.py`, tabel `ml_*`/`research_dataset_*`.
- Tidak `git add -A`, tidak commit, tidak push.

## Laporan akhir (singkat)
1. Daftar file yang diubah.
2. Daftar `date.today()/datetime.now()` di file terlarang (untuk Claude).
3. Baris yang sengaja dibiarkan + alasannya.
4. Command untuk pemilik:
```
venv\Scripts\python.exe -m pytest -q -p no:warnings tests/test_wib_dates.py
venv\Scripts\python.exe -m pytest -q -p no:warnings
```
