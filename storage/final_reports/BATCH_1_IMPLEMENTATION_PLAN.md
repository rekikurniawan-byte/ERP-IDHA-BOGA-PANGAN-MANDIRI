# BATCH 1 IMPLEMENTATION PLAN

ERP PT Idha Boga Pangan Mandiri

Status: GO - CONTROLLED DEVELOPMENT, WAITING OWNER APPROVAL FOR BATCH 1A

Tanggal: 2026-07-27

Baseline acuan:
- Git commit: `cdc296f`
- Git tag: `batch-0-baseline-ready`
- Alembic current/head: `90a0a1b2c3d4`
- Backup pasca Batch 0: `instance/backups/idha_boga_staging_after_batch0_20260727_163653.dump`
- Backup SHA-256: `2e24e969611f79c0d5fc23863cd450741be2184b443558ae81d89b72e457a6db`
- `pg_restore --list`: PASS
- Baseline audit: `storage/final_reports/BASELINE_SAFETY_AUDIT_LATEST.md`

Catatan penting:
Dokumen ini adalah rencana. Tidak ada implementasi portal, route, model, service, template, atau migration pada batch planning ini.

## 1. Ringkasan Blueprint Yang Relevan

Blueprint mewajibkan pengembangan incremental di atas ERP existing. ERP core tetap menjadi single source of truth. Portal hanya boleh menjadi channel input/display, bukan sistem paralel.

Guardrail utama dari blueprint:
- Tidak rebuild.
- Tidak membuat database portal terpisah.
- Tidak menghapus atau mengganti workflow existing.
- Tidak mengubah order, invoice, payment, journal, stock, closing, contract, role, permission, atau migration sensitif tanpa approval.
- Feature berisiko harus default OFF.
- Route hanya request/validation/authorization/response.
- Business rule dan transaction boundary tetap di service.
- Tidak boleh commit/rollback langsung di route.
- Setiap batch kecil, testable, dan rollbackable.

## 2. Fitur Yang Sudah Ada

### Authentication dan User

Existing:
- `User` model sudah ada dengan `branch_id`, `username`, `password_hash`, `role`, `is_active`.
- Login internal sudah memakai Flask-Login.
- Role guard existing memakai `@role_required(...)`.
- OWNER bypass tersedia pada decorator.
- User management internal sudah tersedia di Settings.

Kondisi:
- Role internal yang terbukti dipakai: `OWNER`, `ADMIN`, `FINANCE`, `ACCOUNTING`, `LOGISTICS`, `HR`, `DAPUR`, `PENGANTAR`.
- Belum ada bukti role eksternal resmi seperti `CUSTOMER`, `MANDOR`, atau `PT_USER` sudah didukung penuh.

### Master Data Pelanggan/Mandor/Lokasi

Existing:
- `Client`
- `ClientPic`
- `Mandor`
- `DeliveryLocation`
- Relasi `Client -> Mandor -> DeliveryLocation`
- Order existing sudah mengacu `Mandor` dan `DeliveryLocation`.

Kondisi:
- Data scope portal dapat dibangun dari relasi existing tersebut.
- Mapping user eksternal ke `Client`, `Mandor`, atau `ClientPic` belum ada sebagai field first-class.

### Order Internal

Existing:
- `DailyOrder`
- `DailyOrderDetail`
- `OrderRevision`
- Status lock, detail mandor/lokasi, harga per porsi, lunch/dinner qty.
- Route internal order berada di modul operational.

Kondisi:
- Workflow order internal tidak boleh diubah pada Batch 1A.
- Portal draft/order posting ke workflow internal masuk APPROVAL REQUIRED untuk batch awal.

### Finance/Invoice/Payment

Existing:
- Invoice, payment, receivable, collection log, payment proof/digital attachment sudah ada.
- Manual billing dan realtime invoice sudah ada.
- Financial invariants dan data health sudah mulai tersedia.

