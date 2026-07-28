# Batch 4F1 - Return / Correction Schema Additive

STATUS: VERIFIED

SCOPE:
- Menambahkan model `CustomerCorrection`.
- Menambahkan migration additive `customer_corrections`.
- Menambahkan test model dasar dan migration coverage.
- Tidak membuat service posting, route, template, journal, payment, invoice, stock, atau closing mutation.

BLUEPRINT REFERENCE:
- `erp_development_blueprint_codex/05_DELIVERY_CONTRACT_COMPLAINT_DOCUMENTS.md`
- `erp_development_blueprint_codex/06_SECURITY_AUDIT_DATA_INTEGRITY.md`
- `erp_development_blueprint_codex/roadmap.md` Stage 4F1.

CURRENT BEHAVIOR:
- Belum ada tabel return/correction khusus.

DESIRED BEHAVIOR:
- Return/correction dapat direkam sebagai draft data sendiri.
- Efek stock/financial tersimpan sebagai status `NONE/PENDING/POSTED/NOT_APPLICABLE`, tetapi tidak diposting otomatis.

FILES CHANGED:
- `app/models/correction.py`
- `app/models/__init__.py`
- `migrations/versions/95a0a1b2c3d4_customer_corrections.py`
- `tests/test_customer_correction_model.py`
- `tests/test_optimistic_locking_models.py`
- `tests/test_numeric_migration_coverage.py`
- `erp_development_blueprint_codex/roadmap.md`
- `storage/final_reports/BATCH_4F1_RETURN_CORRECTION_SCHEMA_EXECUTION.md`

DATABASE CHANGE:
- Additive migration baru: create table `customer_corrections`.
- Tidak mengubah tabel transaksi existing.

SENSITIVE CHANGE:
- Schema baru untuk return/correction, sesuai approval roadmap.

APPROVAL STATUS:
- Owner sudah memberi approval blanket untuk eksekusi roadmap.

TARGETED TEST:
- `flask db upgrade` ke revision `95a0a1b2c3d4` pada test DB PASS.
- `python -m compileall app tests migrations` PASS.
- `python -m pytest tests/test_customer_correction_model.py tests/test_optimistic_locking_models.py tests/test_numeric_migration_coverage.py -q` PASS: 6 passed.

FULL TEST:
- `python -m pytest -q` PASS: 383 passed, 109 warnings.
- `python -m pytest tests/test_db_commit_audit_tool.py -q` PASS: 2 passed.
- Route guard PASS: `NO_ROUTE_COMMIT_OR_ROLLBACK`.

ROUTE/TEMPLATE COVERAGE:
- Tidak ada route/template baru.

KNOWN LIMITATIONS:
- Belum ada service draft/submit correction.
- Belum ada approval bridge.
- Belum ada attachment correction.
- Belum ada posting financial/stock.

ROLLBACK:
- Revert commit Batch 4F1 dan downgrade migration `95a0a1b2c3d4` jika belum dipakai data produksi.

NEXT SAFE STEP:
- Batch 4F2 return/correction service foundation.
