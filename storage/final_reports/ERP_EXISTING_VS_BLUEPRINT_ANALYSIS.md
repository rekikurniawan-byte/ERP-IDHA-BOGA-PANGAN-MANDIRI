# ERP Existing vs Blueprint Analysis

Tanggal audit: 2026-07-27

Proyek: ERP PT Idha Boga Pangan Mandiri

Status akhir: **BLOCKED**

Alasan status:

- Blueprint mengarah ke pengembangan portal eksternal, approval, kontrak, pembayaran, dan workflow lintas invoice/payment/journal/stock. Area tersebut menyentuh role, permission, database, invoice, payment, journal, stock, receivable, payable, closing, approval, dan migration sehingga wajib masuk kategori **APPROVAL REQUIRED** sebelum implementasi.
- Stage 0 baseline belum dapat dinyatakan lengkap hanya dari audit struktur. Perlu bukti final untuk migration integrity, test database, restore drill, route smoke/UAT, dan release baseline.
- Role existing masih role internal. Role blueprint seperti PT, Mandor, Pelanggan Umum, dan Delegasi belum boleh ditambahkan tanpa approval karena mengubah authorization surface.
- Ditemukan indikasi risiko migration chain yang wajib diverifikasi sebelum fitur baru besar: ada migration rebuild schema dengan `down_revision = None` di tengah histori migration terbaru. Ini belum berarti pasti rusak, tetapi wajib diaudit sebelum pengembangan schema lanjutan.

Dokumen ini adalah analisis saja. Tidak ada perubahan kode, model, route, service, template, migration, atau business rule.

---

## 1. Blueprint Yang Dibaca

Seluruh dokumen Markdown blueprint berikut sudah dijadikan aturan utama analisis:

| File | Status |
| --- | --- |
| `erp_development_blueprint_codex/README.md` | Dibaca |
| `erp_development_blueprint_codex/00_GOVERNANCE_APPROVAL_GATE.md` | Dibaca |
| `erp_development_blueprint_codex/01_VISION_SCOPE_ARCHITECTURE.md` | Dibaca |
| `erp_development_blueprint_codex/02_ROLES_AND_PORTALS.md` | Dibaca |
| `erp_development_blueprint_codex/03_ORDER_OPERATIONAL_WORKFLOW.md` | Dibaca |
| `erp_development_blueprint_codex/04_PAYMENT_CREDIT_INVOICE_CLOSING.md` | Dibaca |
| `erp_development_blueprint_codex/05_DELIVERY_CONTRACT_COMPLAINT_DOCUMENTS.md` | Dibaca |
| `erp_development_blueprint_codex/06_SECURITY_AUDIT_DATA_INTEGRITY.md` | Dibaca |
| `erp_development_blueprint_codex/07_IMPLEMENTATION_ROADMAP.md` | Dibaca |
| `erp_development_blueprint_codex/08_CODEX_EXECUTION_PROTOCOL.md` | Dibaca |
| `erp_development_blueprint_codex/09_CHANGE_DECISION_LOG_TEMPLATE.md` | Dibaca |

Catatan: `SOURCE_ORIGINAL_DRAFT.txt` juga dibaca sebagai konteks pendukung, tetapi aturan utama tetap file Markdown blueprint.

---

## 2. Ringkasan ERP Existing

ERP existing bukan proyek kosong. Sistem sudah memiliki cakupan internal yang luas:

- Flask application factory dengan registrasi blueprint terpusat.
- 17 blueprint Flask terdaftar.
- 339 URL rule pada route map.
- 102 model class.
- 88 service file.
- 212 template HTML.
- 1 static JS utama.
- 45 migration file.
- Modul internal untuk master data, operational order, production, delivery, logistics, finance, accounting, HR, costing, canteen, field transaction, settings, dashboard, SOP, health, dan prediction.
- Foundation untuk audit log, digital attachment, idempotency key, approval request, backup/recovery, slow query logging, dan system health.

Kesimpulan existing:

- ERP core internal sudah cukup besar dan aktif.
- Sistem sudah bergerak ke arah modular monolith.
- Banyak requirement blueprint sudah punya fondasi, tetapi belum tentu lengkap sebagai portal eksternal atau workflow governance penuh.
- Pengembangan berikutnya harus memperluas ERP existing, bukan membangun sistem baru.

---

## 3. Inventaris Arsitektur Existing