Kondisi:
- Batch 1A tidak boleh menyentuh posting invoice, payment, jurnal, piutang, cash/bank, atau closing.

### Delivery dan Dokumen

Existing:
- Delivery, delivery detail, receipt, attachment foundation sudah ada.
- Digital attachment service sudah ada.

Kondisi:
- Portal delivery visibility dapat menjadi read-only batch lanjutan.
- Upload dokumen portal masuk batch terpisah karena menyentuh security, storage, dan ownership.

## 3. Fitur Yang Akan Dipakai Ulang

Batch 1 harus memakai ulang:
- Flask app factory existing.
- Flask-Login session existing.
- `role_required` atau guard baru yang kompatibel, bila disetujui.
- `User` untuk autentikasi.
- `Client`, `ClientPic`, `Mandor`, `DeliveryLocation` untuk scope data.
- Existing layout/CSS component supaya UI tidak membuat sistem navigasi paralel.
- Existing audit/request ID/security header.
- Existing route smoke/template audit/full pytest baseline.

Tidak boleh membuat:
- database portal baru;
- auth stack baru;
- order table paralel;
- payment table paralel;
- invoice table paralel;
- navigation system terpisah.

## 4. Fitur Yang Benar-Benar Perlu Ditambah

Prioritas additive paling kecil:
1. Portal namespace/shell default OFF.
2. Portal dashboard read-only default OFF.
3. Data-scope resolver read-only untuk user ke client/mandor/PT.
4. Authorization guard portal yang tidak mengubah role existing sampai mapping disetujui.
5. Tests untuk unauthenticated, unauthorized, authorized, dan feature flag OFF.

Fitur yang ditunda:
- submit order portal;
- prepayment;
- payment proof upload;
- admin confirmation bridge;
- invoice/payment visibility detail;
- contract;
- complaint/return;
- subscription;
- approval/cut-off;
- gateway/webhook.

## 5. Route Existing Yang Terdampak

Batch 1A targetnya tidak mengubah route existing. Route existing hanya menjadi baseline pembanding.

Route yang perlu dijaga:
- `/auth/login`
- `/dashboard/owner`
- `/master/*`
- `/operational/*`
- `/finance/*`
- `/delivery/*`
- `/settings/*`

Rencana route baru hanya pada namespace terisolasi:
- `/portal`
- `/portal/dashboard`

Catatan:
Route baru harus default OFF lewat feature flag. Jika feature flag OFF, route harus 404 atau redirect aman sesuai desain yang disetujui, tanpa mempengaruhi internal ERP.

## 6. Model Dan Service Existing Yang Akan Digunakan

Batch 1A read-only dapat menggunakan:
- `User`
- `Client`
- `ClientPic`
- `Mandor`
- `DeliveryLocation`

Service/helper yang dapat dibuat pada Batch 1A bila disetujui:
- `portal_access_service.py`
  - hanya membaca mapping/scope;
  - tidak commit;
  - tidak mutate;
  - tidak membuat order/payment/invoice;
  - tidak mengubah role.

Jika mapping membutuhkan kolom baru pada `users` atau tabel association user-to-client/mandor, status langsung:
`APPROVAL REQUIRED`.

## 7. Apakah Migration Diperlukan

Batch 1A yang direkomendasikan: tidak perlu migration.

Alasan:
- Portal shell dan dashboard read-only bisa dibuat default OFF tanpa schema.
- Role eksternal belum boleh ditambah tanpa approval.
- Mapping user eksternal ke client/mandor/PT belum jelas dan menyentuh auth/data scope.

Migration yang mungkin diperlukan pada batch setelah 1A:
- mapping user ke client;
- mapping user ke mandor;
- portal profile;
- portal invitation/status;
- draft order portal.

Semua migration tersebut termasuk:
`APPROVAL REQUIRED`.

## 8. Role/Permission Impact

