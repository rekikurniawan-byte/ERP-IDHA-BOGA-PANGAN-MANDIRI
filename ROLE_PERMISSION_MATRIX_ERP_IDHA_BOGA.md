# Role Permission Matrix ERP Idha Boga

Laporan ini dihasilkan otomatis dari decorator route agar matrix tidak terpisah dari kode.

## Ringkasan

| Metrik | Nilai |
| --- | --- |
| Total route | 338 |
| Role guarded | 323 |
| Login only | 12 |
| Public | 3 |

## Per Role

| Role | Route Count | File |
| --- | --- | --- |
| ACCOUNTING | 72 | app/routes/accounting/audit_routes.py, app/routes/accounting/closing_routes.py, app/routes/accounting/journal_routes.py, app/routes/accounting/posting_routes.py, app/routes/accounting/report_routes.py, app/routes/dashboard_routes.py, app/routes/field_transaction_routes.py, app/routes/finance/advance_expense_asset_routes.py, app/routes/finance/cash_bank_routes.py, app/routes/finance/manual_billing_routes.py, app/routes/settings/account_routes.py, app/routes/settings/notification_routes.py |
| ADMIN | 205 | app/routes/canteen_routes.py, app/routes/costing/calculator_routes.py, app/routes/costing/menu_routes.py, app/routes/costing/profile_routes.py, app/routes/costing/snapshot_routes.py, app/routes/dashboard_routes.py, app/routes/delivery_routes.py, app/routes/field_transaction_routes.py, app/routes/finance/advance_expense_asset_routes.py, app/routes/finance/cash_bank_routes.py, app/routes/finance/daily_cash_routes.py, app/routes/finance/export_print_routes.py, app/routes/finance/hub_routes.py, app/routes/finance/identity_routes.py, app/routes/finance/invoice_communication_routes.py, app/routes/finance/invoice_detail_routes.py, app/routes/finance/invoice_index_routes.py, app/routes/finance/invoice_print_routes.py, app/routes/finance/manual_billing_routes.py, app/routes/finance/payables_routes.py, app/routes/finance/payment_routes.py, app/routes/finance/period_invoice_routes.py, app/routes/finance/realtime_invoice_routes.py, app/routes/finance/receivables_routes.py, app/routes/hr_routes.py, app/routes/master/client_routes.py, app/routes/master/item_routes.py, app/routes/master/people_location_routes.py, app/routes/operational_routes.py, app/routes/production_routes.py, app/routes/settings/account_routes.py, app/routes/settings/approval_routes.py, app/routes/settings/notification_routes.py, app/routes/settings/recovery_health_routes.py |
| DAPUR | 15 | app/routes/dashboard_routes.py, app/routes/logistics/item_request_routes.py, app/routes/logistics/stock_routes.py, app/routes/production_routes.py, app/routes/settings/account_routes.py, app/routes/settings/notification_routes.py |
| FINANCE | 123 | app/routes/accounting/journal_routes.py, app/routes/dashboard_routes.py, app/routes/field_transaction_routes.py, app/routes/finance/advance_expense_asset_routes.py, app/routes/finance/cash_bank_routes.py, app/routes/finance/daily_cash_routes.py, app/routes/finance/export_print_routes.py, app/routes/finance/hub_routes.py, app/routes/finance/identity_routes.py, app/routes/finance/invoice_communication_routes.py, app/routes/finance/invoice_detail_routes.py, app/routes/finance/invoice_index_routes.py, app/routes/finance/invoice_print_routes.py, app/routes/finance/manual_billing_routes.py, app/routes/finance/payables_routes.py, app/routes/finance/payment_routes.py, app/routes/finance/period_invoice_routes.py, app/routes/finance/realtime_invoice_routes.py, app/routes/finance/receivables_routes.py, app/routes/master/client_routes.py, app/routes/master/supplier_bank_asset_routes.py, app/routes/operational_routes.py, app/routes/settings/account_routes.py, app/routes/settings/notification_routes.py |
| HR | 20 | app/routes/dashboard_routes.py, app/routes/hr_routes.py, app/routes/settings/account_routes.py, app/routes/settings/notification_routes.py |
| LOGISTICS | 45 | app/routes/dashboard_routes.py, app/routes/logistics/item_request_routes.py, app/routes/logistics/procurement_routes.py, app/routes/logistics/stock_audit_routes.py, app/routes/logistics/stock_routes.py, app/routes/master/client_routes.py, app/routes/master/item_routes.py, app/routes/master/supplier_bank_asset_routes.py, app/routes/settings/account_routes.py, app/routes/settings/notification_routes.py |
| OWNER | 200 | app/routes/accounting/audit_routes.py, app/routes/accounting/closing_routes.py, app/routes/accounting/journal_routes.py, app/routes/accounting/posting_routes.py, app/routes/accounting/report_routes.py, app/routes/dashboard_routes.py, app/routes/finance/advance_expense_asset_routes.py, app/routes/finance/cash_bank_routes.py, app/routes/finance/daily_cash_routes.py, app/routes/finance/export_print_routes.py, app/routes/finance/hub_routes.py, app/routes/finance/identity_routes.py, app/routes/finance/invoice_communication_routes.py, app/routes/finance/invoice_detail_routes.py, app/routes/finance/invoice_index_routes.py, app/routes/finance/invoice_print_routes.py, app/routes/finance/manual_billing_routes.py, app/routes/finance/payables_routes.py, app/routes/finance/payment_routes.py, app/routes/finance/period_invoice_routes.py, app/routes/finance/realtime_invoice_routes.py, app/routes/finance/receivables_routes.py, app/routes/logistics/item_request_routes.py, app/routes/logistics/procurement_routes.py, app/routes/logistics/stock_audit_routes.py, app/routes/logistics/stock_routes.py, app/routes/master/client_routes.py, app/routes/master/supplier_bank_asset_routes.py, app/routes/settings/account_routes.py, app/routes/settings/approval_routes.py, app/routes/settings/audit_attachment_routes.py, app/routes/settings/backup_routes.py, app/routes/settings/notification_routes.py, app/routes/settings/recovery_health_routes.py |
| PENGANTAR | 20 | app/routes/dashboard_routes.py, app/routes/delivery_routes.py, app/routes/settings/account_routes.py, app/routes/settings/notification_routes.py |

