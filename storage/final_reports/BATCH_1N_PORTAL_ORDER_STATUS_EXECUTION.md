# Batch 1N - Portal Order Status Dasar

Date: 2026-07-27

## Scope

Batch ini menambahkan status order portal read-only untuk user portal.

Yang dikerjakan:

- menambahkan service `build_portal_order_status_context`;
- menambahkan route `GET /portal/orders/status`;
- menambahkan template `portal/order_status.html`;
- menambahkan link Status Order di dashboard portal dan sidebar;
- menambahkan test bahwa user hanya melihat draft/order miliknya;
- menambahkan test bahwa halaman tidak menampilkan nominal finansial.

Yang tidak dikerjakan:

- tidak membuka invoice;
- tidak membuka payment;
- tidak membuka journal;
- tidak membuka stock;
- tidak menampilkan detail finansial penuh;
- tidak membuat mutation.

## Data Scope

Status membaca `PortalOrderDraft.user_id == current_user.id`.

Jika draft sudah dikonfirmasi, halaman hanya menampilkan:

- nomor order internal;
- status order internal;
- locked/unlocked status via service context;
- tanpa nilai uang.

## Tests

Perintah yang dijalankan:

```text
python -m compileall app tests
.venv\Scripts\python.exe -m pytest tests\test_portal_foundation.py tests\test_db_commit_audit_tool.py -q
.venv\Scripts\python.exe -m pytest -q
```

Hasil:

- compile: PASS;
- targeted portal/audit: `28 passed`;
- full regression: `308 passed`.

## Rollback

Rollback code:

```text
git revert <batch-1n-commit>
```

Tidak ada migration baru.

## Status

READY_FOR_NEXT_BATCH
