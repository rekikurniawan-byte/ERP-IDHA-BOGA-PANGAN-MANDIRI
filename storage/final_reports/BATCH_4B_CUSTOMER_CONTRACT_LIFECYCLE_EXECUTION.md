# Batch 4B - Customer Contract Lifecycle Foundation

STATUS: COMPLETED

Tanggal: 2026-07-28

## Scope

Batch ini menambahkan fondasi kontrak pelanggan/PT:

- model `CustomerContract`;
- migration additive `93a0a1b2c3d4_customer_contracts`;
- service lifecycle kontrak customer;
- create draft/active contract;
- activate draft contract;
- renew active/expired contract;
- expire due active contracts;
- list/get contract;
- audit log service-level;
- optimistic locking via `BaseModel`;
- numeric coverage untuk `credit_limit`.

## Files Changed

- `app/models/contract.py`
- `app/models/__init__.py`
- `app/services/customer_contract_service.py`
- `migrations/versions/93a0a1b2c3d4_customer_contracts.py`
- `tests/test_customer_contract_service.py`
- `tests/test_numeric_migration_coverage.py`
- `tests/test_optimistic_locking_models.py`
- `storage/final_reports/BATCH_4B_CUSTOMER_CONTRACT_LIFECYCLE_EXECUTION.md`

## Database Change

Additive table only:

- `customer_contracts`

No existing transaction table changed.

## Verification

```text
DATABASE_URL=postgresql+psycopg://localhost/test_db flask db upgrade
PASS: upgraded 92a0a1b2c3d4 -> 93a0a1b2c3d4

python -m compileall app tests migrations
PASS

python -m pytest tests/test_customer_contract_service.py tests/test_numeric_migration_coverage.py tests/test_optimistic_locking_models.py -q
10 passed

python -m pytest -q
362 passed, 109 warnings

rg "db\.session\.(commit|rollback)\(" app\routes -n
NO_ROUTE_COMMIT_OR_ROLLBACK
```

## Covered Behavior

- Create draft customer contract.
- Activate draft contract.
- Renew active contract and supersede old contract.
- Expire due active contracts.
- Reject invalid date range.
- Reject PIC that does not belong to selected client.

## Known Limitations

- Belum ada route/template UI.
- Belum ada document attachment contract archive. Itu Batch 4C.
- Belum ada expiry notification. Itu Batch 4D.
- Belum ada complaint workflow. Itu Batch 4E.

## Rollback

```text
git revert <batch-4b-commit>
flask db downgrade 92a0a1b2c3d4
```

## Next Safe Step

Batch 4C - Contract document archive using `DigitalAttachment`.
