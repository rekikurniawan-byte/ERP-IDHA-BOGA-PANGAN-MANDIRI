# Roadmap Pengembangan ERP PT Idha Boga Pangan Mandiri

Status dokumen: ACUAN KERJA UTAMA

Tanggal penyusunan: 2026-07-27

Dokumen ini dibuat setelah membaca ulang seluruh file Markdown blueprint dalam folder `erp_development_blueprint_codex`:

1. `00_GOVERNANCE_APPROVAL_GATE.md`
2. `01_VISION_SCOPE_ARCHITECTURE.md`
3. `02_ROLES_AND_PORTALS.md`
4. `03_ORDER_OPERATIONAL_WORKFLOW.md`
5. `04_PAYMENT_CREDIT_INVOICE_CLOSING.md`
6. `05_DELIVERY_CONTRACT_COMPLAINT_DOCUMENTS.md`
7. `06_SECURITY_AUDIT_DATA_INTEGRITY.md`
8. `07_IMPLEMENTATION_ROADMAP.md`
9. `08_CODEX_EXECUTION_PROTOCOL.md`
10. `09_CHANGE_DECISION_LOG_TEMPLATE.md`
11. `README.md`

## 1. Prinsip Wajib

ERP ini adalah sistem existing yang sudah berjalan. Pengembangan harus incremental, bukan rebuild.

Wajib:

- gunakan PostgreSQL database existing;
- gunakan model, service, route, permission, template, dan workflow existing jika sudah tersedia;
- portal hanya menjadi channel input/display, bukan sistem paralel;
- route hanya request, validation, authorization, response;
- service menyimpan business rule dan transaction boundary;
- tidak ada `db.session.commit()` atau `db.session.rollback()` di route;
- migration lama immutable;
- route, data, dan kompatibilitas lama dipertahankan;
- setiap batch kecil, dapat diuji, dapat di-rollback, dan punya laporan;
- setiap bug wajib menghasilkan regression test;
- ketidakjelasan selalu `APPROVAL REQUIRED`.

Dilarang:

- rebuild total;
- database portal terpisah;
- navigasi sistem paralel;
- chat internal;
- payment gateway tahap awal;
- edit migration lama;
- hard delete transaksi historis;
- menggabungkan invoice antar-periode;
- memberi kredit default ke pelanggan umum;
- memproses order pelanggan umum sebelum prepayment terverifikasi;
- menurunkan test agar build lulus;
- mengklaim production ready hanya karena pytest lulus.

## 2. Status Baseline Saat Ini

Titik aman aktif saat ini adalah tag `stage-1h-1o-complete`.

Perubahan Batch 2A sampai Batch 2F yang lama telah dicabut dan tidak boleh dianggap bagian scope aktif:

- financial visibility;
- order status visibility;
- delivery visibility;
- production visibility;
- inventory visibility;
- procurement/supplier bill visibility.

Batch yang boleh dianggap aktif:

- Batch 0 baseline safety;
- Batch 1A portal foundation;
- Batch 1B portal access scope;
- Batch 1C portal read-only customer/mandor directories;
- Batch 1D portal navigation gate;
- Batch 1E portal status shell;
- Batch 1F portal ownership analysis;
- Batch 1G external mapping approval package.
- Batch 1H approval decision untuk external mapping;
- Batch 1I portal authentication mapping;
- Batch 1J portal profile dan scope resolver final;
- Batch 1K location selection read-only/controlled;
- Batch 1L draft order portal;
- Batch 1M admin confirmation bridge;
- Batch 1N portal order status dasar;
- Batch 1O prepayment guard untuk pelanggan umum.

Portal template aktif yang sah:

- `dashboard.html`;
- `customers.html`;
- `mandors.html`;
- `ownership.html`;
- `status.html`.
- `profile.html`;
- `locations.html`;
- `order_draft.html`;
- `order_status.html`;
- `admin_order_drafts.html`.

## 3. Aturan Anti-Pengulangan

Codex tidak boleh mengulang pekerjaan yang sudah dieksekusi dan dicabut.

Sebelum membuat batch baru, Codex wajib:

1. membuka `erp_development_blueprint_codex/roadmap.md`;
2. memeriksa `git log --oneline --decorate -n 30`;
3. memeriksa `storage/final_reports/BATCH_2_SCOPE_ROLLBACK_REPORT.md`;
4. memastikan batch baru tidak menghidupkan kembali Batch 2A-2F tanpa approval eksplisit;
5. menulis impact plan pendek sebelum edit;
6. berhenti jika scope masuk kategori approval required.

