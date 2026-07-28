# Batch 3A - Static QRIS and Payment Instructions

Status: COMPLETE

Tanggal: 2026-07-28

## Scope

Batch ini menambahkan fondasi instruksi pembayaran statis:

- memakai `branch_settings` existing untuk konfigurasi QRIS statis;
- membaca rekening pembayaran existing dari invoice snapshot/settings;
- hanya menampilkan instruksi untuk invoice milik user portal;
- tidak membuat payment;
- tidak membuat allocation;
- tidak membuat journal;
- tidak membuat cash/bank transaction;
- tidak membuat upload bukti pembayaran;
- tidak membuat route/template portal payment;
- tidak membuat migration.

## Perubahan

- `app/services/company_settings_service.py`
- `app/services/portal_financial_visibility_service.py`
- `app/services/portal_payment_instruction_service.py`
- `tests/test_portal_payment_instruction_service.py`

## Status Verifikasi

Selesai.

```text
.venv\Scripts\python.exe -m compileall app tests
PASS

tests/test_portal_payment_instruction_service.py
5 passed, 12 warnings

tests/test_portal_financial_visibility_service.py tests/test_portal_debt_visibility_service.py tests/test_portal_closing_visibility_service.py tests/test_portal_payment_instruction_service.py tests/test_portal_foundation.py
51 passed, 41 warnings

route commit/rollback guard
NO_ROUTE_COMMIT_OR_ROLLBACK

Batch 3A instruction service commit/rollback guard
NO_BATCH_3A_INSTRUCTION_COMMIT_OR_ROLLBACK

.venv\Scripts\python.exe -m pytest -q
333 passed, 44 warnings in 87.94s
```

## Putusan

COMPLETE

Batch berikutnya yang aman adalah `3B - Upload bukti pembayaran`, tetapi harus tetap tidak otomatis membuat payment/lunas. Upload wajib private, tervalidasi, ownership-guarded, dan masuk verification queue pada 3C.
