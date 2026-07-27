# Batch 2 Scope Rollback Report

Status: REVERTED

## Alasan

Batch 2A sampai 2F di-rollback karena implementasi melebar dari blueprint dan roadmap yang disetujui.

Blueprint menegaskan:

- ketidakjelasan adalah `APPROVAL REQUIRED`;
- Stage 1 fokus pada portal, role mapping, order/lokasi, status, prepayment guard, dan admin confirmation;
- financial, stock, production, delivery mutasi, payment, closing, procurement, supplier bill, dan area sensitif lain tidak boleh diimplementasikan tanpa approval eksplisit.

## Commit Yang Dicabut

- `8f8aec9` - Batch 2A financial visibility
- `f1ace93` - Batch 2B order status visibility
- `cd3d0d2` - Batch 2C delivery visibility
- `721fc50` - Batch 2D production visibility
- `bcea97a` - Batch 2E inventory visibility
- `8f36475` - Batch 2F procurement visibility

## Revert Commits

- `77e3849` - revert Batch 2F
- `6b5ce93` - revert Batch 2E
- `45415d6` - revert Batch 2D
- `c263147` - revert Batch 2C
- `9fae212` - revert Batch 2B
- `8482576` - revert Batch 2A

## Tags Dihapus

- `batch-2a-portal-financial-visibility`
- `batch-2b-portal-order-status-visibility`
- `batch-2c-portal-delivery-visibility`
- `batch-2d-portal-production-visibility`
- `batch-2e-portal-inventory-visibility`
- `batch-2f-portal-procurement-visibility`

## Kondisi Setelah Rollback

Portal template tersisa:

- `dashboard.html`
- `customers.html`
- `mandors.html`
- `ownership.html`
- `status.html`

Tidak ada lagi halaman portal Batch 2:

- `financial.html`
- `orders.html`
- `deliveries.html`
- `productions.html`
- `inventory.html`
- `procurement.html`

## Bukti Verifikasi

- `python -m compileall app tests`: PASS
- `python -m pytest tests/test_portal_foundation.py -q`: 13 passed, 8 warnings
- `python -m pytest -q`: 295 passed, 11 warnings
- `python scripts/baseline_safety_audit.py`: READY_FOR_STAGE_1

Baseline audit terbaru:

- Route total: 346
- Safe GET executed: 151/151
- Smoke failures: 0
- Template parsed: 217/217
- Missing endpoint references: 0
- Route commit: 0
- Route rollback: 0

## Putusan

Batch 2A-2F tidak lagi menjadi bagian scope aktif. Titik aman terakhir untuk lanjut adalah Batch 1G, dengan perubahan berikutnya harus mengikuti blueprint dan membutuhkan approval eksplisit untuk area sensitif.
