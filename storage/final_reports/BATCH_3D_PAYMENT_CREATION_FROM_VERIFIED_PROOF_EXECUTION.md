# Batch 3D - Payment Creation From Verified Proof

STATUS: COMPLETED

Tanggal: 2026-07-28

## Scope

Batch ini menambahkan service payment creation dari portal proof yang sudah diverifikasi finance:

- membuat `Payment` dari `PAYMENT_PROOF_VERIFIED`;
- finance wajib memberi amount/payment method/bank account/reference eksplisit;
- update invoice paid/remaining/status;
- membuat journal payment via service accounting existing;
- membuat cash/bank ledger via service cash-bank existing;
- membuat invoice collection log;
- menandai proof menjadi `PAYMENT_PROOF_PAYMENT_CREATED`;
- memakai idempotency key;
- tidak membuat payment gateway/webhook;
- tidak membuat route/template;
- tidak membuat migration.

## Files Changed

- `app/services/portal_payment_creation_service.py`
- `app/services/idempotency_service.py`
- `tests/test_portal_payment_creation_service.py`
- `storage/final_reports/BATCH_3D_PAYMENT_CREATION_FROM_VERIFIED_PROOF_IMPACT_PLAN.md`
- `storage/final_reports/BATCH_3D_PAYMENT_CREATION_FROM_VERIFIED_PROOF_EXECUTION.md`

## Important Fix

`idempotency_service.reserve_idempotency_key()` sebelumnya memakai `with_for_update()` pada query ORM yang ikut melakukan joined load branch/user. PostgreSQL menolak `FOR UPDATE` pada nullable side outer join. Batch ini memperbaiki lock menjadi:

```text
with_for_update(of=IdempotencyKey)
```

Ini membuat lock hanya berlaku pada tabel `idempotency_keys`.

## Verification

```text
python -m compileall app tests
PASS

python -m pytest tests/test_portal_payment_creation_service.py -q
4 passed, 27 warnings

python -m pytest tests/test_portal_payment_creation_service.py tests/test_portal_payment_verification_queue_service.py tests/test_portal_payment_proof_service.py tests/test_db_commit_audit_tool.py -q
16 passed, 65 warnings

python -m pytest -q
347 passed, 109 warnings

rg "db\.session\.(commit|rollback)\(" app\routes -n
NO_ROUTE_COMMIT_OR_ROLLBACK
```

## Covered Behavior

- Payment dibuat dari proof verified.
- Journal payment dibuat.
- Cash/bank ledger dibuat.
- Invoice collection log dibuat.
- Invoice paid/remaining/status berubah sesuai amount.
- Overpayment ditolak.
- Pending proof ditolak.
- Retry idempotency key yang sama tidak menggandakan payment.

## Known Limitations

- Belum ada route/template finance untuk mengeksekusi service ini dari UI.
- Batch ini belum menambahkan receivable recap khusus. Itu masuk Batch 3E.
- Payment gateway/webhook tetap deferred dan `APPROVAL REQUIRED`.

## Rollback

```text
git revert <batch-3d-commit>
```

Tidak ada migration rollback.

## Next Safe Step

Batch 3E - Allocation and receivable recap.
