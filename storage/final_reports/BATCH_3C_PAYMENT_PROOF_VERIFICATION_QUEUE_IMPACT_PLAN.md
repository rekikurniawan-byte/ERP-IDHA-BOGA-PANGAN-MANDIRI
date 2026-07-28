# Batch 3C - Payment Proof Verification Queue Impact Plan

STATUS: APPROVED_BY_ROADMAP

SCOPE:
- Tambah service finance verification queue untuk bukti pembayaran portal.
- Gunakan `DigitalAttachment` existing.
- Gunakan state melalui `attachment_type`: `PAYMENT_PROOF_PENDING`, `PAYMENT_PROOF_VERIFIED`, `PAYMENT_PROOF_REJECTED`.
- Tidak membuat `Payment`.
- Tidak membuat allocation.
- Tidak mengubah invoice paid/remaining/status.
- Tidak membuat journal.
- Tidak membuat cash/bank transaction.
- Tidak membuat migration.
- Tidak membuat route/template pada batch ini.

BLUEPRINT REFERENCE:
- `erp_development_blueprint_codex/roadmap.md` Stage 3C.
- `erp_development_blueprint_codex/04_PAYMENT_CREDIT_INVOICE_CLOSING.md`.

CURRENT BEHAVIOR:
- Batch 3B sudah bisa menyimpan bukti pembayaran sebagai attachment pending.
- Belum ada service formal untuk finance melihat pending proof dan memberi keputusan.

DESIRED BEHAVIOR:
- Finance dapat mengambil queue pending berdasarkan branch.
- Finance dapat menandai bukti sebagai verified/rejected.
- Keputusan idempotent untuk state yang sama.
- Bukti verified tetap belum otomatis membuat payment.
- Bukti rejected tetap menjadi arsip attachment, bukan hard delete.

DATABASE CHANGE:
- Tidak ada.

SENSITIVE CHANGE:
- Payment verification state pada attachment saja.
- Tidak menyentuh payment actual, allocation, invoice, journal, cash/bank.

APPROVAL STATUS:
- User telah memberi approval untuk menjalankan roadmap Stage 3.
- Payment gateway/webhook tetap deferred dan `APPROVAL REQUIRED`.

TARGETED TEST:
- Queue hanya menampilkan pending proof.
- Verify mengubah attachment_type ke verified.
- Reject mengubah attachment_type ke rejected.
- Verify/reject menolak branch lain.
- Verify/reject tidak membuat payment dan tidak mengubah invoice.
- Idempotent decision untuk attachment yang sudah berada di state sama.

FULL TEST:
- `python -m compileall app tests`
- `python -m pytest tests/test_portal_payment_verification_queue_service.py tests/test_portal_payment_proof_service.py -q`
- `python -m pytest -q`

ROLLBACK:
- `git revert <batch-3c-commit>`
- Tidak ada migration rollback.

NEXT SAFE STEP:
- Batch 3D - Payment creation via existing service dari proof verified.
