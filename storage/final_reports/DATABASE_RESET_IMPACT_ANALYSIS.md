# Database Reset Impact Analysis

Tanggal audit: 2026-07-27

Project: ERP PT Idha Boga Pangan Mandiri

Status akhir: **READY_FOR_OWNER_APPROVAL**

Catatan utama:

- Tidak ada reset nyata yang dijalankan.
- Tidak ada `DELETE`, `TRUNCATE`, `DROP`, `CASCADE`, reset sequence, atau penghapusan file fisik yang dijalankan.
- Semua pemeriksaan database pada tahap ini bersifat read-only.
- Backup fisik belum dibuat karena reset belum disetujui. Laporan ini menyiapkan perintah backup/restore dan script execute akan menolak berjalan tanpa backup `.dump`, SHA-256, dan `pg_restore --list` yang valid.

---

## 1. Identifikasi Database Aktif

| Item | Nilai |
| --- | --- |
| Environment aktif | `development` |
| Flask env | `development` |
| Debug | `true` |
| Driver | `postgresql+psycopg` |
| Host | `localhost` |
| Port | `5432` |
| Database | `idha_boga_staging` |
| Schema | `public` |
| Jumlah tabel database | `113` |
| Alembic current | `88a0a1b2c3d4` |
| Alembic head terdeteksi | `88a0a1b2c3d4` |
| Status environment | Aman untuk analisis reset lokal |

Password database tidak ditampilkan dan tidak ditulis ke laporan.

Putusan tahap 1: **PASS untuk analisis dan dry-run lokal**.

---

## 2. Backup Wajib Sebelum Reset Nyata

Backup belum dijalankan pada tahap ini karena belum ada persetujuan reset. Sebelum reset nyata, jalankan backup PostgreSQL custom format dan verifikasi restore-list.

### Backup Command

PowerShell:

```powershell
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backupDir = "instance\backups"
New-Item -ItemType Directory -Force $backupDir | Out-Null

$backupFile = Join-Path $backupDir "IDHA_BOGA_PRE_RESET_$timestamp.dump"
$shaFile = "$backupFile.sha256"
$restoreListFile = "$backupFile.pg_restore_list.txt"

pg_dump `
  --format=custom `
  --host=localhost `
  --port=5432 `
  --username=idha_boga_user `
  --dbname=idha_boga_staging `
  --file="$backupFile"

Get-FileHash "$backupFile" -Algorithm SHA256 |
  ForEach-Object { "$($_.Hash.ToLower())  $backupFile" } |
  Set-Content "$shaFile"

pg_restore --list "$backupFile" > "$restoreListFile"

Get-Item "$backupFile" | Select-Object FullName,Length,LastWriteTime
Get-Content "$shaFile"
```

Catatan:

- Password tidak ditulis di command. Gunakan prompt PostgreSQL, `.pgpass`, atau `PGPASSFILE` lokal yang tidak ikut ZIP.
- Backup dianggap valid minimal jika file `.dump` ada, ukuran masuk akal, SHA-256 cocok, dan `pg_restore --list` berhasil.

### Restore Command Untuk Drill

PowerShell:

```powershell
$restoreDb = "idha_boga_restore_test"

createdb `
  --host=localhost `
  --port=5432 `
  --username=idha_boga_user `
  "$restoreDb"

pg_restore `
  --no-owner `
  --no-privileges `
  --host=localhost `
  --port=5432 `
  --username=idha_boga_user `
  --dbname="$restoreDb" `
  "$backupFile"
