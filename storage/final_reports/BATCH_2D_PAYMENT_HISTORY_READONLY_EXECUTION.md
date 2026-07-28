# Batch 2D - Payment History Read-only

Status: COMPLETE

Tanggal: 2026-07-28

## Scope

Batch ini menambahkan payment history read-only untuk portal:

- membaca `Payment` yang terkait invoice visible dari Batch 2B;
- memakai ownership invoice existing;
- tidak membuat payment;
- tidak mengubah allocation;
- tidak membuka file bukti pembayaran;
- tidak membuat route;
- tidak membuat template;
- tidak membuat migration;
- tidak mengubah invoice/payment/journal/cash/bank/receivable/stock.

## Perubahan

- `app/services/portal_financial_visibility_service.py`
- `tests/test_portal_financial_visibility_service.py`

## Status Verifikasi

Selesai.

```text
.venv\Scripts\python.exe -m compileall app tests
PASS

tests/test_portal_financial_visibility_service.py
10 passed

tests/test_portal_financial_visibility_service.py tests/test_portal_debt_visibility_service.py tests/test_portal_foundation.py
42 passed, 29 warnings

route commit/rollback guard
NO_ROUTE_COMMIT_OR_ROLLBACK

Batch 2D service commit/rollback guard
NO_BATCH_2D_SERVICE_COMMIT_OR_ROLLBACK

.venv\Scripts\python.exe -m pytest -q
324 passed, 32 warnings in 81.46s
```

## Putusan

COMPLETE

Batch berikutnya yang aman adalah `2E - Closing visibility`, tetap read-only dan tidak menjalankan proses closing.
