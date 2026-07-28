# Batch 3E - Allocation and Receivable Recap Impact Plan

STATUS: APPROVED_BY_ROADMAP

SCOPE:
- Tambah service read-only untuk recap invoice/payment/receivable.
- Gunakan model existing: `Invoice` dan `Payment`.
- Tidak membuat allocation table baru.
- Tidak mengubah payment, invoice, journal, cash-bank, atau receivable.
- Tidak membuat route/template.
- Tidak membuat migration.

BLUEPRINT REFERENCE:
- `erp_development_blueprint_codex/roadmap.md` Stage 3E.
- `erp_development_blueprint_codex/04_PAYMENT_CREDIT_INVOICE_CLOSING.md`.

CURRENT BEHAVIOR:
- Payment customer existing langsung memiliki `invoice_id`.
- Invoice menyimpan `paid_amount` dan `remaining_amount`.
- Belum ada service Stage 3 yang mengekspor recap/invariant khusus setelah payment proof flow.

DESIRED BEHAVIOR:
- Hitung payment sum per invoice.
- Hitung expected remaining = total - payment sum.
- Deteksi paid amount mismatch.
- Deteksi remaining mismatch.
- Deteksi over-allocation/payment sum melebihi invoice total.
- Cancelled invoice tidak dianggap receivable aktif.

DATABASE CHANGE:
- Tidak ada.

SENSITIVE CHANGE:
- Read-only.

TARGETED TEST:
- Recap invoice partial valid.
- Recap invoice paid valid.
- Over-allocation terdeteksi.
- Remaining mismatch terdeteksi.
- Cancelled invoice keluar dari receivable aktif.

FULL TEST:
- `python -m compileall app tests`
- targeted pytest 3E
- `python -m pytest -q`

ROLLBACK:
- `git revert <batch-3e-commit>`

NEXT SAFE STEP:
- Batch 3F - Cash confirmation.
