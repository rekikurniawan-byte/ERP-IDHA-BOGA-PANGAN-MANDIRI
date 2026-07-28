# Batch 3D - Payment Creation From Verified Proof Impact Plan

STATUS: APPROVED_BY_ROADMAP

SCOPE:
- Tambah service untuk membuat customer `Payment` dari portal proof yang sudah `PAYMENT_PROOF_VERIFIED`.
- Finance tetap wajib mengisi amount/payment method/bank account/reference secara eksplisit.
- Gunakan invoice/payment/journal/cash-bank service existing.
- Gunakan idempotency key.
- Mark proof menjadi `PAYMENT_PROOF_PAYMENT_CREATED` setelah payment sukses.

BLUEPRINT REFERENCE:
- `erp_development_blueprint_codex/roadmap.md` Stage 3D.
- `erp_development_blueprint_codex/04_PAYMENT_CREDIT_INVOICE_CLOSING.md`.

CURRENT BEHAVIOR:
- 3B menyimpan bukti sebagai pending.
- 3C memverifikasi/reject bukti.
- Belum ada service yang membuat payment dari proof verified.

DESIRED BEHAVIOR:
- Proof harus verified sebelum payment dibuat.
- Payment dibuat secara atomic bersama invoice update, journal payment, cash-bank ledger, collection log, idempotency complete, dan proof consumed.
- Amount tidak boleh melebihi remaining invoice.
- Retry dengan idempotency key yang sama tidak menggandakan payment.
- Rejected/pending proof tidak bisa membuat payment.

DATABASE CHANGE:
- Tidak ada migration.
- Mutasi row existing:
  - insert `payments`;
  - update `invoices.paid_amount`, `invoices.remaining_amount`, `invoices.status`;
  - insert journal/payment details lewat service existing;
  - insert cash-bank ledger lewat service existing;
  - insert invoice collection log;
  - update `digital_attachments.attachment_type` proof.

SENSITIVE CHANGE:
- Ya, batch ini sengaja menyentuh payment/invoice/journal/cash-bank sesuai Stage 3D.
- Tidak mengubah business rule existing.
- Tidak membuat payment gateway/webhook.

TARGETED TEST:
- Payment berhasil dibuat dari proof verified.
- Invoice paid/remaining/status berubah sesuai amount.
- Journal payment dan cash-bank ledger terbentuk.
- Proof berubah menjadi `PAYMENT_PROOF_PAYMENT_CREATED`.
- Idempotency retry tidak menggandakan payment.
- Amount di atas remaining ditolak.
- Pending/rejected proof ditolak.

FULL TEST:
- `python -m compileall app tests`
- targeted pytest 3D
- `python -m pytest -q`

ROLLBACK:
- `git revert <batch-3d-commit>`
- Tidak ada migration rollback.

NEXT SAFE STEP:
- Batch 3E - Allocation and receivable recap.