### 3.1 Blueprint Flask

Blueprint yang terdaftar di app factory:

| Blueprint | Fungsi Existing |
| --- | --- |
| `auth` | Login dan logout |
| `dashboard` | Dashboard role dan summary operasional |
| `master` | Branch, user, client, mandor, lokasi, employee, supplier, item, menu, recipe |
| `operational` | Daily order, order detail, order workflow internal |
| `production` | Produksi dan detail produksi |
| `delivery` | Delivery dan bukti serah terima |
| `canteen` | Penjualan kantin, hutang pekerja, kas harian |
| `logistics` | Procurement, stock movement, stock adjustment, item request |
| `finance` | Invoice, payment, receivable, payable, cash bank, manual billing, advance, expense, fixed asset |
| `accounting` | Account, journal, fixed asset accounting, closing/report |
| `hr` | Employee attendance, assignment, payroll |
| `settings` | Company setting, user, role, backup, recovery, audit, security setting |
| `costing` | Costing/HPP |
| `sop` | SOP/dashboard SOP |
| `health` | Health check |
| `field_transactions` | Transaksi lapangan manual receivable/payable/settlement |
| `prediction` | Forecast/prediction |

### 3.2 Route Map Summary

| Blueprint | Jumlah URL Rule |
| --- | ---: |
| accounting | 35 |
| auth | 2 |
| canteen | 6 |
| costing | 16 |
| dashboard | 11 |
| delivery | 15 |
| field_transactions | 18 |
| finance | 86 |
| health | 2 |
| hr | 13 |
| logistics | 25 |
| master | 45 |
| operational | 16 |
| prediction | 5 |
| production | 3 |
| settings | 36 |
| sop | 4 |
| static | 1 |
| **Total** | **339** |

### 3.3 Service Layer Existing

Service layer sudah luas. Area penting yang terlihat:

- Accounting posting, reporting, expense drilldown, period closing.
- Accounts payable/receivable.
- Advance, operational expense, transport expense, fixed asset.
- Audit log, approval, idempotency, sensitive action guard.
- Backup, recovery center, disaster recovery SOP.
- Billing input source, billing trace, manual billing, manual backfill.
- Business logic guard, atomic transaction audit/simulation.
- Canteen, daily cash, daily closing.
- Dashboard analytics, command center, global filter, live reminder.
- Delivery, delivery SLA.
- Digital attachment.
- Finance collection, finance print/export, invoice identity/profit.
- HPP/costing and stock consumption.
- HR, logistics transaction, stock.
- Prediction/material forecast.
- User management.
- Visual/browser QA utilities.

### 3.4 Model Domain Existing

| Domain | Model Existing |
| --- | --- |
| Master | Branch, User, Client, ClientPic, Mandor, DeliveryLocation, Employee, Driver, Supplier, Item, UnitConversion, ItemCostProfile, Menu, Recipe, PackagingProfile, OverheadProfile, Worker |
| Operational | DailyOrder, DailyOrderDetail, OrderRevision, OrderSnapshot, HPP snapshot, stock consumption snapshot |
| Production | Production, ProductionDetail |
| Delivery | Delivery, DeliveryDetail, DeliveryReceipt |
| Logistics | Procurement, ProcurementItem, StockMovement, StockOpeningBalance, DamagedItem, StockAdjustment, ItemRequest |
| Finance | Invoice, InvoiceItem, ManualBillingBatch, Payment, BankAccount, CashBankTransaction, SupplierBill, SupplierPayment, CollectionLog, Advance, Expense |
| Accounting | Account, Journal, JournalDetail, FixedAsset, Depreciation, Asset Financing, PeriodClosing |
| HR | Attendance, Assignment, Payroll, Salary History |
| Canteen | CanteenSale, WorkerDebt, DebtPayment, ExternalReceivable, CashDaily |
| Field Transaction | Counterparty, Transaction, Attachment, ReviewLog, Link, Settlement, ManualReceivable, ManualPayable |
| System | Notification, AuditLog, DigitalAttachment, IdempotencyKey, ApprovalRequest |

### 3.5 Role Existing

Role resmi existing dari user management:

| Role Existing | Keterangan |
| --- | --- |
| OWNER | Owner/Pemilik |
| ADMIN | Admin Operasional |
| FINANCE | Finance |
| ACCOUNTING | Accounting |
| LOGISTICS | Logistics/Stok |
| HR | HR/SDM |
| DAPUR | Dapur/Produksi |
| PENGANTAR | Pengantar/Delivery |

