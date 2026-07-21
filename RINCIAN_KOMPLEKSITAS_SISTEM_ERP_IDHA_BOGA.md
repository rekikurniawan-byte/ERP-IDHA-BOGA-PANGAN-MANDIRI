# Rincian Kompleksitas Sistem ERP PT Idha Boga Pangan Mandiri

Dokumen ini dibuat dari pembacaan struktur project ERP: `app/routes`, `app/templates`, `app/models`, `app/services`, `tests`, `migrations`, dan aset statis. Tujuannya adalah memperlihatkan seberapa luas sistem ini dari sisi modul, halaman, alur bisnis, database, service layer, dan titik kontrol.

## 1. Ringkasan Angka Kompleksitas

| Komponen | Jumlah | Makna |
|---|---:|---|
| File route / blueprint | 17 | Sistem dibagi ke banyak area bisnis, bukan satu modul tunggal. |
| Endpoint route | 331 | Terdiri dari halaman, aksi POST, export CSV, print, download, view attachment, dan API. |
| Template HTML | 207 | Banyak layar operasional dan laporan yang terpisah per kebutuhan pengguna. |
| Model/class database dan domain | 99 | Entitas bisnis sudah mencakup master, operasional, logistik, finance, accounting, delivery, HR, warung, audit, dan transaksi lapangan. |
| Service Python | 76 | Logika bisnis dipisahkan dari route; ini menandakan sistem cukup matang secara arsitektur. |
| Migration Alembic | 39 | Skema database berkembang bertahap, dengan banyak fitur tambahan produksi. |
| Test file | 11 | Ada pengujian untuk billing, piutang, transaksi lapangan, advance, dan guard bisnis. |
| CSS modular | 65 | UI dibuat dengan banyak lapisan styling modul dan polish/regression lock. |

Secara praktis, sistem ini sudah berada pada level ERP operasional internal, bukan sekadar CRUD biasa. Modulnya sudah menyentuh order harian, stok, HPP, produksi, delivery, invoice, pembayaran, kas/bank, piutang, hutang, jurnal, closing, audit, backup, recovery, warung, HR, dan transaksi lapangan.

## 2. Peta Modul Utama

| Modul | Fungsi Besar | Kompleksitas Bisnis |
|---|---|---|
| Auth | Login dan logout pengguna. | Kontrol akses dasar sebelum masuk ERP. |
| Dashboard | Dashboard owner, admin, dapur, pengantar, finance, accounting, logistics, HR, dan revenue explorer. | Menyatukan ringkasan lintas modul untuk pengambilan keputusan. |
| Master Data | Client, PIC client, mandor, lokasi, pekerja, driver, item, supplier, bank account, aset tetap, konversi satuan, profil biaya. | Fondasi data semua transaksi. Kesalahan master akan menjalar ke modul lain. |
| Operational | Order harian, detail order per mandor/lokasi, revisi, lock order, HPP default, snapshot HPP, konsumsi stok. | Pusat transaksi catering realtime. |
| Production | Daftar produksi, detail produksi, dan realisasi produksi. | Menghubungkan order dengan pekerjaan dapur. |
| Delivery | Pengiriman, dispatch, SLA, penerimaan, shortage replacement, attachment bukti, history. | Membuktikan makanan benar-benar dikirim dan diterima. |
| Logistics | Stock in/out, adjustment, material forecast, kartu barang, pembelian, attachment pembelian, barang rusak, audit stok, permintaan barang dapur, kitchen usage. | Menjaga bahan baku dan stok agar cocok dengan produksi dan HPP. |
| Costing/HPP | Menu, resep/BOM, packaging profile, overhead profile, kalkulator HPP, order HPP snapshots. | Menghitung biaya produksi dan margin per porsi. |
| Finance | Invoice, generate invoice order/periode, payment, piutang, statement, cash/bank ledger, supplier bill, AP aging, manual billing, manual backfill, advance, biaya transport, biaya operasional, aset, depresiasi, cicilan aset. | Modul terbesar; mengubah operasi menjadi tagihan, kas, hutang, aset, dan laporan finance. |
| Accounting | Data health, daily closing, expense drilldown, posting status, order-to-cash trace, journal, reports, COA mapping, opening balance, posting jurnal, period closing. | Menjaga transaksi finance menjadi jurnal dan laporan akuntansi. |
| Field Transactions | Transaksi lapangan, counterparty, attachment, review status, posting, manual receivable/payable, settlement, bridge ke biaya/panjar. | Menangkap transaksi nonformal/manual agar tetap terkendali. |
| Canteen/Warung | Penjualan warung, quick sale, hutang pekerja, pembayaran hutang, piutang eksternal. | Sub-bisnis warung yang bisa masuk ke piutang/tagihan. |
| HR | Karyawan, payroll, generate payroll, finalisasi, posting jurnal payroll, pembayaran payroll, riwayat pembayaran. | Mengelola tenaga kerja dan beban gaji. |
| Settings | Identitas perusahaan, user management, backup, recovery, audit log, attachment, reminder, notification, health, QA visual, atomic transaction map. | Lapisan administrasi, keamanan, audit, dan operasional sistem. |
| SOP | SOP role, disaster recovery, backup/restore. | Dokumentasi operasional pengguna dan recovery. |
| Prediction/ML | Train, predict, evaluate, API predict. | Area prediksi/ML untuk dukungan analitik. |
| Health | Healthz dan readiness check. | Kesiapan deployment/monitoring server. |

## 3. Alur Bisnis Besar yang Sudah Tercakup

### 3.1 Order-to-Cash Catering Realtime