```

Restore drill harus dilanjutkan dengan:

- cek `alembic_version`;
- login admin pada database restore test;
- buka dashboard;
- cek invoice/journal/stock sample jika backup sebelum reset masih berisi data;
- baru setelah itu backup boleh dipakai sebagai syarat reset nyata.

---

## 3. Inventaris Tabel

Inventaris penuh per tabel tersedia di:

`storage/final_reports/DATABASE_RESET_TABLE_CLASSIFICATION.json`

Ringkasan klasifikasi:

| Kategori | Jumlah tabel |
| --- | ---: |
| WAJIB_DIPERTAHANKAN | 5 |
| DIPERTAHANKAN_SEMENTARA_KARENA_DEPENDENCY | 0 |
| AMAN_DIKOSONGKAN | 76 |
| MEMERLUKAN_KEPUTUSAN_SAYA | 32 |
| **Total** | **113** |

### A. WAJIB DIPERTAHANKAN

Tabel:

```text
alembic_version
branch_settings
branches
migrations
users
```

Alasan:

- `users` wajib dipertahankan agar akun tetap ada.
- `branches` wajib dipertahankan karena `users.branch_id` wajib valid.
- `branch_settings` wajib dipertahankan sebagai konfigurasi dasar cabang.
- `alembic_version` wajib dipertahankan agar migration database tetap dikenali.
- `migrations` dipertahankan karena tabel ini ada di database aktif dan berhubungan dengan histori/status migrasi aplikasi; jangan dikosongkan sebelum asal-usulnya dipastikan.

### B. DIPERTAHANKAN SEMENTARA KARENA DEPENDENCY

Saat ini tidak ada tabel yang masuk kategori ini secara terpisah. Dependency minimum user langsung masuk kategori wajib dipertahankan.

### C. AMAN DIKOSONGKAN

Tabel operasional/transaksi/detail yang direkomendasikan dikosongkan untuk **Option A - Safe Operational Reset**:

```text
advance_settlements
advance_transactions
asset_financing_contracts
asset_installment_payments
asset_installment_schedules
canteen_external_receivable_payments
canteen_external_receivables
canteen_sale_items
canteen_sales
cash_bank_adjustments
cash_bank_opening_balances
cash_bank_transactions
cash_bank_transfers
cash_daily
cash_expenses
daily_order_details
daily_orders
damaged_items
debt_payments
deliveries
delivery_details
delivery_receipts
employee_assignments
employee_attendance
employee_salary_history
field_counterparties
field_transaction_attachments
field_transaction_links
field_transaction_review_logs
field_transaction_settlements
field_transactions
fixed_asset_depreciation_configs
fixed_asset_depreciations
fixed_asset_purchases
idempotency_keys
invoice_collection_logs
invoice_items
invoices
item_request_details
item_requests
journal_details
journals
manual_billing_batch_items
manual_billing_batches
manual_book_recap_catering_lines
manual_book_recap_warung_lines
manual_book_recaps
manual_payable_payments
manual_payables
manual_receivable_payments
manual_receivables
notifications
operational_expenses
order_hpp_snapshot_allocations
order_hpp_snapshot_components
order_hpp_snapshot_lines
order_hpp_snapshots
order_hpp_stock_consumption_lines
order_hpp_stock_consumptions
order_revisions
order_snapshots
payments
payroll_details
payrolls
period_closings
procurement_items
procurements
production_details
productions
stock_adjustments
stock_movements
stock_opening_balances
supplier_bills
supplier_payments
transport_vehicle_expenses
worker_debts
```

Alasan:

- Tabel tersebut adalah data operasional, transaksi, detail, allocation, journal transaksi, payroll transaksi, delivery transaksi, produksi, stok movement, procurement, invoice, payment, backfill/manual billing, notifikasi transaksi, atau generated state.
- Penghapusan harus mengikuti urutan dependency yang dihasilkan dry-run, bukan urutan alfabet manual.

### D. MEMERLUKAN KEPUTUSAN SAYA

Tabel:

```text
accounts
approval_requests
audit_logs
bank_accounts
client_pics
clients
delivery_locations
digital_attachments
drivers
employee_skills
employees
fixed_assets
item_cost_profiles
items
mandors
menus
ml_catering_historical
ml_mandor
ml_predictions
ml_recipe_bom
ml_training_runs
overhead_profiles
packaging_profiles
recipe_headers
recipe_items
recipe_version_items
recipe_versions
research_dataset_clean
research_dataset_features
suppliers
unit_conversions
workers
```

Alasan:

- `accounts`: chart of accounts dasar. Bisa dibutuhkan untuk posting transaksi baru.
- `bank_accounts`: rekening/kas master. Menghapusnya dapat mengganggu payment/cash bank setup.
- `clients`, `client_pics`, `mandors`, `delivery_locations`, `workers`: master pelanggan/mandor/lokasi/pekerja. Option A sebaiknya mempertahankan, Option B dapat mengosongkan hanya setelah approval.
- `suppliers`, `items`, `menus`, recipe/cost profile/packaging/overhead/unit conversion: master bisnis untuk procurement, stok, produksi, HPP. Menghapusnya membuat ERP benar-benar kosong untuk operasional.
- `employees`, `drivers`, `employee_skills`: master SDM/delivery.
- `fixed_assets`: master aset bernilai. Jangan hapus tanpa keputusan.
- `approval_requests`: menyentuh approval governance.
- `audit_logs`: dapat menjadi bukti histori pengembangan/reset. Jangan hapus tanpa keputusan.
- `digital_attachments`: metadata file fisik. Menghapus DB metadata dapat membuat file upload menjadi orphan.
- tabel `ml_*` dan `research_dataset_*`: dataset prediction/research; belum boleh dianggap sampah tanpa keputusan.

---

## 4. Dependency User

Model user existing:

- `users.branch_id` wajib mengarah ke `branches.id`;
- role disimpan sebagai string pada kolom `users.role`;
- tidak ada tabel `roles`, `permissions`, `user_roles`, atau `role_permissions` yang ditemukan pada schema aktif;
- role resmi existing dikendalikan oleh application service, bukan relational RBAC table.

Query validasi read-only:

| Validasi | Hasil |
| --- | ---: |
| Total user | 8 |
| Active OWNER/ADMIN | 2 |
| User tanpa branch valid | 0 |
| User pada branch tidak aktif | 0 |
| Duplicate username | 0 |
| Total branch | 1 |
| Total branch settings | 9 |

Role count:

| Role | Jumlah |
| --- | ---: |
| ACCOUNTING | 1 |
| ADMIN | 1 |
| DAPUR | 1 |
| FINANCE | 1 |
| HR | 1 |
| LOGISTICS | 1 |
| OWNER | 1 |
| PENGANTAR | 1 |

Kesimpulan:

- Akun admin aktif tersedia.
- User tidak orphan.
- Cabang user valid.
- Reset tidak boleh menghapus `users`, `branches`, atau `branch_settings`.

---

## 5. Rencana Reset

### Option A - Safe Operational Reset

Rekomendasi: **DIPILIH**

Menghapus data operasional dan transaksi, tetapi mempertahankan user, branch, setting, chart/master bisnis, dan konfigurasi dasar.

Dry-run Option A:

| Item | Jumlah |
| --- | ---: |
| Safety errors | 0 |
| Tabel preserve | 27 |
| Tabel empty | 76 |
| Tabel approval required | 10 |
| Tabel unknown | 0 |
| FK blocker | 0 |

File dry-run:

`storage/final_reports/database_reset_dry_run_option_a_latest.json`

Catatan penting:

- Walaupun dry-run aman, execute mode tetap akan menolak berjalan selama masih ada 10 tabel `approval_required`.
- Owner harus memutuskan tindakan untuk `approval_requests`, `audit_logs`, `digital_attachments`, dan tabel ML/research sebelum reset nyata.

### Option B - Near-Empty Reset

Mengosongkan master bisnis setelah dependency aman, hanya mempertahankan minimum user/system.

Dry-run Option B:

| Item | Jumlah |
| --- | ---: |
| Safety errors | 0 |
| Tabel preserve | 5 |
| Tabel empty | 76 |
| Tabel approval required | 32 |
| Tabel unknown | 0 |
| FK blocker | 0 |

File dry-run:

`storage/final_reports/database_reset_dry_run_option_b_latest.json`

Kesimpulan:

- Option B terlalu destruktif untuk langkah pertama.
- Option B baru aman bila owner memang ingin menghapus master bisnis seperti client, mandor, item, menu, supplier, bank account, fixed asset, employee, driver, dan dataset ML/research.

---

## 6. Script Reset Dry-Run

Script dibuat di:

`scripts/reset_development_data.py`

Default:

```powershell
python scripts/reset_development_data.py --option A
```

Mode nyata, contoh setelah backup dan approval:

```powershell
python scripts/reset_development_data.py `
  --option A `
  --execute `
  --confirm-token RESET_ERP_DEVELOPMENT_DATA_CONFIRMED `
  --backup-file "instance\backups\IDHA_BOGA_PRE_RESET_YYYYMMDD_HHMMSS.dump" `
  --backup-sha256 "instance\backups\IDHA_BOGA_PRE_RESET_YYYYMMDD_HHMMSS.dump.sha256"
```

