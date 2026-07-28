# Batch 4E - Complaint Workflow Impact Plan

STATUS: APPROVAL_REQUIRED

SCOPE:
- Audit existing complaint/keluhan/return/correction workflow.
- Menentukan rancangan paling aman sebelum coding.
- Tidak membuat model, migration, route, service, atau template pada batch ini.

BLUEPRINT REFERENCE:
- `erp_development_blueprint_codex/05_DELIVERY_CONTRACT_COMPLAINT_DOCUMENTS.md`
- `erp_development_blueprint_codex/06_SECURITY_AUDIT_DATA_INTEGRITY.md`
- `erp_development_blueprint_codex/roadmap.md` Stage 4E.

CURRENT BEHAVIOR:
- Tidak ditemukan model khusus `Complaint`, `CustomerComplaint`, `Return`, atau `Correction`.
- Tidak ditemukan service/route/template khusus complaint workflow.
- Ada mekanisme umum yang bisa dipakai ulang:
  - `DigitalAttachment` untuk bukti dokumen/foto;
  - `ApprovalRequest` untuk gate approval bersama;
  - `Notification` untuk reminder/status;
  - `AuditLog` untuk jejak perubahan;
  - model existing order/delivery/invoice sebagai referensi.

DESIRED BEHAVIOR:
- Complaint punya lifecycle: `OPEN -> IN_PROGRESS -> RESOLVED -> CLOSED`.
- Kategori awal: makanan kurang/rusak, salah menu, terlambat, kurang porsi.
- Complaint dapat mereferensikan order/delivery/invoice bila tersedia.
- Bukti complaint memakai `DigitalAttachment`.
- Semua transisi status diaudit.
- Complaint tidak otomatis membuat return, koreksi invoice, payment, journal, stock movement, atau closing.

APPROVAL REQUIRED:
Perubahan:
- Membuat tabel complaint baru dan migration baru.
- Menentukan lifecycle complaint dan relasinya ke order/delivery/invoice.
- Menentukan role yang boleh submit/review/resolve/close complaint.

Alasan:
- Complaint workflow belum memiliki struktur data existing.
- Menyentuh lifecycle operasional dan dapat menjadi dasar return/correction.

Modul/tabel terdampak:
- Tabel baru kandidat: `customer_complaints`.
- Relasi opsional ke existing: `branches`, `users`, `clients`, `mandors`, `daily_orders`, `deliveries`, `invoices`, `digital_attachments`, `approval_requests`, `notifications`, `audit_logs`.

Risiko:
- Jika langsung dibuat tanpa approval, alur complaint bisa bertabrakan dengan SOP operasional.
- Jika complaint langsung mengubah invoice/stock/journal, histori transaksi bisa rusak.
- Jika role/scope salah, data pelanggan/mandor/PT bisa bocor.

Alternatif paling aman:
- Batch 4E1: schema additive `customer_complaints` minimal, tanpa route/template, status lifecycle dasar.
- Batch 4E2: service submit/list/read complaint, branch scope, no financial mutation.
- Batch 4E3: status transition service dengan audit log.
- Batch 4E4: attachment service untuk bukti complaint via `DigitalAttachment`.
- Batch 4E5: notification read/service untuk complaint pending.
- Batch 4E6: route/template setelah service dan tests stabil.

Dampak jika tidak dilakukan:
- Keluhan tetap dicatat manual/off-system.
- Tidak ada SLA complaint dan tidak ada bukti formal untuk return/correction.

Rencana rollback:
- Setiap sub-batch additive dan dipisah.
- Jika schema batch disetujui, rollback lewat downgrade migration baru yang hanya drop tabel baru saat masih belum dipakai produksi.
- Tidak ada perubahan ke tabel transaksi existing pada fase awal.

Test yang akan ditambahkan:
- model/migration contract test;
- service submit complaint;
- status transition legal/illegal;
- branch scope;
- attachment validation;
- no mutation ke invoice/payment/journal/stock;
- idempotency duplicate submit;
- route auth/role tests bila UI dibuat.

PROPOSED MINIMAL MODEL:

```text
customer_complaints
- id
- branch_id
- complaint_number
- category
- status
- title
- description
- client_id nullable
- mandor_id nullable
- order_id nullable
- delivery_id nullable
- invoice_id nullable
- submitted_by
- assigned_to nullable
- resolved_by nullable
- closed_by nullable
- submitted_at
- resolved_at nullable
- closed_at nullable
- resolution_note nullable
- created_at
- version_id
```

NON-GOALS FOR FIRST IMPLEMENTATION:
- Tidak membuat return/correction otomatis.
- Tidak mengubah invoice/payment/journal/stock/closing.
- Tidak membuat approval engine baru.
- Tidak mengirim WhatsApp/email eksternal.

FILES CHANGED:
- `storage/final_reports/BATCH_4E_COMPLAINT_WORKFLOW_IMPACT_PLAN.md`
- `erp_development_blueprint_codex/roadmap.md`

DATABASE CHANGE:
- Tidak ada pada impact plan ini.

SENSITIVE CHANGE:
- Ya untuk implementasi berikutnya karena membutuhkan schema/lifecycle/role.

APPROVAL STATUS:
- APPROVAL REQUIRED sebelum Batch 4E1.

TARGETED TEST:
- Tidak dijalankan; dokumen-only.

FULL TEST:
- Tidak dijalankan; dokumen-only.

ROUTE/TEMPLATE COVERAGE:
- Tidak ada route/template.

KNOWN LIMITATIONS:
- Belum ada complaint workflow executable.
- Dokumen ini sengaja berhenti sebelum perubahan sensitif.

ROLLBACK:
- Revert commit dokumen Batch 4E impact plan.

NEXT SAFE STEP:
- Setelah approval eksplisit: Batch 4E1 complaint schema additive.
