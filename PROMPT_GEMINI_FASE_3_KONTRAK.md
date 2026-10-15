# TUGAS: Fase 3 — Pengaturan kontrak (fondasi)

Repo Flask ERP PT Idha Boga (Python 3.11, Flask, Jinja2, SQLAlchemy, Alembic, PostgreSQL, Windows PowerShell, `venv\`).
**Wajib baca dulu `RENCANA_PENGEMBANGAN_ERP.md` bagian 1 (aturan) dan bagian 5 (Fase 3).** Itu acuan keputusan owner; kalau prompt ini bertentangan dengan dokumen itu, dokumen yang benar — berhenti dan laporkan. Baca kode terkait sendiri; jangan menebak nama field.

Fase ini **hanya menyimpan pengaturan kontrak dan memakai jam lock + tempo**. Pesanan otomatis (Fase 5), invoice otomatis (Fase 6), ta'zir (Fase 7), dan surat kontrak (Fase 9) **belum** dikerjakan — cukup simpan datanya.

## Aturan wajib
- Tidak ada commit/rollback di route; commit lewat `atomic_business_action` di service; service yang memanggil fungsi publik ber-commit kirim `commit=False`. Tidak ada except luas yang diam. Uang `Decimal` / `Numeric(18,2)`. Waktu `now_wib()/today_wib()`. Query dibatasi `branch_id`.
- Ikuti UI yang sudah ada (token radius: card `var(--radius-lg)`, input/tombol `var(--radius)`; tanpa hex baru; rapi di HP 390px). CSS di `app/static/css/app/*.css` lalu `venv\Scripts\python.exe tools\build_css.py`.
- Migrasi baru: `down_revision` = head sekarang (`flask db heads`). Daftarkan di `tests/test_numeric_migration_coverage.py` / `tests/test_optimistic_locking_models.py` bila diminta test (contoh migrasi `c1d2e3f4a5b6`).
- Jangan sentuh `.env`, `storage/`, `instance/`, `app.zip`, `tools/reset_staging_demo.py`, tabel `ml_*`/`research_dataset_*`. Jangan git add/commit/push. Jangan jalankan server. **Dilarang `git clean`, `git checkout -- .`, `git reset --hard`, atau menghapus file yang belum di-commit (termasuk `app/static/uploads/`).**

## Fakta kode
- Kontrak: `CustomerContract` di `app/models/contract.py` (per **client**: `client_id`, `start_date`, `end_date`, `payment_terms` String, `credit_limit`, `status`, `version_no`, `parent_contract_id`). Lifecycle di `app/services/contract_lifecycle_service.py`; halaman kontrak di modul Customer Success (cari route/template kontrak).
- Mode tagih per sub client: `CreditAccount.billing_mode` + `payment_terms_days` di `app/models/credit.py`, konstanta `BILLING_VIA_CLIENT / BILLING_DIRECT / BILLING_CASH` di `app/services/credit_account_service.py`.
- Ambang kredit: `DEFAULT_THRESHOLDS` di `app/services/credit_control_service.py` (`credit.terms_days_direct` = 14).
- Batas pesan: `PORTAL_CUTOFF_TIMES` (LUNCH 10:00, DINNER 15:00) dan `session_closed_reason(branch_id, order_date, meal_type)` di `app/services/portal_order_draft_service.py`; dipakai form pesan portal, server, dan upload bukti bayar.
- Pengantar: model `Driver` (`app/models/master.py`), `Delivery.driver_id`. Reminder pengantar (`_get_driver_ids_for_user` di `live_reminder_service.py`) sekarang mencocokkan lewat nama/HP.

## Yang dikerjakan

### 1. Kolom pengaturan di `CustomerContract` (migrasi)
| Kolom | Tipe | Bawaan |
|---|---|---|
| `lunch_lock_time` | Time | 10:00 |
| `dinner_lock_time` | Time | 15:00 |
| `weekly_holidays` | String(20), daftar hari ISO 1–7 dipisah koma (mis. `"7"` = Minggu); kosong = kirim setiap hari | kosong |
| `default_billing_mode` | String(20): `VIA_CLIENT` / `DIRECT` / `CASH` (pakai konstanta yang ada) | `VIA_CLIENT` |
| `billing_cycle` | String(20): `WEEKLY` / `BIWEEKLY` / `MONTHLY` | `BIWEEKLY` (14 hari) |
| `billing_anchor_date` | Date, tanggal awal siklus | = `start_date` |
| `due_days` | Integer ≥ 1 | **7** |
| `dispute_court` | String(40): `PN_PANGKALAN_BALAI` / `PN_KAYUAGUNG` | `PN_PANGKALAN_BALAI` |
| `tazir_amount` | Numeric(18,2) ≥ 0; 0 = tidak dipakai | 0 |

Tabel baru `contract_holidays` (`contract_id`, `holiday_date`, `note`; unik per kontrak+tanggal). Isi bawaan untuk kontrak lama lewat `server_default`/backfill di migrasi.

### 2. Form & detail kontrak
- Bagian baru **"Aturan Pesanan & Tagihan"** di form buat/ubah kontrak dan halaman detail: jam lock siang/malam, hari libur rutin (checkbox Sen–Min), daftar tanggal libur khusus (tambah/hapus), siklus tagihan, tanggal awal siklus, jatuh tempo (hari), pengadilan sengketa (label: "PN Pangkalan Balai (alamat PT, Kab. Banyuasin)" / "PN Kayuagung (lokasi OKI)"), nominal ta'zir (dengan teks bantu: "Nominal tetap per kejadian. Diusulkan sistem, diputuskan Owner, masuk Dana Sosial — bukan pendapatan.").
- **Pihak yang ditagih**: pilihan bawaan kontrak + tabel semua sub client client tersebut dengan pilihan per sub client (Lewat client / Langsung ke sub client / Bayar di muka). Sumber data per sub client **tetap `CreditAccount.billing_mode`** (jangan buat kolom kedua); halaman kontrak hanya menampilkan & menyimpan ke sana lewat service yang sudah ada. Sub client tanpa pilihan → pakai bawaan kontrak.
- Validasi: jam lock 05:00–20:00 dan lock siang < lock malam; `due_days` 1–60; ta'zir ≥ 0; tanggal libur di dalam masa kontrak.
- Perubahan pengaturan **berlaku untuk pesanan berikutnya** (tidak mengubah pesanan/invoice yang sudah ada) dan dicatat di audit log (nilai lama → baru). Hanya OWNER & ADMIN yang bisa mengubah.

### 3. Satu sumber aturan: `app/services/contract_rules_service.py` (baru)
Fungsi murni + query ringan, dipakai semua fase berikutnya:
- `active_contract_for(client_id, on_date)` → kontrak status aktif yang mencakup tanggal itu (pakai aturan lifecycle yang ada; jangan duplikasi definisi "aktif").
- `lock_time_for(client_id, meal_type, on_date)` → jam lock dari kontrak aktif; tanpa kontrak → `PORTAL_CUTOFF_TIMES`.
- `is_contract_holiday(client_id, on_date)` → libur rutin atau tanggal khusus.
- `billing_mode_for(mandor_id)` → `CreditAccount.billing_mode` bila diisi, else `default_billing_mode` kontrak aktif client-nya, else perilaku lama.
- `due_days_for(client_id, on_date)` → `due_days` kontrak aktif, else ambang `credit.terms_days_direct`.
- `next_cycle_cutoff(contract, after_date)` → tanggal potong berikutnya menurut siklus & anchor (untuk Fase 6; cukup fungsi + test).

### 4. Pakai aturan baru sekarang
- `session_closed_reason` memakai `lock_time_for(...)` (client diambil dari lokasi/draft). Form pesan portal menampilkan jam lock yang berlaku ("Pesan sebelum 09.30 WIB" bila kontrak mengatur 09:30).
- Ubah `DEFAULT_THRESHOLDS["credit.terms_days_direct"]` dari 14 menjadi **7** (keputusan owner). Tempat yang menghitung jatuh tempo invoice kredit memakai `due_days_for(...)` bila ada kontrak aktif. **Hanya tanggal jatuh tempo yang berubah — jangan ubah nominal, jurnal, atau status invoice yang sudah ada.**
- Ambang lain (`watch 1`, `hold 8`, `blocked 22`, `write_off 61`, ingkar janji, deposit 20%) **tidak diubah**.

### 5. Hubungkan akun pengantar ke Driver
- Kolom baru `drivers.user_id` (FK `users.id`, nullable, unik). Di form master Driver: pilihan "Akun login pengantar" (hanya user role PENGANTAR cabang yang sama, yang belum terhubung).
- `_get_driver_ids_for_user` di `live_reminder_service.py`: pakai `Driver.user_id == user.id` lebih dulu; pencocokan nama/HP tetap sebagai cadangan sementara.

## Test (file baru `tests/test_contract_rules.py`)
- Simpan & tampilkan semua pengaturan; validasi (lock siang ≥ malam ditolak, due_days 0 ditolak, ta'zir negatif ditolak, libur di luar masa kontrak ditolak).
- `lock_time_for`: kontrak 09:30 → pesan jam 09:45 ditolak, 09:15 diterima (waktu di-mock); tanpa kontrak → 10:00.
- `is_contract_holiday`: Minggu rutin + tanggal khusus.
- `billing_mode_for`: override sub client menang atas bawaan kontrak; tanpa keduanya → perilaku lama.
- `due_days_for` + invoice kredit baru jatuh tempo +7 hari; invoice lama tidak berubah.
- `next_cycle_cutoff` untuk WEEKLY/BIWEEKLY/MONTHLY (termasuk akhir bulan, mis. anchor 31 Jan → 28/29 Feb).
- Hanya OWNER/ADMIN bisa ubah pengaturan; perubahan tercatat di audit log.
- Driver ↔ user: reminder pengantar memakai `user_id` walau nama berbeda.

## Verifikasi
```powershell
venv\Scripts\python.exe tools\build_css.py
venv\Scripts\python.exe -m pytest tests/test_contract_rules.py tests/test_contract_lifecycle.py tests/test_portal_session_cutoff.py tests/test_reminder_role_scope.py tests/test_db_commit_audit_tool.py tests/test_exception_hygiene.py tests/test_numeric_migration_coverage.py -q
venv\Scripts\python.exe -m pytest -q
```
Semua harus lulus; test lama yang gagal karena aturan baru (mis. tempo 14 → 7) disesuaikan datanya dan disebutkan di laporan. Laporan akhir: file baru/diubah, hasil test, asumsi, perintah migrasi untuk owner (`venv\Scripts\python.exe -m flask db upgrade` — jangan dijalankan di database dev), langkah uji manual singkat. Tambahkan juga satu baris ke bagian "Riwayat perubahan" di `RENCANA_PENGEMBANGAN_ERP.md` dan ubah status Fase 3 di tabel status menjadi "✅ (belum commit)".
