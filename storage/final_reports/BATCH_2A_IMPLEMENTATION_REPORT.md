# BATCH 2A IMPLEMENTATION REPORT

ERP PT Idha Boga Pangan Mandiri

Status: VERIFIED

Tanggal: 2026-07-27

## Scope

Batch 2A menambahkan financial visibility read-only pada portal internal.

Yang dibuat:
- Route `/portal/financial`.
- Template `portal/financial.html`.
- Read model `build_portal_financial_visibility`.
- Link `Financial` di dashboard portal dan sidebar.
- Regression test financial visibility branch-scoped untuk ADMIN.

Yang tidak dilakukan:
- Tidak ada migration.
- Tidak ada role eksternal.
- Tidak ada permission baru.
- Tidak ada mapping user eksternal.
- Tidak ada POST portal.
- Tidak ada create/edit/delete.
- Tidak membuat atau mengubah invoice.
- Tidak membuat atau mengubah payment.
- Tidak membuat jurnal.
- Tidak mengubah piutang/hutang/stock/HPP/closing.

## Behavior After

Saat `PORTAL_ENABLED=1`:
- OWNER/ADMIN dapat membuka `/portal/financial`.
- OWNER melihat preview semua branch.
- ADMIN hanya melihat invoice/payment/supplier bill dari branch sendiri.
- Halaman menampilkan invoice aktif, terbayar, outstanding, payment count, dan hutang supplier terbuka.
- Invoice `CANCELLED`/`VOID` tidak masuk ringkasan aktif.

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
- order;
- invoice/payment mutation;
- journal;
- stock;
- HPP;
- receivable/payable mutation;
- closing.

## Targeted Test

Command:

```bash
python -m pytest -q tests/test_portal_foundation.py tests/test_route_endpoint_references.py tests/test_baseline_safety_audit_tool.py
```

Result:

```text
19 passed
```

## Full Test

Command:

```bash
python -m compileall app tests scripts
python -m pytest -q
```

Result:

```text
296 passed, 12 warnings
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
Total route: 347
Duplicate rule/method: 0
Safe GET candidates: 152
Safe GET executed: 152
Smoke failures: 0
Total template: 218
Parsed: 218
Missing endpoint references: 0
Route commit: 0
Route rollback: 0
```

## Rollback

Rollback Batch 2A:

```bash
git revert <batch-2a-commit>
```

Tidak ada rollback database karena tidak ada schema/data migration.

## Next Safe Step

Batch 2B - order status visibility read-only internal.

Catatan:
External user mapping, draft order, invoice/payment external visibility, dan payment upload tetap `APPROVAL_REQUIRED`.
