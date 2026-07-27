# BATCH 1A IMPLEMENTATION REPORT

ERP PT Idha Boga Pangan Mandiri

Status: VERIFIED

Tanggal: 2026-07-27

## Scope

Batch 1A mengimplementasikan portal foundation yang additive, read-only, dan default OFF.

Yang dibuat:
- Feature flag `PORTAL_ENABLED`, default `False`.
- Blueprint namespace `/portal`.
- Portal dashboard read-only untuk preview internal.
- Authorization awal: hanya OWNER/ADMIN saat flag ON.
- Regression tests untuk feature flag, auth, role guard, dan no route commit/rollback.
- Baseline audit diperbarui agar route portal default-off tidak dihitung sebagai failure palsu.

Yang tidak dilakukan:
- Tidak ada migration.
- Tidak ada model baru.
- Tidak ada service bisnis baru.
- Tidak ada workflow order portal.
- Tidak ada payment/upload/invoice/journal/stock/closing.
- Tidak ada role eksternal baru.
- Tidak ada perubahan lifecycle atau business rule existing.

## Files Changed

- `config.py`
- `.env.example`
- `.env.production.example`
- `app/__init__.py`
- `app/routes/portal_routes.py`
- `app/templates/portal/dashboard.html`
- `tests/test_portal_foundation.py`
- `scripts/baseline_safety_audit.py`
- `storage/final_reports/BATCH_1_IMPLEMENTATION_PLAN.md`

## Behavior Before

- Tidak ada namespace portal.
- Tidak ada feature flag portal.
- Tidak ada route/template portal.

## Behavior After

- `PORTAL_ENABLED=0` atau default:
  - `/portal` dan `/portal/dashboard` mengembalikan 404.
- `PORTAL_ENABLED=1`:
  - unauthenticated user diarahkan ke login;
  - OWNER/ADMIN dapat membuka dashboard portal read-only;
  - role internal lain ditolak oleh role guard existing;
  - tidak ada mutasi database.

## Database Change

Tidak ada.

Alembic tetap:
- current: `90a0a1b2c3d4`
- head: `90a0a1b2c3d4`

## Sensitive Change

Tidak ada perubahan sensitif.

Tidak menyentuh:
- order;
- payment;
- invoice;
- journal;
- stock;
- receivable/payable;
- closing;
- role existing;
- permission existing;
- migration.

## Targeted Test

Command:

```bash
python -m pytest -q tests/test_portal_foundation.py tests/test_route_endpoint_references.py tests/test_baseline_safety_audit_tool.py
```

Result:

```text
10 passed
```

## Full Test

Command:

```bash
python -m compileall app tests scripts
python -m pytest -q
```

Result:

```text
287 passed, 5 warnings
```

Warnings yang tersisa adalah `LegacyAPIWarning` SQLAlchemy `Query.get()` pada kode existing, bukan regression Batch 1A.

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
- `storage/final_reports/BASELINE_SAFETY_AUDIT_20260727_164557.md`
- `storage/final_reports/baseline_route_map_20260727_164557.json`
- `storage/final_reports/baseline_runtime_smoke_20260727_164557.json`
- `storage/final_reports/baseline_template_audit_20260727_164557.json`

## Rollback

Rollback Batch 1A:

```bash
git revert <batch-1a-commit>
```

Karena tidak ada migration dan tidak ada data mutation, rollback database tidak diperlukan.

## Known Limitations

- Portal masih shell read-only.
- Role eksternal belum dibuat.
- Mapping user ke client/mandor/PT belum dibuat.
- Order portal belum dibuat.
- Dashboard portal belum membuka data bisnis eksternal.
- Tidak ada POST portal.

## Next Safe Step

Batch 1B - Portal Access Scope Read-only.

Sebelum Batch 1B, owner perlu menyetujui apakah mapping eksternal akan:
- memakai user internal sementara untuk preview;
- memakai role existing terbatas;
- atau menambah role/mapping baru, yang berarti `APPROVAL REQUIRED`.
