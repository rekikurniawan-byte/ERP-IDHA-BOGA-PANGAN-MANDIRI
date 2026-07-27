# Batch 1M - Admin Confirmation Bridge

Date: 2026-07-27

## Scope

Batch ini menambahkan bridge admin untuk mengonfirmasi `PortalOrderDraft` menjadi `DailyOrder` DRAFT existing.

Yang dikerjakan:

- menambahkan list admin `GET /portal/admin/order-drafts`;
- menambahkan action `POST /portal/admin/order-drafts/<id>/confirm`;
- menambahkan action `POST /portal/admin/order-drafts/<id>/reject`;
- menambahkan template `portal/admin_order_drafts.html`;
- menambahkan service atomik `confirm_portal_order_draft`;
- menambahkan service `reject_portal_order_draft`;
- menambahkan guard admin cabang;
- menambahkan idempotency confirm: draft confirmed tidak membuat order/detail kedua.

Yang sengaja tidak dikerjakan:

- tidak lock order;
- tidak membuat produksi;
- tidak membuat delivery;
- tidak membuat invoice;
- tidak membuat payment;
- tidak membuat journal;
- tidak mengubah stok;
- tidak menjalankan closing.

## Business Rule

Confirm:

- hanya untuk draft `PENDING_ADMIN_CONFIRMATION`;
- menolak jika admin bukan OWNER dan cabangnya berbeda;
- menolak jika order harian tujuan sudah `LOCKED`;
- membuat atau memakai `DailyOrder` DRAFT existing untuk branch/tanggal yang sama;
- membuat `DailyOrderDetail` sesuai meal type dan portion;
- menolak jika detail mandor/lokasi sudah ada agar tidak silent-duplicate;
- menyimpan `converted_daily_order_id`;
- satu service commit.

Reject:

- hanya untuk draft pending;
- tidak membuat `DailyOrder`;
- menyimpan reviewer, waktu review, dan catatan.

## PostgreSQL Locking Fix

Awalnya `with_for_update()` memicu error PostgreSQL karena model draft memiliki relationship eager join.

Perbaikan:

- query lock memakai `lazyload("*")`;
- `with_for_update(of=PortalOrderDraft)`;
- lock hanya diterapkan ke tabel `portal_order_drafts`.

## Tests

Perintah yang dijalankan:

```text
python -m compileall app tests
.venv\Scripts\python.exe -m pytest tests\test_portal_foundation.py tests\test_db_commit_audit_tool.py tests\test_optimistic_locking_models.py -q
.venv\Scripts\python.exe -m pytest -q
```

Hasil:

- compile: PASS;
- targeted portal/audit/locking: `30 passed`;
- full regression: `307 passed`;
- route commit tetap 0;
- bridge confirm/reject diuji via login route nyata.

## Rollback

Rollback code:

```text
git revert <batch-1m-commit>
```

Tidak ada migration baru pada batch ini.

## Status

READY_FOR_NEXT_BATCH
