# Batch 4E1 - Complaint Schema Additive

STATUS: VERIFIED

SCOPE:
- Menambahkan model `CustomerComplaint`.
- Menambahkan migration additive `customer_complaints`.
- Menambahkan test model dasar dan migration optimistic locking coverage.
- Tidak membuat route/template/service mutasi complaint.

BLUEPRINT REFERENCE:
- `erp_development_blueprint_codex/05_DELIVERY_CONTRACT_COMPLAINT_DOCUMENTS.md`
- `erp_development_blueprint_codex/06_SECURITY_AUDIT_DATA_INTEGRITY.md`
- `erp_development_blueprint_codex/roadmap.md` Stage 4E1.

CURRENT BEHAVIOR:
- Belum ada tabel complaint khusus.

DESIRED BEHAVIOR:
- Complaint dapat dicatat sebagai record sendiri dengan lifecycle dasar.
- Relasi ke order/delivery/invoice bersifat opsional.
- Tidak ada perubahan ke invoice/payment/journal/stock/closing.

FILES CHANGED:
- `app/models/complaint.py`
- `app/models/__init__.py`
- `migrations/versions/94a0a1b2c3d4_customer_complaints.py`
- `tests/test_customer_complaint_model.py`
- `tests/test_optimistic_locking_models.py`
- `erp_development_blueprint_codex/roadmap.md`
- `storage/final_reports/BATCH_4E1_COMPLAINT_SCHEMA_EXECUTION.md`

DATABASE CHANGE:
- Additive migration baru: create table `customer_complaints`.
- Tidak mengubah tabel existing.

SENSITIVE CHANGE:
- Schema baru untuk complaint, sesuai approval roadmap.

APPROVAL STATUS:
- Owner sudah memberi approval blanket untuk eksekusi roadmap.

TARGETED TEST:
- `flask db upgrade` ke revision `94a0a1b2c3d4` pada test DB PASS.
- `python -m compileall app tests migrations` PASS.
- `python -m pytest tests/test_customer_complaint_model.py tests/test_optimistic_locking_models.py -q` PASS: 4 passed.
- `python -m pytest tests/test_db_commit_audit_tool.py tests/test_numeric_migration_coverage.py -q` PASS: 4 passed.

FULL TEST:
- `python -m pytest -q` PASS: 371 passed, 109 warnings.
- Route guard PASS: `NO_ROUTE_COMMIT_OR_ROLLBACK`.

ROUTE/TEMPLATE COVERAGE:
- Tidak ada route/template baru.

KNOWN LIMITATIONS:
- Belum ada service submit/transition complaint.
- Belum ada attachment complaint.
- Belum ada UI.

ROLLBACK:
- Revert commit Batch 4E1 dan downgrade migration `94a0a1b2c3d4` jika belum dipakai data produksi.

NEXT SAFE STEP:
- Batch 4E2 complaint service foundation.
