# Batch 2F Implementation Report - Portal Procurement Visibility

Status: READY

## Scope

Batch 2F menambahkan visibility procurement dan supplier bill read-only untuk portal internal OWNER/ADMIN.

Perubahan ini additive dan tidak menyentuh:

- migration;
- role/permission existing;
- pembuatan procurement;
- posting hutang supplier;
- pembayaran supplier;
- cash/bank;
- journal;
- stock;
- HPP;
- closing.

## Perubahan

1. `app/services/portal_access_service.py`
   - Menambahkan `build_portal_procurement_visibility`.
   - Membaca `Procurement`, `ProcurementItem`, dan `SupplierBill`.
   - ADMIN hanya melihat data sesuai `user.branch_id`.
   - OWNER tetap preview lintas cabang.
   - Menampilkan summary pembelian, item pembelian, supplier bill terbuka, dan outstanding.
   - Tidak ada `db.session.commit()` atau `db.session.rollback()`.

2. `app/routes/portal_routes.py`
   - Menambahkan GET `/portal/procurement`.
   - Tetap di belakang feature flag `PORTAL_ENABLED`.
   - Tetap memakai `@role_required("ADMIN")`.

3. `app/templates/portal/procurement.html`
   - Halaman ringkasan pembelian dan supplier bill read-only.
   - Menampilkan pembelian terbaru dan supplier bill terdekat.
   - Tidak ada form, tombol bayar, tombol posting, atau aksi mutasi.

4. `app/templates/portal/dashboard.html`
   - Menambah link internal ke Procurement Visibility.

5. `app/templates/layouts/sidebar.html`
   - Menambah menu portal Procurement saat feature flag aktif dan role eligible.

6. `tests/test_portal_foundation.py`
   - Menambah fixture nyata berbasis `Supplier`, `Item`, `Procurement`, `ProcurementItem`, dan `SupplierBill`.
   - Menambah regression test `/portal/procurement` dengan branch-scope.
   - Memastikan procurement/supplier bill cabang lain tidak tampil.
   - Memastikan halaman portal procurement tidak memiliki form mutasi.

## Bukti Verifikasi

- `python -m compileall app tests`: PASS
- `python -m pytest tests/test_portal_foundation.py -q`: 19 passed, 14 warnings
- `python -m pytest -q`: 301 passed, 17 warnings
- `python scripts/baseline_safety_audit.py`: READY_FOR_STAGE_1

## Baseline Audit Terbaru

- Report: `storage/final_reports/BASELINE_SAFETY_AUDIT_20260727_180009.md`
- Route map: `storage/final_reports/baseline_route_map_20260727_180009.json`
- Template audit: `storage/final_reports/baseline_template_audit_20260727_180009.json`
- Runtime smoke: `storage/final_reports/baseline_runtime_smoke_20260727_180009.json`

Ringkasan audit:

- Total route: 352
- Duplicate rule/method: 0
- Safe GET candidates: 157
- Safe GET executed: 157
- Smoke failures: 0
- Total template: 223
- Parsed: 223
- Template parse errors: 0
- Literal endpoint references: 339
- Missing endpoint references: 0
- Route commit: 0
- Route rollback: 0

## Rollback Plan

Rollback batch:

```text
git revert <batch-2f-commit>
```

Tidak ada rollback database karena tidak ada migration dan tidak ada schema/data seed baru.

## Risiko Tersisa

- Halaman ini hanya read-only internal.
- Posting hutang, pembayaran supplier, cash/bank ledger, dan jurnal tetap belum dibuka karena menyentuh keuangan sensitif.
- Mapping portal eksternal tetap APPROVAL_REQUIRED.

## Putusan

READY
