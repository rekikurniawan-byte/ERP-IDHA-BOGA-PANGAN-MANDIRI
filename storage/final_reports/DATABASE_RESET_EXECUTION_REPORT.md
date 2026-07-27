# Database Reset Execution Report

Tanggal eksekusi: 2026-07-27

Database: `idha_boga_staging`

Host: `localhost:5432`

Schema: `public`

Status: **COMPLETED**

---

## Ringkasan

Reset data operasional Option A sudah dieksekusi setelah approval owner.

Metode eksekusi:

```text
TRUNCATE TABLE <76 tabel eksplisit> CONTINUE IDENTITY RESTRICT
```

Catatan safety:

- Tidak memakai `CASCADE`.
- Tidak memakai `RESTART IDENTITY`.
- Tidak drop schema.
- Tidak drop table.
- Tidak menghapus migration.
- Tidak menghapus `alembic_version`.
- Tidak menghapus user.
- Tidak menghapus branch.
- Tidak menghapus branch settings.
- Tidak menghapus file fisik upload.
- Tabel sensitif yang sebelumnya `approval_required` dipertahankan.

---

## Backup Pre-Reset

Backup dibuat sebelum reset:

```text
instance/backups/IDHA_BOGA_PRE_RESET_20260727_153047.dump
```

Checksum:

```text
fff8f562d38cf42c0025d565c2fd35006d65e729ce2e8e4da462ee225dafcff2
```

Ukuran:

```text
744123 bytes
```

Verifikasi:

```text
pg_restore --list = PASS
```

Manifest:

```text
storage/final_reports/database_reset_backup_manifest_latest.json
```

---

## File Eksekusi

```text
storage/final_reports/DATABASE_RESET_TABLE_CLASSIFICATION_OWNER_APPROVED_OPTION_A.json
storage/final_reports/database_reset_dry_run_owner_approved_option_a_latest.json
storage/final_reports/database_reset_execute_option_a_latest.json
storage/final_reports/database_reset_post_validation_latest.json
scripts/reset_development_data.py
```

---

## Hasil Validasi

| Validasi | Hasil |
| --- | ---: |
| Tabel target reset | 76 |
| Tabel target yang masih berisi data | 0 |
| Semua tabel target kosong | true |
| User dipertahankan | 8 |
| Active OWNER/ADMIN | 2 |
| User tanpa branch valid | 0 |
| Duplicate username | 0 |
| Branch dipertahankan | 1 |
| Branch settings dipertahankan | 9 |
| Alembic current | `88a0a1b2c3d4` |
| Alembic status | head |

Role yang tetap ada:

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

Preserve sample:

| Tabel | Count |
| --- | ---: |
| `users` | 8 |
| `branches` | 1 |
| `branch_settings` | 9 |
| `accounts` | 40 |
| `bank_accounts` | 1 |
| `audit_logs` | 243 |
| `digital_attachments` | 9 |

User snapshot SHA-256 setelah reset:

```text
fd2a8ea9f191ab6d34c5f8eba17aec820d2740e6b8e67a604422eeff021cdb06
```

---

## Verifikasi Command

Berhasil:

```text
python -m flask db current
```

Hasil:

```text
88a0a1b2c3d4 (head)
```

Berhasil:

```text
python -m pytest -q tests/test_reset_development_data_safety.py tests/test_auth_security.py
```

Hasil:

```text
11 passed
```

Berhasil:

```text
python -m compileall app scripts tests/test_reset_development_data_safety.py
```

Hasil:

```text
PASS
```

Berhasil:

```text
python -m flask routes
```

Hasil:

```text
FLASK_ROUTES_OK
341 lines written to storage/final_reports/post_reset_flask_routes_latest.txt
```

Berhasil:

```text
python -m pytest -q
```

Hasil:

```text
278 passed, 3 warnings in 41.67s
```

Warning tersisa:

```text
SQLAlchemy LegacyAPIWarning untuk Query.get() pada period_invoice_routes.py dan company_settings_service.py
```

Runtime smoke setelah reset:

| Check | Status |
| --- | ---: |
| Owner user ditemukan | true |
| Active OWNER/ADMIN | 2 |
| `/auth/login` | 200 |
| `/dashboard/owner` | 200 |
| `/finance/` | 200 |
| `/master/` | 200 |

