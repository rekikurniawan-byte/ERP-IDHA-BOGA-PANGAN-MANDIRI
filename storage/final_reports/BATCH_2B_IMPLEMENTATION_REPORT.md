# BATCH 2B IMPLEMENTATION REPORT

ERP PT Idha Boga Pangan Mandiri

Status: VERIFIED

Tanggal: 2026-07-27

## Scope

Batch 2B menambahkan order status visibility read-only pada portal internal.

Yang dibuat:
- Route `/portal/orders`.
- Template `portal/orders.html`.
- Read model `build_portal_order_status_visibility`.
- Link `Status Order` di dashboard portal dan sidebar.
- Regression test branch-scoped untuk ADMIN.

Yang tidak dilakukan:
- Tidak ada migration.
- Tidak ada role eksternal.
- Tidak ada permission baru.
- Tidak ada mapping user eksternal.
- Tidak ada POST portal.
- Tidak membuat order.
- Tidak mengubah status order.
- Tidak mengubah produksi atau delivery.
- Tidak membuat invoice/payment/journal/stock movement.

## Behavior After

Saat `PORTAL_ENABLED=1`:
- OWNER/ADMIN dapat membuka `/portal/orders`.
- OWNER melihat preview semua branch.
- ADMIN hanya melihat order/produksi/delivery dari branch sendiri.
- Halaman menampilkan jumlah order, locked/draft, total porsi, produksi, dan delivery.
- List order terbaru hanya read-only.

Saat `PORTAL_ENABLED=0`:
- Route portal tetap 404 melalui guard existing.

## Database Change

Tidak ada.

Alembic tetap:
- current: `90a0a1b2c3d4`
- head: `90a0a1b2c3d4`

## Sensitive Change

Tidak ada perubahan sensitif.

Tidak menyentuh:
- schema;
- migration;
- role/permission;
- order mutation/lifecycle;
- production mutation;
- delivery mutation;
- invoice/payment;
- journal;
- stock;
- HPP;
- closing.

## Targeted Test

Command:

```bash
python -m pytest -q tests/test_portal_foundation.py tests/test_route_endpoint_references.py tests/test_baseline_safety_audit_tool.py
```

Result:

```text
20 passed
```

## Full Test

Command:

```bash
python -m compileall app tests scripts
python -m pytest -q
```

Result:

```text
297 passed, 13 warnings
```

Warnings yang tersisa adalah `LegacyAPIWarning` SQLAlchemy `Query.get()` pada kode existing.

## Route And Template Coverage

Command:

```bash
python scripts/baseline_safety_audit.py
```

Result:

```text
Status: READY_FOR_STAGE_1
Total route: 348
Duplicate rule/method: 0
Safe GET candidates: 153
Safe GET executed: 153
Smoke failures: 0
Total template: 219
Parsed: 219
Missing endpoint references: 0
Route commit: 0
Route rollback: 0
```

## Rollback

Rollback Batch 2B:

```bash
git revert <batch-2b-commit>
```

Tidak ada rollback database karena tidak ada schema/data migration.

## Next Safe Step

Batch 2C - delivery visibility read-only detail internal.

Catatan:
External user mapping, draft order, update status order, update delivery, invoice/payment external visibility, dan payment upload tetap `APPROVAL_REQUIRED`.
