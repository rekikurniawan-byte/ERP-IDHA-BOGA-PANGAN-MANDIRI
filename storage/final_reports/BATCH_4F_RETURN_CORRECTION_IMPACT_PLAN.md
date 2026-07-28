# Batch 4F - Return / Correction Workflow Impact Plan

STATUS: APPROVAL_REQUIRED

SCOPE:
- Audit existing support untuk return/correction.
- Menentukan batas aman sebelum implementasi.
- Tidak membuat model, migration, route, service, atau template pada batch ini.

BLUEPRINT REFERENCE:
- `erp_development_blueprint_codex/05_DELIVERY_CONTRACT_COMPLAINT_DOCUMENTS.md`
- `erp_development_blueprint_codex/06_SECURITY_AUDIT_DATA_INTEGRITY.md`
- `erp_development_blueprint_codex/roadmap.md` Stage 4F.

CURRENT BEHAVIOR:
- Belum ditemukan model/service/route khusus return/correction customer.
- Support existing yang dapat dipakai ulang:
  - `CustomerComplaint` sebagai sumber kasus awal;
  - `ApprovalRequest` sebagai approval bersama;
  - `DigitalAttachment` untuk bukti return/correction;
  - `AuditLog` untuk jejak perubahan;
  - `StockAdjustment` untuk koreksi stok, tetapi belum boleh dipanggil otomatis;
  - `CashBankAdjustment` untuk koreksi kas/bank, tetapi belum boleh dipanggil otomatis;
  - invoice/payment/journal existing wajib tetap immutable kecuali lewat reversal/koreksi terkontrol.

DESIRED BEHAVIOR:
- Return/correction mencatat penyebab, tindakan, nilai koreksi, referensi order/delivery/invoice, approval, dan audit.
- Tidak menimpa histori transaksi asli.
- Tidak otomatis membuat invoice/payment/journal/stock/closing mutation pada fase awal.
- Semua koreksi finansial/stok berikutnya harus lewat service existing dan approval gate terpisah.

APPROVAL REQUIRED:
Perubahan:
- Membuat workflow return/correction baru.
- Kemungkinan membuat tabel baru untuk return/correction.
- Menentukan apakah koreksi berdampak pada invoice, stock, journal, payment, cash-bank, receivable, dan closing.

Alasan:
- Return/correction menyentuh area paling sensitif: dokumen transaksi historis dan kemungkinan efek finansial/stok.
- Blueprint melarang menimpa transaksi asli.

Modul/tabel terdampak:
- Kandidat tabel baru: `customer_corrections`.
- Referensi opsional: `customer_complaints`, `daily_orders`, `deliveries`, `invoices`, `payments`, `journals`, `stock_movements`, `stock_adjustments`, `approval_requests`, `digital_attachments`, `audit_logs`.

Risiko:
- Koreksi langsung ke invoice/payment/journal dapat membuat laporan finansial tidak rekonsiliasi.
- Koreksi stok otomatis dapat membuat saldo stok berubah tanpa audit operasional.
- Koreksi setelah closing dapat melanggar period closing.
- Return tanpa approval dapat dipakai untuk mengubah histori secara tidak sah.

Alternatif paling aman:
- Batch 4F1: schema additive return/correction header saja, tanpa posting finansial/stok.
- Batch 4F2: service draft/submit correction, hanya `customer_corrections`.
- Batch 4F3: approval request bridge memakai `ApprovalRequest`.
- Batch 4F4: attachment evidence via `DigitalAttachment`.
- Batch 4F5: read queue/notification.
- Posting ke invoice/payment/journal/stock tetap deferred sampai rule detail disetujui.

Dampak jika tidak dilakukan:
- Return/koreksi tetap manual/off-system.
- Complaint tidak memiliki jalur formal untuk koreksi yang bisa diaudit.

Rencana rollback:
- Sub-batch awal additive dan dapat direvert.
- Migration baru hanya membuat tabel baru dan tidak mengubah tabel transaksi existing.
- Tidak ada posting otomatis pada fase awal.

Test yang akan ditambahkan:
- migration/model contract;
- submit draft correction;
- branch scope;
- approval required sebelum status final;
- no mutation ke invoice/payment/journal/stock;
- attachment validation;
- illegal transition rejected;
- full regression.

PROPOSED MINIMAL MODEL:

```text
customer_corrections
- id
- branch_id
- correction_number
- correction_type RETURN/CORRECTION/COMPENSATION
- status DRAFT/SUBMITTED/APPROVED/REJECTED/CLOSED/CANCELLED
- complaint_id nullable
- order_id nullable
- delivery_id nullable
- invoice_id nullable
- client_id nullable
- mandor_id nullable
- reason
- proposed_action
- correction_amount Numeric(18,2)
- stock_effect NONE/PENDING/POSTED/NOT_APPLICABLE
- financial_effect NONE/PENDING/POSTED/NOT_APPLICABLE
- approval_request_id nullable
- submitted_by
- approved_by nullable
- closed_by nullable
- submitted_at nullable
- approved_at nullable
- closed_at nullable
- notes nullable
- created_at
- version_id
```

NON-GOALS FOR FIRST IMPLEMENTATION:
- Tidak mengubah invoice lama.
- Tidak membuat payment reversal.
- Tidak membuat journal.
- Tidak membuat stock movement.
- Tidak membuka period closing.
- Tidak membuat approval engine baru.

FILES CHANGED:
- `storage/final_reports/BATCH_4F_RETURN_CORRECTION_IMPACT_PLAN.md`
- `erp_development_blueprint_codex/roadmap.md`

DATABASE CHANGE:
- Tidak ada pada impact plan ini.

SENSITIVE CHANGE:
- Ya untuk implementasi berikutnya.

APPROVAL STATUS:
- APPROVAL REQUIRED sebelum Batch 4F1.

TARGETED TEST:
- Tidak dijalankan; dokumen-only.

FULL TEST:
- Tidak dijalankan; dokumen-only.

ROUTE/TEMPLATE COVERAGE:
- Tidak ada route/template.

KNOWN LIMITATIONS:
- Belum ada return/correction executable.
- Dokumen ini sengaja berhenti sebelum perubahan sensitif.

ROLLBACK:
- Revert commit dokumen Batch 4F impact plan.

NEXT SAFE STEP:
- Setelah approval eksplisit: Batch 4F1 return/correction schema additive.
