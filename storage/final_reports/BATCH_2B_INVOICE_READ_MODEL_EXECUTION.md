# Batch 2B - Invoice/Hutang Read Model

Status: COMPLETE

Tanggal: 2026-07-28

## Scope

Batch ini menambahkan service read-only untuk financial visibility portal:

- membaca `Invoice` dan `Payment`;
- memakai ownership dari `PortalUserMapping` melalui `build_portal_external_scope`;
- tidak membuat route;
- tidak membuat template;
- tidak membuat migration;
- tidak mengubah invoice/payment/journal/receivable/cash/bank/stock/procurement/supplier;
- tidak melakukan `commit()` atau `rollback()`.

## Perubahan

- `app/services/portal_financial_visibility_service.py`
- `tests/test_portal_financial_visibility_service.py`

## Guard Ownership

- `PORTAL_CLIENT`: hanya invoice dengan `client_id` miliknya.
- `PORTAL_MANDOR`: hanya invoice dengan `mandor_id` miliknya.
- `PORTAL_DELEGATE`: hanya mapping eksplisit client, mandor, lokasi, atau PIC.
- `PORTAL_CUSTOMER`: financial visibility diblokir sampai Stage 3 payment/prepayment flow.

## Status Verifikasi

Selesai.

```text
.venv\Scripts\python.exe -m compileall app tests
PASS

tests/test_portal_financial_visibility_service.py
6 passed

tests/test_portal_foundation.py tests/test_portal_financial_visibility_service.py tests/test_period_invoice_route_runtime.py
34 passed, 32 warnings

route commit/rollback guard
NO_ROUTE_COMMIT_OR_ROLLBACK

Batch 2B service commit/rollback guard
NO_BATCH_2B_SERVICE_COMMIT_OR_ROLLBACK

.venv\Scripts\python.exe -m pytest -q
315 passed, 32 warnings in 73.15s
```

## Putusan

COMPLETE

Batch berikutnya yang aman adalah `2C - Mandor debt and worker debt detail`, tetap read-only dan tetap tanpa invoice coverage baru.