Role blueprint yang belum menjadi role resmi existing:

| Role Blueprint | Status |
| --- | --- |
| PT | Belum role resmi existing, approval required |
| Mandor | Ada model master `Mandor`, tetapi belum role portal resmi, approval required |
| Pelanggan Umum | Belum role resmi existing, approval required |
| Delegasi Mandor | Belum role resmi existing, approval required |
| Viewer/Direktur terpisah | Sebagian terwakili OWNER/dashboard, perubahan permission approval required |

---

## 4. Modul Yang Sudah Lengkap, Manual, dan Sensitif

### 4.1 Modul Yang Relatif Lengkap Sebagai ERP Internal

| Modul | Status Existing | Catatan |
| --- | --- | --- |
| Master data internal | Cukup lengkap | Branch, user, client, mandor, lokasi, employee, supplier, item, menu, recipe tersedia |
| Order internal | Cukup lengkap | Daily order dan detail order tersedia |
| Production internal | Ada | Model dan route produksi tersedia |
| Delivery internal | Ada | Delivery, detail, receipt tersedia |
| Logistics/stock | Cukup kuat | Procurement, movement, adjustment, opening balance, request tersedia |
| Finance internal | Cukup luas | Invoice, payment, AR/AP, cash bank, manual billing, advance, expense |
| Accounting | Ada | Account, journal, fixed asset, period closing |
| Costing/HPP | Ada | Snapshot HPP, costing service, stock consumption |
| HR/payroll | Ada | Attendance, assignment, payroll |
| Dashboard internal | Ada | Dashboard role tersedia |
| Audit/system foundation | Ada | AuditLog, Notification, DigitalAttachment, ApprovalRequest, IdempotencyKey |

### 4.2 Modul Yang Masih Manual atau Belum Terbukti Lengkap

| Modul Blueprint | Status Existing | Gap |
| --- | --- | --- |
| Portal pelanggan umum | Belum terbukti sebagai portal lengkap | Butuh login eksternal, order mandiri, pembayaran awal, riwayat, upload bukti |
| Portal mandor | Sebagian data ada | Model Mandor ada, tetapi portal role/ownership/fitur belum lengkap |
| Portal PT | Belum lengkap | Belum ada role PT dan tampilan khusus PT untuk mandor/invoice/kontrak |
| Delegasi mandor | Belum ada sebagai permission formal | Butuh role dan batas akses khusus |
| Kontrak PT | Belum lengkap sebagai domain kontrak catering | Ada asset financing contract, bukan kontrak pelanggan catering |
| Komplain/retur | Belum terlihat sebagai domain lengkap | Butuh workflow dan audit terpisah |
| Subscription order | Belum terlihat lengkap | Harus menghasilkan daily order normal, bukan jalur paralel |
| Payment gateway/webhook | Belum scope aman | Blueprint menyarankan tahap lanjut dan approval-required |
| Approval engine penuh | Foundation ada | Belum terbukti semua aksi sensitif memakai maker-checker |
| Document archive penuh | Foundation ada | Belum terbukti versioning, retention, akses private per dokumen |
| Restore drill | Belum terbukti | Backup service bukan bukti pemulihan |

### 4.3 Area Sensitif

Area berikut tidak boleh diubah tanpa approval:

- Database schema dan migration.
- Role dan permission.
- Invoice, payment, receivable, payable.
- Journal, posting, reversal, closing.
- Stock, HPP, procurement, fulfillment.
- Approval/maker-checker.
- Kontrak dan credit limit.
- Numbering document resmi.
- Report keuangan.
- Payment gateway, webhook, auto-settlement.
- Data migration atau perubahan data historis.

---

## 5. Business Rule Existing Yang Terlihat

