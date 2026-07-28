# Batch 4C - Contract Document Archive

STATUS: VERIFIED

SCOPE:
- Menambahkan service arsip dokumen kontrak customer via `DigitalAttachment` existing.
- Menambahkan test attachment kontrak, branch scope, tipe dokumen, dan validasi file aman.
- Tidak menambahkan route/template.

BLUEPRINT REFERENCE:
- `erp_development_blueprint_codex/05_DELIVERY_CONTRACT_COMPLAINT_DOCUMENTS.md`
- `erp_development_blueprint_codex/roadmap.md` Stage 4C.

CURRENT BEHAVIOR:
- Kontrak customer sudah memiliki lifecycle dasar pada Batch 4B.
- File evidence existing sudah ditangani oleh `DigitalAttachment`.

DESIRED BEHAVIOR:
- Dokumen kontrak, amendment, dan terminasi dapat diarsipkan sebagai attachment private.
- Akses attachment mengikuti `branch_id` kontrak.
- Arsip dokumen tidak mengubah status, termin, limit kredit, invoice, payment, journal, stock, atau closing.

FILES CHANGED:
- `app/services/customer_contract_document_service.py`
- `tests/test_customer_contract_document_service.py`
- `erp_development_blueprint_codex/roadmap.md`
- `storage/final_reports/BATCH_4C_CONTRACT_DOCUMENT_ARCHIVE_EXECUTION.md`

DATABASE CHANGE:
- Tidak ada migration baru.
- Memakai tabel existing `digital_attachments`.

SENSITIVE CHANGE:
- Contract touched only as reference/read scope.
- Tidak mengubah lifecycle kontrak atau business rule finansial.

APPROVAL STATUS:
- Tidak memerlukan approval tambahan karena tidak ada schema/role/business rule baru.

TARGETED TEST:
- `python -m compileall app tests migrations` PASS.
- `python -m pytest tests/test_customer_contract_document_service.py -q` PASS: 5 passed.

FULL TEST:
- `python -m pytest -q` PASS: 367 passed, 109 warnings.
- `python -m pytest tests/test_db_commit_audit_tool.py -q` PASS: 2 passed.
- Route guard PASS: `NO_ROUTE_COMMIT_OR_ROLLBACK`.

ROUTE/TEMPLATE COVERAGE:
- Tidak ada route/template baru.

KNOWN LIMITATIONS:
- UI upload/list dokumen kontrak belum dibuat.
- Retention policy dan delete fisik tetap approval required.

ROLLBACK:
- Revert commit Batch 4C.
- Tidak ada migration rollback.

NEXT SAFE STEP:
- Stage 4D expiry notification.