Batch 1A:
- Tidak mengubah role existing.
- Tidak menambah role di user management.
- Tidak mengubah `role_required` existing.
- Tidak membuka data internal ke role baru.

Strategi paling aman:
- Portal feature flag default OFF.
- Pada mode OFF: semua route portal tidak dapat digunakan.
- Pada mode ON untuk development: hanya OWNER/ADMIN internal boleh membuka shell portal untuk preview.

Role eksternal seperti `CUSTOMER`, `MANDOR`, `PT_USER`, atau `DELEGATE` perlu keputusan owner karena blueprint menyatakan perubahan role/permission adalah approval required.

## 9. Compatibility Risks

Risiko rendah:
- route baru bertabrakan dengan route existing jika namespace tidak dicek;
- sidebar/topbar terganggu jika navigasi portal masuk layout global terlalu awal;
- feature flag salah default menjadi ON.

Risiko sedang:
- user eksternal dicampur dengan user internal tanpa data scope jelas;
- OWNER bypass dapat terlalu luas untuk portal ownership test;
- template portal memakai endpoint lama yang belum ada.

Risiko tinggi dan harus ditunda:
- menulis order dari portal ke `DailyOrder`;
- upload bukti payment dari portal;
- mengubah status order;
- membuat payment/invoice/journal;
- menambah role eksternal permanen;
- menambah tabel mapping user eksternal tanpa approval.

## 10. Rollback Plan

Rollback Batch 1A bila sudah disetujui dan diimplementasikan:
1. Revert commit Batch 1A.
2. Pastikan feature flag portal kembali tidak ada/default OFF.
3. Jalankan `python -m compileall app tests`.
4. Jalankan targeted route/template tests.
5. Jalankan full pytest.
6. Jalankan baseline safety audit.

Karena Batch 1A direkomendasikan tanpa migration, rollback database tidak diperlukan.

Jika owner menyetujui migration pada batch berikutnya:
- backup sebelum migration wajib;
- migration harus additive;
- downgrade/rollback harus didokumentasikan;
- no drop/no rename/no destructive backfill.

## 11. Targeted Tests

Batch 1A wajib menambah test berikut setelah disetujui:
- feature flag OFF menolak `/portal`.
- app factory tetap berhasil.
- route map lama tidak hilang.
- tidak ada duplicate endpoint.
- unauthenticated user tidak bisa akses portal.
- unauthorized internal role ditolak sesuai policy.
- OWNER/ADMIN development preview dapat akses shell jika feature flag ON.
- template portal parse.
- `url_for` portal valid.
- no `db.session.commit()` di route portal.
- no `db.session.rollback()` di route portal.
- existing `/auth/login` tetap 200.
- existing dashboard owner tetap 200 pada smoke test.

Tidak diuji pada Batch 1A:
- order submission;
- payment upload;
- invoice visibility;
- delivery update;
- mutation POST.

## 12. Full Regression Tests

Setiap batch setelah implementasi harus menjalankan:
- `python -m compileall app tests scripts`
- targeted pytest untuk batch terkait
- `python -m pytest -q`
- `python scripts/baseline_safety_audit.py`

Untuk batch yang menyentuh migration:
- `python -m flask db upgrade` pada database test kosong
- model-vs-schema diff harus 0
- backup sebelum migration

## 13. Acceptance Criteria Batch 1A

Batch 1A baru boleh dinyatakan selesai jika:
- tidak mengubah role existing;
- tidak mengubah data order existing;
- tidak membuat database baru;
- tidak membuat workflow paralel;
- tidak menyentuh invoice, payment, journal, stock, receivable, payable, closing, HPP;
- tidak ada migration;
- portal feature flag default OFF;
- route portal berada di namespace terpisah;
- existing internal login tetap bekerja;
- route map lama tidak hilang;
- full pytest lulus;
- baseline safety audit lulus;
- route baru memiliki auth/authorization tests;
- rollback cukup revert commit karena tidak ada schema change.

## 14. Daftar APPROVAL REQUIRED

