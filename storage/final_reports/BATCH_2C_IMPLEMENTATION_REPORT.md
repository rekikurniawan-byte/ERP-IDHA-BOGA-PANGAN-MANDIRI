# Batch 2C Implementation Report - Portal Delivery Visibility

Status: READY

## Scope

Batch 2C menambahkan visibility delivery read-only untuk portal internal OWNER/ADMIN.

Perubahan ini additive dan tidak menyentuh:

- migration;
- role/permission existing;
- status delivery;
- invoice;
- payment;
- journal;
- stock;
- closing;
- workflow mutasi operasional.

## Perubahan

1. `app/services/portal_access_service.py`
   - Menambahkan `build_portal_delivery_visibility`.
   - Membaca `Delivery` dan `DeliveryDetail`.
   - ADMIN hanya melihat data sesuai `user.branch_id`.
   - OWNER tetap preview lintas cabang.
   - Tidak ada `db.session.commit()` atau `db.session.rollback()`.

2. `app/routes/portal_routes.py`
   - Menambahkan GET `/portal/deliveries`.
   - Tetap di belakang feature flag `PORTAL_ENABLED`.
   - Tetap memakai `@role_required("ADMIN")`.

3. `app/templates/portal/deliveries.html`
   - Halaman ringkasan delivery read-only.
   - Menampilkan jumlah delivery, delivered, quantity terkirim, shortage, driver, dan detail.
   - Tidak ada form atau tombol mutasi.

4. `app/templates/portal/dashboard.html`
   - Menambah link internal ke Delivery Visibility.

5. `app/templates/layouts/sidebar.html`
   - Menambah menu portal Delivery saat feature flag aktif dan role eligible.

6. `tests/test_portal_foundation.py`
   - Menambah fixture delivery nyata berbasis `Delivery`, `DeliveryDetail`, `DailyOrder`, `DailyOrderDetail`, dan `Driver`.
   - Menambah regression test `/portal/deliveries` dengan branch-scope.
   - Memastikan data cabang lain tidak tampil.
   - Memastikan halaman portal delivery tidak memiliki form mutasi.

## Bukti Verifikasi

- `python -m compileall app tests`: PASS
- `python -m pytest tests/test_portal_foundation.py -q`: 16 passed, 11 warnings
- `python -m pytest -q`: 298 passed, 14 warnings
- `python scripts/baseline_safety_audit.py`: READY_FOR_STAGE_1

## Baseline Audit Terbaru

- Report: `storage/final_reports/BASELINE_SAFETY_AUDIT_20260727_174029.md`
- Route map: `storage/final_reports/baseline_route_map_20260727_174029.json`
- Template audit: `storage/final_reports/baseline_template_audit_20260727_174029.json`
- Runtime smoke: `storage/final_reports/baseline_runtime_smoke_20260727_174029.json`

Ringkasan audit:

- Total route: 349
- Duplicate rule/method: 0
- Safe GET candidates: 154
- Safe GET executed: 154
- Smoke failures: 0
- Total template: 220
- Parsed: 220
- Template parse errors: 0
- Literal endpoint references: 336
- Missing endpoint references: 0
- Route commit: 0
- Route rollback: 0

## Rollback Plan

Rollback batch:

```text
git revert <batch-2c-commit>
```

Tidak ada rollback database karena tidak ada migration dan tidak ada schema/data seed baru.

## Risiko Tersisa

- Halaman ini hanya read-only internal. Portal eksternal untuk client/mandor/PT tetap belum diaktifkan.
- Update status delivery, bukti terima, upload dokumen, dan aksi fulfillment tetap belum dibuka karena menyentuh workflow operasional dan perlu approval terpisah.
- Full authorization matrix eksternal belum relevan sampai role/mapping eksternal disetujui.

## Putusan

READY
