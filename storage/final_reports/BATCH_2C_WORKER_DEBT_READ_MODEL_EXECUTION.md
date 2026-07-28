# Batch 2C - Mandor Debt and Worker Debt Detail

Status: COMPLETE

Tanggal: 2026-07-28

## Scope

Batch ini menambahkan service read-only untuk hutang pekerja warung pada portal:

- membaca `WorkerDebt`, `DebtPayment`, `Worker`, dan `CanteenSale`;
- memakai ownership mandor dari `PortalUserMapping`;
- tidak membuat invoice coverage baru;
- tidak membuat route;
- tidak membuat template;
- tidak membuat migration;
- tidak mengubah hutang, payment, invoice, journal, cash/bank, stock, procurement, atau supplier;
- tidak melakukan `commit()` atau `rollback()`.

## Perubahan

- `app/services/portal_debt_visibility_service.py`
- `tests/test_portal_debt_visibility_service.py`

## Guard Ownership

- `PORTAL_CLIENT`: hanya hutang pekerja dari mandor di bawah client miliknya.
- `PORTAL_MANDOR`: hanya hutang pekerja mandor miliknya.
- `PORTAL_DELEGATE`: hanya hutang pekerja mandor/lokasi yang didelegasikan eksplisit.
- `PORTAL_CUSTOMER`: worker debt visibility diblokir.

## Status Verifikasi

Selesai.

```text
.venv\Scripts\python.exe -m compileall app tests
PASS

tests/test_portal_debt_visibility_service.py
5 passed

tests/test_portal_financial_visibility_service.py tests/test_portal_debt_visibility_service.py tests/test_portal_foundation.py
38 passed, 29 warnings

route commit/rollback guard
NO_ROUTE_COMMIT_OR_ROLLBACK

Batch 2C service commit/rollback guard
NO_BATCH_2C_SERVICE_COMMIT_OR_ROLLBACK

.venv\Scripts\python.exe -m pytest -q
320 passed, 32 warnings in 78.75s
```

## Putusan

COMPLETE

Batch berikutnya yang aman adalah `2D - Payment history read-only`, memakai invoice ownership dari Batch 2B dan tetap tanpa membuat payment/allocation.