## Detail Route

| File | Line | Methods | Path | Auth | Roles |
| --- | --- | --- | --- | --- | --- |
| app/routes/accounting/audit_routes.py | 11 | GET | / | role_required | OWNER, ACCOUNTING |
| app/routes/accounting/audit_routes.py | 18 | GET | /data-health | role_required | OWNER, ACCOUNTING |
| app/routes/accounting/audit_routes.py | 26 | GET | /data-health/export.csv | role_required | OWNER, ACCOUNTING |
| app/routes/accounting/audit_routes.py | 36 | GET | /daily-closing | role_required | OWNER, ACCOUNTING |
| app/routes/accounting/audit_routes.py | 45 | GET | /daily-closing/export.csv | role_required | OWNER, ACCOUNTING |
| app/routes/accounting/audit_routes.py | 57 | GET | /expense-drilldown | role_required | OWNER, ACCOUNTING |
| app/routes/accounting/audit_routes.py | 82 | GET | /posting-status | role_required | OWNER, ACCOUNTING |
| app/routes/accounting/audit_routes.py | 120 | GET | /order-to-cash-trace | role_required | OWNER, ACCOUNTING |
| app/routes/accounting/audit_routes.py | 129 | GET | /order-to-cash-trace/export.csv | role_required | OWNER, ACCOUNTING |
| app/routes/accounting/audit_routes.py | 143 | GET | /data-health/print | role_required | OWNER, ACCOUNTING |
| app/routes/accounting/audit_routes.py | 154 | GET | /daily-closing/print | role_required | OWNER, ACCOUNTING |
| app/routes/accounting/audit_routes.py | 166 | GET | /order-to-cash-trace/print | role_required | OWNER, ACCOUNTING |
| app/routes/accounting/closing_routes.py | 429 | GET | /period-closing | role_required | OWNER, ACCOUNTING |
| app/routes/accounting/closing_routes.py | 455 | POST | /period-closing/post | role_required | OWNER, ACCOUNTING |
| app/routes/accounting/closing_routes.py | 505 | GET | /period-closing/<int:closing_id> | role_required | OWNER, ACCOUNTING |
| app/routes/accounting/journal_routes.py | 22 | GET | /journals | role_required | OWNER, ACCOUNTING |
| app/routes/accounting/journal_routes.py | 64 | GET | /journals/<int:journal_id> | role_required | OWNER, ACCOUNTING, FINANCE |
| app/routes/accounting/journal_routes.py | 92 | GET | /journals/export.csv | role_required | OWNER, ACCOUNTING |
| app/routes/accounting/journal_routes.py | 101 | GET | /journal-details/export.csv | role_required | OWNER, ACCOUNTING |
| app/routes/accounting/journal_routes.py | 120 | GET | /journals/print | role_required | OWNER, ACCOUNTING |
| app/routes/accounting/journal_routes.py | 130 | GET | /journals/<int:journal_id>/print | role_required | OWNER, ACCOUNTING, FINANCE |
| app/routes/accounting/journal_routes.py | 188 | POST | /journals/generate-period-invoice | role_required | OWNER, ACCOUNTING |
| app/routes/accounting/journal_routes.py | 254 | POST | /journals/generate-payment | role_required | OWNER, ACCOUNTING |
| app/routes/accounting/posting_routes.py | 280 | GET,POST | /opening-balance | role_required | OWNER, ACCOUNTING |
| app/routes/accounting/posting_routes.py | 533 | POST | /journals/generate-hpp-production | role_required | OWNER, ACCOUNTING |
| app/routes/accounting/posting_routes.py | 774 | POST | /journals/generate-warung-payment-correction | role_required | OWNER, ACCOUNTING |
| app/routes/accounting/report_routes.py | 178 | GET | /reports | role_required | OWNER, ACCOUNTING |
| app/routes/accounting/report_routes.py | 207 | GET | /reports/trial-balance/export.csv | role_required | OWNER, ACCOUNTING |
| app/routes/accounting/report_routes.py | 226 | GET | /reports/general-ledger/export.csv | role_required | OWNER, ACCOUNTING |
| app/routes/accounting/report_routes.py | 245 | GET | /reports/income-summary/export.csv | role_required | OWNER, ACCOUNTING |
| app/routes/accounting/report_routes.py | 264 | GET | /reports/trial-balance/print | role_required | OWNER, ACCOUNTING |
| app/routes/accounting/report_routes.py | 284 | GET | /reports/general-ledger/print | role_required | OWNER, ACCOUNTING |
| app/routes/accounting/report_routes.py | 304 | GET | /reports/income-summary/print | role_required | OWNER, ACCOUNTING |
| app/routes/accounting/report_routes.py | 650 | GET | /coa-mapping | role_required | OWNER, ACCOUNTING |
| app/routes/accounting/report_routes.py | 752 | POST | /journals/generate-procurement | role_required | OWNER, ACCOUNTING |
| app/routes/auth_routes.py | 16 | GET,POST | /login | public | - |
| app/routes/auth_routes.py | 65 | POST | /logout | login_required | - |
| app/routes/canteen_routes.py | 105 | GET | / | role_required | ADMIN |
| app/routes/canteen_routes.py | 181 | GET,POST | /quick | role_required | ADMIN |
| app/routes/canteen_routes.py | 272 | GET,POST | /sales/create | role_required | ADMIN |
| app/routes/canteen_routes.py | 338 | GET | /debts | role_required | ADMIN |
| app/routes/canteen_routes.py | 373 | GET,POST | /debts/<int:debt_id>/payment | role_required | ADMIN |
| app/routes/canteen_routes.py | 427 | GET,POST | /external-receivables/<int:receivable_id>/payment | role_required | ADMIN |
| app/routes/costing/calculator_routes.py | 10 | GET | /hpp-calculator | role_required | ADMIN |
| app/routes/costing/menu_routes.py | 10 | GET | /menus | role_required | ADMIN |
| app/routes/costing/menu_routes.py | 66 | GET,POST | /menus/create | role_required | ADMIN |
| app/routes/costing/menu_routes.py | 109 | GET,POST | /menus/<int:menu_id>/edit | role_required | ADMIN |
| app/routes/costing/menu_routes.py | 154 | POST | /menus/<int:menu_id>/toggle | role_required | ADMIN |
| app/routes/costing/menu_routes.py | 168 | GET,POST | /menus/<int:menu_id>/recipe | role_required | ADMIN |
| app/routes/costing/menu_routes.py | 326 | POST | /recipe-items/<int:recipe_item_id>/delete | role_required | ADMIN |
| app/routes/costing/profile_routes.py | 10 | GET | /packaging-profiles | role_required | ADMIN |
| app/routes/costing/profile_routes.py | 44 | GET,POST | /packaging-profiles/create | role_required | ADMIN |
| app/routes/costing/profile_routes.py | 81 | GET,POST | /packaging-profiles/<int:profile_id>/edit | role_required | ADMIN |
| app/routes/costing/profile_routes.py | 123 | POST | /packaging-profiles/<int:profile_id>/toggle | role_required | ADMIN |
| app/routes/costing/profile_routes.py | 137 | GET | /overhead-profiles | role_required | ADMIN |
| app/routes/costing/profile_routes.py | 171 | GET,POST | /overhead-profiles/create | role_required | ADMIN |
| app/routes/costing/profile_routes.py | 225 | GET,POST | /overhead-profiles/<int:profile_id>/edit | role_required | ADMIN |
| app/routes/costing/profile_routes.py | 284 | POST | /overhead-profiles/<int:profile_id>/toggle | role_required | ADMIN |
| app/routes/costing/snapshot_routes.py | 10 | GET | /order-hpp-snapshots | role_required | ADMIN |
| app/routes/dashboard_routes.py | 165 | GET | / | login_required | - |
| app/routes/dashboard_routes.py | 175 | GET | /dashboard/owner | role_required | OWNER |
| app/routes/dashboard_routes.py | 182 | GET | /dashboard/admin | role_required | ADMIN |
| app/routes/dashboard_routes.py | 191 | GET | /dashboard/revenue-explorer | role_required | ADMIN |
| app/routes/dashboard_routes.py | 237 | GET | /dashboard/dapur | role_required | DAPUR |
| app/routes/dashboard_routes.py | 244 | GET | /dashboard/pengantar | role_required | PENGANTAR |
| app/routes/dashboard_routes.py | 251 | GET | /dashboard/finance | role_required | FINANCE |
| app/routes/dashboard_routes.py | 257 | GET | /dashboard/accounting | role_required | ACCOUNTING |
| app/routes/dashboard_routes.py | 263 | GET | /dashboard/logistics | role_required | LOGISTICS |
| app/routes/dashboard_routes.py | 269 | GET | /dashboard/hr | role_required | HR |
| app/routes/dashboard_routes.py | 275 | GET | /module/<module_name> | login_required | - |
| app/routes/delivery_routes.py | 92 | GET | / | role_required | ADMIN, PENGANTAR |
| app/routes/delivery_routes.py | 109 | GET | /<int:delivery_id> | role_required | ADMIN, PENGANTAR |
| app/routes/delivery_routes.py | 147 | POST | /create-from-order/<int:order_id>/<delivery_type> | role_required | ADMIN, PENGANTAR |
| app/routes/delivery_routes.py | 172 | POST | /<int:delivery_id>/dispatch | role_required | ADMIN, PENGANTAR |
| app/routes/delivery_routes.py | 209 | POST | /<int:delivery_id>/sla | role_required | ADMIN |
| app/routes/delivery_routes.py | 261 | GET,POST | /details/<int:detail_id>/receive | role_required | ADMIN, PENGANTAR |
| app/routes/delivery_routes.py | 333 | POST | /details/<int:detail_id>/shortage-replacement | role_required | ADMIN, PENGANTAR |
| app/routes/delivery_routes.py | 357 | POST | /receipts/<int:receipt_id>/attachments/upload | role_required | ADMIN, PENGANTAR |
| app/routes/delivery_routes.py | 385 | GET | /attachments/<int:attachment_id>/view | role_required | ADMIN, PENGANTAR |
| app/routes/delivery_routes.py | 405 | GET | /attachments/<int:attachment_id>/download | role_required | ADMIN, PENGANTAR |
| app/routes/delivery_routes.py | 425 | POST | /attachments/<int:attachment_id>/delete | role_required | ADMIN |
| app/routes/delivery_routes.py | 437 | GET | /today | role_required | ADMIN, PENGANTAR |
| app/routes/delivery_routes.py | 474 | GET | /receiving | role_required | ADMIN, PENGANTAR |
| app/routes/delivery_routes.py | 515 | GET | /history | role_required | ADMIN, PENGANTAR |
| app/routes/delivery_routes.py | 589 | POST | /<int:delivery_id>/cancel | role_required | ADMIN, PENGANTAR |
| app/routes/field_transaction_routes.py | 345 | GET | / | role_required | ADMIN, FINANCE, ACCOUNTING |
| app/routes/field_transaction_routes.py | 386 | GET | /monitoring | role_required | ADMIN, FINANCE, ACCOUNTING |
| app/routes/field_transaction_routes.py | 397 | GET,POST | /create | role_required | ADMIN, FINANCE |
| app/routes/field_transaction_routes.py | 487 | GET,POST | /<int:transaction_id>/edit | role_required | ADMIN, FINANCE |
| app/routes/field_transaction_routes.py | 584 | GET | /<int:transaction_id> | role_required | ADMIN, FINANCE, ACCOUNTING |
| app/routes/field_transaction_routes.py | 663 | POST | /<int:transaction_id>/attachments/link | role_required | FINANCE, ACCOUNTING |
| app/routes/field_transaction_routes.py | 691 | POST | /attachments/<int:attachment_id>/verify | role_required | FINANCE, ACCOUNTING |
| app/routes/field_transaction_routes.py | 716 | GET | /attachments/<int:attachment_id>/download | role_required | ADMIN, FINANCE, ACCOUNTING |
| app/routes/field_transaction_routes.py | 756 | GET | /attachments/<int:attachment_id>/view | role_required | ADMIN, FINANCE, ACCOUNTING |
| app/routes/field_transaction_routes.py | 798 | POST | /<int:transaction_id>/review-status | role_required | FINANCE, ACCOUNTING |
| app/routes/field_transaction_routes.py | 824 | POST | /<int:transaction_id>/post | role_required | FINANCE, ACCOUNTING |
| app/routes/field_transaction_routes.py | 846 | POST | /<int:transaction_id>/manual-receivable/create | role_required | FINANCE, ACCOUNTING |
| app/routes/field_transaction_routes.py | 874 | POST | /<int:transaction_id>/manual-payable/create | role_required | FINANCE, ACCOUNTING |
| app/routes/field_transaction_routes.py | 902 | POST | /manual-receivables/<int:receivable_id>/payments/create | role_required | FINANCE, ACCOUNTING |
| app/routes/field_transaction_routes.py | 951 | POST | /manual-payables/<int:payable_id>/payments/create | role_required | FINANCE, ACCOUNTING |
| app/routes/field_transaction_routes.py | 988 | POST | /<int:transaction_id>/bridge/operational-expense | role_required | FINANCE, ACCOUNTING |
| app/routes/field_transaction_routes.py | 1021 | POST | /<int:transaction_id>/bridge/transport-expense | role_required | FINANCE, ACCOUNTING |
| app/routes/field_transaction_routes.py | 1056 | POST | /<int:transaction_id>/bridge/advance | role_required | FINANCE, ACCOUNTING |
| app/routes/finance/advance_expense_asset_routes.py | 10 | GET | /advances | role_required | OWNER, ADMIN, FINANCE, ACCOUNTING |
| app/routes/finance/advance_expense_asset_routes.py | 51 | GET,POST | /advances/create | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/advance_expense_asset_routes.py | 135 | GET | /advances/<int:advance_id> | role_required | OWNER, ADMIN, FINANCE, ACCOUNTING |
| app/routes/finance/advance_expense_asset_routes.py | 192 | POST | /advances/<int:advance_id>/settle | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/advance_expense_asset_routes.py | 255 | GET | /transport-expenses | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/advance_expense_asset_routes.py | 293 | GET,POST | /transport-expenses/create | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/advance_expense_asset_routes.py | 345 | GET | /transport-expenses/<int:expense_id> | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/advance_expense_asset_routes.py | 374 | GET | /operational-expenses | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/advance_expense_asset_routes.py | 410 | GET,POST | /operational-expenses/create | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/advance_expense_asset_routes.py | 457 | GET | /operational-expenses/<int:expense_id> | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/advance_expense_asset_routes.py | 487 | GET | /fixed-asset-depreciation | role_required | OWNER, ADMIN, FINANCE, ACCOUNTING |
| app/routes/finance/advance_expense_asset_routes.py | 512 | GET,POST | /fixed-asset-depreciation/<int:asset_id>/configure | role_required | OWNER, ADMIN, FINANCE, ACCOUNTING |
| app/routes/finance/advance_expense_asset_routes.py | 567 | POST | /fixed-asset-depreciation/<int:asset_id>/post | role_required | OWNER, ADMIN, FINANCE, ACCOUNTING |
| app/routes/finance/advance_expense_asset_routes.py | 592 | GET | /fixed-asset-purchases | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/advance_expense_asset_routes.py | 621 | GET,POST | /fixed-asset-purchases/create | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/advance_expense_asset_routes.py | 707 | GET | /fixed-asset-purchases/<int:purchase_id> | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/advance_expense_asset_routes.py | 727 | GET | /fixed-asset-installments | role_required | OWNER, ADMIN, FINANCE, ACCOUNTING |
| app/routes/finance/advance_expense_asset_routes.py | 758 | GET,POST | /fixed-asset-installments/create | role_required | OWNER, ADMIN, FINANCE, ACCOUNTING |
| app/routes/finance/advance_expense_asset_routes.py | 840 | GET | /fixed-asset-installments/<int:contract_id> | role_required | OWNER, ADMIN, FINANCE, ACCOUNTING |
| app/routes/finance/advance_expense_asset_routes.py | 866 | POST | /fixed-asset-installments/<int:contract_id>/pay/<int:schedule_id> | role_required | OWNER, ADMIN, FINANCE, ACCOUNTING |
| app/routes/finance/cash_bank_routes.py | 10 | GET | /cash-bank-ledger | role_required | OWNER, ADMIN, FINANCE, ACCOUNTING |
| app/routes/finance/cash_bank_routes.py | 427 | GET | /cash-bank-ledger/<int:transaction_id> | role_required | OWNER, ADMIN, FINANCE, ACCOUNTING |
| app/routes/finance/cash_bank_routes.py | 450 | GET,POST | /cash-bank-opening-balances | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/cash_bank_routes.py | 507 | GET,POST | /cash-bank-transfers | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/cash_bank_routes.py | 570 | GET,POST | /cash-bank-adjustments | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/cash_bank_routes.py | 631 | POST | /cash-bank-ledger/<int:transaction_id>/reconcile | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/cash_bank_routes.py | 663 | POST | /cash-bank-ledger/<int:transaction_id>/unreconcile | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/daily_cash_routes.py | 17 | GET,POST | /daily-cash | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/daily_cash_routes.py | 58 | GET | /daily-cash/<int:cash_id> | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/export_print_routes.py | 6 | GET | /invoices/export.csv | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/export_print_routes.py | 13 | GET | /payment-history/export.csv | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/export_print_routes.py | 20 | GET | /cash-bank-ledger/export.csv | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/export_print_routes.py | 28 | GET | /receivables/export.csv | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/export_print_routes.py | 39 | GET | /supplier-bills/export.csv | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/export_print_routes.py | 46 | GET | /receivables/statement/export.csv | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/export_print_routes.py | 53 | GET | /accounts-payable-aging/export.csv | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/export_print_routes.py | 60 | GET | /supplier-payable-card/export.csv | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/export_print_routes.py | 67 | GET | /invoice-profit-report/export.csv | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/export_print_routes.py | 75 | GET | /cash-bank-ledger/print | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/export_print_routes.py | 83 | GET | /accounts-payable-aging/print | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/export_print_routes.py | 91 | GET | /supplier-payable-card/print | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/export_print_routes.py | 99 | GET | /invoice-profit-report/print | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/hub_routes.py | 6 | GET | / | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/identity_routes.py | 6 | POST | /invoices/<int:invoice_id>/official-identity/refresh | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/invoice_communication_routes.py | 149 | POST | /invoices/<int:invoice_id>/collection/create | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/invoice_communication_routes.py | 243 | GET | /invoices/<int:invoice_id>/whatsapp/send | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/invoice_detail_routes.py | 7 | GET | /invoices/<int:invoice_id> | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/invoice_index_routes.py | 6 | GET | /invoices | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/invoice_print_routes.py | 258 | GET | /invoices/<int:invoice_id>/print | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/manual_billing_routes.py | 11 | GET,POST | /transactions | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/manual_billing_routes.py | 173 | GET,POST | /manual-billing | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/manual_billing_routes.py | 414 | GET | /manual-billing/batches | role_required | OWNER, ADMIN, FINANCE, ACCOUNTING |
| app/routes/finance/manual_billing_routes.py | 499 | GET,POST | /manual-billing/input-buku | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/manual_billing_routes.py | 607 | GET,POST | /manual-billing/batches/<int:batch_id>/edit | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/manual_billing_routes.py | 744 | GET | /manual-billing/batches/<int:batch_id> | role_required | OWNER, ADMIN, FINANCE, ACCOUNTING |
| app/routes/finance/manual_billing_routes.py | 809 | GET | /manual-billing/batches/<int:batch_id>/print | role_required | OWNER, ADMIN, FINANCE, ACCOUNTING |
| app/routes/finance/manual_billing_routes.py | 830 | POST | /manual-billing/batches/<int:batch_id>/lock | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/manual_billing_routes.py | 878 | POST | /manual-billing/batches/<int:batch_id>/void | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/manual_billing_routes.py | 927 | POST | /manual-billing/batches/<int:batch_id>/create-invoice | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/manual_billing_routes.py | 979 | POST | /manual-billing/create | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/payables_routes.py | 14 | GET | /accounts-payable-aging | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/payables_routes.py | 59 | GET | /supplier-payable-card | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/payables_routes.py | 109 | GET | /supplier-bills | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/payables_routes.py | 205 | GET | /supplier-bills/<int:bill_id> | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/payables_routes.py | 306 | POST | /supplier-bills/<int:bill_id>/payments/create | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/payables_routes.py | 516 | POST | /supplier-payments/<int:payment_id>/attachments/upload | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/payables_routes.py | 543 | GET | /supplier-payments/attachments/<int:attachment_id>/view | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/payables_routes.py | 563 | GET | /supplier-payments/attachments/<int:attachment_id>/download | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/payables_routes.py | 583 | POST | /supplier-payments/attachments/<int:attachment_id>/delete | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/payment_routes.py | 36 | POST | /invoices/<int:invoice_id>/payments/create | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/period_invoice_routes.py | 48 | GET | /invoice-profit-report | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/period_invoice_routes.py | 100 | GET | /invoices/<int:invoice_id>/profit-report | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/period_invoice_routes.py | 121 | GET,POST | /invoices/generate-period | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/period_invoice_routes.py | 540 | POST | /invoices/generate-period/save | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/realtime_invoice_routes.py | 155 | GET | /invoices/generate-order | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/realtime_invoice_routes.py | 237 | POST | /invoices/generate-order/<int:order_id>/<int:mandor_id> | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/receivables_routes.py | 18 | GET | /receivables | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/receivables_routes.py | 25 | GET | /receivables/print | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/receivables_routes.py | 32 | GET | /receivables/statement | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/receivables_routes.py | 354 | GET | /receivables/statement/send | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/receivables_routes.py | 586 | GET | /payments/<int:payment_id>/receipt | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/receivables_routes.py | 675 | POST | /payments/<int:payment_id>/attachments/upload | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/receivables_routes.py | 702 | GET | /payments/attachments/<int:attachment_id>/view | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/receivables_routes.py | 722 | GET | /payments/attachments/<int:attachment_id>/download | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/receivables_routes.py | 742 | POST | /payments/attachments/<int:attachment_id>/delete | role_required | OWNER, ADMIN, FINANCE |
| app/routes/finance/receivables_routes.py | 753 | GET | /payment-history | role_required | OWNER, ADMIN, FINANCE |
| app/routes/health_routes.py | 26 | GET | /healthz | public | - |
| app/routes/health_routes.py | 37 | GET | /readiness | public | - |
| app/routes/hr_routes.py | 209 | GET | / | role_required | ADMIN, HR |
| app/routes/hr_routes.py | 258 | GET | /employees | role_required | ADMIN, HR |
| app/routes/hr_routes.py | 295 | GET,POST | /employees/create | role_required | ADMIN, HR |
| app/routes/hr_routes.py | 327 | GET,POST | /employees/<int:employee_id>/edit | role_required | ADMIN, HR |
| app/routes/hr_routes.py | 381 | POST | /employees/<int:employee_id>/toggle | role_required | ADMIN, HR |
| app/routes/hr_routes.py | 391 | GET | /payrolls | role_required | ADMIN, HR |
| app/routes/hr_routes.py | 440 | GET,POST | /payrolls/generate | role_required | ADMIN, HR |
| app/routes/hr_routes.py | 495 | GET | /payrolls/<int:payroll_id> | role_required | ADMIN, HR |
| app/routes/hr_routes.py | 511 | POST | /payrolls/<int:payroll_id>/details/<int:detail_id>/update | role_required | ADMIN, HR |
| app/routes/hr_routes.py | 535 | POST | /payrolls/<int:payroll_id>/finalize | role_required | ADMIN, HR |
| app/routes/hr_routes.py | 569 | POST | /payrolls/<int:payroll_id>/post-journal | role_required | ADMIN, HR |
| app/routes/hr_routes.py | 604 | POST | /payrolls/<int:payroll_id>/pay | role_required | ADMIN, HR |
| app/routes/hr_routes.py | 640 | GET | /payroll-payment-history | role_required | ADMIN, HR |
| app/routes/logistics/item_request_routes.py | 10 | GET | /item-requests | role_required | OWNER, LOGISTICS, DAPUR |
| app/routes/logistics/item_request_routes.py | 43 | GET,POST | /item-requests/create | role_required | DAPUR |
| app/routes/logistics/item_request_routes.py | 152 | GET | /item-requests/<int:request_id> | role_required | OWNER, LOGISTICS, DAPUR |
| app/routes/logistics/item_request_routes.py | 179 | POST | /item-requests/<int:request_id>/approve | role_required | OWNER, LOGISTICS |
| app/routes/logistics/item_request_routes.py | 212 | POST | /item-requests/<int:request_id>/reject | role_required | OWNER, LOGISTICS |
| app/routes/logistics/item_request_routes.py | 251 | POST | /item-requests/<int:request_id>/fulfill | role_required | OWNER, LOGISTICS |
| app/routes/logistics/item_request_routes.py | 349 | GET | /kitchen-usage | role_required | OWNER, LOGISTICS, DAPUR |
| app/routes/logistics/procurement_routes.py | 11 | GET | /purchases | role_required | OWNER, LOGISTICS |
| app/routes/logistics/procurement_routes.py | 84 | GET,POST | /purchases/create | role_required | OWNER, LOGISTICS |
| app/routes/logistics/procurement_routes.py | 446 | GET | /purchases/<int:procurement_id> | role_required | OWNER, LOGISTICS |
| app/routes/logistics/procurement_routes.py | 497 | POST | /purchases/<int:procurement_id>/attachments/upload | role_required | OWNER, LOGISTICS |
| app/routes/logistics/procurement_routes.py | 524 | GET | /purchases/attachments/<int:attachment_id>/view | role_required | OWNER, LOGISTICS |
| app/routes/logistics/procurement_routes.py | 544 | GET | /purchases/attachments/<int:attachment_id>/download | role_required | OWNER, LOGISTICS |
| app/routes/logistics/procurement_routes.py | 564 | POST | /purchases/attachments/<int:attachment_id>/delete | role_required | OWNER, LOGISTICS |
| app/routes/logistics/stock_audit_routes.py | 10 | GET | /damaged | role_required | OWNER, LOGISTICS |
| app/routes/logistics/stock_audit_routes.py | 35 | GET,POST | /damaged/create | role_required | OWNER, LOGISTICS |
| app/routes/logistics/stock_audit_routes.py | 106 | GET | /audit | role_required | OWNER, LOGISTICS |
| app/routes/logistics/stock_audit_routes.py | 132 | GET,POST | /audit/create | role_required | OWNER, LOGISTICS |
| app/routes/logistics/stock_routes.py | 10 | GET | / | role_required | OWNER, LOGISTICS |
| app/routes/logistics/stock_routes.py | 23 | GET | /material-forecast | role_required | OWNER, LOGISTICS, DAPUR |
| app/routes/logistics/stock_routes.py | 62 | GET,POST | /stock-in | role_required | OWNER, LOGISTICS |
| app/routes/logistics/stock_routes.py | 119 | GET,POST | /stock-out | role_required | OWNER, LOGISTICS |
| app/routes/logistics/stock_routes.py | 180 | GET,POST | /adjustment | role_required | OWNER, LOGISTICS |
| app/routes/logistics/stock_routes.py | 230 | GET,POST | /opening-balances | role_required | OWNER, LOGISTICS |
| app/routes/logistics/stock_routes.py | 325 | GET | /items/<int:item_id>/card | role_required | OWNER, LOGISTICS |
| app/routes/master/client_routes.py | 10 | GET | / | role_required | ADMIN, LOGISTICS |
| app/routes/master/client_routes.py | 66 | GET | /clients | role_required | OWNER, FINANCE |
| app/routes/master/client_routes.py | 104 | GET,POST | /clients/create | role_required | OWNER, FINANCE |
| app/routes/master/client_routes.py | 141 | GET,POST | /clients/<int:client_id>/edit | role_required | OWNER, FINANCE |
| app/routes/master/client_routes.py | 184 | POST | /clients/<int:client_id>/toggle | role_required | OWNER, FINANCE |
| app/routes/master/client_routes.py | 202 | POST | /clients/<int:client_id>/pics/create | role_required | OWNER |
| app/routes/master/client_routes.py | 233 | POST | /clients/<int:client_id>/pics/<int:pic_id>/toggle | role_required | OWNER |
| app/routes/master/item_routes.py | 10 | GET | /items | role_required | ADMIN, LOGISTICS |
| app/routes/master/item_routes.py | 48 | GET,POST | /items/create | role_required | ADMIN, LOGISTICS |
| app/routes/master/item_routes.py | 95 | GET,POST | /items/<int:item_id>/edit | role_required | ADMIN, LOGISTICS |
| app/routes/master/item_routes.py | 151 | POST | /items/<int:item_id>/toggle | role_required | ADMIN, LOGISTICS |
| app/routes/master/item_routes.py | 170 | POST | /items/<int:item_id>/delete | role_required | ADMIN, LOGISTICS |
| app/routes/master/item_routes.py | 212 | GET | /item-cost-profiles | role_required | ADMIN, LOGISTICS |
| app/routes/master/item_routes.py | 269 | GET,POST | /items/<int:item_id>/cost-profile | role_required | ADMIN, LOGISTICS |
| app/routes/master/item_routes.py | 361 | GET,POST | /unit-conversions | role_required | ADMIN, LOGISTICS |
| app/routes/master/item_routes.py | 445 | POST | /unit-conversions/<int:conversion_id>/toggle | role_required | ADMIN, LOGISTICS |
| app/routes/master/people_location_routes.py | 10 | GET | /mandors | role_required | ADMIN |
| app/routes/master/people_location_routes.py | 41 | GET,POST | /mandors/create | role_required | ADMIN |
| app/routes/master/people_location_routes.py | 73 | GET,POST | /mandors/<int:mandor_id>/edit | role_required | ADMIN |
| app/routes/master/people_location_routes.py | 112 | POST | /mandors/<int:mandor_id>/toggle | role_required | ADMIN |
| app/routes/master/people_location_routes.py | 131 | GET | /locations | role_required | ADMIN |
| app/routes/master/people_location_routes.py | 165 | GET,POST | /locations/create | role_required | ADMIN |
| app/routes/master/people_location_routes.py | 200 | GET,POST | /locations/<int:location_id>/edit | role_required | ADMIN |
| app/routes/master/people_location_routes.py | 242 | POST | /locations/<int:location_id>/toggle | role_required | ADMIN |
| app/routes/master/people_location_routes.py | 261 | GET | /workers | role_required | ADMIN |
| app/routes/master/people_location_routes.py | 295 | GET,POST | /workers/create | role_required | ADMIN |
| app/routes/master/people_location_routes.py | 334 | GET,POST | /workers/<int:worker_id>/edit | role_required | ADMIN |
| app/routes/master/people_location_routes.py | 380 | POST | /workers/<int:worker_id>/toggle | role_required | ADMIN |
| app/routes/master/people_location_routes.py | 394 | POST | /workers/<int:worker_id>/delete | role_required | ADMIN |
| app/routes/master/people_location_routes.py | 416 | GET | /drivers | role_required | ADMIN |
| app/routes/master/people_location_routes.py | 448 | GET,POST | /drivers/create | role_required | ADMIN |
| app/routes/master/people_location_routes.py | 476 | GET,POST | /drivers/<int:driver_id>/edit | role_required | ADMIN |
| app/routes/master/people_location_routes.py | 509 | POST | /drivers/<int:driver_id>/toggle | role_required | ADMIN |
| app/routes/master/supplier_bank_asset_routes.py | 10 | GET | /suppliers | role_required | OWNER, LOGISTICS |
| app/routes/master/supplier_bank_asset_routes.py | 50 | GET,POST | /suppliers/create | role_required | OWNER, LOGISTICS |
| app/routes/master/supplier_bank_asset_routes.py | 118 | GET,POST | /suppliers/<int:supplier_id>/edit | role_required | OWNER, LOGISTICS |
| app/routes/master/supplier_bank_asset_routes.py | 191 | POST | /suppliers/<int:supplier_id>/toggle | role_required | OWNER, LOGISTICS |
| app/routes/master/supplier_bank_asset_routes.py | 219 | GET | /bank-accounts | role_required | OWNER, FINANCE |
| app/routes/master/supplier_bank_asset_routes.py | 251 | GET,POST | /bank-accounts/create | role_required | OWNER, FINANCE |
| app/routes/master/supplier_bank_asset_routes.py | 292 | GET,POST | /bank-accounts/<int:account_id>/edit | role_required | OWNER, FINANCE |
| app/routes/master/supplier_bank_asset_routes.py | 347 | POST | /bank-accounts/<int:account_id>/toggle | role_required | OWNER, FINANCE |
| app/routes/master/supplier_bank_asset_routes.py | 376 | GET | /fixed-assets | role_required | OWNER |
| app/routes/master/supplier_bank_asset_routes.py | 413 | GET,POST | /fixed-assets/create | role_required | OWNER |
| app/routes/master/supplier_bank_asset_routes.py | 463 | GET,POST | /fixed-assets/<int:asset_id>/edit | role_required | OWNER |
| app/routes/master/supplier_bank_asset_routes.py | 519 | POST | /fixed-assets/<int:asset_id>/toggle | role_required | OWNER |
| app/routes/operational_routes.py | 119 | GET | /daily-log | role_required | ADMIN, FINANCE |
| app/routes/operational_routes.py | 143 | GET | /monthly-recap | role_required | ADMIN, FINANCE |
| app/routes/operational_routes.py | 229 | GET | /orders | role_required | ADMIN |
| app/routes/operational_routes.py | 239 | GET,POST | /orders/create | role_required | ADMIN |
| app/routes/operational_routes.py | 302 | GET,POST | /orders/<int:order_id>/add-detail | role_required | ADMIN |
| app/routes/operational_routes.py | 351 | GET,POST | /orders/<int:order_id>/add-increase-after-lock | role_required | ADMIN |
| app/routes/operational_routes.py | 413 | GET | /orders/<int:order_id> | role_required | ADMIN |
| app/routes/operational_routes.py | 463 | GET,POST | /orders/<int:order_id>/hpp-defaults | role_required | ADMIN |
| app/routes/operational_routes.py | 497 | POST | /orders/<int:order_id>/lock | role_required | ADMIN |
| app/routes/operational_routes.py | 535 | POST | /orders/<int:order_id>/generate-production | role_required | ADMIN |
| app/routes/operational_routes.py | 550 | GET,POST | /order-details/<int:detail_id>/revision | role_required | ADMIN |
| app/routes/operational_routes.py | 600 | GET,POST | /orders/<int:order_id>/hpp-snapshot/create | role_required | ADMIN |
| app/routes/operational_routes.py | 648 | GET | /orders/<int:order_id>/hpp-snapshot/<int:snapshot_id> | role_required | ADMIN |
| app/routes/operational_routes.py | 668 | GET | /orders/<int:order_id>/hpp-snapshot/<int:snapshot_id>/stock-dry-run | role_required | ADMIN |
| app/routes/operational_routes.py | 694 | POST | /orders/<int:order_id>/hpp-snapshot/<int:snapshot_id>/stock-commit | role_required | ADMIN |
| app/routes/operational_routes.py | 740 | GET | /orders/<int:order_id>/hpp-snapshot/<int:snapshot_id>/stock-consumption/<int:consumption_id> | role_required | ADMIN |
| app/routes/prediction_routes.py | 34 | GET | / | login_required | - |
| app/routes/prediction_routes.py | 56 | POST | /train | login_required | - |
| app/routes/prediction_routes.py | 75 | GET,POST | /predict | login_required | - |
| app/routes/prediction_routes.py | 125 | GET | /evaluate | login_required | - |
| app/routes/prediction_routes.py | 151 | POST | /api/predict | login_required | - |
| app/routes/production_routes.py | 26 | GET | / | role_required | ADMIN, DAPUR |
| app/routes/production_routes.py | 62 | GET | /<int:production_id> | role_required | ADMIN, DAPUR |
| app/routes/production_routes.py | 97 | POST | /<int:production_id>/realization | role_required | ADMIN, DAPUR |
| app/routes/settings/account_routes.py | 10 | GET,POST | /company | role_required | OWNER |
| app/routes/settings/account_routes.py | 45 | GET | /users | role_required | OWNER |
| app/routes/settings/account_routes.py | 57 | GET,POST | /users/create | role_required | OWNER |
| app/routes/settings/account_routes.py | 117 | GET,POST | /users/<int:user_id>/edit | role_required | OWNER |
| app/routes/settings/account_routes.py | 178 | POST | /users/<int:user_id>/toggle | role_required | OWNER |
| app/routes/settings/account_routes.py | 210 | GET,POST | /users/<int:user_id>/reset-password | role_required | OWNER |
| app/routes/settings/account_routes.py | 251 | GET,POST | /change-password | role_required | OWNER, ADMIN, FINANCE, ACCOUNTING, LOGISTICS, HR, DAPUR, PENGANTAR |
| app/routes/settings/approval_routes.py | 10 | GET | /approvals | role_required | OWNER, ADMIN |
| app/routes/settings/approval_routes.py | 25 | POST | /approvals/<int:approval_id>/approve | role_required | OWNER, ADMIN |
| app/routes/settings/approval_routes.py | 40 | POST | /approvals/<int:approval_id>/reject | role_required | OWNER, ADMIN |
| app/routes/settings/audit_attachment_routes.py | 52 | GET | /audit-logs | role_required | OWNER |
| app/routes/settings/audit_attachment_routes.py | 90 | GET | /audit-logs/export.csv | role_required | OWNER |
| app/routes/settings/audit_attachment_routes.py | 149 | GET | /audit-logs/<int:log_id> | role_required | OWNER |
| app/routes/settings/audit_attachment_routes.py | 159 | GET | /digital-attachments | role_required | OWNER |
| app/routes/settings/audit_attachment_routes.py | 196 | GET | /digital-attachments/<int:attachment_id> | role_required | OWNER |
| app/routes/settings/audit_attachment_routes.py | 222 | GET | /digital-attachments/<int:attachment_id>/download | role_required | OWNER |
| app/routes/settings/audit_attachment_routes.py | 251 | GET | /digital-attachments/<int:attachment_id>/view | role_required | OWNER |
| app/routes/settings/audit_attachment_routes.py | 283 | POST | /digital-attachments/<int:attachment_id>/delete | role_required | OWNER |
| app/routes/settings/backup_routes.py | 10 | GET | /backups | role_required | OWNER |
| app/routes/settings/backup_routes.py | 40 | POST | /backups/validate | role_required | OWNER |
| app/routes/settings/backup_routes.py | 116 | POST | /backups/create | role_required | OWNER |
| app/routes/settings/backup_routes.py | 166 | POST | /backups/create-full | role_required | OWNER |
| app/routes/settings/backup_routes.py | 226 | GET | /backups/download-confirm/<path:filename> | role_required | OWNER |
| app/routes/settings/backup_routes.py | 245 | POST | /backups/download/<path:filename> | role_required | OWNER |
| app/routes/settings/notification_routes.py | 10 | GET | /reminders | role_required | OWNER, ADMIN, FINANCE, ACCOUNTING, LOGISTICS, HR, DAPUR, PENGANTAR |
| app/routes/settings/notification_routes.py | 42 | GET | /notifications | role_required | OWNER, ADMIN, FINANCE, ACCOUNTING, LOGISTICS, HR, DAPUR, PENGANTAR |
| app/routes/settings/notification_routes.py | 99 | POST | /notifications/generate | role_required | OWNER, ADMIN |
| app/routes/settings/notification_routes.py | 163 | POST | /notifications/<int:notification_id>/read | role_required | OWNER, ADMIN, FINANCE, ACCOUNTING, LOGISTICS, HR, DAPUR, PENGANTAR |
| app/routes/settings/notification_routes.py | 180 | POST | /notifications/<int:notification_id>/unread | role_required | OWNER, ADMIN, FINANCE, ACCOUNTING, LOGISTICS, HR, DAPUR, PENGANTAR |
| app/routes/settings/notification_routes.py | 197 | POST | /notifications/<int:notification_id>/dismiss | role_required | OWNER, ADMIN, FINANCE, ACCOUNTING, LOGISTICS, HR, DAPUR, PENGANTAR |
| app/routes/settings/recovery_health_routes.py | 10 | GET | /recovery-center | role_required | OWNER, ADMIN |
| app/routes/settings/recovery_health_routes.py | 24 | GET | /system-health | role_required | OWNER, ADMIN |
| app/routes/settings/recovery_health_routes.py | 37 | GET | /atomic-transaction-map | role_required | OWNER |
| app/routes/settings/recovery_health_routes.py | 44 | GET | /atomic-smoke-simulation | role_required | OWNER |
| app/routes/settings/recovery_health_routes.py | 59 | GET | /visual-sweep | role_required | OWNER, ADMIN |
| app/routes/settings/recovery_health_routes.py | 72 | GET | /final-visual-qa | role_required | OWNER, ADMIN |
| app/routes/sop_routes.py | 646 | GET | / | login_required | - |
| app/routes/sop_routes.py | 658 | GET | /disaster-recovery | login_required | - |
| app/routes/sop_routes.py | 670 | GET | /backup-restore | login_required | - |
| app/routes/sop_routes.py | 682 | GET | /<slug> | login_required | - |

