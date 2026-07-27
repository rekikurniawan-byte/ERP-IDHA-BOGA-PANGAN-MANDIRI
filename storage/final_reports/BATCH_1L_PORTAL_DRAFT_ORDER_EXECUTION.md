# Batch 1L - Portal Draft Order

Date: 2026-07-27

## Scope

Batch ini menambahkan draft order portal sebagai antrian `PENDING_ADMIN_CONFIRMATION`.

Yang dikerjakan:

- menambahkan model `PortalOrderDraft`;
- menambahkan migration `92a0a1b2c3d4_portal_order_drafts.py`;
- menambahkan service `portal_order_draft_service.py`;
- menambahkan route `GET/POST /portal/orders/draft`;
- menambahkan template `portal/draft_order.html`;
- menambahkan idempotency key per user untuk mencegah double submit;
- menambahkan test bahwa draft tidak membuat `DailyOrder`.

Yang sengaja tidak dikerjakan:

- tidak menulis ke `daily_orders`;
- tidak masuk produksi;
- tidak membuat delivery;
- tidak membuat invoice/payment/journal/stock;
- tidak mengubah status closing;
- belum ada admin confirmation bridge.

## Safety

Draft hanya dapat dibuat jika mapping portal user memiliki `access_level="DRAFT_ORDER"`.

Mapping `READ_ONLY` tetap dapat melihat portal, tetapi tidak dapat submit draft order.

Route tidak memiliki `db.session.commit()` atau `db.session.rollback()`. Transaction boundary ada di service.

## Migration

Database lokal aktif dinaikkan:

```text
91a0a1b2c3d4 -> 92a0a1b2c3d4
```

Migration bersifat additive dan membuat tabel baru `portal_order_drafts`.

## Tests

Perintah yang dijalankan:

```text
python -m compileall app tests
.venv\Scripts\python.exe -m flask db upgrade  # test_db
.venv\Scripts\python.exe -m pytest tests\test_portal_foundation.py tests\test_optimistic_locking_models.py -q
.venv\Scripts\python.exe -m pytest tests\test_db_commit_audit_tool.py tests\test_portal_foundation.py tests\test_optimistic_locking_models.py -q
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m flask db upgrade  # active local DB
```

Hasil:

- compile: PASS;
- targeted portal/locking: PASS;
- commit audit guard: PASS, route commit tetap 0;
- full regression: `304 passed`;
- active DB current: `92a0a1b2c3d4 (head)`.

## Rollback

Rollback code:

```text
git revert <batch-1l-commit>
```

Rollback database lokal:

```text
.venv\Scripts\python.exe -m flask db downgrade 91a0a1b2c3d4
```

Catatan: downgrade menghapus tabel `portal_order_drafts`.

## Status

READY_FOR_NEXT_BATCH
