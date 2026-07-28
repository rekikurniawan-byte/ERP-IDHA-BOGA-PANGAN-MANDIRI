# Batch 4E4 - Complaint Notification / Read Queue

STATUS: VERIFIED

SCOPE:
- Menambahkan read queue complaint aktif.
- Menambahkan generator notifikasi idempotent untuk complaint `OPEN` dan `IN_PROGRESS`.
- Tidak menambahkan route/template.
- Tidak mengirim layanan eksternal.

BLUEPRINT REFERENCE:
- `erp_development_blueprint_codex/05_DELIVERY_CONTRACT_COMPLAINT_DOCUMENTS.md`
- `erp_development_blueprint_codex/roadmap.md` Stage 4E4.

CURRENT BEHAVIOR:
- Complaint schema, service lifecycle, dan attachment service sudah tersedia.
- `Notification` existing mendukung generated key.

DESIRED BEHAVIOR:
- Complaint aktif dapat dibaca sebagai queue internal.
- Admin mendapat notifikasi persistent tanpa duplikasi.
- Notifikasi lama resolved saat complaint tidak lagi aktif.

FILES CHANGED:
- `app/services/customer_complaint_notification_service.py`
- `tests/test_customer_complaint_notification_service.py`
- `erp_development_blueprint_codex/roadmap.md`
- `storage/final_reports/BATCH_4E4_COMPLAINT_NOTIFICATION_EXECUTION.md`

DATABASE CHANGE:
- Tidak ada migration baru.

SENSITIVE CHANGE:
- Mutasi hanya pada `notifications`.

APPROVAL STATUS:
- Owner sudah memberi approval blanket untuk eksekusi roadmap.

TARGETED TEST:
- `python -m compileall app tests migrations` PASS.
- `python -m pytest tests/test_customer_complaint_notification_service.py -q` PASS: 3 passed.

FULL TEST:
- `python -m pytest -q` PASS: 382 passed, 109 warnings.
- `python -m pytest tests/test_db_commit_audit_tool.py -q` PASS: 2 passed.
- Route guard PASS: `NO_ROUTE_COMMIT_OR_ROLLBACK`.

ROUTE/TEMPLATE COVERAGE:
- Tidak ada route/template baru.

KNOWN LIMITATIONS:
- Belum ada UI complaint.
- Belum ada return/correction workflow.

ROLLBACK:
- Revert commit Batch 4E4.

NEXT SAFE STEP:
- Batch 4F return/correction workflow impact plan.