Safety guard script:

- menolak env selain development/testing/local;
- menolak host database non-lokal;
- menolak database di luar allowlist;
- menolak database non-PostgreSQL;
- menolak tabel tidak terklasifikasi;
- menolak classification stale;
- menolak dependency cycle;
- menolak FK dari tabel preserve/pending ke tabel target empty;
- menolak Alembic current yang bukan head;
- menolak jika admin aktif tidak ada;
- menolak jika user orphan terhadap branch;
- mode execute wajib confirmation token;
- mode execute wajib backup file dan SHA-256;
- mode execute memverifikasi checksum;
- mode execute memverifikasi `pg_restore --list`;
- mode execute menolak bila masih ada tabel approval-required.

Script tidak mematikan foreign key dan tidak memakai wildcard seluruh schema.

---

## 7. Urutan Penghapusan Option A

Urutan lengkap ada pada dry-run JSON. Ringkasannya:

1. child/detail/allocation/log transaksi;
2. payment/detail;
3. invoice item dan invoice;
4. manual billing/backfill;
5. production/delivery/detail;
6. HPP snapshot/stock consumption;
7. payroll/detail;
8. procurement/detail;
9. stock movement/adjustment/opening;
10. cash bank transaction/transfer/adjustment/opening;
11. journal detail dan journal;
12. parent operational records.

