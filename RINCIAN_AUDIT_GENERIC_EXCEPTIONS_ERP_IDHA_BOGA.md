# Audit Generic Exception ERP Idha Boga

Laporan ini read-only. Fokus P1 adalah handler yang menangkap semua Exception tanpa logger dan tanpa raise pada route, service transaksi, dashboard, backup, dan context processor.

## Ringkasan

| Metrik | Nilai |
| --- | --- |
| Total except Exception | 305 |
| P1 perlu logging/exception spesifik | 0 |
| P2 review bertahap | 305 |
| Handler tanpa logger dan tanpa raise | 0 |

## Per Scope

| Scope | Jumlah |
| --- | --- |
| route | 146 |
| service | 113 |
| dashboard/background-read | 25 |
| backup/recovery | 16 |
| app_factory/context/error_handler | 5 |

## Detail

| Prioritas | File | Line | Scope | Logged | Reraised |
| --- | --- | --- | --- | --- | --- |
| P2 | app/__init__.py | 107 | app_factory/context/error_handler | ya | tidak |
| P2 | app/__init__.py | 129 | app_factory/context/error_handler | ya | tidak |
| P2 | app/__init__.py | 184 | app_factory/context/error_handler | ya | tidak |
| P2 | app/__init__.py | 225 | app_factory/context/error_handler | ya | tidak |
| P2 | app/__init__.py | 241 | app_factory/context/error_handler | ya | tidak |
| P2 | app/routes/accounting/closing_routes.py | 11 | route | ya | tidak |
| P2 | app/routes/accounting/closing_routes.py | 495 | route | ya | tidak |
| P2 | app/routes/accounting/journal_routes.py | 232 | route | ya | tidak |
| P2 | app/routes/accounting/journal_routes.py | 290 | route | ya | tidak |
| P2 | app/routes/accounting/posting_routes.py | 28 | route | ya | tidak |
| P2 | app/routes/accounting/posting_routes.py | 134 | route | ya | tidak |
| P2 | app/routes/accounting/posting_routes.py | 312 | route | ya | tidak |
| P2 | app/routes/accounting/posting_routes.py | 330 | route | ya | tidak |
| P2 | app/routes/accounting/posting_routes.py | 582 | route | ya | tidak |
| P2 | app/routes/accounting/posting_routes.py | 594 | route | ya | tidak |
| P2 | app/routes/accounting/posting_routes.py | 815 | route | ya | tidak |
| P2 | app/routes/accounting/report_routes.py | 16 | route | ya | tidak |
| P2 | app/routes/accounting/report_routes.py | 24 | route | ya | tidak |
| P2 | app/routes/accounting/report_routes.py | 325 | route | ya | tidak |
| P2 | app/routes/accounting/report_routes.py | 663 | route | ya | tidak |
| P2 | app/routes/accounting/report_routes.py | 800 | route | ya | tidak |
| P2 | app/routes/auth_routes.py | 80 | route | ya | tidak |
| P2 | app/routes/canteen_routes.py | 59 | route | ya | tidak |
| P2 | app/routes/delivery_routes.py | 201 | route | ya | tidak |
| P2 | app/routes/delivery_routes.py | 253 | route | ya | tidak |
| P2 | app/routes/delivery_routes.py | 306 | route | ya | tidak |
| P2 | app/routes/delivery_routes.py | 376 | route | ya | tidak |
| P2 | app/routes/delivery_routes.py | 390 | route | ya | tidak |
| P2 | app/routes/delivery_routes.py | 410 | route | ya | tidak |
| P2 | app/routes/field_transaction_routes.py | 109 | route | tidak | ya |
| P2 | app/routes/field_transaction_routes.py | 116 | route | ya | tidak |
| P2 | app/routes/field_transaction_routes.py | 329 | route | ya | tidak |
| P2 | app/routes/field_transaction_routes.py | 406 | route | ya | tidak |
| P2 | app/routes/field_transaction_routes.py | 466 | route | ya | tidak |
| P2 | app/routes/field_transaction_routes.py | 505 | route | ya | tidak |
| P2 | app/routes/field_transaction_routes.py | 563 | route | ya | tidak |
| P2 | app/routes/field_transaction_routes.py | 683 | route | ya | tidak |
| P2 | app/routes/field_transaction_routes.py | 703 | route | ya | tidak |
| P2 | app/routes/field_transaction_routes.py | 724 | route | ya | tidak |
| P2 | app/routes/field_transaction_routes.py | 757 | route | ya | tidak |
| P2 | app/routes/field_transaction_routes.py | 798 | route | ya | tidak |
| P2 | app/routes/field_transaction_routes.py | 820 | route | ya | tidak |
| P2 | app/routes/field_transaction_routes.py | 848 | route | ya | tidak |
| P2 | app/routes/field_transaction_routes.py | 876 | route | ya | tidak |
| P2 | app/routes/field_transaction_routes.py | 925 | route | ya | tidak |
| P2 | app/routes/field_transaction_routes.py | 962 | route | ya | tidak |
| P2 | app/routes/field_transaction_routes.py | 995 | route | ya | tidak |
| P2 | app/routes/field_transaction_routes.py | 1030 | route | ya | tidak |
| P2 | app/routes/field_transaction_routes.py | 1059 | route | ya | tidak |
| P2 | app/routes/finance/advance_expense_asset_routes.py | 76 | route | ya | tidak |
| P2 | app/routes/finance/advance_expense_asset_routes.py | 83 | route | ya | tidak |
| P2 | app/routes/finance/advance_expense_asset_routes.py | 91 | route | ya | tidak |
| P2 | app/routes/finance/advance_expense_asset_routes.py | 112 | route | ya | tidak |
| P2 | app/routes/finance/advance_expense_asset_routes.py | 214 | route | ya | tidak |
| P2 | app/routes/finance/advance_expense_asset_routes.py | 221 | route | ya | tidak |
| P2 | app/routes/finance/advance_expense_asset_routes.py | 228 | route | ya | tidak |
| P2 | app/routes/finance/advance_expense_asset_routes.py | 244 | route | ya | tidak |
| P2 | app/routes/finance/advance_expense_asset_routes.py | 325 | route | ya | tidak |
| P2 | app/routes/finance/advance_expense_asset_routes.py | 439 | route | ya | tidak |
| P2 | app/routes/finance/advance_expense_asset_routes.py | 547 | route | ya | tidak |
| P2 | app/routes/finance/advance_expense_asset_routes.py | 583 | route | ya | tidak |
| P2 | app/routes/finance/advance_expense_asset_routes.py | 645 | route | ya | tidak |
| P2 | app/routes/finance/advance_expense_asset_routes.py | 691 | route | ya | tidak |
| P2 | app/routes/finance/advance_expense_asset_routes.py | 824 | route | ya | tidak |
| P2 | app/routes/finance/advance_expense_asset_routes.py | 902 | route | ya | tidak |
| P2 | app/routes/finance/ar_dashboard_routes.py | 7 | route | ya | tidak |
| P2 | app/routes/finance/ar_dashboard_routes.py | 21 | route | ya | tidak |
| P2 | app/routes/finance/ar_dashboard_routes.py | 32 | route | ya | tidak |
| P2 | app/routes/finance/ar_dashboard_routes.py | 42 | route | ya | tidak |
| P2 | app/routes/finance/cash_bank_routes.py | 67 | route | ya | tidak |
| P2 | app/routes/finance/cash_bank_routes.py | 75 | route | ya | tidak |
| P2 | app/routes/finance/cash_bank_routes.py | 490 | route | ya | tidak |
| P2 | app/routes/finance/cash_bank_routes.py | 553 | route | ya | tidak |
| P2 | app/routes/finance/cash_bank_routes.py | 614 | route | ya | tidak |
| P2 | app/routes/finance/cash_bank_routes.py | 654 | route | ya | tidak |
| P2 | app/routes/finance/cash_bank_routes.py | 683 | route | ya | tidak |
| P2 | app/routes/finance/invoice_communication_routes.py | 25 | route | ya | tidak |
| P2 | app/routes/finance/invoice_communication_routes.py | 97 | route | ya | tidak |
| P2 | app/routes/finance/invoice_print_routes.py | 7 | route | ya | tidak |
| P2 | app/routes/finance/invoice_print_routes.py | 48 | route | ya | tidak |
| P2 | app/routes/finance/invoice_print_routes.py | 109 | route | ya | tidak |
| P2 | app/routes/finance/invoice_print_routes.py | 146 | route | ya | tidak |
| P2 | app/routes/finance/manual_billing_routes.py | 47 | route | ya | tidak |
| P2 | app/routes/finance/manual_billing_routes.py | 62 | route | ya | tidak |
| P2 | app/routes/finance/manual_billing_routes.py | 69 | route | ya | tidak |
| P2 | app/routes/finance/manual_billing_routes.py | 137 | route | ya | tidak |
| P2 | app/routes/finance/manual_billing_routes.py | 579 | route | ya | tidak |
| P2 | app/routes/finance/manual_billing_routes.py | 688 | route | ya | tidak |
| P2 | app/routes/finance/manual_billing_routes.py | 868 | route | ya | tidak |
| P2 | app/routes/finance/manual_billing_routes.py | 917 | route | ya | tidak |
| P2 | app/routes/finance/manual_billing_routes.py | 969 | route | ya | tidak |
| P2 | app/routes/finance/manual_billing_routes.py | 1008 | route | ya | tidak |
| P2 | app/routes/finance/payables_routes.py | 24 | route | ya | tidak |
| P2 | app/routes/finance/payables_routes.py | 73 | route | ya | tidak |
| P2 | app/routes/finance/payables_routes.py | 81 | route | ya | tidak |
| P2 | app/routes/finance/payables_routes.py | 343 | route | ya | tidak |
| P2 | app/routes/finance/payables_routes.py | 381 | route | ya | tidak |
| P2 | app/routes/finance/payables_routes.py | 508 | route | ya | tidak |
| P2 | app/routes/finance/payables_routes.py | 534 | route | ya | tidak |
| P2 | app/routes/finance/payables_routes.py | 548 | route | ya | tidak |
| P2 | app/routes/finance/payables_routes.py | 568 | route | ya | tidak |
| P2 | app/routes/finance/payment_routes.py | 66 | route | ya | tidak |
| P2 | app/routes/finance/payment_routes.py | 105 | route | ya | tidak |
| P2 | app/routes/finance/payment_routes.py | 216 | route | ya | tidak |
| P2 | app/routes/finance/payment_routes.py | 315 | route | ya | tidak |
| P2 | app/routes/finance/period_invoice_routes.py | 9 | route | ya | tidak |
| P2 | app/routes/finance/period_invoice_routes.py | 702 | route | ya | tidak |
| P2 | app/routes/finance/realtime_invoice_routes.py | 377 | route | ya | tidak |
| P2 | app/routes/finance/receivables_routes.py | 44 | route | ya | tidak |
| P2 | app/routes/finance/receivables_routes.py | 54 | route | ya | tidak |
| P2 | app/routes/finance/receivables_routes.py | 189 | route | ya | tidak |
| P2 | app/routes/finance/receivables_routes.py | 363 | route | ya | tidak |
| P2 | app/routes/finance/receivables_routes.py | 373 | route | ya | tidak |
| P2 | app/routes/finance/receivables_routes.py | 413 | route | ya | tidak |
| P2 | app/routes/finance/receivables_routes.py | 576 | route | ya | tidak |
| P2 | app/routes/finance/receivables_routes.py | 693 | route | ya | tidak |
| P2 | app/routes/finance/receivables_routes.py | 707 | route | ya | tidak |
| P2 | app/routes/finance/receivables_routes.py | 727 | route | ya | tidak |
| P2 | app/routes/health_routes.py | 19 | route | ya | tidak |
| P2 | app/routes/hr_routes.py | 477 | route | ya | tidak |
| P2 | app/routes/hr_routes.py | 560 | route | ya | tidak |
| P2 | app/routes/hr_routes.py | 594 | route | ya | tidak |
| P2 | app/routes/hr_routes.py | 631 | route | ya | tidak |
| P2 | app/routes/logistics/item_request_routes.py | 138 | route | ya | tidak |
| P2 | app/routes/logistics/item_request_routes.py | 339 | route | ya | tidak |
| P2 | app/routes/logistics/procurement_routes.py | 427 | route | ya | tidak |
| P2 | app/routes/logistics/procurement_routes.py | 514 | route | ya | tidak |
| P2 | app/routes/logistics/procurement_routes.py | 528 | route | ya | tidak |
| P2 | app/routes/logistics/procurement_routes.py | 548 | route | ya | tidak |
| P2 | app/routes/production_routes.py | 175 | route | ya | tidak |
| P2 | app/routes/settings/audit_attachment_routes.py | 30 | route | ya | tidak |
| P2 | app/routes/settings/audit_attachment_routes.py | 205 | route | ya | tidak |
| P2 | app/routes/settings/audit_attachment_routes.py | 226 | route | ya | tidak |
| P2 | app/routes/settings/audit_attachment_routes.py | 251 | route | ya | tidak |
| P2 | app/routes/settings/backup_routes.py | 14 | route | ya | tidak |
| P2 | app/routes/settings/backup_routes.py | 44 | route | ya | tidak |
| P2 | app/routes/settings/backup_routes.py | 102 | route | ya | tidak |
| P2 | app/routes/settings/backup_routes.py | 157 | route | ya | tidak |
| P2 | app/routes/settings/backup_routes.py | 217 | route | ya | tidak |
| P2 | app/routes/settings/backup_routes.py | 229 | route | ya | tidak |
| P2 | app/routes/settings/backup_routes.py | 257 | route | ya | tidak |
| P2 | app/routes/settings/notification_routes.py | 14 | route | ya | tidak |
| P2 | app/routes/settings/notification_routes.py | 25 | route | ya | tidak |
| P2 | app/routes/settings/notification_routes.py | 107 | route | ya | tidak |
| P2 | app/routes/settings/notification_routes.py | 114 | route | ya | tidak |
| P2 | app/routes/settings/notification_routes.py | 148 | route | ya | tidak |
| P2 | app/routes/settings/recovery_health_routes.py | 14 | route | ya | tidak |
| P2 | app/routes/settings/recovery_health_routes.py | 27 | route | ya | tidak |
| P2 | app/routes/settings/recovery_health_routes.py | 47 | route | ya | tidak |
| P2 | app/routes/settings/recovery_health_routes.py | 62 | route | ya | tidak |
| P2 | app/routes/settings/recovery_health_routes.py | 75 | route | ya | tidak |
| P2 | app/services/accounting_expense_drilldown_service.py | 88 | service | ya | tidak |
| P2 | app/services/accounting_expense_drilldown_service.py | 152 | service | ya | tidak |
| P2 | app/services/accounting_expense_drilldown_service.py | 274 | service | ya | tidak |
| P2 | app/services/accounting_expense_drilldown_service.py | 307 | service | ya | tidak |
| P2 | app/services/accounting_posting_status_service.py | 68 | service | ya | tidak |
| P2 | app/services/accounting_posting_status_service.py | 97 | service | ya | tidak |
| P2 | app/services/accounting_posting_status_service.py | 244 | service | ya | tidak |
| P2 | app/services/accounting_posting_status_service.py | 275 | service | ya | tidak |
| P2 | app/services/accounting_posting_status_service.py | 306 | service | ya | tidak |
| P2 | app/services/accounting_posting_status_service.py | 374 | service | ya | tidak |
| P2 | app/services/accounting_service.py | 30 | service | tidak | ya |
| P2 | app/services/accounting_service.py | 458 | service | tidak | ya |
| P2 | app/services/accounting_service.py | 492 | service | tidak | ya |
| P2 | app/services/accounting_service.py | 505 | service | ya | tidak |
| P2 | app/services/accounting_service.py | 659 | service | tidak | ya |
| P2 | app/services/accounting_service.py | 680 | service | ya | tidak |
| P2 | app/services/accounts_payable_service.py | 26 | service | ya | tidak |
| P2 | app/services/advance_service.py | 36 | service | tidak | ya |
| P2 | app/services/advance_service.py | 134 | service | ya | tidak |
| P2 | app/services/advance_service.py | 148 | service | ya | tidak |
| P2 | app/services/approval_service.py | 69 | service | tidak | ya |
| P2 | app/services/approval_service.py | 104 | service | tidak | ya |
| P2 | app/services/approval_service.py | 123 | service | tidak | ya |
| P2 | app/services/approval_service.py | 145 | service | tidak | ya |
| P2 | app/services/atomic_failure_simulation_service.py | 61 | service | tidak | ya |
| P2 | app/services/atomic_failure_simulation_service.py | 74 | service | ya | tidak |
| P2 | app/services/atomic_failure_simulation_service.py | 83 | service | ya | tidak |
| P2 | app/services/atomic_transaction_audit_map_service.py | 118 | service | ya | tidak |
| P2 | app/services/atomic_transaction_service.py | 84 | service | ya | tidak |
| P2 | app/services/atomic_transaction_service.py | 92 | service | ya | tidak |
| P2 | app/services/atomic_transaction_service.py | 96 | service | ya | tidak |
| P2 | app/services/atomic_transaction_service.py | 129 | service | ya | tidak |
| P2 | app/services/atomic_transaction_service.py | 148 | service | ya | tidak |
| P2 | app/services/atomic_transaction_service.py | 159 | service | ya | tidak |
| P2 | app/services/atomic_transaction_service.py | 224 | service | tidak | ya |
| P2 | app/services/audit_log_service.py | 56 | service | ya | tidak |
| P2 | app/services/audit_log_service.py | 70 | service | ya | tidak |
| P2 | app/services/audit_log_service.py | 168 | service | ya | tidak |
| P2 | app/services/audit_log_service.py | 243 | service | ya | tidak |
| P2 | app/services/audit_log_service.py | 312 | service | ya | tidak |
| P2 | app/services/backup_service.py | 109 | backup/recovery | ya | tidak |
| P2 | app/services/backup_service.py | 139 | backup/recovery | ya | tidak |
| P2 | app/services/backup_service.py | 170 | backup/recovery | ya | tidak |
| P2 | app/services/backup_service.py | 189 | backup/recovery | ya | tidak |
| P2 | app/services/backup_service.py | 211 | backup/recovery | ya | tidak |
| P2 | app/services/backup_service.py | 446 | backup/recovery | ya | tidak |
| P2 | app/services/backup_service.py | 611 | backup/recovery | ya | tidak |
| P2 | app/services/backup_service.py | 639 | backup/recovery | ya | tidak |
| P2 | app/services/backup_service.py | 652 | backup/recovery | ya | tidak |
| P2 | app/services/backup_service.py | 682 | backup/recovery | ya | tidak |
| P2 | app/services/backup_service.py | 698 | backup/recovery | ya | tidak |
| P2 | app/services/backup_service.py | 708 | backup/recovery | ya | tidak |
| P2 | app/services/backup_service.py | 743 | backup/recovery | ya | tidak |
| P2 | app/services/billing_trace_service.py | 36 | service | ya | tidak |
| P2 | app/services/canteen_service.py | 34 | service | tidak | ya |
| P2 | app/services/cash_bank_service.py | 14 | service | tidak | ya |
| P2 | app/services/cash_bank_service.py | 22 | service | ya | tidak |
| P2 | app/services/catering_report_service.py | 17 | service | ya | tidak |
| P2 | app/services/catering_report_service.py | 26 | service | ya | tidak |
| P2 | app/services/costing_transaction_service.py | 11 | service | tidak | ya |
| P2 | app/services/daily_closing_service.py | 42 | service | ya | tidak |
| P2 | app/services/daily_closing_service.py | 110 | service | ya | tidak |
| P2 | app/services/dashboard_analytics_service.py | 115 | dashboard/background-read | ya | tidak |
| P2 | app/services/dashboard_analytics_service.py | 126 | dashboard/background-read | ya | tidak |
| P2 | app/services/dashboard_analytics_service.py | 170 | dashboard/background-read | ya | tidak |
| P2 | app/services/dashboard_analytics_service.py | 180 | dashboard/background-read | ya | tidak |
| P2 | app/services/dashboard_command_center_service.py | 23 | dashboard/background-read | ya | tidak |
| P2 | app/services/dashboard_command_center_service.py | 31 | dashboard/background-read | ya | tidak |
| P2 | app/services/dashboard_command_center_service.py | 103 | dashboard/background-read | ya | tidak |
| P2 | app/services/dashboard_service.py | 87 | dashboard/background-read | ya | tidak |
| P2 | app/services/dashboard_service.py | 96 | dashboard/background-read | ya | tidak |
| P2 | app/services/dashboard_service.py | 105 | dashboard/background-read | ya | tidak |
| P2 | app/services/dashboard_service.py | 115 | dashboard/background-read | ya | tidak |
| P2 | app/services/dashboard_service.py | 123 | dashboard/background-read | ya | tidak |
| P2 | app/services/dashboard_service.py | 572 | dashboard/background-read | ya | tidak |
| P2 | app/services/dashboard_service.py | 669 | dashboard/background-read | ya | tidak |
| P2 | app/services/dashboard_service.py | 727 | dashboard/background-read | ya | tidak |
| P2 | app/services/dashboard_service.py | 731 | dashboard/background-read | ya | tidak |
| P2 | app/services/dashboard_service.py | 769 | dashboard/background-read | ya | tidak |
| P2 | app/services/dashboard_service.py | 876 | dashboard/background-read | ya | tidak |
| P2 | app/services/dashboard_service.py | 880 | dashboard/background-read | ya | tidak |
| P2 | app/services/digital_attachment_service.py | 61 | service | ya | tidak |
| P2 | app/services/digital_attachment_service.py | 226 | service | tidak | ya |
| P2 | app/services/disaster_recovery_sop_service.py | 30 | backup/recovery | ya | tidak |
| P2 | app/services/disaster_recovery_sop_service.py | 44 | backup/recovery | ya | tidak |
| P2 | app/services/field_transaction_policy_service.py | 299 | service | tidak | ya |
| P2 | app/services/field_transaction_posting_service.py | 31 | service | ya | tidak |
| P2 | app/services/field_transaction_settlement_service.py | 43 | service | ya | tidak |
| P2 | app/services/final_visual_browser_qa_service.py | 131 | service | ya | tidak |
| P2 | app/services/final_visual_browser_qa_service.py | 173 | service | ya | tidak |
| P2 | app/services/finance_collection_service.py | 8 | service | tidak | ya |
| P2 | app/services/finance_collection_service.py | 18 | service | tidak | ya |
| P2 | app/services/finance_export_service.py | 246 | service | ya | tidak |
| P2 | app/services/finance_export_service.py | 466 | service | ya | tidak |
| P2 | app/services/fixed_asset_depreciation_service.py | 33 | service | tidak | ya |
| P2 | app/services/fixed_asset_depreciation_service.py | 87 | service | ya | tidak |
| P2 | app/services/fixed_asset_depreciation_service.py | 96 | service | ya | tidak |
| P2 | app/services/fixed_asset_installment_service.py | 79 | service | ya | tidak |
| P2 | app/services/fixed_asset_installment_service.py | 112 | service | ya | tidak |
| P2 | app/services/fixed_asset_purchase_service.py | 27 | service | tidak | ya |
| P2 | app/services/fixed_asset_purchase_service.py | 45 | service | ya | tidak |
| P2 | app/services/global_filter_service.py | 66 | service | ya | tidak |
| P2 | app/services/global_filter_service.py | 164 | service | ya | tidak |
| P2 | app/services/hpp_stock_consumption_service.py | 389 | service | ya | tidak |
| P2 | app/services/hpp_stock_consumption_service.py | 436 | service | ya | tidak |
| P2 | app/services/hr_service.py | 76 | service | tidak | ya |
| P2 | app/services/idempotency_service.py | 82 | service | tidak | ya |
| P2 | app/services/idempotency_service.py | 95 | service | tidak | ya |
| P2 | app/services/invoice_identity_service.py | 15 | service | tidak | ya |
| P2 | app/services/live_reminder_service.py | 85 | dashboard/background-read | ya | tidak |
| P2 | app/services/live_reminder_service.py | 435 | dashboard/background-read | ya | tidak |
| P2 | app/services/live_reminder_service.py | 440 | dashboard/background-read | ya | tidak |
| P2 | app/services/live_reminder_service.py | 514 | dashboard/background-read | ya | tidak |
| P2 | app/services/logistics_transaction_service.py | 10 | service | tidak | ya |
| P2 | app/services/manual_backfill_billing_service.py | 96 | service | tidak | ya |
| P2 | app/services/manual_backfill_billing_service.py | 106 | service | ya | tidak |
| P2 | app/services/manual_backfill_duplicate_service.py | 104 | service | ya | tidak |
| P2 | app/services/manual_backfill_duplicate_service.py | 147 | service | ya | tidak |
| P2 | app/services/manual_billing_service.py | 38 | service | tidak | ya |
| P2 | app/services/manual_billing_service.py | 46 | service | ya | tidak |
| P2 | app/services/master_data_service.py | 78 | service | tidak | ya |
| P2 | app/services/ml_prediction_service.py | 82 | service | ya | tidak |
| P2 | app/services/ml_prediction_service.py | 99 | service | ya | tidak |
| P2 | app/services/ml_prediction_service.py | 122 | service | ya | tidak |
| P2 | app/services/ml_prediction_service.py | 447 | service | ya | tidak |
| P2 | app/services/ml_prediction_service.py | 465 | service | ya | tidak |
| P2 | app/services/ml_prediction_service.py | 629 | service | ya | tidak |
| P2 | app/services/notification_service.py | 70 | dashboard/background-read | ya | tidak |
| P2 | app/services/notification_service.py | 174 | dashboard/background-read | ya | tidak |
| P2 | app/services/operational_expense_service.py | 24 | service | tidak | ya |
| P2 | app/services/operational_expense_service.py | 76 | service | ya | tidak |
| P2 | app/services/operational_expense_service.py | 86 | service | ya | tidak |
| P2 | app/services/operational_service.py | 11 | service | tidak | ya |
| P2 | app/services/order_to_cash_trace_service.py | 20 | service | ya | tidak |
| P2 | app/services/period_closing_service.py | 44 | service | ya | tidak |
| P2 | app/services/production_runtime_health_service.py | 83 | service | ya | tidak |
| P2 | app/services/production_runtime_health_service.py | 96 | service | ya | tidak |
| P2 | app/services/production_runtime_health_service.py | 115 | service | ya | tidak |
| P2 | app/services/production_runtime_health_service.py | 140 | service | ya | tidak |
| P2 | app/services/production_runtime_health_service.py | 150 | service | ya | tidak |
| P2 | app/services/production_runtime_health_service.py | 168 | service | ya | tidak |
| P2 | app/services/recovery_center_service.py | 82 | backup/recovery | ya | tidak |
| P2 | app/services/sensitive_action_guard_service.py | 143 | service | ya | tidak |
| P2 | app/services/sensitive_action_guard_service.py | 153 | service | ya | tidak |
| P2 | app/services/sensitive_action_guard_service.py | 266 | service | ya | tidak |
| P2 | app/services/system_health_service.py | 37 | service | ya | tidak |
| P2 | app/services/system_health_service.py | 45 | service | ya | tidak |
| P2 | app/services/system_health_service.py | 104 | service | ya | tidak |
| P2 | app/services/system_health_service.py | 233 | service | ya | tidak |
| P2 | app/services/transport_expense_service.py | 25 | service | tidak | ya |
| P2 | app/services/transport_expense_service.py | 56 | service | ya | tidak |
| P2 | app/services/transport_expense_service.py | 66 | service | ya | tidak |
| P2 | app/services/visual_sweep_service.py | 31 | service | ya | tidak |
| P2 | app/services/visual_sweep_service.py | 230 | service | ya | tidak |

## Rekomendasi

- Ganti generic exception dengan exception spesifik untuk validasi, database operational error, integrity error, dan file I/O.

- Jika fallback tetap diperlukan, gunakan logger.exception agar kegagalan tidak terlihat sebagai kondisi normal.

- Hindari mengubah kegagalan query ERP menjadi label aman seperti badge hijau tanpa sinyal error internal.

