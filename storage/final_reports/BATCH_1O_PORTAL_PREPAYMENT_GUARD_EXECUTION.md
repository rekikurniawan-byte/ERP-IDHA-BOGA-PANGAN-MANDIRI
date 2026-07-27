# Batch 1O - Prepayment Guard Pelanggan Umum

Date: 2026-07-27

## Scope

Batch ini menambahkan guard pelanggan umum agar order tidak diproses sebelum pembayaran terverifikasi.

Yang dikerjakan:

- role `PORTAL_CUSTOMER` ditahan dari submit draft order;
- service draft order mengembalikan alasan eksplisit prepayment;
- status portal menampilkan gate `Prepayment pelanggan umum`;
- status `Draft order portal` dikoreksi menjadi READY terbatas karena batch 1L/1M sudah aktif;
- test memastikan `PORTAL_CUSTOMER` GET/POST draft tidak membuat `PortalOrderDraft`.

Yang tidak dikerjakan:

- tidak membuat payment;
- tidak membuat QRIS;
- tidak upload bukti payment;
- tidak membuat invoice;
- tidak membuat journal;
- tidak menyentuh receivable;
- tidak mengubah proses finance existing.

## Business Rule

Pelanggan umum wajib memiliki pembayaran terverifikasi sebelum order diproses.

Pada batch ini, verifikasi pembayaran belum diimplementasikan. Karena itu default aman adalah block.

## Tests

Perintah yang dijalankan:

```text
python -m compileall app tests
.venv\Scripts\python.exe -m pytest tests\test_portal_foundation.py tests\test_db_commit_audit_tool.py -q
.venv\Scripts\python.exe -m pytest -q
```

Hasil:

- compile: PASS;
- targeted portal/audit: `29 passed`;
- full regression: `309 passed`.

## Rollback

Rollback code:

```text
git revert <batch-1o-commit>
```

Tidak ada migration baru.

## Status

STAGE_1H_TO_1O_COMPLETE