Metode default script memakai `DELETE FROM <table>` eksplisit berdasarkan tabel terklasifikasi.

`TRUNCATE` tidak dipilih sebagai default karena:

- risiko `CASCADE` terlalu besar;
- beberapa tabel harus dipertahankan;
- dependency harus terlihat eksplisit;
- rollback transaksi lebih mudah diaudit.

Sequence:

- Dry-run menampilkan sequence yang akan direset.
- Execute tidak mereset sequence kecuali flag `--restart-identity` diberikan.
- Reset sequence harus diputuskan saat approval karena dapat memengaruhi nomor teknis ID.

---

## 8. File dan Dokumen

Konfigurasi upload:

- `UPLOAD_ROOT`: default `instance/uploads`
- `DIGITAL_ATTACHMENT_UPLOAD_DIR`: default `instance/uploads/digital_attachments`
- `BACKUP_ROOT`: default `instance/backups`

Metadata `digital_attachments` saat audit:

| Module | Reference Type | Attachment Type | Count |
| --- | --- | --- | ---: |
| CUSTOMER_PAYMENT | PAYMENT | BUKTI_TRANSFER | 1 |
| CUSTOMER_PAYMENT | PAYMENT | BUKTI_TRANSFER_CUSTOMER | 1 |
| CUSTOMER_PAYMENT | PAYMENT | SCREENSHOT_PAYMENT | 1 |
| DELIVERY | DELIVERY | RECEIPT | 1 |
| DELIVERY | DELIVERY_RECEIPT | RECEIPT | 1 |
| FIELD_TRANSACTION | FIELD_TRANSACTION | EVIDENCE | 1 |
| PROCUREMENT | PROCUREMENT | NOTA_PEMBELIAN | 1 |
| QA_SMOKE | GENERAL | GENERAL | 1 |
| SUPPLIER_PAYMENT | SUPPLIER_PAYMENT | BUKTI_TRANSFER | 1 |

Keputusan:

- Jangan hapus file fisik otomatis.
- Jangan hapus `digital_attachments` sebelum owner memutuskan apakah metadata dan file upload ikut dibersihkan.
- Bila transaksi dikosongkan tetapi `digital_attachments` dipertahankan, akan ada logical orphan karena `reference_type/reference_id` bukan FK langsung.
- Bila `digital_attachments` dikosongkan tetapi file fisik dipertahankan, akan ada orphan file di `instance/uploads/digital_attachments`.
- Penghapusan file fisik harus menjadi operasi terpisah dengan approval.

---

## 9. Validasi Setelah Reset

Validasi wajib setelah reset nyata:

```sql
SELECT version_num FROM alembic_version;
SELECT COUNT(*) FROM users;
SELECT COUNT(*) FROM users WHERE is_active = true AND role IN ('OWNER', 'ADMIN');
SELECT COUNT(*) FROM users u LEFT JOIN branches b ON b.id = u.branch_id WHERE b.id IS NULL;
SELECT role, COUNT(*) FROM users GROUP BY role ORDER BY role;
```

Validasi target kosong:

```sql
SELECT COUNT(*) FROM invoices;
SELECT COUNT(*) FROM payments;
SELECT COUNT(*) FROM journal_details;
SELECT COUNT(*) FROM journals;
SELECT COUNT(*) FROM daily_orders;
SELECT COUNT(*) FROM stock_movements;
SELECT COUNT(*) FROM procurements;
SELECT COUNT(*) FROM deliveries;
SELECT COUNT(*) FROM productions;
```

Validasi aplikasi:

- app startup berhasil;
- login admin berhasil;
- role dan dashboard internal berjalan;
- `python -m flask db current` tetap di head;
- tidak ada foreign key orphan;
- tabel target reset bernilai 0;
- tabel preserve tidak berubah;
- dashboard bisa dibuka;
- create data baru berhasil;
- nomor dokumen tidak bentrok;
- full pytest lulus.

Snapshot user sebelum dan sesudah:

```sql
SELECT id, branch_id, full_name, username, role, is_active, created_at, updated_at, version_id
FROM users
ORDER BY id;
```

Hash/snapshot hasil query tersebut harus sama sebelum dan sesudah reset.

---

## 10. Bukti Verifikasi Tahap Ini

| Pemeriksaan | Hasil |
| --- | --- |
| Blueprint reset dipatuhi | Tidak ada operasi destruktif |
| Database read-only inventory | PASS |
| Environment local development | PASS |
| Alembic current=head | PASS |
| User dependency audit | PASS |
| Table classification JSON dibuat | PASS |
| Option A dry-run | PASS, safety errors 0 |
| Option B dry-run | PASS, safety errors 0 |
| Script reset default dry-run | PASS |
| `compileall scripts tests/test_reset_development_data_safety.py` | PASS |
| `pytest tests/test_reset_development_data_safety.py` | PASS, 7 passed |

File yang dibuat:

```text
storage/final_reports/DATABASE_RESET_IMPACT_ANALYSIS.md
storage/final_reports/DATABASE_RESET_TABLE_CLASSIFICATION.json
storage/final_reports/database_reset_dry_run_option_a_latest.json
storage/final_reports/database_reset_dry_run_option_b_latest.json
scripts/reset_development_data.py
scripts/__init__.py
tests/test_reset_development_data_safety.py
```

---

## 11. Risiko

| Risiko | Status |
| --- | --- |
| Backup belum dibuat | Wajar untuk tahap analisis; wajib sebelum reset nyata |
| `digital_attachments` dan file fisik dapat menjadi orphan | Approval required |
| `audit_logs` bisa menjadi bukti historis yang masih dibutuhkan | Approval required |
| Dataset ML/research mungkin masih bernilai | Approval required |
| Option B menghapus master bisnis | Tidak direkomendasikan untuk langkah pertama |
| Sequence reset dapat memengaruhi ID teknis | Jangan aktifkan tanpa keputusan |
| Existing backup folder bukan pengganti backup baru pre-reset | Harus buat dump baru tepat sebelum reset |

---

## 12. Rekomendasi

Rekomendasi saya: **Option A - Safe Operational Reset**.

Namun sebelum reset nyata, owner perlu menyetujui:

1. Apakah `audit_logs` dipertahankan atau dikosongkan.
2. Apakah `approval_requests` dipertahankan atau dikosongkan.
3. Apakah `digital_attachments` metadata dipertahankan atau dikosongkan.
4. Apakah file fisik upload tetap dibiarkan atau dibuat rencana cleanup terpisah.
5. Apakah tabel ML/research dipertahankan atau dikosongkan.
6. Apakah sequence ID ikut di-reset.
7. Backup `.dump` baru yang sudah diverifikasi `pg_restore --list`.

Setelah owner menyetujui daftar tersebut, script execute masih akan meminta token:

```text
RESET_ERP_DEVELOPMENT_DATA_CONFIRMED
```

Sampai approval eksplisit diberikan, reset nyata tetap tidak boleh dijalankan.