1. Admin membuat order harian.
2. Order diisi detail mandor, lokasi, porsi siang, porsi sore, dan harga per porsi.
3. Order bisa direvisi sebelum/atau setelah lock sesuai flow.
4. Order dikunci untuk menjadi dasar produksi, delivery, HPP, dan invoice.
5. Produksi dapat dibuat dari order.
6. Delivery dibuat dari order dan diproses sampai penerimaan.
7. Invoice dibuat berdasarkan order/periode.
8. Payment dicatat, bisa partial atau lunas.
9. Transaksi masuk kas/bank.
10. Accounting membuat jurnal invoice dan jurnal payment.
11. Trace order-to-cash menampilkan rantai sumber data sampai jurnal dan kas/bank.

### 3.2 Manual Backfill / Buku Manual ke Invoice

1. Finance input rekap manual dari buku/catatan lama.
2. Sistem memisahkan input_source `MANUAL_BACKFILL` dari `REALTIME`.
3. Sistem mengelompokkan item catering dan warung.
4. Sistem cek duplicate agar tidak dobel tagih.
5. Batch manual bisa dilock.
6. Batch dipromosikan menjadi invoice.
7. Invoice dibayar partial/lunas.
8. Payment masuk kas/bank.
9. Jurnal invoice dan payment dibuat.
10. Trace billing menunjukkan asal data manual sampai buku kas/bank.

### 3.3 Procure-to-Stock-to-HPP

1. Logistik mencatat pembelian bahan.
2. Stock movement masuk dibuat.
3. Dapur membuat permintaan barang.
4. Stok keluar/fulfillment dicatat.
5. Resep, profil biaya item, konversi satuan, packaging, dan overhead menjadi dasar HPP.
6. Snapshot HPP order menyimpan perhitungan biaya pada titik waktu tertentu.
7. Konsumsi stok HPP bisa di-dry-run lalu commit.

### 3.4 Finance-to-Accounting

1. Invoice, payment, supplier bill, supplier payment, operational expense, transport expense, fixed asset purchase, cicilan aset, depresiasi, payroll, dan warung menjadi sumber jurnal.
2. Accounting melakukan generate/posting jurnal berdasarkan reference type dan reference id.
3. Sistem menjaga jurnal agar tidak dobel.
4. Laporan accounting menyediakan jurnal, ledger, trial balance, income summary, data health, dan daily closing.
5. Period closing menutup periode akuntansi.

### 3.5 Field Transaction Control

1. Transaksi lapangan dicatat dengan counterparty.
2. Bukti digital dapat dilampirkan dan diverifikasi.
3. Status review diproses dari draft sampai posted/reconciled.
4. Transaksi dapat dijembatani ke operational expense, transport expense, atau advance.
5. Transaksi bisa melahirkan manual receivable/payable dan pembayaran.

## 4. Modul Database / Model Utama

### 4.1 Master Data

- `Branch`
- `BranchSetting`
- `User`
- `Client`
- `ClientPic`
- `Mandor`
- `DeliveryLocation`
- `Employee`
- `EmployeeSkill`
- `Driver`
- `Supplier`
- `Item`
- `UnitConversion`
- `ItemCostProfile`
- `Menu`
- `RecipeHeader`
- `RecipeItem`
- `RecipeVersion`
- `RecipeVersionItem`
- `PackagingProfile`
- `OverheadProfile`
- `Worker`

### 4.2 Operational dan HPP

- `DailyOrder`
- `DailyOrderDetail`
- `OrderRevision`
- `OrderSnapshot`
- `OrderHppSnapshot`
- `OrderHppSnapshotLine`
- `OrderHppSnapshotComponent`
- `OrderHppSnapshotAllocation`
- `OrderHppStockConsumption`
- `OrderHppStockConsumptionLine`

### 4.3 Production dan Delivery

- `Production`
- `ProductionDetail`
- `Delivery`
- `DeliveryDetail`
- `DeliveryReceipt`

### 4.4 Logistics

- `Procurement`
- `ProcurementItem`
- `StockMovement`
- `DamagedItem`
- `StockAdjustment`
- `ItemRequest`
- `ItemRequestDetail`

### 4.5 Finance

- `Invoice`
- `InvoiceItem`
- `ManualBillingBatch`
- `ManualBillingBatchItem`
- `Payment`
- `BankAccount`
- `CashBankTransaction`
- `CashBankOpeningBalance`
- `CashBankTransfer`
- `CashBankAdjustment`
- `SupplierBill`
- `SupplierPayment`
- `InvoiceCollectionLog`
- `AdvanceTransaction`
- `AdvanceSettlement`
- `TransportVehicleExpense`
- `OperationalExpense`

### 4.6 Accounting dan Aset

- `Account`
- `Journal`
- `JournalDetail`
- `FixedAsset`
- `FixedAssetPurchase`
- `FixedAssetDepreciationConfig`
- `FixedAssetDepreciation`
- `AssetFinancingContract`
- `AssetInstallmentSchedule`
- `AssetInstallmentPayment`
- `PeriodClosing`

### 4.7 Field Transaction

- `FieldCounterparty`
- `FieldTransaction`
- `FieldTransactionAttachment`
- `FieldTransactionReviewLog`
- `FieldTransactionLink`
- `FieldTransactionSettlement`
- `ManualReceivable`
- `ManualReceivablePayment`
- `ManualPayable`
- `ManualPayablePayment`

### 4.8 Canteen / Warung

- `CanteenSale`
- `CanteenSaleItem`
- `WorkerDebt`
- `DebtPayment`
- `CanteenExternalReceivable`
- `CanteenExternalReceivablePayment`
- `CashDaily`
- `CashExpense`

### 4.9 HR dan System

- `EmployeeAttendance`
- `EmployeeAssignment`
- `Payroll`
- `PayrollDetail`
- `EmployeeSalaryHistory`
- `Notification`
- `AuditLog`
- `DigitalAttachment`

## 5. Inventaris Halaman Template

Bagian ini menunjukkan layar UI yang tersedia berdasarkan file `app/templates`.

