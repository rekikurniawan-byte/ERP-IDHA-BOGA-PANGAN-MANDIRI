# BATCH 1E IMPLEMENTATION REPORT

ERP PT Idha Boga Pangan Mandiri

Status: VERIFIED

Tanggal: 2026-07-27

## Scope

Batch 1E menambahkan portal read-only status shell dan empty-state pengembangan portal.

Yang dibuat:
- Route `/portal/status`.
- Template `portal/status.html`.
- Read model `build_portal_status_shell`.
- Menu sidebar `Status Portal`.
- Link status dari dashboard portal.
- Regression test status shell read-only.

Yang tidak dilakukan:
- Tidak ada migration.
- Tidak ada role eksternal.
- Tidak ada permission baru.
- Tidak ada mapping akun eksternal.
- Tidak ada POST portal.
- Tidak ada create/edit/delete portal.
- Tidak ada order portal.
- Tidak ada invoice/payment portal.
- Tidak ada perubahan journal, stock, HPP, receivable/payable, atau closing.

## Files Changed

- `app/services/portal_access_service.py`
- `app/routes/portal_routes.py`
- `app/templates/portal/status.html`
- `app/templates/portal/dashboard.html`
- `app/templates/layouts/sidebar.html`
- `tests/test_portal_foundation.py`
- `storage/final_reports/BASELINE_SAFETY_AUDIT_LATEST.md`

## Behavior Before

Portal memiliki dashboard, Client/PT directory, dan Mandor directory. Status gate pengembangan berikutnya belum terlihat di UI.

## Behavior After

Saat `PORTAL_ENABLED=1`:
- OWNER/ADMIN dapat membuka `/portal/status`.
- Halaman status menampilkan area READY dan APPROVAL_REQUIRED.
- Area sensitif seperti external account, draft order, order status, invoice/payment tetap ditandai belum aktif.
- Tidak ada form/action mutasi portal.

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
17 passed
```

## Full Test

Command:

```bash
python -m compileall app tests scripts
python -m pytest -q
```

Result:

```text
294 passed, 10 warnings
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
Total route: 345
Duplicate rule/method: 0
Safe GET candidates: 150
Safe GET executed: 150
Smoke failures: 0
Total template: 216
Parsed: 216
Missing endpoint references: 0
Route commit: 0
Route rollback: 0
```

Audit files:
- `storage/final_reports/BASELINE_SAFETY_AUDIT_20260727_171200.md`
- `storage/final_reports/baseline_route_map_20260727_171200.json`
- `storage/final_reports/baseline_runtime_smoke_20260727_171200.json`
- `storage/final_reports/baseline_template_audit_20260727_171200.json`

## Rollback

Rollback Batch 1E:

```bash
git revert <batch-1e-commit>
```

Tidak ada rollback database karena tidak ada schema/data migration.

## Known Limitations

- Portal masih preview internal OWNER/ADMIN.
- External account mapping belum ada.
- Draft order portal belum dibuat.
- Status order portal belum membaca data transaksi.
- Invoice/payment portal belum dibuka.

## Next Safe Step

Batch 1F - Portal customer ownership analysis report.

Catatan:
Mapping user eksternal, role eksternal, atau workflow order portal tetap `APPROVAL REQUIRED`.
