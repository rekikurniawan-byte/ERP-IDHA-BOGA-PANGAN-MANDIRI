# BATCH 1F IMPLEMENTATION REPORT

ERP PT Idha Boga Pangan Mandiri

Status: VERIFIED

Tanggal: 2026-07-27

## Scope

Batch 1F menambahkan portal ownership analysis read-only.

Yang dibuat:
- Route `/portal/ownership`.
- Template `portal/ownership.html`.
- Read model `build_portal_ownership_analysis`.
- Link `Ownership` di dashboard portal dan sidebar.
- Regression test ownership analysis dengan branch scoping ADMIN.

Yang tidak dilakukan:
- Tidak ada migration.
- Tidak ada role eksternal.
- Tidak ada permission baru.
- Tidak ada mapping user eksternal.
- Tidak ada perubahan model `User`, `Client`, `Mandor`, atau `ClientPic`.
- Tidak ada POST portal.
- Tidak ada create/edit/delete portal.
- Tidak ada order portal.
- Tidak ada invoice/payment portal.
- Tidak ada perubahan journal, stock, HPP, receivable/payable, atau closing.

## Files Changed

- `app/services/portal_access_service.py`
- `app/routes/portal_routes.py`
- `app/templates/portal/ownership.html`
- `app/templates/portal/dashboard.html`
- `app/templates/layouts/sidebar.html`
- `tests/test_portal_foundation.py`
- `storage/final_reports/BASELINE_SAFETY_AUDIT_LATEST.md`

## Behavior Before

Portal sudah memiliki dashboard, directory Client/PT, directory Mandor, dan status shell. Belum ada halaman yang menjelaskan sumber ownership dan gap mapping akun eksternal.

## Behavior After

Saat `PORTAL_ENABLED=1`:
- OWNER/ADMIN dapat membuka `/portal/ownership`.
- Halaman menampilkan ringkasan scope dari master existing.
- Halaman menunjukkan relationship:
  - Client/PT dari `clients`;
  - Mandor dari `mandors`;
  - Client PIC dari `client_pics`;
  - Delivery Location dari `delivery_locations`;
  - User internal dari `users`.
- Halaman menegaskan bahwa `User` saat ini hanya punya `branch_id` dan `role`, belum punya `client_id`, `mandor_id`, atau principal eksternal.
- Decision gate untuk principal eksternal dan mapping user tetap `APPROVAL_REQUIRED`.

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
- schema;
- migration;
- order;
- invoice;
- payment;
- journal;
- stock;
- HPP;
- receivable/payable;
- closing.

## Targeted Test

Command:

```bash
python -m pytest -q tests/test_portal_foundation.py tests/test_route_endpoint_references.py tests/test_baseline_safety_audit_tool.py
```

Result:

```text
18 passed
```

## Full Test

Command:

```bash
python -m compileall app tests scripts
python -m pytest -q
```

Result:

```text
295 passed, 11 warnings
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
Total route: 346
Duplicate rule/method: 0
Safe GET candidates: 151
Safe GET executed: 151
Smoke failures: 0
Total template: 217
Parsed: 217
Missing endpoint references: 0
Route commit: 0
Route rollback: 0
```

Audit files:
- `storage/final_reports/BASELINE_SAFETY_AUDIT_20260727_171707.md`
- `storage/final_reports/baseline_route_map_20260727_171707.json`
- `storage/final_reports/baseline_runtime_smoke_20260727_171707.json`
- `storage/final_reports/baseline_template_audit_20260727_171707.json`

## Rollback

Rollback Batch 1F:

```bash
git revert <batch-1f-commit>
```

Tidak ada rollback database karena tidak ada schema/data migration.

## Known Limitations

- Halaman ownership masih analisis internal OWNER/ADMIN.
- Belum ada akun eksternal.
- Belum ada mapping user ke Client/PT/Mandor.
- Belum ada authorization matrix eksternal final.
- Belum ada route portal untuk order/invoice/payment.

## Next Safe Step

Batch 1G - Owner approval package untuk external role dan mapping design.

Catatan:
Batch berikutnya harus berhenti pada dokumen approval bila mulai menyentuh role, permission, schema mapping, atau order portal.