| Area | Business Rule Existing |
| --- | --- |
| Auth | Login required dan role required dipakai di route bisnis. OWNER bypass role guard. Logout sudah POST. |
| Role guard | Unauthorized role diarahkan ke dashboard, bukan 403. Ini existing behavior. |
| Finance | Invoice, payment, AR/AP, cash bank, manual billing, advance, expense, fixed asset sudah ada. |
| Accounting | Jurnal dan detail jurnal tersedia, PeriodClosing ada. |
| Digital proof | DigitalAttachment tersedia dan sudah dipakai untuk bukti digital. |
| Idempotency | IdempotencyKey tersedia sebagai foundation. |
| Approval | ApprovalRequest tersedia sebagai foundation. |
| Numeric precision | Banyak model inti sudah memakai `Numeric(18, 2)`, `Numeric(18, 4)`, dan `Numeric(8, 4)` berdasarkan inventaris terbaru. |
| Optimistic locking | `BaseModel` memiliki `version_id`. |
| Security headers | Header dasar dan CSP/report-only optional sudah tersedia di app factory. |
| Error handling | 500 handler melakukan rollback. Beberapa context processor memakai fallback dan logging. |

Catatan penting: rule di atas adalah hasil inventaris struktur, bukan bukti UAT penuh semua cabang bisnis.

---

## 6. ERP Existing vs Blueprint Matrix

| Blueprint | Status Existing | Implementasi Existing | Gap | Prioritas | Risiko |
| --- | --- | --- | --- | --- | --- |
| Tidak rebuild, extend ERP existing | Selaras | Struktur monolith Flask existing | Perlu disiplin agar fitur baru tidak paralel | P0 governance | Risiko duplikasi modul |
| Single PostgreSQL database | Selaras secara arah | App dikunci ke PostgreSQL-only pada konfigurasi proyek | Perlu verifikasi test DB dan migration chain | P0 | Database/migration risk |
| Modular monolith | Sebagian selaras | 17 blueprint, subroute finance/accounting/logistics/master/settings sudah ada | Service/domain boundary perlu terus dijaga | P1 | God service/module risk |
| Thin routes, business logic in service | Sebagian selaras | Banyak service domain tersedia | Perlu audit kontinu route mutasi dan nested commit | P0/P1 | Partial commit |
| Internal ERP as source of truth | Selaras | Internal order/finance/accounting/stock menjadi pusat data | Portal eksternal belum boleh menjadi source paralel | P0 governance | Data duplication |
| Role internal | Ada | OWNER, ADMIN, FINANCE, ACCOUNTING, LOGISTICS, HR, DAPUR, PENGANTAR | Role PT/Mandor/Pelanggan/Delegasi belum resmi | APPROVAL REQUIRED | Authorization exposure |
| Portal pelanggan umum | Belum lengkap | Ada Client model dan finance/order internal | Butuh portal login, order, upload bukti, riwayat | Stage 1 | Role/schema/payment approval |
| Portal mandor | Sebagian | Ada Mandor model dan invoice helper | Butuh portal, ownership guard, hutang, invoice, delegasi | Stage 1/2 | Role/permission/data isolation |
| Portal PT | Belum lengkap | Ada Client/ClientPic | Butuh relasi PT-mandor, dashboard PT, kontrak/invoice | Stage 2/4 | Schema/permission approval |
| Delegasi mandor | Belum ada | Belum role formal | Butuh permission terbatas | Stage 1/2 | Role approval |
| Order pelanggan self-service | Belum lengkap | DailyOrder internal tersedia | Butuh UI portal dan guard prepayment | Stage 1 | Payment/order lifecycle approval |
| Multi-location order | Sebagian | DeliveryLocation tersedia | Perlu bukti workflow portal/location ownership | Stage 1 | Data isolation |
| Subscription order | Belum lengkap | DailyOrder bisa menjadi target | Butuh generator yang membuat order normal | Stage 2/5 | Order lifecycle approval |
| Cutoff dan perubahan order | Sebagian/belum terbukti | OrderRevision ada | Policy cutoff/change approval belum dibakukan | APPROVAL REQUIRED | Operational disruption |
| Production workflow | Ada | Production dan ProductionDetail | Perlu integrasi portal status tanpa ubah rule | Stage 1 | Stock/HPP coupling |
| Delivery workflow | Ada | Delivery, detail, receipt | Perlu map/WA deep link bila belum ada | Stage 1/3 | Low sampai medium |
| Bukti serah terima | Ada | DeliveryReceipt | Perlu archive/versioning/access review | Stage 3 | Document access |
| Invoice periodik | Ada | Invoice, period invoice routes/services | Perlu ownership dan customer portal view | Stage 2 | Invoice approval |
| Payment manual verification | Ada sebagian | Payment, DigitalAttachment, finance payment UI | Perlu portal upload bukti dan verifikasi finance formal | Stage 1/2 | Payment approval |
| QRIS static/manual | Belum terkonfirmasi | Bisa sebagai payment method/config | Perlu config dan SOP tanpa webhook | Stage 1/2 | Payment approval |
| Payment gateway/webhook | Belum ada atau belum scope | Tidak boleh langsung | Approval dan desain idempotency wajib | Stage 5 | High |
| Credit/tempo PT/mandor | Sebagian | Receivable/invoice/payment ada | Credit limit/eligibility perlu formal | APPROVAL REQUIRED | High financial risk |
| Closing period | Ada foundation | PeriodClosing model/service | Perlu bukti guard seluruh transaksi saat closed | P0/P1 | High accounting risk |
| Journal invariant | Ada foundation | Journal/JournalDetail | Perlu regression invariant debit=credit per workflow | P0/P1 | High financial risk |
| Stock invariant | Ada foundation | StockMovement/OpenBalance/Adjustment | Perlu expected balance audit otomatis | P0/P1 | High inventory risk |
| Approval/maker-checker | Foundation ada | ApprovalRequest, approval_service, sensitive guard | Perlu mapping aksi sensitif | APPROVAL REQUIRED | High control risk |
| Audit trail | Ada | AuditLog dan services | Perlu pastikan semua aksi sensitif tercatat before/after | P1 | Compliance risk |
| Document archive | Foundation ada | DigitalAttachment | Perlu archive taxonomy, versioning, retention, ownership | Stage 3/4 | Data leakage |
| Contract PT | Belum lengkap | Asset financing contract bukan kontrak catering PT | Modul kontrak pelanggan perlu desain | APPROVAL REQUIRED | Legal/financial risk |
| Complaint/return | Belum lengkap | Belum terlihat domain utama | Modul baru perlu workflow dan audit | APPROVAL REQUIRED jika menyentuh invoice/stock/payment |
| Dashboard role | Ada internal | dashboard_bp dan role dashboards | Portal dashboards eksternal belum lengkap | Stage 1/2 | Permission exposure |
| Security headers | Sebagian kuat | Header dasar, optional CSP | CSP enforcement bertahap perlu UAT | P1 | UI breakage |
| Logout POST | Selaras | auth logout POST | Tidak perlu perubahan | Done | Low |
| Login enumeration | Perlu verifikasi | Tidak disimpulkan dari inventaris ini | Test security regression diperlukan | P1 | Security risk |
| Rate limit shared storage | Perlu verifikasi prod | Limiter init ada | Redis/shared storage production harus dicek env | P1 | Brute-force risk |
| Backup/restore | Foundation ada | backup/recovery services | Restore drill belum terbukti | P0 | Disaster recovery risk |
| Release engineering | Belum fokus karena dev | Dirty worktree boleh untuk dev | Tetap butuh clean release sebelum UAT luas | Stage gate | Reproducibility risk |