### 5.1 Accounting

- `accounting/coa_mapping.html` - pengaturan mapping COA.
- `accounting/daily_closing.html` - pemeriksaan closing harian.
- `accounting/data_health.html` - kesehatan data akuntansi.
- `accounting/expense_drilldown.html` - drilldown biaya.
- `accounting/journal_index.html` - daftar jurnal.
- `accounting/journal_detail.html` - detail jurnal.
- `accounting/opening_balance.html` - saldo awal.
- `accounting/order_to_cash_trace.html` - trace order sampai kas/jurnal.
- `accounting/period_closing.html` - daftar/tindakan closing periode.
- `accounting/period_closing_detail.html` - detail closing periode.
- `accounting/posting_status.html` - status posting.
- `accounting/reports.html` - laporan accounting.
- `accounting/print_daily_closing.html` - print daily closing.
- `accounting/print_data_health.html` - print data health.
- `accounting/print_general_ledger.html` - print general ledger.
- `accounting/print_income_summary.html` - print income summary.
- `accounting/print_journal_detail.html` - print detail jurnal.
- `accounting/print_journals.html` - print daftar jurnal.
- `accounting/print_order_to_cash_trace.html` - print order-to-cash trace.
- `accounting/print_trial_balance.html` - print trial balance.
- `accounting/_accounting_flow_panel.html` - panel alur accounting.
- `accounting/_accounting_print_report_styles.html` - style cetak accounting.
- `accounting/_precision_guard_panel.html` - panel guard presisi data.

### 5.2 Auth

- `auth/login.html` - halaman login.

### 5.3 Canteen / Warung

- `canteen/index.html` - dashboard/daftar transaksi warung.
- `canteen/quick_sale.html` - input cepat penjualan warung.
- `canteen/sale_form.html` - form penjualan warung.
- `canteen/debts.html` - daftar hutang pekerja/piutang warung.
- `canteen/debt_payment.html` - pembayaran hutang/piutang warung.

### 5.4 Components dan Layout

- `components/csrf_token.html` - token keamanan form.
- `components/global_filter_bar.html` - filter global periode/cabang.
- `components/page_header.html` - header halaman.
- `components/sensitive_action_guard.html` - guard aksi sensitif.
- `layouts/base.html` - layout dasar.
- `layouts/sidebar.html` - sidebar navigasi.
- `layouts/topbar.html` - topbar.
- `module_placeholder.html` - placeholder modul.

### 5.5 Costing / HPP

- `costing/order_hpp_snapshots.html` - daftar snapshot HPP order.
- `costing/menus.html` - daftar menu.
- `costing/menu_form.html` - form menu.
- `costing/recipe_form.html` - form resep/BOM.
- `costing/packaging_profiles.html` - daftar profil packaging.
- `costing/packaging_profile_form.html` - form profil packaging.
- `costing/overhead_profiles.html` - daftar profil overhead.
- `costing/overhead_profile_form.html` - form profil overhead.
- `costing/hpp_calculator.html` - kalkulator HPP.

### 5.6 Dashboard

- `dashboard/owner.html` - dashboard owner.
- `dashboard/admin.html` - dashboard admin.
- `dashboard/dapur.html` - dashboard dapur.
- `dashboard/pengantar.html` - dashboard pengantar.
- `dashboard/revenue_explorer.html` - eksplorasi revenue.
- `dashboard/role_landing.html` - landing role finance/accounting/logistics/HR.
- `dashboard/_analytics_charts.html` - komponen chart analytics.
- `dashboard/_revenue_explorer_panel.html` - panel revenue explorer.

### 5.7 Delivery

- `delivery/index.html` - daftar delivery.
- `delivery/detail.html` - detail delivery.
- `delivery/receive.html` - form penerimaan delivery.
- `delivery/today.html` - delivery hari ini.
- `delivery/receiving.html` - daftar yang perlu diterima.
- `delivery/history.html` - riwayat delivery.

### 5.8 Error Pages

- `errors/400_csrf.html`
- `errors/403.html`
- `errors/404.html`
- `errors/500.html`

### 5.9 Field Transactions

- `field_transactions/index.html` - daftar transaksi lapangan.
- `field_transactions/monitoring.html` - monitoring transaksi lapangan.
- `field_transactions/form.html` - form transaksi lapangan.
- `field_transactions/detail.html` - detail transaksi lapangan.

### 5.10 Finance

