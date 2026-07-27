# Batch 2D Implementation Report - Portal Production Visibility

Status: READY

## Scope

Batch 2D menambahkan visibility produksi read-only untuk portal internal OWNER/ADMIN.

Perubahan ini additive dan tidak menyentuh:

- migration;
- role/permission existing;
- completion produksi;
- konsumsi stok;
- HPP;
- invoice;
- payment;
- journal;
- closing;
- workflow mutasi operasional.

## Perubahan

1. `app/services/portal_access_service.py`
   - Menambahkan `build_portal_production_visibility`.
   - Membaca `Production`, `ProductionDetail`, dan nama `Item`.
   - ADMIN hanya melihat data produksi sesuai `user.branch_id`.
   - OWNER tetap preview lintas cabang.
   - Loop detail memakai query eksplisit agar tidak terkena stale relationship saat fixture/runtime.
   - Tidak ada `db.session.commit()` atau `db.session.rollback()`.

2. `app/routes/portal_routes.py`
   - Menambahkan GET `/portal/productions`.
   - Tetap di belakang feature flag `PORTAL_ENABLED`.
   - Tetap memakai `@role_required("ADMIN")`.

3. `app/templates/portal/productions.html`
   - Halaman ringkasan produksi read-only.
   - Menampilkan count produksi, draft, completed, planned, actual, variance, dan item.
   - Menggunakan `row["items"]` agar Jinja tidak membaca method `dict.items`.
   - Tidak ada form atau tombol mutasi.

4. `app/templates/portal/dashboard.html`
   - Menambah link internal ke Production Visibility.

5. `app/templates/layouts/sidebar.html`
   - Menambah menu portal Produksi saat feature flag aktif dan role eligible.

6. `tests/test_portal_foundation.py`
   - Menambah fixture produksi nyata berbasis `Production`, `ProductionDetail`, dan `Item`.
   - Menambah regression test `/portal/productions` dengan branch-scope.
   - Memastikan data cabang lain tidak tampil.
   - Memastikan halaman portal production tidak memiliki form mutasi.
   - Test menangkap regresi Jinja `row.items` yang sempat merender object repr.

## Bukti Verifikasi

- `python -m compileall app tests`: PASS
- `python -m pytest tests/test_portal_foundation.py::test_portal_production_visibility_is_read_only_and_branch_scoped -q`: 1 passed, 1 warning
- `python -m pytest tests/test_portal_foundation.py -q`: 17 passed, 12 warnings
- `python -m pytest -q`: 299 passed, 15 warnings
- `python scripts/baseline_safety_audit.py`: READY_FOR_STAGE_1

## Baseline Audit Terbaru

- Report: `storage/final_reports/BASELINE_SAFETY_AUDIT_20260727_174819.md`
- Route map: `storage/final_reports/baseline_route_map_20260727_174819.json`
- Template audit: `storage/final_reports/baseline_template_audit_20260727_174819.json`
- Runtime smoke: `storage/final_reports/baseline_runtime_smoke_20260727_174819.json`

Ringkasan audit:

- Total route: 350
- Duplicate rule/method: 0
- Safe GET candidates: 155
- Safe GET executed: 155
- Smoke failures: 0
- Total template: 221
- Parsed: 221
- Template parse errors: 0
- Literal endpoint references: 337
- Missing endpoint references: 0
- Route commit: 0
- Route rollback: 0

## Rollback Plan

Rollback batch:

```text
git revert <batch-2d-commit>
```

Tidak ada rollback database karena tidak ada migration dan tidak ada schema/data seed baru.

## Risiko Tersisa

- Halaman ini hanya read-only internal.
- Aksi completion produksi, konsumsi stok, variance approval, dan integrasi HPP tetap belum dibuka karena menyentuh workflow sensitif.
- Mapping portal eksternal tetap APPROVAL_REQUIRED.

## Putusan

READY
