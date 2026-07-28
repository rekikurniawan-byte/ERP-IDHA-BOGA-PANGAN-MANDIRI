# Batch 3E - Allocation and Receivable Recap

STATUS: COMPLETED

Tanggal: 2026-07-28

## Scope

Batch ini menambahkan service read-only untuk recap invoice/payment/receivable:

- payment sum per invoice;
- expected remaining = invoice total - payment sum;
- mismatch paid amount;
- mismatch remaining amount;
- over-allocation;
- cancelled invoice tidak masuk active receivable;
- branch recap active receivable total.

Tidak ada route/template/migration dan tidak ada mutasi data.

## Files Changed

- `app/services/portal_payment_recap_service.py`
- `tests/test_portal_payment_recap_service.py`
- `storage/final_reports/BATCH_3E_ALLOCATION_RECEIVABLE_RECAP_IMPACT_PLAN.md`
- `storage/final_reports/BATCH_3E_ALLOCATION_RECEIVABLE_RECAP_EXECUTION.md`

## Verification

```text
python -m compileall app tests
PASS

python -m pytest tests/test_portal_payment_recap_service.py -q
5 passed

python -m pytest -q
352 passed, 109 warnings

rg "db\.session\.(commit|rollback)\(" app\routes -n
NO_ROUTE_COMMIT_OR_ROLLBACK
```

## Covered Behavior

- Valid partial invoice recap PASS.
- Valid paid invoice recap PASS.
- Over-allocation detected.
- Remaining mismatch detected.
- Cancelled invoice excluded from active receivable.

## Known Limitations

- Recap ini read-only dan belum menjadi halaman UI.
- Sistem existing belum memakai allocation table terpisah untuk customer payment; allocation masih direpresentasikan oleh `payments.invoice_id`.
- Batch 3F masih diperlukan untuk cash confirmation/readiness gate.

## Rollback

```text
git revert <batch-3e-commit>
```

Tidak ada migration rollback.

## Next Safe Step

Batch 3F - Cash confirmation.