Jika user meminta "lanjut", Codex tidak boleh otomatis memilih area sensitif. Codex harus lanjut ke batch berikutnya sesuai roadmap ini.

## 4. Kategori Approval Required

Codex wajib berhenti dan meminta persetujuan jika perubahan menyentuh:

- schema, migration, tabel, kolom, tipe data;
- role atau permission;
- order lifecycle;
- invoice;
- payment;
- journal;
- stock;
- HPP;
- cash/bank;
- receivable;
- payable;
- closing;
- contract;
- numbering dokumen;
- credit limit;
- pihak ditagih;
- cicilan;
- auto approval;
- auto posting;
- auto settlement;
- payment gateway atau webhook;
- laporan keuangan;
- data migration massal.

Format wajib:

```text
APPROVAL REQUIRED
Perubahan:
Alasan:
Modul/tabel terdampak:
Risiko:
Alternatif paling aman:
Dampak jika tidak dilakukan:
Rencana rollback:
Test yang akan ditambahkan:
```

## 5. Roadmap Tahap Utama

Roadmap ini mengikuti blueprint dan harus dijalankan berurutan. Tahap berikutnya tidak boleh dimulai sebelum gate tahap sebelumnya selesai.

### Stage 0 - Baseline Hardening

Tujuan: memastikan ERP existing sehat sebelum fitur besar.

Status: sebagian besar sudah dilakukan, tetapi belum boleh dianggap selesai penuh sampai semua gate lulus.

Batch yang sah:

0A. Baseline compile, pytest, route smoke, template audit.

0B. Migration integrity.

0C. Backup dan restore drill di database/mesin berbeda.

0D. Transaction atomicity dan failure injection untuk use case kritis.

0E. Security regression:

- logout POST;
- generic login error;
- CSRF form coverage;
- no traceback production;
- rate limit shared storage production;
- secure cookie production;
- upload validation.

0F. Data integrity regression:

- invoice invariant;
- payment allocation invariant;
- journal debit-credit;
- stock movement balance;
- order-production-delivery-invoice coverage;
- no duplicate business key.

Gate Stage 0:

- `python -m compileall app tests` PASS;
- targeted tests PASS;
- full pytest PASS;
- route smoke safe GET PASS;
- template/url_for audit PASS;
- route commit/rollback = 0;
- migration current=head;
- restore drill documented;
- no P0 blocker open;
- final Stage 0 report exists.

### Stage 1 - Portal dan Order Dasar

Tujuan: portal menjadi channel controlled untuk user eksternal tanpa merusak ERP core.

Tidak termasuk:

- financial visibility penuh;
- stock visibility;
- production visibility;
- procurement visibility;
- supplier bill visibility;
- payment gateway;
- subscription;
- scoring;
- approval engine kompleks.

Batch 1 aktif yang sudah selesai:

1A. Portal foundation.

1B. Portal access scope preview.

1C. Customer/mandor directory read-only.

1D. Navigation gate.

1E. Portal status shell.

1F. Ownership analysis.

1G. External mapping approval package.

1H. Approval decision untuk external mapping.

- Tidak coding sebelum approval.
- Putuskan mapping user ke pelanggan umum, mandor, PT, dan delegasi.
- Jika butuh schema, buat `APPROVAL REQUIRED`.

1I. Portal authentication mapping.

- Memakai auth existing.
- Tidak membuat auth paralel.
- Tidak mengubah role existing tanpa approval.
- Test unauthenticated, unauthorized, authorized, ownership.

1J. Portal profile dan scope resolver final.

- Pelanggan umum hanya melihat miliknya.
- Mandor hanya melihat mandor miliknya.
- PT hanya melihat mandor/client di bawah PT.
- Delegasi hanya akses terbatas.

1K. Location selection read-only/controlled.

- Gunakan `DeliveryLocation` existing jika kompatibel.
- Jika perlu field alamat/lat-long/patokan/kontak tambahan, `APPROVAL REQUIRED`.

1L. Draft order portal.

- Tidak langsung masuk produksi.
- Tidak langsung invoice/payment/journal/stock.
- Status harus pending/admin confirmation.
- Double submit wajib dicegah.

1M. Admin confirmation bridge.

- Admin mengonfirmasi order portal ke workflow internal existing.
- Harus atomik dan idempotent.
- Perubahan status menggunakan service.

1N. Portal order status dasar.

