# Batch 2E Implementation Report - Portal Inventory Visibility

Status: READY

## Scope

Batch 2E menambahkan visibility inventory/stok read-only untuk portal internal OWNER/ADMIN.

Perubahan ini additive dan tidak menyentuh:

- migration;
- role/permission existing;
- stock adjustment;
- fulfillment;
- procurement posting;
- produksi;
- HPP;
- invoice;
- journal;
- closing.

## Perubahan

1. `app/services/portal_access_service.py`
   - Menambahkan `build_portal_inventory_visibility`.
   - Menggunakan `get_item_stock` dari service stok existing.
   - Membaca `StockMovement`, `StockOpeningBalance`, dan `Item`.
   - ADMIN hanya melihat saldo/movement sesuai `user.branch_id`.
   - Item yang tampil dibatasi ke item yang punya opening balance atau movement dalam branch scope.
   - Tidak ada `db.session.commit()` atau `db.session.rollback()`.

2. `app/routes/portal_routes.py`
   - Menambahkan GET `/portal/inventory`.
   - Tetap di belakang feature flag `PORTAL_ENABLED`.
   - Tetap memakai `@role_required("ADMIN")`.

3. `app/templates/portal/inventory.html`
   - Halaman ringkasan stok read-only.
   - Menampilkan item stok, status aman/menipis/kosong, saldo, minimum, dan mutasi terbaru.
   - Tidak ada form atau tombol mutasi.

4. `app/templates/portal/dashboard.html`
   - Menambah link internal ke Inventory Visibility.

5. `app/templates/layouts/sidebar.html`
   - Menambah menu portal Inventory saat feature flag aktif dan role eligible.

6. `tests/test_portal_foundation.py`
   - Menambah fixture stok nyata berbasis `Item`, `StockOpeningBalance`, dan `StockMovement`.
   - Menambah regression test `/portal/inventory` dengan branch-scope.
   - Memastikan data cabang lain tidak tampil.
   - Memastikan halaman portal inventory tidak memiliki form mutasi.

## Bukti Verifikasi

- `python -m compileall app tests`: PASS
- `python -m pytest tests/test_portal_foundation.py -q`: 18 passed, 13 warnings
- `python -m pytest -q`: 300 passed, 16 warnings
- `python scripts/baseline_safety_audit.py`: READY_FOR_STAGE_1

## Baseline Audit Terbaru

- Report: `storage/final_reports/BASELINE_SAFETY_AUDIT_20260727_175303.md`
- Route map: `storage/final_reports/baseline_route_map_20260727_175303.json`
- Template audit: `storage/final_reports/baseline_template_audit_20260727_175303.json`
- Runtime smoke: `storage/final_reports/baseline_runtime_smoke_20260727_175303.json`

Ringkasan audit:

- Total route: 351
- Duplicate rule/method: 0
- Safe GET candidates: 156
- Safe GET executed: 156
- Smoke failures: 0
- Total template: 222
- Parsed: 222
- Template parse errors: 0
- Literal endpoint references: 338
- Missing endpoint references: 0
- Route commit: 0
- Route rollback: 0

## Rollback Plan

Rollback batch:

```text
git revert <batch-2e-commit>
```

Tidak ada rollback database karena tidak ada migration dan tidak ada schema/data seed baru.

## Risiko Tersisa

- Halaman ini hanya read-only internal.
- Adjustment stok, issue barang, fulfillment, dan konsumsi HPP tetap belum dibuka karena menyentuh stok operasional.
- Mapping portal eksternal tetap APPROVAL_REQUIRED.

## Putusan

READY