- `finance/hub.html` - pusat navigasi finance.
- `finance/invoice_index.html` - daftar invoice.
- `finance/invoice_detail.html` - detail invoice.
- `finance/invoice_generate_order.html` - generate invoice dari order.
- `finance/invoice_generate_period_preview.html` - preview generate invoice periode.
- `finance/invoice_print.html` - cetak invoice.
- `finance/invoice_profit_report.html` - laporan profit invoice.
- `finance/invoice_profit_detail.html` - detail profit invoice.
- `finance/payment_history.html` - riwayat pembayaran.
- `finance/payment_receipt.html` - bukti pembayaran.
- `finance/receivables_dashboard.html` - dashboard piutang.
- `finance/receivables_print.html` - cetak piutang.
- `finance/receivables_statement.html` - statement piutang.
- `finance/cash_bank_ledger.html` - buku kas/bank.
- `finance/cash_bank_transaction_detail.html` - detail transaksi kas/bank.
- `finance/cash_bank_opening_balances.html` - saldo awal kas/bank.
- `finance/cash_bank_transfers.html` - transfer kas/bank.
- `finance/cash_bank_adjustments.html` - penyesuaian kas/bank.
- `finance/accounts_payable_aging.html` - aging hutang.
- `finance/supplier_payable_card.html` - kartu hutang supplier.
- `finance/supplier_bills.html` - daftar tagihan supplier.
- `finance/supplier_bill_detail.html` - detail tagihan supplier.
- `finance/transactions.html` - transaksi finance umum.
- `finance/manual_billing.html` - rekap/manual billing.
- `finance/manual_billing_backfill_form.html` - input buku manual.
- `finance/manual_billing_batches.html` - daftar batch manual billing.
- `finance/manual_billing_batch_detail.html` - detail batch manual billing.
- `finance/print_manual_billing_batch.html` - cetak batch manual billing.
- `finance/advances.html` - daftar panjar/advance.
- `finance/advance_form.html` - form panjar.
- `finance/advance_detail.html` - detail panjar.
- `finance/transport_expenses.html` - biaya transport.
- `finance/transport_expense_form.html` - form biaya transport.
- `finance/transport_expense_detail.html` - detail biaya transport.
- `finance/operational_expenses.html` - biaya operasional.
- `finance/operational_expense_form.html` - form biaya operasional.
- `finance/operational_expense_detail.html` - detail biaya operasional.
- `finance/fixed_asset_depreciation.html` - depresiasi aset.
- `finance/fixed_asset_depreciation_configure.html` - konfigurasi depresiasi aset.
- `finance/fixed_asset_purchases.html` - pembelian aset tetap.
- `finance/fixed_asset_purchase_form.html` - form pembelian aset.
- `finance/fixed_asset_purchase_detail.html` - detail pembelian aset.
- `finance/fixed_asset_installments.html` - cicilan aset.
- `finance/fixed_asset_installment_form.html` - form cicilan aset.
- `finance/fixed_asset_installment_detail.html` - detail cicilan aset.
- `finance/print_accounts_payable_aging.html`
- `finance/print_cash_bank_ledger.html`
- `finance/print_invoice_profit_report.html`
- `finance/print_supplier_payable_card.html`
- `finance/_billing_trace_panel.html`
- `finance/_finance_flow_panel.html`
- `finance/_finance_print_report_styles.html`
- `finance/daily_cash.html`
- `finance/daily_cash_detail.html`

### 5.11 HR

- `hr/index.html` - dashboard HR.
- `hr/employees.html` - daftar karyawan.
- `hr/employee_form.html` - form karyawan.
- `hr/payrolls.html` - daftar payroll.
- `hr/payroll_generate.html` - generate payroll.
- `hr/payroll_detail.html` - detail payroll.
- `hr/payroll_payment_history.html` - riwayat pembayaran payroll.

### 5.12 Logistics

- `logistics/index.html` - dashboard logistik.
- `logistics/material_forecast.html` - forecast bahan.
- `logistics/stock_form.html` - form stok masuk/keluar.
- `logistics/adjustment.html` - penyesuaian stok.
- `logistics/item_card.html` - kartu barang.
- `logistics/purchase_index.html` - daftar pembelian.
- `logistics/purchase_form.html` - form pembelian.
- `logistics/purchase_detail.html` - detail pembelian.
- `logistics/damaged_index.html` - daftar barang rusak.
- `logistics/damaged_form.html` - form barang rusak.
- `logistics/audit_index.html` - audit stok.
- `logistics/audit_form.html` - form audit stok.
- `logistics/item_request_index.html` - daftar permintaan barang.
- `logistics/item_request_form.html` - form permintaan barang.
- `logistics/item_request_detail.html` - detail permintaan barang.
- `logistics/kitchen_usage.html` - penggunaan dapur.
- `logistics/_logistics_hpp_flow_panel.html` - panel alur logistik-HPP.

### 5.13 Master Data

- `master/index.html` - dashboard master data.
- `master/clients.html` - daftar client.
- `master/client_form.html` - form client.
- `master/mandors.html` - daftar mandor.
- `master/mandor_form.html` - form mandor.
- `master/locations.html` - daftar lokasi.
- `master/location_form.html` - form lokasi.
- `master/workers.html` - daftar pekerja.
- `master/worker_form.html` - form pekerja.
- `master/drivers.html` - daftar driver.
- `master/driver_form.html` - form driver.
- `master/items.html` - daftar item/bahan.
- `master/item_form.html` - form item.
- `master/item_cost_profiles.html` - daftar profil biaya item.
- `master/item_cost_profile_form.html` - form profil biaya item.
- `master/unit_conversions.html` - konversi satuan.
- `master/suppliers.html` - daftar supplier.
- `master/supplier_form.html` - form supplier.
- `master/bank_accounts.html` - daftar akun bank.
- `master/bank_account_form.html` - form akun bank.
- `master/fixed_assets.html` - daftar aset tetap.
- `master/fixed_asset_form.html` - form aset tetap.

### 5.14 Operational

- `operational/daily_log.html` - log harian operasional.
- `operational/monthly_recap.html` - rekap bulanan.
- `operational/orders.html` - daftar order.
- `operational/order_form.html` - form order.
- `operational/order_detail.html` - detail order.
- `operational/revision_form.html` - form revisi order.
- `operational/order_hpp_defaults_form.html` - default HPP order.
- `operational/order_hpp_snapshot_form.html` - buat snapshot HPP.
- `operational/order_hpp_snapshot_detail.html` - detail snapshot HPP.
- `operational/order_hpp_stock_dry_run.html` - simulasi konsumsi stok HPP.
- `operational/order_hpp_stock_consumption_detail.html` - detail konsumsi stok HPP.
- `operational/_op_prod_delivery_flow_panel.html` - panel alur operasional-produksi-delivery.

### 5.15 Production

- `production/index.html` - daftar produksi.
- `production/detail.html` - detail produksi.

### 5.16 Settings