Catatan:

- `/settings/` mengembalikan 404 pada smoke karena route settings tidak berada di path slash tersebut. Ini bukan error reset dan tidak menghasilkan traceback.

---

## Catatan Insiden Aman

Percobaan eksekusi awal dengan metode `DELETE` terputus karena server PostgreSQL menutup koneksi saat rangkaian delete berjalan. Validasi setelah kejadian menunjukkan data belum berubah karena transaksi belum commit.

Setelah itu metode diganti ke `TRUNCATE` eksplisit tanpa `CASCADE` dan tanpa `RESTART IDENTITY`, lalu eksekusi berhasil.

Setelah reset pertama, full pytest sempat dijalankan dan ternyata memakai database development aktif karena environment `.env` sudah berisi `DATABASE_URL=idha_boga_staging`. Akibatnya data fixture `QA-SMOKE` muncul kembali di halaman read-only health/closing. Ini bukan data yang sengaja dipertahankan.

Tindakan koreksi:

- reset operasional Option A dijalankan ulang setelah pytest;
- marker QA di tabel master/preserve discan secara eksplisit;
- baris master/metadata QA dihapus berdasarkan ID eksplisit;
- fixture pytest diperkuat agar default-nya tidak memakai database development aktif.

Validasi koreksi:

| Validasi | Hasil |
| --- | ---: |
| Marker `QA-SMOKE` / `QA_SMOKE` / `QA Smoke` di seluruh tabel | 0 |
| Tabel operasional target reset | 76 |
| Tabel operasional target yang masih berisi data | 0 |
| User | 8 |
| Active OWNER/ADMIN | 2 |
| User tanpa branch valid | 0 |
| Alembic | `88a0a1b2c3d4` |

File bukti koreksi:

```text
storage/final_reports/database_reset_execute_option_a_after_pytest_cleanup_latest.json
storage/final_reports/qa_smoke_preserved_table_scan_latest.json
storage/final_reports/qa_smoke_master_cleanup_latest.json
storage/final_reports/qa_smoke_marker_validation_latest.json
storage/final_reports/database_reset_clean_final_validation_latest.json
storage/final_reports/post_reset_readonly_audit_summary_latest.json
```

Catatan health page:

- `/accounting/data-health` dan `/accounting/daily-closing` sekarang tidak mengandung data QA.
- Status dapat tetap `WARNING` saat database operasional kosong karena service read-only memang memberi warning untuk kondisi belum ada order/invoice/payment/stock/journal, bukan karena sisa data test.

Pembersihan tambahan:

- Item `PROD-CATERING-PORSI` (`items.id=10`) dicek dan tidak memiliki referensi FK.
- Row-level `DELETE FROM items WHERE id=10` membuat PostgreSQL lokal menutup koneksi, sehingga item dibersihkan memakai `TRUNCATE` eksplisit pada `items` beserta child table kosong yang memiliki FK ke `items`.
- Metode yang dipakai: `TRUNCATE TABLE <child kosong>, items CONTINUE IDENTITY RESTRICT`.
- Tidak memakai `CASCADE`.
- Tidak memakai `RESTART IDENTITY`.
- Hasil akhir: `items.id=10 = 0`, `items_total = 0`.
- Route delete item diperkeras agar `SQLAlchemyError` tidak lagi jatuh ke halaman traceback; sistem akan rollback, log exception, flash pesan gagal, dan redirect ke daftar item.

File bukti:

```text
storage/final_reports/delete_bad_item_10_truncate_result_latest.json
storage/final_reports/delete_bad_item_10_validation_latest.json
```

---

## Sisa Data Yang Sengaja Dipertahankan

Tabel berikut tidak dikosongkan karena masuk kategori konfigurasi, master, audit, dokumen, atau data sensitif:

```text
accounts
alembic_version
approval_requests
audit_logs
bank_accounts
branch_settings
branches
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
migrations
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
users
workers
```

Penghapusan tabel-tabel ini membutuhkan keputusan terpisah.

---

## Putusan

Reset operasional Option A selesai dan database siap dipakai untuk pengembangan bertahap berikutnya.
