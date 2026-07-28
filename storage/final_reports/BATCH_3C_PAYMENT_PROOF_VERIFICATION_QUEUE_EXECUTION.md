# Batch 3C - Payment Proof Verification Queue

STATUS: COMPLETED

Tanggal: 2026-07-28

## Scope

Batch ini menambahkan finance verification queue berbasis service untuk bukti pembayaran portal:

- queue pending proof per branch finance;
- decision `VERIFIED` dan `REJECTED`;
- state disimpan di `DigitalAttachment.attachment_type`;
- tidak membuat `Payment`;
- tidak membuat allocation;
- tidak mengubah invoice paid/remaining/status;
- tidak membuat journal;
- tidak membuat cash/bank transaction;
- tidak membuat migration;
- tidak membuat route/template.

## Files Changed

- `app/services/portal_payment_verification_queue_service.py`
- `tests/test_portal_payment_verification_queue_service.py`
- `storage/final_reports/BATCH_3C_PAYMENT_PROOF_VERIFICATION_QUEUE_IMPACT_PLAN.md`
- `storage/final_reports/BATCH_3C_PAYMENT_PROOF_VERIFICATION_QUEUE_EXECUTION.md`

## Business Rules

- Queue hanya mengambil attachment portal payment sesuai branch finance.
- Attachment pending dapat diputuskan menjadi verified atau rejected.
- Keputusan state yang sama idempotent.
- Attachment yang sudah rejected tidak dapat langsung diubah menjadi verified pada batch ini.
- Verified proof belum otomatis membuat payment. Payment creation baru masuk Batch 3D.

## Verification

```text
python -m compileall app tests
PASS

python -m pytest tests/test_portal_payment_verification_queue_service.py tests/test_portal_payment_proof_service.py -q
10 passed, 38 warnings

python -m pytest -q
343 passed, 82 warnings

rg "db\.session\.(commit|rollback)\(" app\routes -n
NO_ROUTE_COMMIT_OR_ROLLBACK

rg "Payment\(|invoice\.(paid_amount|remaining_amount|status)\s*=" app\services\portal_payment_verification_queue_service.py -n
NO_PAYMENT_OR_INVOICE_MUTATION_IN_3C_SERVICE
```

## Known Limitations

- Belum ada UI finance untuk queue. Service sudah siap dipakai oleh route/template batch berikutnya bila diperlukan.
- Belum membuat `Payment` dari proof verified. Itu Batch 3D dan wajib memakai service existing.
- Belum ada payment gateway/webhook. Tetap deferred dan `APPROVAL REQUIRED`.

## Rollback

```text
git revert <batch-3c-commit>
```

Tidak ada migration rollback.

## Next Safe Step

Batch 3D - Payment creation via existing service dari proof verified.