- `settings/company_settings.html` - pengaturan perusahaan.
- `settings/users.html` - daftar user.
- `settings/user_form.html` - form user.
- `settings/reset_password.html` - reset password.
- `settings/change_password.html` - ubah password.
- `settings/recovery_center.html` - recovery center.
- `settings/system_health.html` - kesehatan sistem.
- `settings/atomic_transaction_map.html` - peta transaksi atomik.
- `settings/atomic_smoke_simulation.html` - simulasi atomic smoke.
- `settings/visual_sweep.html` - visual sweep.
- `settings/final_visual_browser_qa.html` - QA visual final.
- `settings/backup.html` - backup.
- `settings/backup_download_confirm.html` - konfirmasi download backup.
- `settings/audit_logs.html` - daftar audit log.
- `settings/audit_log_detail.html` - detail audit log.
- `settings/digital_attachments.html` - daftar attachment digital.
- `settings/digital_attachment_detail.html` - detail attachment digital.
- `settings/live_reminders.html` - reminder live.
- `settings/notifications.html` - notifikasi.
- `settings/_hr_master_settings_flow_panel.html` - panel alur settings-HR-master.

### 5.17 SOP

- `sop/index.html` - pusat SOP.
- `sop/role_sop.html` - SOP berdasarkan role.
- `sop/disaster_recovery.html` - SOP disaster recovery.
- `sop/backup_restore.html` - SOP backup dan restore.
- `sop/_sop_nav.html` - navigasi SOP.

## 6. Endpoint Route per Modul

Bagian ini memperlihatkan permukaan aplikasi dari sisi URL. Route POST biasanya adalah aksi/transaksi, sedangkan GET biasanya halaman, print, export, download, atau view.

### 6.1 Auth

- `GET, POST /auth/login`
- `GET /auth/logout`

### 6.2 Dashboard

- `GET /`
- `GET /dashboard/owner`
- `GET /dashboard/admin`
- `GET /dashboard/revenue-explorer`
- `GET /dashboard/dapur`
- `GET /dashboard/pengantar`
- `GET /dashboard/finance`
- `GET /dashboard/accounting`
- `GET /dashboard/logistics`
- `GET /dashboard/hr`
- `GET /module/<module_name>`

### 6.3 Master Data

- `GET /master/`
- `GET /master/clients`
- `GET, POST /master/clients/create`
- `GET, POST /master/clients/<client_id>/edit`
- `POST /master/clients/<client_id>/toggle`
- `POST /master/clients/<client_id>/pics/create`
- `POST /master/clients/<client_id>/pics/<pic_id>/toggle`
- `GET /master/mandors`
- `GET, POST /master/mandors/create`
- `GET, POST /master/mandors/<mandor_id>/edit`
- `POST /master/mandors/<mandor_id>/toggle`
- `GET /master/locations`
- `GET, POST /master/locations/create`
- `GET, POST /master/locations/<location_id>/edit`
- `POST /master/locations/<location_id>/toggle`
- `GET /master/workers`
- `GET, POST /master/workers/create`
- `GET, POST /master/workers/<worker_id>/edit`
- `POST /master/workers/<worker_id>/toggle`
- `POST /master/workers/<worker_id>/delete`
- `GET /master/drivers`
- `GET, POST /master/drivers/create`
- `GET, POST /master/drivers/<driver_id>/edit`
- `POST /master/drivers/<driver_id>/toggle`
- `GET /master/items`
- `GET, POST /master/items/create`
- `GET, POST /master/items/<item_id>/edit`
- `POST /master/items/<item_id>/toggle`
- `POST /master/items/<item_id>/delete`
- `GET /master/item-cost-profiles`
- `GET, POST /master/items/<item_id>/cost-profile`
- `GET, POST /master/unit-conversions`
- `POST /master/unit-conversions/<conversion_id>/toggle`
- `GET /master/suppliers`
- `GET, POST /master/suppliers/create`
- `GET, POST /master/suppliers/<supplier_id>/edit`
- `POST /master/suppliers/<supplier_id>/toggle`
- `GET /master/bank-accounts`
- `GET, POST /master/bank-accounts/create`
- `GET, POST /master/bank-accounts/<account_id>/edit`
- `POST /master/bank-accounts/<account_id>/toggle`
- `GET /master/fixed-assets`
- `GET, POST /master/fixed-assets/create`
- `GET, POST /master/fixed-assets/<asset_id>/edit`
- `POST /master/fixed-assets/<asset_id>/toggle`

### 6.4 Operational

- `GET /operational/daily-log`
- `GET /operational/monthly-recap`
- `GET /operational/orders`
- `GET, POST /operational/orders/create`
- `GET, POST /operational/orders/<order_id>/add-detail`
- `GET, POST /operational/orders/<order_id>/add-increase-after-lock`
- `GET /operational/orders/<order_id>`
- `GET, POST /operational/orders/<order_id>/hpp-defaults`
- `POST /operational/orders/<order_id>/lock`
- `POST /operational/orders/<order_id>/generate-production`
- `GET, POST /operational/order-details/<detail_id>/revision`
- `GET, POST /operational/orders/<order_id>/hpp-snapshot/create`
- `GET /operational/orders/<order_id>/hpp-snapshot/<snapshot_id>`
- `GET /operational/orders/<order_id>/hpp-snapshot/<snapshot_id>/stock-dry-run`
- `POST /operational/orders/<order_id>/hpp-snapshot/<snapshot_id>/stock-commit`
- `GET /operational/orders/<order_id>/hpp-snapshot/<snapshot_id>/stock-consumption/<consumption_id>`

### 6.5 Production

- `GET /production/`
- `GET /production/<production_id>`
- `POST /production/<production_id>/realization`

### 6.6 Delivery

