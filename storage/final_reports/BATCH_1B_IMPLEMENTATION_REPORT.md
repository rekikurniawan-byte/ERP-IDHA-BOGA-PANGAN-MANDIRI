# BATCH 1B IMPLEMENTATION REPORT

ERP PT Idha Boga Pangan Mandiri

Status: VERIFIED

Tanggal: 2026-07-27

## Scope

Batch 1B menambahkan portal access scope read-only berdasarkan master data existing.

Yang dibuat:
- `portal_access_service.py` untuk menghitung scope portal preview.
- OWNER: preview aggregate lintas cabang.
- ADMIN: preview dibatasi cabang user melalui relasi `Mandor.branch_id`.
- Dashboard portal menampilkan jumlah client, mandor, lokasi, active counts, scope mode, dan preview terbatas.
- Regression tests untuk branch-scoped scope ADMIN.

Yang tidak dilakukan:
- Tidak ada migration.
- Tidak ada role eksternal baru.
- Tidak ada mapping user eksternal ke client/mandor/PT.
- Tidak ada order portal.
- Tidak ada POST portal.
- Tidak ada payment, invoice, journal, stock, receivable, payable, HPP, atau closing.

## Files Changed

- `app/services/portal_access_service.py`
- `app/routes/portal_routes.py`
- `app/templates/portal/dashboard.html`
- `tests/test_portal_foundation.py`
- `storage/final_reports/BASELINE_SAFETY_AUDIT_LATEST.md`

## Behavior Before

Portal Batch 1A hanya shell read-only dengan card statis.

## Behavior After

Saat `PORTAL_ENABLED=1`:
- OWNER/ADMIN melihat scope preview dari data master existing.
- ADMIN hanya melihat data yang terhubung ke mandor pada `branch_id` user.
- Dashboard tetap read-only dan tidak punya form/action mutasi.

Saat `PORTAL_ENABLED=0`:
- `/portal` dan `/portal/dashboard` tetap 404.

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
12 passed
```

## Full Test

Command:

```bash
python -m compileall app tests scripts
python -m pytest -q
```

Result:

```text
289 passed, 5 warnings
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
Total route: 342
Duplicate rule/method: 0
Safe GET candidates: 147
Safe GET executed: 147
Smoke failures: 0
Total template: 213
Parsed: 213
Missing endpoint references: 0
Route commit: 0
Route rollback: 0
```

Audit files:
- `storage/final_reports/BASELINE_SAFETY_AUDIT_20260727_165236.md`
- `storage/final_reports/baseline_route_map_20260727_165236.json`
- `storage/final_reports/baseline_runtime_smoke_20260727_165236.json`
- `storage/final_reports/baseline_template_audit_20260727_165236.json`

## Rollback

Rollback Batch 1B:

```bash
git revert <batch-1b-commit>
```

Tidak ada rollback database karena tidak ada schema/data migration.

## Known Limitations

- Scope masih preview internal OWNER/ADMIN.
- User eksternal belum bisa login sebagai client/mandor/PT.
- Belum ada tabel/kolom mapping user ke client/mandor/PT.
- Portal belum membuat draft/order.
- Portal belum menampilkan invoice/payment/detail finansial.

## Next Safe Step

Batch 1C - Customer/Mandor/PT Read-only Dashboard.

Sebelum Batch 1C membuka data ke pihak eksternal nyata, owner perlu approval untuk ownership matrix dan role/mapping eksternal.
