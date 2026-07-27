# BATCH 1D IMPLEMENTATION REPORT

ERP PT Idha Boga Pangan Mandiri

Status: VERIFIED

Tanggal: 2026-07-27

## Scope

Batch 1D menambahkan integrasi navigasi portal internal yang tetap dikendalikan feature flag `PORTAL_ENABLED`.

Yang dibuat:
- Context value `global_portal_enabled` untuk template.
- Menu sidebar `Portal` hanya untuk OWNER/ADMIN saat `PORTAL_ENABLED=1`.
- Link read-only:
  - `/portal/dashboard`
  - `/portal/customers`
  - `/portal/mandors`
- Regression test untuk memastikan menu portal tidak muncul saat flag OFF.
- Regression test untuk memastikan role non-preview tidak melihat menu portal walaupun flag ON.

Yang tidak dilakukan:
- Tidak ada migration.
- Tidak ada role eksternal.
- Tidak ada permission baru.
- Tidak ada mapping user eksternal.
- Tidak ada POST portal.
- Tidak ada create/edit/delete portal.
- Tidak ada perubahan order, invoice, payment, journal, stock, HPP, receivable/payable, atau closing.

## Files Changed

- `app/__init__.py`
- `app/templates/layouts/sidebar.html`
- `tests/test_portal_foundation.py`
- `storage/final_reports/BASELINE_SAFETY_AUDIT_LATEST.md`

## Behavior Before

Route portal sudah ada, tetapi belum masuk navigasi global. User harus membuka `/portal/dashboard` langsung saat feature flag aktif.

## Behavior After

Saat `PORTAL_ENABLED=0`:
- Portal route tetap 404.
- Sidebar tidak menampilkan link `/portal`.

Saat `PORTAL_ENABLED=1`:
- OWNER/ADMIN melihat menu Portal di sidebar.
- FINANCE dan role non-preview lain tidak melihat menu Portal.
- Link mengarah ke route portal yang sudah ada dan sudah diuji.

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
python -m pytest -q tests/test_portal_foundation.py tests/test_route_endpoint_references.py
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
293 passed, 9 warnings
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
- `storage/final_reports/BASELINE_SAFETY_AUDIT_20260727_170723.md`
- `storage/final_reports/baseline_route_map_20260727_170723.json`
- `storage/final_reports/baseline_runtime_smoke_20260727_170723.json`
- `storage/final_reports/baseline_template_audit_20260727_170723.json`

## Rollback

Rollback Batch 1D:

```bash
git revert <batch-1d-commit>
```

Tidak ada rollback database karena tidak ada schema/data migration.

## Known Limitations

- Menu portal masih internal OWNER/ADMIN.
- Belum ada external user login untuk client/mandor/PT.
- Belum ada portal order draft.
- Belum ada status order portal.
- Belum ada data invoice/payment eksternal.

## Next Safe Step

Batch 1E - Portal empty-state dan read-only status shell.

Catatan:
Menambah role eksternal, mapping akun eksternal, atau membuka transaksi order/invoice/payment tetap `APPROVAL REQUIRED`.