- Hanya status milik user.
- Tidak membuka data cabang/mandor/PT lain.
- Tidak menampilkan financial detail penuh.

1O. Prepayment guard untuk pelanggan umum.

- Order pelanggan umum tidak diproses sebelum pembayaran terverifikasi.
- QRIS/payment upload masuk Stage 3 jika menyentuh payment actual.

Status Stage 1: selesai pada tag `stage-1h-1o-complete`.

Catatan batas Stage 1:

- portal sudah memakai auth existing;
- mapping eksternal memakai `PortalUserMapping`;
- draft order portal tidak membuat invoice/payment/journal/stock/closing;
- admin confirmation bridge hanya menghubungkan draft portal ke workflow order internal existing;
- pelanggan umum tetap ditahan oleh prepayment guard;
- financial visibility, payment upload, payment creation, journal, stock, procurement, dan supplier tetap bukan bagian Stage 1.

Gate Stage 1:

- semua endpoint portal punya test unauthenticated, unauthorized, authorized, ownership;
- tidak ada role leak;
- tidak ada data leak antar user/mandor/PT;
- tidak ada mutation langsung dari route;
- order portal tidak membuat transaksi finansial otomatis;
- double submit tidak membuat order ganda;
- full pytest PASS;
- route smoke PASS;
- UAT portal dasar PASS.

### Stage 2 - Financial Visibility

Tujuan: transparansi hutang/invoice/payment history sesuai role.

Stage ini tidak boleh dimulai sebelum Stage 1 selesai dan disetujui.

Status Stage 2: selesai sebagai read model only pada tag `batch-2e-portal-closing-visibility-read-model`.

Catatan batas Stage 2:

- service read model invoice/outstanding, payment history, worker debt, dan closing visibility tersedia;
- belum ada route/template portal financial;
- tidak ada payment creation/allocation;
- tidak ada invoice/payment/journal/closing mutation;
- procurement/supplier/cash-bank/HPP/profit tetap out of scope.

Batch:

2A. Impact plan financial visibility.

- Hanya dokumen.
- Tentukan scope pelanggan umum, mandor, PT.
- Tentukan data mana yang boleh tampil.
- Jangan menghidupkan kembali Batch 2A-2F lama yang sudah dicabut.
- Tidak membuat route/template/service baru pada batch ini.
- Tidak mengubah invoice/payment/journal/stock/cash/bank/receivable/payable.

2B. Invoice/hutang read model.

- Read model dari invoice/payment/receivable existing.
- Tidak mengubah invoice/payment/journal.

2C. Mandor debt and worker debt detail.

- Hanya milik mandor/PT yang sah.
- Tidak membuat invoice coverage baru tanpa approval.

2D. Payment history read-only.

- Tidak membuat payment.
- Tidak mengubah allocation.

2E. Closing visibility.

- Tidak menjalankan closing.
- Tidak mengubah status closing.

Gate Stage 2:

- ownership/data scope PASS;
- invoice/payment numbers reconcile;
- outstanding = invoice - allocation;
- cancelled/void tidak masuk piutang aktif;
- full pytest PASS;
- financial UAT PASS.

### Stage 3 - Payment Enhancement

Tujuan: pembayaran terkontrol tanpa auto-lunas palsu.

Status Stage 3: selesai sebagai service foundation pada tag berikut:

- `batch-3a-static-payment-instructions`;
- `batch-3b-payment-proof-upload-service`;
- `batch-3c-payment-proof-verification-queue`;
- `batch-3d-payment-creation-from-verified-proof`;
- `batch-3e-allocation-receivable-recap`;
- `batch-3f-cash-confirmation`.

Catatan batas Stage 3A:

- instruksi pembayaran statis tersedia sebagai service read-only;
- QRIS statis memakai `branch_settings` existing, tanpa migration;
- belum ada upload bukti pembayaran;
- belum ada payment creation/allocation;
- belum ada journal/cash-bank mutation;
- bukti bayar tidak otomatis membuat invoice lunas.

Catatan batas Stage 3B:

- upload bukti pembayaran tersedia sebagai service;
- upload menyimpan `DigitalAttachment` private dengan attachment type `PAYMENT_PROOF_PENDING`;
- upload tidak membuat `Payment`;
- upload tidak mengubah paid/remaining/status invoice;
- upload tidak membuat journal/cash-bank/allocation.

Catatan batas Stage 3C:

- finance verification queue tersedia sebagai service;
- keputusan proof memakai attachment type `PAYMENT_PROOF_VERIFIED` atau `PAYMENT_PROOF_REJECTED`;
- keputusan verified/rejected belum membuat `Payment`;
- payment creation tetap masuk Batch 3D melalui service existing;
- tidak ada migration, route, template, journal, cash-bank, atau allocation baru.

Catatan batas Stage 3D:

- payment creation dari proof verified tersedia sebagai service;
- finance wajib mengisi amount/payment method/bank account/reference eksplisit;
- service membuat `Payment`, update invoice paid/remaining/status, journal payment, cash-bank ledger, collection log, dan proof consumed;
- idempotency key wajib dan retry tidak menggandakan payment;
- tidak ada route/template, migration, gateway, webhook, atau auto-settlement baru.

Catatan batas Stage 3E:

- allocation/receivable recap tersedia sebagai read-only service;
- sistem existing masih merepresentasikan allocation customer payment via `payments.invoice_id`;
- recap mendeteksi payment sum mismatch, remaining mismatch, over-allocation, dan cancelled invoice pada active receivable;
- tidak ada route/template, migration, atau mutasi data.

Catatan batas Stage 3F:

- cash confirmation tersedia sebagai read-only service;
- service mendeteksi missing ledger, duplicate ledger, amount mismatch, account type mismatch, dan bank account mismatch;
- tidak ada route/template, migration, atau mutasi data.

Catatan batas akhir Stage 3:

- Stage 3 selesai sebagai fondasi service, belum UI end-to-end;
- payment gateway/webhook tetap deferred dan `APPROVAL REQUIRED`;
- existing route payment lama belum direfactor ke service baru;
- UAT finance tetap diperlukan sebelum dipakai operasional.

Batch:

3A. QRIS statis dan instruksi pembayaran.

3B. Upload bukti pembayaran.

3C. Finance verification queue.

3D. Payment creation via existing service.

3E. Allocation and receivable recap.

3F. Cash confirmation.

Payment gateway/webhook tetap deferred dan `APPROVAL REQUIRED`.

Gate Stage 3:

- upload private dan tervalidasi;
- bukti upload tidak otomatis lunas;
- finance verification membuat payment lewat service;
- allocation tidak melebihi payment;
- invoice remaining tidak negatif;
- retry tidak menggandakan payment;
- journal/payment/cash invariant PASS.

### Stage 4 - Contract, Complaint, Document Archive

Tujuan: memperkuat kontrak, keluhan, return, dan arsip dokumen.

Batch:

4A. Contract model impact plan.

4B. Contract lifecycle.

4C. Contract document archive.

4D. Expiry notification.

4E. Complaint workflow.

4F. Return/correction workflow.

4G. Document archive access control.

Gate Stage 4:

- contract tidak dihapus, hanya versi baru/expired;
- perubahan limit/termin diaudit;
- complaint punya lifecycle;
- return/correction tidak menimpa transaksi asli;
- file private, versioned, uploader/timestamp tersimpan;
- delete fisik hanya dengan retention policy dan approval.

### Stage 5 - Operational Automation

Tujuan: automasi operasional setelah portal dan pembayaran stabil.

Batch:

5A. Subscription order configuration.

5B. Occurrence generation via existing order service.

5C. Cut-off policy implementation setelah approval.

5D. Change/cancel approval.

5E. Delivery SLA.

5F. Notification center.

5G. Delegation workflow.

Gate Stage 5:

- subscription tidak membuat jalur transaksi paralel;
- cut-off policy disetujui;
- perubahan setelah produksi perlu approval;
- tidak ada hard delete order;
- notification tidak mengirim layanan eksternal nyata dalam test;
- SLA tidak mengubah histori delivery lama.

### Stage 6 - Advanced Governance

Tujuan: governance lanjutan setelah ERP stabil.

Batch:

6A. Approval engine bersama.

6B. Customer scoring.

6C. Blacklist.

6D. Advanced reporting.

6E. Optimization.

6F. Integration lanjutan.

Gate Stage 6:

- approval engine tidak duplikatif per modul;
- scoring/blacklist tidak otomatis memblokir tanpa rule disetujui;
- reporting reconcile dengan sumber transaksi;
- optimization tidak mengubah hasil;
- integration eksternal dimock dalam test.

## 6. Production Readiness Track

Track ini berjalan paralel, tetapi tidak boleh mengubah business rule tanpa approval.

P0 Production Gates:

- clean git baseline dan tag release;
- dependency lock;
- `.env` tidak ikut paket;
- secret rotated;
- PostgreSQL production config valid;
- Redis/shared rate-limit jika multi-worker;
- HTTPS dan secure cookie;
- no debug/traceback production;
- backup schedule;
- restore drill sukses;
- migration empty DB sukses;
- migration from snapshot sukses;
- full pytest sukses;
- route smoke sukses;
- template audit sukses;
- role matrix sukses;
- transaction failure injection sukses;
- idempotency critical workflow sukses;
- financial reconciliation sukses;
- stock reconciliation sukses;
- UAT owner/admin/finance/operational sukses;
- rollback procedure terbukti.

Tidak boleh memakai status `PRODUCTION_READY` sebelum seluruh gate di atas lulus dan terdokumentasi.

## 7. Format Batch Wajib

Setiap batch harus memiliki:

```text
STATUS:
SCOPE:
BLUEPRINT REFERENCE:
CURRENT BEHAVIOR:
DESIRED BEHAVIOR:
FILES CHANGED:
DATABASE CHANGE:
SENSITIVE CHANGE:
APPROVAL STATUS:
TARGETED TEST:
FULL TEST:
ROUTE/TEMPLATE COVERAGE:
KNOWN LIMITATIONS:
ROLLBACK:
NEXT SAFE STEP:
```

## 8. Urutan Kerja Codex Setelah Dokumen Ini

Jika diminta lanjut, urutan yang benar:

1. Jangan implementasi otomatis.
2. Buka roadmap ini.
3. Tentukan stage dan batch berikutnya yang sah.
4. Jika batch menyentuh approval required, berhenti dan tulis approval request.
5. Jika batch aman, tulis impact plan singkat.
6. Implementasi hanya scope batch itu.
7. Jalankan targeted test.
8. Jalankan full test.
9. Jalankan audit sesuai scope.
10. Buat report.
11. Commit dan tag.
12. Jangan lanjut batch berikutnya tanpa instruksi baru.

## 9. Next Safe Step

Next safe step saat ini:

```text
Stage 4F - Return/correction workflow impact plan
```

Status:

```text
READY_FOR_BATCH_4F_IMPACT_PLAN
```

Alasan:

- Stage 1 dan Stage 2 sudah memiliki checkpoint yang sah;
- Stage 3A menambahkan instruksi pembayaran statis;
- Stage 3B menambahkan upload bukti pembayaran pending;
- Stage 3C menambahkan queue dan decision state finance;
- Batch 3D sudah menyentuh `Payment`, invoice remaining, journal, cash-bank, dan collection log melalui service atomic.
- Stage 4A contract model impact plan selesai pada tag `stage-4a-contract-model-impact-plan`.
- Stage 4B customer contract lifecycle foundation selesai pada tag `batch-4b-customer-contract-lifecycle`.
- Batch 4C contract document archive selesai sebagai service foundation memakai `DigitalAttachment` existing, tanpa file store paralel.
- Batch 4D contract expiry notification selesai sebagai service foundation memakai `notifications` existing, tanpa auto-expire kontrak dan tanpa scheduler eksternal.
- Batch 4E complaint workflow impact plan selesai dan menyimpulkan implementasi membutuhkan approval karena perlu schema/lifecycle/role.
- Batch 4E1 complaint schema additive selesai dengan tabel baru `customer_complaints`, tanpa route/template dan tanpa mutasi transaksi existing.
- Batch 4E2 complaint service foundation selesai untuk submit/list/read dan transisi status, tanpa route/template.
- Batch 4E3 complaint attachment service selesai memakai `DigitalAttachment`, tanpa mengubah status complaint dari upload bukti.
- Batch 4E4 complaint notification/read queue selesai sebagai service foundation, tanpa route/template dan tanpa layanan eksternal.

Alternatif aman sebelum approval:

- dokumentasi Batch 4F return/correction impact plan;
- audit existing correction/return/approval support;
- berhenti dengan `APPROVAL REQUIRED` bila return/correction menyentuh invoice/payment/journal/stock/closing;
- tidak mengubah invoice/payment/journal/stock/closing;
- tetap berhenti jika diminta membuat return/correction otomatis sebelum Stage 4F.

## 10. Catatan Disiplin Scope

Batch berikut tidak boleh dibuat ulang tanpa approval eksplisit:

- financial visibility;
- procurement visibility;
- inventory visibility;
- production visibility;
- delivery visibility;
- order status visibility yang membuka data transaksi lintas role.

Jika fitur tersebut diperlukan di masa depan, harus masuk stage yang benar dan dimulai dari impact plan + approval, bukan langsung implementasi.