---

## 7. Perubahan Yang Diperlukan

### A. Tidak Perlu Perubahan Saat Ini

| Area | Alasan |
| --- | --- |
| Rebuild aplikasi | Dilarang blueprint dan tidak diperlukan |
| Database paralel baru | Dilarang blueprint |
| Microservices | Tidak diperlukan, monolith modular masih sesuai |
| Mengganti PostgreSQL | Tidak sesuai blueprint |
| Menghapus ERP internal existing | Dilarang dan berisiko tinggi |
| Membuat jalur order/finance paralel | Berisiko duplikasi source of truth |
| Logout POST | Existing sudah selaras |
| Foundation Numeric/locking | Banyak model sudah memakai Numeric dan BaseModel punya version_id; cukup verifikasi, jangan migrasi massal tanpa scope |

### B. Perlu Penambahan Kecil

| Perubahan | Syarat |
| --- | --- |
| Dokumentasi route ownership dan domain owner | Aman, dokumentasi saja |
| Manual UAT checklist portal/order/payment | Aman |
| Route-map snapshot dan manifest coverage | Aman jika hanya test/dokumen |
| Template/link audit lanjutan | Aman jika bug fix non-business-rule |
| Logging dan request ID coverage | Aman jika tidak mengubah business rule |
| Slow query config documentation | Aman |
| SOP backup restore drill | Aman sebagai dokumen |
| Feature flag default-off untuk calon portal | Aman jika tidak mengubah flow existing |

### C. Perlu Penambahan Modul