- `GET /delivery/`
- `GET /delivery/<delivery_id>`
- `POST /delivery/create-from-order/<order_id>/<delivery_type>`
- `POST /delivery/<delivery_id>/dispatch`
- `POST /delivery/<delivery_id>/sla`
- `GET, POST /delivery/details/<detail_id>/receive`
- `POST /delivery/details/<detail_id>/shortage-replacement`
- `POST /delivery/receipts/<receipt_id>/attachments/upload`
- `GET /delivery/attachments/<attachment_id>/view`
- `GET /delivery/attachments/<attachment_id>/download`
- `POST /delivery/attachments/<attachment_id>/delete`
- `GET /delivery/today`
- `GET /delivery/receiving`
- `GET /delivery/history`
- `POST /delivery/<delivery_id>/cancel`

### 6.7 Logistics

- `GET /logistics/`
- `GET /logistics/material-forecast`
- `GET, POST /logistics/stock-in`
- `GET, POST /logistics/stock-out`
- `GET, POST /logistics/adjustment`
- `GET /logistics/items/<item_id>/card`
- `GET /logistics/purchases`
- `GET, POST /logistics/purchases/create`
- `GET /logistics/purchases/<procurement_id>`
- `POST /logistics/purchases/<procurement_id>/attachments/upload`
- `GET /logistics/purchases/attachments/<attachment_id>/view`
- `GET /logistics/purchases/attachments/<attachment_id>/download`
- `POST /logistics/purchases/attachments/<attachment_id>/delete`
- `GET /logistics/damaged`
- `GET, POST /logistics/damaged/create`
- `GET /logistics/audit`
- `GET, POST /logistics/audit/create`
- `GET /logistics/item-requests`
- `GET, POST /logistics/item-requests/create`
- `GET /logistics/item-requests/<request_id>`
- `POST /logistics/item-requests/<request_id>/approve`
- `POST /logistics/item-requests/<request_id>/reject`
- `POST /logistics/item-requests/<request_id>/fulfill`
- `GET /logistics/kitchen-usage`

### 6.8 Costing / HPP

- `GET /costing/order-hpp-snapshots`
- `GET /costing/menus`
- `GET, POST /costing/menus/create`
- `GET, POST /costing/menus/<menu_id>/edit`
- `POST /costing/menus/<menu_id>/toggle`
- `GET, POST /costing/menus/<menu_id>/recipe`
- `POST /costing/recipe-items/<recipe_item_id>/delete`
- `GET /costing/packaging-profiles`
- `GET, POST /costing/packaging-profiles/create`
- `GET, POST /costing/packaging-profiles/<profile_id>/edit`
- `POST /costing/packaging-profiles/<profile_id>/toggle`
- `GET /costing/overhead-profiles`
- `GET, POST /costing/overhead-profiles/create`
- `GET, POST /costing/overhead-profiles/<profile_id>/edit`
- `POST /costing/overhead-profiles/<profile_id>/toggle`
- `GET /costing/hpp-calculator`

### 6.9 Finance

Finance adalah modul route terbesar, dengan 84 endpoint. Cakupannya bukan hanya invoice, tetapi juga export, print, payment, receivable, cash/bank, supplier bill, manual billing, panjar, biaya, aset, depresiasi, dan cicilan.

- `GET /finance/`
- `GET /finance/invoices`
- `GET /finance/invoices/export.csv`
- `GET /finance/payment-history/export.csv`
- `GET /finance/cash-bank-ledger/export.csv`
- `GET /finance/receivables/export.csv`
- `GET /finance/supplier-bills/export.csv`
- `GET /finance/receivables/statement/export.csv`
- `GET /finance/accounts-payable-aging/export.csv`
- `GET /finance/supplier-payable-card/export.csv`
- `GET /finance/invoice-profit-report/export.csv`
- `GET /finance/cash-bank-ledger/print`
- `GET /finance/accounts-payable-aging/print`
- `GET /finance/supplier-payable-card/print`
- `GET /finance/invoice-profit-report/print`
- `GET /finance/invoices/<invoice_id>`
- `GET /finance/invoices/generate-order`
- `POST /finance/invoices/generate-order/<order_id>/<mandor_id>`
- `GET /finance/invoice-profit-report`
- `GET /finance/invoices/<invoice_id>/profit-report`
- `GET, POST /finance/invoices/generate-period`
- `POST /finance/invoices/generate-period/save`
- `POST /finance/invoices/<invoice_id>/payments/create`
- `GET /finance/invoices/<invoice_id>/print`
- `POST /finance/invoices/<invoice_id>/collection/create`
- `GET /finance/invoices/<invoice_id>/whatsapp/send`
- `GET /finance/receivables`
- `GET /finance/receivables/print`
- `GET /finance/receivables/statement`
- `GET /finance/receivables/statement/send`
- `GET /finance/payments/<payment_id>/receipt`
- `POST /finance/payments/<payment_id>/attachments/upload`
- `GET /finance/payments/attachments/<attachment_id>/view`
- `GET /finance/payments/attachments/<attachment_id>/download`
- `POST /finance/payments/attachments/<attachment_id>/delete`
- `GET /finance/payment-history`
- `GET /finance/cash-bank-ledger`
- `GET /finance/cash-bank-ledger/<transaction_id>`
- `GET, POST /finance/cash-bank-opening-balances`
- `GET, POST /finance/cash-bank-transfers`
- `GET, POST /finance/cash-bank-adjustments`
- `POST /finance/cash-bank-ledger/<transaction_id>/reconcile`
- `POST /finance/cash-bank-ledger/<transaction_id>/unreconcile`
- `GET /finance/accounts-payable-aging`
- `GET /finance/supplier-payable-card`
- `GET /finance/supplier-bills`
- `GET /finance/supplier-bills/<bill_id>`
- `POST /finance/supplier-bills/<bill_id>/payments/create`
- `POST /finance/supplier-payments/<payment_id>/attachments/upload`
- `GET /finance/supplier-payments/attachments/<attachment_id>/view`
- `GET /finance/supplier-payments/attachments/<attachment_id>/download`
- `POST /finance/supplier-payments/attachments/<attachment_id>/delete`
- `GET, POST /finance/transactions`
- `GET, POST /finance/manual-billing`
- `GET /finance/manual-billing/batches`
- `GET, POST /finance/manual-billing/input-buku`
- `GET, POST /finance/manual-billing/batches/<batch_id>/edit`
- `GET /finance/manual-billing/batches/<batch_id>`
- `GET /finance/manual-billing/batches/<batch_id>/print`
- `POST /finance/manual-billing/batches/<batch_id>/lock`
- `POST /finance/manual-billing/batches/<batch_id>/void`
- `POST /finance/manual-billing/batches/<batch_id>/create-invoice`
- `POST /finance/manual-billing/create`
- `GET /finance/advances`
- `GET, POST /finance/advances/create`
- `GET /finance/advances/<advance_id>`
- `POST /finance/advances/<advance_id>/settle`
- `GET /finance/transport-expenses`
- `GET, POST /finance/transport-expenses/create`
- `GET /finance/transport-expenses/<expense_id>`
- `GET /finance/operational-expenses`
- `GET, POST /finance/operational-expenses/create`
- `GET /finance/operational-expenses/<expense_id>`
- `GET /finance/fixed-asset-depreciation`
- `GET, POST /finance/fixed-asset-depreciation/<asset_id>/configure`
- `POST /finance/fixed-asset-depreciation/<asset_id>/post`
- `GET /finance/fixed-asset-purchases`
- `GET, POST /finance/fixed-asset-purchases/create`
- `GET /finance/fixed-asset-purchases/<purchase_id>`
- `GET /finance/fixed-asset-installments`
- `GET, POST /finance/fixed-asset-installments/create`
- `GET /finance/fixed-asset-installments/<contract_id>`
- `POST /finance/fixed-asset-installments/<contract_id>/pay/<schedule_id>`
- `POST /finance/invoices/<invoice_id>/official-identity/refresh`

