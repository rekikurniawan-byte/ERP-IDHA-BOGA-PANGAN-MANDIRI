# BATCH 1C IMPLEMENTATION REPORT

ERP PT Idha Boga Pangan Mandiri

Status: VERIFIED

Tanggal: 2026-07-27

## Scope

Batch 1C menambahkan read-only directory dashboard untuk Client/PT dan Mandor di namespace portal internal.

Yang dibuat:
- `/portal/customers`
- `/portal/mandors`
- Read model untuk customer directory.
- Read model untuk mandor directory.
- Branch scoping untuk ADMIN.
- OWNER aggregate preview.
- Regression test untuk memastikan ADMIN tidak melihat data branch lain.

Yang tidak dilakukan:
- Tidak ada migration.
- Tidak ada role eksternal.
- Tidak ada mapping user eksternal.
- Tidak ada form/action POST portal.
- Tidak ada create/edit/delete.
- Tidak ada order portal.
- Tidak ada payment, invoice, journal, stock, HPP, receivable/payable, atau closing.

## Files Changed

- `app/services/portal_access_service.py`
- `app/routes/portal_routes.py`
- `app/templates/portal/dashboard.html`
- `app/templates/portal/customers.html`
- `app/templates/portal/mandors.html`
- `tests/test_portal_foundation.py`
- `storage/final_reports/BASELINE_SAFETY_AUDIT_LATEST.md`

## Behavior Before

Batch 1B hanya menampilkan scope preview terbatas di dashboard portal.

## Behavior After

Saat `PORTAL_ENABLED=1`:
- OWNER/ADMIN dapat membuka dashboard portal.
- OWNER/ADMIN dapat membuka directory read-only:
  - `/portal/customers`
  - `/portal/mandors`
- ADMIN hanya melihat client/mandor/lokasi yang tersambung ke branch user.
- Directory tidak memiliki form mutasi atau action ke `/portal`.

Saat `PORTAL_ENABLED=0`:
- Route portal tetap 404.

## Database Change

Tidak ada.

Alembic tetap:
- current: `90a0a1b2c3d4`
- head: `90a0a1b2c3d4`

## Sensitive Change

Tidak ada perubahan sensitif.

Tidak menyentuh:
- role existing;
- permission existing;
- order;
- invoice;
- payment;
- journal;
- stock;
- HPP;
- receivable/payable;
- closing;
- migration.

## Targeted Test

Command:

```bash
python -m pytest -q tests/test_portal_foundation.py tests/test_route_endpoint_references.py tests/test_baseline_safety_audit_tool.py
```

Result:

```text
13 passed
```

## Full Test

Command:

```bash
python -m compileall app tests scripts
python -m pytest -q
```

Result:

```text
290 passed, 6 warnings
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
Total route: 344
Duplicate rule/method: 0
Safe GET candidates: 149
Safe GET executed: 149
Smoke failures: 0
Total template: 215
Parsed: 215
Missing endpoint references: 0
Route commit: 0
Route rollback: 0
```

Audit files:
- `storage/final_reports/BASELINE_SAFETY_AUDIT_20260727_165947.md`
- `storage/final_reports/baseline_route_map_20260727_165947.json`
- `storage/final_reports/baseline_runtime_smoke_20260727_165947.json`
- `storage/final_reports/baseline_template_audit_20260727_165947.json`

## Rollback

Rollback Batch 1C:

```bash
git revert <batch-1c-commit>
```

Tidak ada rollback database karena tidak ada schema/data migration.

## Known Limitations

- Directory masih preview internal OWNER/ADMIN.
- Belum ada akun eksternal client/mandor/PT.
- Belum ada ownership matrix final untuk external user.
- Belum ada order portal.
- Belum ada data invoice/payment eksternal.

## Next Safe Step

Batch 1D - Portal Navigation Integration default OFF.

Catatan:
Menampilkan menu portal ke user eksternal nyata, menambah role eksternal, atau membuka invoice/payment tetap `APPROVAL REQUIRED`.