Semua item di bawah perlu desain teknis sebelum implementasi. Bila menyentuh schema/role/payment/invoice/stock/journal, statusnya tetap approval-required.

| Modul | Alasan |
| --- | --- |
| Portal Pelanggan Umum | Belum ada sebagai pengalaman eksternal lengkap |
| Portal Mandor | Model Mandor ada, tetapi portal/ownership/fitur perlu dibuat |
| Portal PT | Butuh dashboard invoice/mandor/kontrak/receivable khusus |
| Delegasi Mandor | Butuh role/permission terbatas |
| Kontrak pelanggan/PT | Belum ada domain kontrak catering formal |
| Complaint/return | Belum ada workflow formal |
| Subscription order | Belum lengkap sebagai generator order normal |
| Archive taxonomy | DigitalAttachment ada, tetapi taxonomy/versioning/retention perlu diperluas |
| Approval policy mapping | ApprovalRequest ada, tetapi perlu mapping aksi sensitif |

### D. Perlu Refactor

Refactor boleh dilakukan hanya jika behavior-preserving atau sudah mendapat approval bila menyentuh business rule.

| Refactor | Status |
| --- | --- |
| Pemisahan service besar billing/manual backfill | Boleh bertahap jika behavior-preserving |
| Audit nested commit lintas service | Wajib sebelum workflow baru |
| Mengurangi coupling route wrapper lama ke modul baru | Boleh bertahap selama endpoint compatibility terjaga |
| Dashboard query performance | Boleh jika hasil query tidak berubah |
| Error handling generic exception | Boleh jika tidak membuat fallback palsu |
| Ownership guard helper reusable | Approval jika mengubah akses role; aman jika hanya bug fix existing |

### E. Perlu Approval Pengguna

| Perubahan | Kenapa Approval Required |
| --- | --- |
| Menambahkan role PT, Mandor, Pelanggan Umum, Delegasi | Mengubah role/permission |
| Menambahkan table portal/contract/complaint/subscription | Mengubah database/migration |
| Mengubah order status/lifecycle/cutoff | Mengubah business rule operasional |
| Mengubah invoice generation atau numbering | Menyentuh invoice resmi |
| Mengubah payment verification, allocation, auto-posting | Menyentuh payment dan receivable |
| Menambahkan credit limit/scoring/blacklist | Menyentuh credit/receivable |
| Menambahkan maker-checker pada transaksi berjalan | Menyentuh approval dan workflow |
| Mengubah journal posting/reversal/closing guard | Menyentuh accounting |
| Mengubah stock fulfillment/HPP calculation | Menyentuh stock dan HPP |
| Payment gateway/webhook | Menyentuh external payment, idempotency, security |
| Migration cleanup atau perubahan migration lama | Menyentuh migration integrity |
| Data backfill/migration operasional | Menyentuh data historis |

---

## 8. Dependency Map

### 8.1 Dependency Internal Existing

```text
Master Data
  -> Client, Mandor, Branch, DeliveryLocation, Employee, Supplier, Item, Menu

Operational Order
  -> Master Data
  -> Costing/HPP snapshot
  -> Production
  -> Delivery
  -> Finance invoice/manual billing
  -> Stock consumption

Production
  -> Operational Order
  -> Recipe/Menu/Item
  -> Stock/Logistics

Delivery
  -> Operational Order
  -> Driver/DeliveryLocation
  -> DeliveryReceipt/DigitalAttachment

Logistics/Stock
  -> Item/Supplier
  -> Procurement
  -> StockMovement
  -> StockAdjustment
  -> HPP/Costing

Finance
  -> Client/Mandor/Branch
  -> Invoice/InvoiceItem
  -> Payment/BankAccount/CashBank
  -> Receivable/Payable
  -> ManualBilling/ManualBackfill
  -> DigitalAttachment
  -> Accounting Journal

Accounting
  -> Finance
  -> FixedAsset
  -> Journal/JournalDetail
  -> PeriodClosing

System Governance
  -> AuditLog
  -> ApprovalRequest
  -> IdempotencyKey
  -> Notification
  -> Backup/Recovery
```

### 8.2 Dependency Blueprint Future

