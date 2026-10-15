# TUGAS: Fase 5 — Pesanan otomatis untuk Client/Sub Client kontrak

Repo Flask ERP PT Idha Boga (Python 3.11, Flask, Jinja2, SQLAlchemy, Alembic, PostgreSQL, Windows PowerShell, `venv\`).
**Wajib baca dulu `RENCANA_PENGEMBANGAN_ERP.md` bagian 1, 5, 6, dan 7 (Fase 5).** Itu keputusan owner; kalau prompt ini bertentangan dengan dokumen itu, dokumen yang benar — berhenti dan laporkan. Baca kode terkait sendiri; jangan menebak nama field/fungsi.

## ATURAN KERJA (WAJIB)
- **JANGAN menjalankan pytest sama sekali** (owner yang menjalankan). Tetap **tulis** file test-nya. Di akhir laporan, berikan **daftar perintah** yang harus owner jalankan.
- Jangan menjalankan `flask db upgrade/downgrade`, `flask jobs tick`, atau perintah apa pun ke database. Jangan jalankan server.
- **Dilarang `git clean`, `git checkout -- .`, `git reset --hard`, `Remove-Item`/`rm` pada file yang belum di-commit, `Stop-Process`.** Jangan git add/commit/push.
- Jangan sentuh `.env`, `storage/`, `instance/`, `app.zip`, `tools/reset_staging_demo.py`, tabel `ml_*`/`research_dataset_*`.
- Tidak ada commit/rollback di route; commit lewat `atomic_business_action` di service; service yang memanggil fungsi publik ber-commit kirim `commit=False`. Tidak ada except luas yang diam. Uang `Decimal`. Waktu `now_wib()/today_wib()` (naif WIB — **jangan** dibungkus `to_wib()` lagi). Query dibatasi `branch_id`.
- Ikuti UI yang sudah ada (card `var(--radius-lg)`, tombol/input `var(--radius)`, tanpa hex baru, rapi di HP 390px, tombol besar untuk jempol). CSS di `app/static/css/app/*.css` lalu jalankan `venv\Scripts\python.exe tools\build_css.py` (ini boleh dijalankan, bukan pytest).
- Migrasi baru: `down_revision` = head terakhir di `migrations/versions` (cek file, jangan jalankan flask). Daftarkan di `tests/test_numeric_migration_coverage.py` / `tests/test_optimistic_locking_models.py` seperti migrasi sebelumnya.

## Pakai yang sudah ada (jangan buat ulang)
- Aturan kontrak: `app/services/contract_rules_service.py` (`active_contract_for`, `lock_time_for`, `is_contract_holiday`, `billing_mode_for`).
- Penjadwal: `app/services/scheduler_service.py` (`register_job`, `daily_at`). Daftarkan tugas baru di tempat tugas lain didaftarkan.
- Batas sesi: `session_closed_reason` di `portal_order_draft_service.py`.
- Pesanan: `DailyOrder` / `DailyOrderDetail` (`lunch_qty`, `dinner_qty`, `price_per_portion`, ongkir per sesi) — cari fungsi yang sudah dipakai admin/portal untuk membuat/menggabung detail order + mengunci harga & ongkir (mis. jalur `confirm_portal_order_draft` dan rute order Operasional) dan **pakai ulang** logika harga/ongkir itu.
- Kontrol kredit: `evaluate_credit` / status kredit di `credit_control_service.py`.
- Notifikasi: `create_or_update_notification`.

## Yang dikerjakan

### 1. Data (migrasi)
- `standing_order_states`: satu baris per `(branch_id, mandor_id, delivery_location_id, meal_type)` — `status` (`ACTIVE` / `PAUSED_UNTIL` / `STOPPED`), `resume_date` (Date, nullable), `last_nonzero_qty` (int), `updated_at`, `updated_by`.
- `order_qty_changes` (riwayat): `daily_order_detail_id`, `meal_type`, `old_qty`, `new_qty`, `reason_code` (nullable), `note`, `source` (`AUTO` / `PORTAL` / `ADMIN`), `changed_by`, `changed_at`.

### 2. Tugas otomatis jam 18.00 WIB (`auto_daily_orders`, per cabang)
Untuk **besok** (= tanggal periode + 1):
- Ambil client dengan **kontrak aktif** pada tanggal besok; untuk tiap sub client (mandor) aktif client itu dan tiap lokasi antar aktifnya, untuk tiap sesi (Siang/Malam):
  - Lewati bila: besok **hari libur kontrak**; state `STOPPED`; state `PAUSED_UNTIL` dan besok < `resume_date`; pihak tagih = **bayar di muka** (`CASH`) — jalur prabayar tetap lewat portal; status kredit **Tahan/Blokir** (catat alasan & beri notifikasi admin + client "Pesanan besok tidak dibuat karena …").
  - Porsi = porsi **hari kerja terakhir** (hari sebelumnya yang bukan libur kontrak) untuk lokasi+sesi itu; bila porsi itu 0 → pakai `last_nonzero_qty` **kecuali** state menyuruh tetap 0. Tidak ada riwayat sama sekali → **jangan buat** (pesanan pertama tetap manual/portal).
  - Bila detail besok **sudah ada** (dipesan manual/portal) → **jangan ditimpa**.
  - Buat/isi `DailyOrderDetail` besok dengan harga & ongkir terkunci seperti jalur pembuatan order yang sudah ada; catat `order_qty_changes` source `AUTO`.
- Idempoten: menjalankan tugas dua kali untuk tanggal yang sama tidak menggandakan porsi.
- Kirim notifikasi ke akun portal sub client/client: "Pesanan besok: Siang 40, Malam 35. Ubah sebelum 10.00 / 15.00 WIB." (jam dari `lock_time_for`). Ringkasan ke admin & dapur: jumlah pesanan & total porsi yang dibuat, dan daftar yang dilewati beserta alasannya.

### 3. Ubah porsi dari portal (Client/Sub Client kontrak)
- Kartu **"Pesanan Hari Ini & Besok"** di dashboard portal sub client & client: per lokasi × sesi tampil porsi, jam lock, status (Bisa diubah / Sudah dikunci / Dalam perjalanan), tombol **− / +** besar dan input angka, tombol **Simpan**.
- Server menolak perubahan bila: lewat jam lock (`session_closed_reason`), order harian tanggal itu sudah di-lock, pengiriman sudah berjalan/diterima, atau lokasi di luar akses akun. Tombol tidak tampil pada kondisi itu; tampil "Sudah dikunci, hubungi admin" / "Dalam perjalanan — tidak bisa diubah".
- Perubahan **langsung masuk** `DailyOrderDetail` (tanpa konfirmasi admin), total & ongkir dihitung ulang dengan aturan yang sama, `order_qty_changes` source `PORTAL`, notifikasi ke admin & dapur: "Mandor Hendra · Lokasi X · Siang 40 → 32".
- Porsi dinaikkan juga harus lolos kontrol kredit yang sama dengan pesanan baru (lewat limit → ditolak dengan pesan jelas).

### 4. Porsi 0 wajib alasan
Saat porsi diubah menjadi 0, wajib pilih alasan (modal/pilihan di kartu). Efek ke `standing_order_states`:
| Kode | Label | Efek |
|---|---|---|
| `OFF_TODAY` | Libur hari ini saja | state tetap ACTIVE; besok kembali ke `last_nonzero_qty` |
| `OFF_UNTIL` | Libur sampai tanggal … (wajib tanggal) | `PAUSED_UNTIL` + `resume_date`; setelah itu lanjut otomatis dengan `last_nonzero_qty` |
| `PAUSE` | Berhenti sementara, saya pesan lagi nanti | `STOPPED`; hidup lagi saat client menekan **"Mulai pesan lagi"** dan mengisi porsi |
| `PROJECT_DONE` | Proyek/pekerjaan selesai | `STOPPED` + notifikasi admin untuk meninjau kontrak |
| `NO_WORKERS` | Pekerja tidak di lokasi | seperti `OFF_TODAY`, tapi tercatat terpisah untuk laporan |
| `OTHER` | Lainnya (catatan wajib) | seperti `OFF_TODAY` |
Setiap porsi > 0 memperbarui `last_nonzero_qty`. Tombol **"Mulai pesan lagi"** tampil untuk lokasi/sesi berstatus `STOPPED`/`PAUSED_UNTIL`.

### 5. Admin
- Setelah lock: admin tetap bisa ubah porsi **dengan alasan wajib** (source `ADMIN`); **saat pengiriman sudah berjalan/diterima: ditolak untuk semua orang termasuk admin**.
- Halaman/riwayat **"Perubahan Porsi"** (OWNER/ADMIN/DAPUR): filter tanggal, sub client, sumber; kolom siapa, kapan, dari → ke, alasan.
- Di halaman tugas otomatis (Fase 4), `auto_daily_orders` tampil dengan jadwal 18:00.

### 6. Test (tulis saja, JANGAN dijalankan) — `tests/test_auto_daily_orders.py`
- Tugas membuat pesanan besok dari porsi hari kerja terakhir; libur kontrak dilewati; setelah libur memakai hari kerja terakhir.
- Detail yang sudah ada tidak ditimpa; jalan dua kali tidak menggandakan.
- Dilewati untuk: STOPPED, PAUSED_UNTIL sebelum resume, bayar di muka, kredit Tahan/Blokir, tanpa riwayat.
- 6 alasan porsi 0 menghasilkan state & porsi hari berikutnya yang benar.
- Ubah porsi portal: diterima sebelum lock; ditolak lewat lock/order terkunci/dalam perjalanan/lokasi milik akun lain; kenaikan yang melewati limit kredit ditolak; riwayat & notifikasi tercatat.
- Admin: ubah setelah lock wajib alasan; saat dalam perjalanan ditolak.
Waktu di-mock; jangan bergantung jam asli.

## LAPORAN AKHIR (wajib)
1. File baru & diubah.
2. Asumsi/ketidaksesuaian dengan dokumen rencana.
3. **Perintah untuk owner**, urut:
   ```powershell
   venv\Scripts\python.exe -m pytest tests/test_auto_daily_orders.py -v -p no:warnings -x
   venv\Scripts\python.exe -m pytest tests/test_scheduler_service.py tests/test_portal_session_cutoff.py tests/test_contract_rules.py tests/test_db_commit_audit_tool.py tests/test_exception_hygiene.py tests/test_numeric_migration_coverage.py tests/test_optimistic_locking_models.py -q -p no:warnings
   venv\Scripts\python.exe -m flask db upgrade
   ```
4. Langkah uji manual singkat (portal sub client ubah porsi, porsi 0 + alasan, jalankan tugas dari halaman Tugas Otomatis).
5. Perbarui status Fase 5 di `RENCANA_PENGEMBANGAN_ERP.md` menjadi "⏳ (kode selesai, test belum dijalankan owner)" dan tambah satu baris di "Riwayat perubahan".