Butuh approval owner sebelum dilakukan:
- menambah role eksternal (`CUSTOMER`, `MANDOR`, `PT_USER`, `DELEGATE`);
- mengubah role/permission existing;
- menambah kolom/tabel mapping portal user ke client/mandor/PT;
- membuat draft order portal yang tersimpan di database;
- menghubungkan portal ke `DailyOrder`;
- mengubah status order atau lifecycle;
- membuat admin confirmation bridge yang menulis order;
- upload bukti transfer dari portal;
- membuat atau mengalokasikan payment;
- menampilkan invoice/payment detail ke pihak eksternal tanpa ownership matrix;
- membuat contract portal;
- complaint/return yang berdampak koreksi nilai;
- prepayment guard yang mengubah proses order;
- QRIS/payment gateway/webhook;
- credit limit atau credit hold policy;
- perubahan delivery status dari portal;
- mutation POST dari user eksternal;
- migration apa pun di Batch 1.

## 15. Pembagian Batch 1

### Batch 1A - Portal Foundation Shell Default OFF

Tujuan:
- route namespace portal;
- blueprint registration terisolasi;
- feature flag default OFF;
- dashboard/shell read-only;
- auth guard awal;
- tests route/template/feature flag.

Schema:
- tidak ada.

Business rule:
- tidak berubah.

Rollback:
- revert commit.

Status:
- paling aman untuk batch pertama.

### Batch 1B - Portal Access Scope Read-only

Tujuan:
- helper/service read-only untuk menghitung scope client/mandor/PT dari data existing;
- belum membuat mapping baru;
- OWNER/ADMIN preview data scope;
- dokumentasikan gap mapping eksternal.

Schema:
- tidak ada jika hanya read-only.
- jika butuh mapping user eksternal: APPROVAL REQUIRED.

Rollback:
- revert commit.

### Batch 1C - Customer/Mandor/PT Read-only Dashboard

Tujuan:
- tampilkan ringkasan dummy/read-only dari data existing yang sudah terscope;
- tidak expose invoice/payment detail sensitif sebelum matrix disetujui;
- tidak mutasi.

Schema:
- tidak ada.

Approval:
- wajib sebelum membuka ke role eksternal nyata.

### Batch 1D - Portal Navigation Integration

Tujuan:
- link portal hanya muncul saat feature flag ON dan user berwenang;
- tidak mengubah sidebar internal saat flag OFF.

Schema:
- tidak ada.

Rollback:
- revert commit.

### Batch 1E - Draft Order Analysis Only

Tujuan:
- analisis bridge portal ke order existing.
- belum implementasi submit order.

Status:
- APPROVAL REQUIRED sebelum coding karena menyentuh order workflow.

### Batch 1F - Admin Confirmation Bridge

Tujuan:
- menerima draft portal menjadi proses internal.

Status:
- APPROVAL REQUIRED.

Alasan:
- menyentuh order lifecycle, status, admin confirmation, dan potensi produksi/invoice.

## 16. Rekomendasi Urutan Paling Aman

1. Approve Batch 1A saja.
2. Implement Batch 1A tanpa migration.
3. Verify compile, targeted tests, full pytest, baseline audit.
4. Commit dan tag `batch-1a-portal-foundation`.
5. Baru evaluasi Batch 1B.

Jangan menggabungkan 1A sampai 1D dalam satu commit besar.

## 17. Putusan

GO - CONTROLLED DEVELOPMENT

Batch berikutnya yang direkomendasikan untuk disetujui:
Batch 1A - Portal Foundation Shell Default OFF

Belum boleh:
GO - FULL IMPLEMENTATION

Alasan:
Batch 0 membuktikan baseline runtime aman untuk safe GET, template, route map, migration head, dan full pytest. Namun Batch 0 belum membuktikan route detail, semua POST, workflow order/payment/invoice/stock, atomicity lintas service, dan authorization matrix eksternal penuh.