```text
Portal Pelanggan/Mandor/PT
  -> Auth/User/Role/Permission
  -> Ownership Guard
  -> Master Client/Mandor/PT mapping
  -> Order Service
  -> Payment Proof Upload
  -> Invoice/Receivable View
  -> Digital Attachment
  -> Notification
  -> AuditLog

Contract Module
  -> Client/PT
  -> Mandor mapping
  -> Credit terms/limit
  -> Invoice rules
  -> Approval
  -> Document Archive
  -> AuditLog

Complaint/Return
  -> Order/Delivery/Invoice references
  -> Stock impact if return affects inventory
  -> Finance impact if credit note/refund appears
  -> Approval/AuditLog

Subscription
  -> Client/Mandor/PT
  -> DeliveryLocation
  -> Menu/price
  -> DailyOrder generator
  -> Cutoff policy
  -> AuditLog
```

### 8.3 Critical Cross-Module Risks

| Dependency | Risiko |
| --- | --- |
| Portal role -> invoice/payment view | Data pelanggan bisa bocor bila ownership guard salah |
| Order -> production -> stock -> HPP | Perubahan order dapat merusak stok dan HPP |
| Payment -> receivable -> cash bank -> journal | Partial commit dapat merusak saldo |
| Closing -> transaction guards | Transaksi periode tertutup bisa masuk bila guard tidak merata |
| Contract -> credit -> invoice | Salah rule kontrak bisa salah tagihan |
| Complaint/return -> invoice/stock | Bisa butuh reversal atau adjustment |

---

## 9. Workflow Existing

Workflow internal yang terlihat:

1. Master data dibuat: branch, client, mandor, lokasi, item, menu, recipe, supplier, employee.
2. Operational membuat daily order dan detail order.
3. Production mengelola produksi berdasarkan order/menu.
4. Logistics mengelola procurement, stock movement, adjustment, dan item request.
5. Delivery mengelola pengiriman, detail, dan receipt.
6. Costing/HPP menyimpan snapshot biaya dan konsumsi stok.
7. Finance membuat invoice, manual billing/backfill, payment, receivable/payable, cash bank, advance/expense.
8. Accounting membuat journal, asset accounting, dan period closing/report.
9. Dashboard menampilkan ringkasan sesuai role internal.
10. System layer menyediakan audit log, notification, digital attachment, backup/recovery, approval/idempotency foundation.

Workflow blueprint yang belum boleh langsung dibuat tanpa approval:

1. Pelanggan umum login dan order sendiri.
2. Pelanggan umum wajib bayar dulu sebelum diproses.
3. Mandor/PT melihat piutang/invoice/kontrak melalui portal.
4. Delegasi mandor dapat order tanpa akses finansial penuh.
5. Kontrak PT mengatur term, limit, document, expiry, renewal.
6. Complaint/return dapat terkait delivery, invoice, atau stock.
7. Subscription otomatis membuat order reguler.

---

## 10. Potensi Konflik Dengan Blueprint

| Potensi Konflik | Dampak | Rekomendasi |
| --- | --- | --- |
| Existing role internal berbeda dari role portal blueprint | Portal tidak bisa dibuat hanya dengan role lama | Buat desain role mapping, approval required |
| Mandor ada sebagai master, bukan user portal | Auth/ownership belum otomatis ada | Jangan jadikan Mandor login tanpa approval role dan user mapping |
| Client/PT/Pelanggan Umum belum jelas pemisahannya | Bisa salah expose invoice/receivable | Definisikan taxonomy customer dulu |
| Existing route finance sangat besar walau sudah dipisah | Risiko coupling saat fitur portal masuk | Refactor bertahap behavior-preserving |
| ApprovalRequest foundation belum berarti semua aksi sensitif maker-checker | Kontrol internal belum lengkap | Mapping aksi sensitif perlu approval |
| DigitalAttachment foundation belum berarti archive policy lengkap | Risiko akses dan retensi dokumen | Buat taxonomy dan retention SOP |
| Migration chain perlu audit | Schema baru berisiko bila baseline tidak jelas | Stage 0 migration verification wajib |
| Dashboard internal bisa berbeda dengan portal dashboard | Risiko membocorkan data internal | Portal dashboard harus punya ownership guard sendiri |
| Payment prepayment untuk pelanggan umum bisa bertentangan dengan flow invoice existing | Bisa mengubah receivable/cash/journal | Approval required |

---

## 11. Roadmap Implementasi Paling Aman

### Stage 0 - Baseline Hardening Wajib

Tujuan: memastikan ERP existing stabil sebelum fitur portal/kontrak/complaint.

Aktivitas aman:

- Finalisasi route-map snapshot dan endpoint coverage manifest.
- Jalankan full route smoke untuk GET aman dan POST fixture aman.
- Jalankan template/url_for audit.
- Jalankan compileall dan full pytest.
- Verifikasi migration chain: heads, current, upgrade database kosong, upgrade snapshot.
- Verifikasi no route commit/rollback dan audit nested commit service.
- Restore drill test database dan attachment.
- Review role matrix existing tanpa mengubah role.
- Dokumentasikan current business rule.
- Dokumentasikan release baseline dev/staging.

Gate keluar Stage 0:

- Tidak ada route 500 pada smoke test yang wajib.
- Tidak ada BuildError/NameError/UndefinedError pada template dan route utama.
- Migration chain terbukti valid.
- Test database bisa dibuat dari kosong.
- Restore drill berhasil.
- Semua approval-required change sudah dipisahkan dari bug fix.

### Stage 1 - Portal Foundation Default-Off

Status: **Approval required sebelum implementasi**.

Aktivitas setelah approval:

- Desain mapping user eksternal: Pelanggan Umum, Mandor, PT, Delegasi.
- Tambahkan ownership guard.
- Tambahkan route/template portal default-off.
- Tampilkan data read-only dulu.
- Jangan ubah invoice/payment/journal/stock behavior.
- Order portal hanya masuk ke service existing setelah policy disetujui.

### Stage 2 - Order dan Payment Portal

Status: **Approval required**.

Aktivitas setelah approval:

- Order pelanggan umum lewat service existing.
- Payment proof upload memakai DigitalAttachment.
- Finance verification manual.
- Jangan gateway/webhook dulu.
- Pastikan idempotency double-submit.
- Pastikan audit log semua aksi.

### Stage 3 - Finance Visibility PT/Mandor

Status: **Approval required**.

Aktivitas setelah approval:

- Portal invoice/receivable/payment history.
- Outstanding per mandor/PT.
- Download dokumen yang sudah diizinkan.
- Ownership guard ketat.
- No mutation financial dari portal kecuali upload bukti/komunikasi yang disetujui.

### Stage 4 - Contract, Complaint, Document Archive

Status: **Approval required**.

Aktivitas setelah approval:

- Contract customer/PT domain.
- Complaint/return workflow.
- Archive taxonomy dan retention.
- Approval untuk perubahan kontrak/limit/status.

### Stage 5 - Automation

Status: **Approval required**.

Aktivitas setelah approval:

- Subscription generator.
- Reminder otomatis.
- WhatsApp/email integration jika disetujui.
- Payment gateway/webhook jika disetujui.
- Advanced approval and reconciliation automation.

---

## 12. Keputusan Untuk Tahap Berikutnya

### Bisa Dilakukan Sekarang Tanpa Approval Bisnis

- Membuat dan memperbarui dokumentasi analisis.
- Membuat checklist UAT manual.
- Menambahkan test regresi non-mutating.
- Memperbaiki bug UI/template/url_for yang jelas tanpa mengubah business rule.
- Refactor kecil behavior-preserving.
- Audit route map, template, import, JS.
- Logging dan observability non-invasive.

### Harus Menunggu Approval

- Role portal eksternal.
- Schema baru untuk portal/contract/complaint/subscription.
- Workflow order pelanggan umum.
- Payment prepayment atau verification rule.
- Credit/tempo/limit.
- Invoice, journal, stock, HPP, closing.
- Maker-checker enforcement.
- Payment gateway/webhook.
- Migration/data backfill.

---

## 13. Putusan Akhir

**BLOCKED**

ERP existing sudah cukup kuat sebagai fondasi internal, tetapi belum boleh langsung masuk implementasi Stage 1 blueprint karena perubahan berikutnya menyentuh area sensitif:

- role dan permission eksternal;
- invoice/payment/receivable visibility;
- order portal;
- payment proof dan prepayment rule;
- contract dan credit terms;
- approval workflow;
- migration/database bila diperlukan.

Tahap berikutnya yang paling aman:

1. Selesaikan Stage 0 baseline hardening dan buktikan dengan laporan teknis.
2. Minta approval eksplisit untuk role portal dan scope Stage 1.
3. Setelah approval, implementasi Stage 1 secara default-off dan read-only dulu, lalu naik bertahap ke order/payment.

Tidak disarankan memulai coding fitur baru sebelum gate di atas terpenuhi.
