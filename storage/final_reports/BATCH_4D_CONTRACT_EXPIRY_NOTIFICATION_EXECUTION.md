# Batch 4D - Contract Expiry Notification

STATUS: VERIFIED

SCOPE:
- Menambahkan read model kandidat kontrak aktif yang mendekati tanggal akhir.
- Menambahkan generator notifikasi persistent idempotent memakai tabel `notifications` existing.
- Tidak mengubah status kontrak otomatis.

BLUEPRINT REFERENCE:
- `erp_development_blueprint_codex/05_DELIVERY_CONTRACT_COMPLAINT_DOCUMENTS.md`
- `erp_development_blueprint_codex/roadmap.md` Stage 4D.

CURRENT BEHAVIOR:
- Kontrak memiliki `start_date`, `end_date`, dan status lifecycle.
- Notification center existing sudah mendukung `generated_key` untuk deduplikasi.

DESIRED BEHAVIOR:
- Admin branch mendapat notifikasi saat kontrak ACTIVE expired atau akan berakhir dalam window tertentu.
- Retry generator tidak membuat notifikasi duplikat.
- Notifikasi lama resolved ketika kontrak keluar dari window.

FILES CHANGED:
- `app/services/customer_contract_expiry_notification_service.py`
- `tests/test_customer_contract_expiry_notification_service.py`
- `erp_development_blueprint_codex/roadmap.md`
- `storage/final_reports/BATCH_4D_CONTRACT_EXPIRY_NOTIFICATION_EXECUTION.md`

DATABASE CHANGE:
- Tidak ada migration baru.
- Memakai tabel existing `notifications`.

SENSITIVE CHANGE:
- Tidak mengubah lifecycle/status kontrak.
- Tidak menambah scheduler eksternal.
- Tidak mengirim layanan eksternal.

APPROVAL STATUS:
- Tidak memerlukan approval tambahan karena hanya notification service foundation.

TARGETED TEST:
- `python -m compileall app tests migrations` PASS.
- `python -m pytest tests/test_customer_contract_expiry_notification_service.py -q` PASS: 3 passed.

FULL TEST:
- `python -m pytest -q` PASS: 370 passed, 109 warnings.
- `python -m pytest tests/test_db_commit_audit_tool.py -q` PASS: 2 passed.
- Route guard PASS: `NO_ROUTE_COMMIT_OR_ROLLBACK`.

ROUTE/TEMPLATE COVERAGE:
- Tidak ada route/template baru.

KNOWN LIMITATIONS:
- Belum ada UI khusus kontrak expiry.
- Belum ada scheduler background; generator dipanggil manual/service.

ROLLBACK:
- Revert commit Batch 4D.
- Tidak ada migration rollback.

NEXT SAFE STEP:
- Stage 4E complaint workflow impact plan.