### 6.10 Accounting

- `GET /accounting/`
- `GET /accounting/data-health`
- `GET /accounting/data-health/export.csv`
- `GET /accounting/daily-closing`
- `GET /accounting/daily-closing/export.csv`
- `GET /accounting/expense-drilldown`
- `GET /accounting/posting-status`
- `GET /accounting/order-to-cash-trace`
- `GET /accounting/order-to-cash-trace/export.csv`
- `GET /accounting/data-health/print`
- `GET /accounting/daily-closing/print`
- `GET /accounting/order-to-cash-trace/print`
- `GET /accounting/journals`
- `GET /accounting/journals/<journal_id>`
- `GET /accounting/journals/export.csv`
- `GET /accounting/journal-details/export.csv`
- `GET /accounting/journals/print`
- `GET /accounting/journals/<journal_id>/print`
- `POST /accounting/journals/generate-period-invoice`
- `POST /accounting/journals/generate-payment`
- `GET /accounting/reports`
- `GET /accounting/reports/trial-balance/export.csv`
- `GET /accounting/reports/general-ledger/export.csv`
- `GET /accounting/reports/income-summary/export.csv`
- `GET /accounting/reports/trial-balance/print`
- `GET /accounting/reports/general-ledger/print`
- `GET /accounting/reports/income-summary/print`
- `GET /accounting/coa-mapping`
- `POST /accounting/journals/generate-procurement`
- `GET, POST /accounting/opening-balance`
- `POST /accounting/journals/generate-hpp-production`
- `POST /accounting/journals/generate-warung-payment-correction`
- `GET /accounting/period-closing`
- `POST /accounting/period-closing/post`
- `GET /accounting/period-closing/<closing_id>`

### 6.11 Field Transactions

- `GET /field-transactions/`
- `GET /field-transactions/monitoring`
- `GET, POST /field-transactions/create`
- `GET, POST /field-transactions/<transaction_id>/edit`
- `GET /field-transactions/<transaction_id>`
- `POST /field-transactions/<transaction_id>/attachments/link`
- `POST /field-transactions/attachments/<attachment_id>/verify`
- `GET /field-transactions/attachments/<attachment_id>/download`
- `GET /field-transactions/attachments/<attachment_id>/view`
- `POST /field-transactions/<transaction_id>/review-status`
- `POST /field-transactions/<transaction_id>/post`
- `POST /field-transactions/<transaction_id>/manual-receivable/create`
- `POST /field-transactions/<transaction_id>/manual-payable/create`
- `POST /field-transactions/manual-receivables/<receivable_id>/payments/create`
- `POST /field-transactions/manual-payables/<payable_id>/payments/create`
- `POST /field-transactions/<transaction_id>/bridge/operational-expense`
- `POST /field-transactions/<transaction_id>/bridge/transport-expense`
- `POST /field-transactions/<transaction_id>/bridge/advance`

### 6.12 Canteen / Warung

- `GET /canteen/`
- `GET, POST /canteen/quick`
- `GET, POST /canteen/sales/create`
- `GET /canteen/debts`
- `GET, POST /canteen/debts/<debt_id>/payment`
- `GET, POST /canteen/external-receivables/<receivable_id>/payment`

### 6.13 HR

- `GET /hr/`
- `GET /hr/employees`
- `GET, POST /hr/employees/create`
- `GET, POST /hr/employees/<employee_id>/edit`
- `POST /hr/employees/<employee_id>/toggle`
- `GET /hr/payrolls`
- `GET, POST /hr/payrolls/generate`
- `GET /hr/payrolls/<payroll_id>`
- `POST /hr/payrolls/<payroll_id>/details/<detail_id>/update`
- `POST /hr/payrolls/<payroll_id>/finalize`
- `POST /hr/payrolls/<payroll_id>/post-journal`
- `POST /hr/payrolls/<payroll_id>/pay`
- `GET /hr/payroll-payment-history`

### 6.14 Settings

- `GET, POST /settings/company`
- `GET /settings/users`
- `GET, POST /settings/users/create`
- `GET, POST /settings/users/<user_id>/edit`
- `POST /settings/users/<user_id>/toggle`
- `GET, POST /settings/users/<user_id>/reset-password`
- `GET /settings/recovery-center`
- `GET /settings/system-health`
- `GET /settings/atomic-transaction-map`
- `GET /settings/atomic-smoke-simulation`
- `GET /settings/visual-sweep`
- `GET /settings/final-visual-qa`
- `GET /settings/backups`
- `POST /settings/backups/validate`
- `POST /settings/backups/create`
- `POST /settings/backups/create-full`
- `GET /settings/backups/download-confirm/<filename>`
- `POST /settings/backups/download/<filename>`
- `GET /settings/audit-logs`
- `GET /settings/audit-logs/<log_id>`
- `GET /settings/digital-attachments`
- `GET /settings/digital-attachments/<attachment_id>`
- `GET /settings/digital-attachments/<attachment_id>/download`
- `GET /settings/digital-attachments/<attachment_id>/view`
- `POST /settings/digital-attachments/<attachment_id>/delete`
- `GET /settings/reminders`
- `GET /settings/notifications`
- `POST /settings/notifications/generate`
- `POST /settings/notifications/<notification_id>/read`
- `POST /settings/notifications/<notification_id>/unread`
- `POST /settings/notifications/<notification_id>/dismiss`
- `GET, POST /settings/change-password`

### 6.15 SOP

- `GET /sop/`
- `GET /sop/disaster-recovery`
- `GET /sop/backup-restore`
- `GET /sop/<slug>`

### 6.16 Prediction / ML

- `GET /prediction/`
- `POST /prediction/train`
- `GET, POST /prediction/predict`
- `GET /prediction/evaluate`
- `POST /prediction/api/predict`

### 6.17 Health

- `GET /healthz`
- `GET /readiness`

## 7. Service Layer Penting

Sistem ini tidak hanya memakai route langsung ke database. Banyak proses inti dipisahkan ke service layer. Contoh kelompok service:

- Accounting: `accounting_service`, `accounting_export_service`, `accounting_print_service`, `accounting_posting_status_service`, `accounting_expense_drilldown_service`.
- Finance: `invoice_service`, `manual_billing_service`, `manual_backfill_billing_service`, `finance_receivables_service`, `finance_export_service`, `finance_print_service`, `invoice_profit_service`, `billing_trace_service`, `billing_input_source_service`.
- Kas/bank dan closing: `cash_bank_service`, `daily_cash_service`, `daily_closing_service`, `period_closing_service`.
- HPP dan stok: `hpp_service`, `hpp_stock_consumption_service`, `order_hpp_snapshot_service`, `stock_service`, `material_forecast_service`.
- Operasional/produksi/delivery: `operational_service`, `production_service`, `delivery_service`, `delivery_sla_service`.
- Field transaction: `field_transaction_service`, `field_transaction_policy_service`, `field_transaction_posting_service`, `field_transaction_bridge_service`, `field_transaction_settlement_service`, `field_transaction_monitoring_service`.
- System control: `audit_log_service`, `backup_service`, `database_backup_strategy_service`, `recovery_center_service`, `system_health_service`, `sensitive_action_guard_service`, `atomic_transaction_service`, `digital_attachment_service`.
- Dashboard dan analytics: `dashboard_service`, `dashboard_analytics_service`, `dashboard_command_center_service`.
- HR dan canteen: `hr_service`, `canteen_service`.

## 8. Guard dan Kontrol Internal

Beberapa kontrol penting yang sudah ada di sistem:

- Pemisahan sumber invoice `REALTIME` dan `MANUAL_BACKFILL`.
- Unique constraint invoice berdasarkan source untuk mencegah invoice dobel.
- Unique constraint jurnal berdasarkan `reference_type` dan `reference_id`.
- Validasi pembayaran tidak boleh melebihi sisa tagihan.
- Validasi tanggal pembayaran tidak boleh lebih awal dari tanggal invoice.
- Validasi stok keluar tidak boleh melebihi stok tersedia.
- Audit log untuk aksi penting.
- Sensitive action guard untuk aksi sensitif.
- Digital attachment untuk bukti transaksi.
- Backup, restore, recovery center, dan SOP disaster recovery.
- Data health dan daily closing untuk mendeteksi ketidaksesuaian data.

## 9. Kesimpulan Kompleksitas

Sistem ERP PT Idha Boga Pangan Mandiri ini sudah kompleks karena mencakup banyak siklus bisnis yang saling terhubung:

1. Siklus operasional catering: order, revisi, produksi, delivery, penerimaan.
2. Siklus logistik: pembelian, stok, request dapur, audit, damaged item.
3. Siklus costing: resep, konversi satuan, packaging, overhead, HPP, margin.
4. Siklus finance: invoice, payment, piutang, hutang, cash/bank, manual billing, aset, biaya.
5. Siklus accounting: jurnal, ledger, laporan, posting status, closing.
6. Siklus transaksi lapangan: pencatatan, bukti, review, posting, settlement, bridge.
7. Siklus warung: penjualan, hutang pekerja, pembayaran, piutang eksternal.
8. Siklus HR: employee, payroll, payment, jurnal payroll.
9. Siklus administrasi sistem: user, audit, backup, recovery, notification, SOP.

Dengan 331 endpoint, 207 template, 99 model/class, 76 service, dan 39 migration, sistem ini sudah layak dijelaskan sebagai ERP internal yang luas dan bertahap, bukan aplikasi CRUD sederhana. Kompleksitas terbesarnya berada pada integrasi finance-accounting, pemisahan realtime dan manual backfill, HPP/stok, serta traceability dari transaksi operasional sampai jurnal dan kas/bank.
