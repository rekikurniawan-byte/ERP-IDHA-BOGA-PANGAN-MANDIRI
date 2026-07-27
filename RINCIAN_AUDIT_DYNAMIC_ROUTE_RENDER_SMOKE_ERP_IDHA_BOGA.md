# Audit Dynamic Route Render Smoke ERP Idha Boga

Audit ini melakukan GET render pada route berparameter memakai sample ID dari database lokal.

## Ringkasan

| Metrik | Nilai |
| --- | ---: |
| Total route dinamis | 73 |
| Gagal | 0 |
| Skip tanpa sample data | 0 |

## Detail

| Status | Endpoint | Rule | Detail |
| --- | --- | --- | --- |
| PASS | `accounting.journal_detail` | `/accounting/journals/<int:journal_id>` | HTTP 200 |
| PASS | `accounting.print_journal_detail` | `/accounting/journals/<int:journal_id>/print` | HTTP 200 |
| PASS | `accounting.period_closing_detail` | `/accounting/period-closing/<int:closing_id>` | HTTP 200 |
| PASS | `canteen.debt_payment` | `/canteen/debts/<int:debt_id>/payment` | HTTP 200 |
| PASS | `canteen.external_receivable_payment` | `/canteen/external-receivables/<int:receivable_id>/payment` | HTTP 200 |
| PASS | `costing.edit_menu` | `/costing/menus/<int:menu_id>/edit` | HTTP 200 |
| PASS | `costing.menu_recipe` | `/costing/menus/<int:menu_id>/recipe` | HTTP 200 |
| PASS | `costing.edit_overhead_profile` | `/costing/overhead-profiles/<int:profile_id>/edit` | HTTP 200 |
| PASS | `costing.edit_packaging_profile` | `/costing/packaging-profiles/<int:profile_id>/edit` | HTTP 200 |
| PASS | `delivery.detail` | `/delivery/<int:delivery_id>` | HTTP 200 |
| PASS | `delivery.download_attachment` | `/delivery/attachments/<int:attachment_id>/download` | HTTP 200 |
| PASS | `delivery.view_attachment` | `/delivery/attachments/<int:attachment_id>/view` | HTTP 200 |
| PASS | `delivery.receive` | `/delivery/details/<int:detail_id>/receive` | HTTP 200 |
| PASS | `field_transactions.detail` | `/field-transactions/<int:transaction_id>` | HTTP 200 |
| PASS | `field_transactions.edit` | `/field-transactions/<int:transaction_id>/edit` | HTTP 302 |
| PASS | `field_transactions.download_attachment` | `/field-transactions/attachments/<int:attachment_id>/download` | HTTP 200 |
| PASS | `field_transactions.view_attachment` | `/field-transactions/attachments/<int:attachment_id>/view` | HTTP 200 |
| PASS | `finance.advance_detail` | `/finance/advances/<int:advance_id>` | HTTP 200 |
| PASS | `finance.cash_bank_transaction_detail` | `/finance/cash-bank-ledger/<int:transaction_id>` | HTTP 200 |
| PASS | `finance.daily_cash_detail` | `/finance/daily-cash/<int:cash_id>` | HTTP 200 |
| PASS | `finance.fixed_asset_depreciation_configure` | `/finance/fixed-asset-depreciation/<int:asset_id>/configure` | HTTP 200 |
| PASS | `finance.fixed_asset_installment_detail` | `/finance/fixed-asset-installments/<int:contract_id>` | HTTP 200 |
| PASS | `finance.fixed_asset_purchase_detail` | `/finance/fixed-asset-purchases/<int:purchase_id>` | HTTP 200 |
| PASS | `finance.invoice_detail` | `/finance/invoices/<int:invoice_id>` | HTTP 200 |
| PASS | `finance.invoice_print` | `/finance/invoices/<int:invoice_id>/print` | HTTP 200 |
| PASS | `finance.invoice_profit_detail` | `/finance/invoices/<int:invoice_id>/profit-report` | HTTP 200 |
| PASS | `finance.invoice_whatsapp_send` | `/finance/invoices/<int:invoice_id>/whatsapp/send` | HTTP 302 |
| PASS | `finance.manual_billing_batch_detail` | `/finance/manual-billing/batches/<int:batch_id>` | HTTP 200 |
| PASS | `finance.edit_manual_billing_backfill_batch` | `/finance/manual-billing/batches/<int:batch_id>/edit` | HTTP 302 |
| PASS | `finance.print_manual_billing_batch` | `/finance/manual-billing/batches/<int:batch_id>/print` | HTTP 200 |
| PASS | `finance.operational_expense_detail` | `/finance/operational-expenses/<int:expense_id>` | HTTP 200 |
| PASS | `finance.payment_receipt` | `/finance/payments/<int:payment_id>/receipt` | HTTP 200 |
| PASS | `finance.download_customer_payment_attachment` | `/finance/payments/attachments/<int:attachment_id>/download` | HTTP 200 |
| PASS | `finance.view_customer_payment_attachment` | `/finance/payments/attachments/<int:attachment_id>/view` | HTTP 200 |
| PASS | `finance.supplier_bill_detail` | `/finance/supplier-bills/<int:bill_id>` | HTTP 200 |
| PASS | `finance.download_supplier_payment_attachment` | `/finance/supplier-payments/attachments/<int:attachment_id>/download` | HTTP 200 |
| PASS | `finance.view_supplier_payment_attachment` | `/finance/supplier-payments/attachments/<int:attachment_id>/view` | HTTP 200 |
| PASS | `finance.transport_expense_detail` | `/finance/transport-expenses/<int:expense_id>` | HTTP 200 |
| PASS | `hr.edit_employee` | `/hr/employees/<int:employee_id>/edit` | HTTP 200 |
| PASS | `hr.payroll_detail` | `/hr/payrolls/<int:payroll_id>` | HTTP 200 |
| PASS | `logistics.item_request_detail` | `/logistics/item-requests/<int:request_id>` | HTTP 200 |
| PASS | `logistics.item_card` | `/logistics/items/<int:item_id>/card` | HTTP 200 |
| PASS | `logistics.purchase_detail` | `/logistics/purchases/<int:procurement_id>` | HTTP 200 |
| PASS | `logistics.download_procurement_attachment` | `/logistics/purchases/attachments/<int:attachment_id>/download` | HTTP 200 |
| PASS | `logistics.view_procurement_attachment` | `/logistics/purchases/attachments/<int:attachment_id>/view` | HTTP 200 |
| PASS | `master.edit_bank_account` | `/master/bank-accounts/<int:account_id>/edit` | HTTP 200 |
| PASS | `master.edit_client` | `/master/clients/<int:client_id>/edit` | HTTP 200 |
| PASS | `master.edit_driver` | `/master/drivers/<int:driver_id>/edit` | HTTP 200 |
| PASS | `master.edit_fixed_asset` | `/master/fixed-assets/<int:asset_id>/edit` | HTTP 200 |
| PASS | `master.edit_item_cost_profile` | `/master/items/<int:item_id>/cost-profile` | HTTP 200 |
| PASS | `master.edit_item` | `/master/items/<int:item_id>/edit` | HTTP 200 |
| PASS | `master.edit_location` | `/master/locations/<int:location_id>/edit` | HTTP 200 |
| PASS | `master.edit_mandor` | `/master/mandors/<int:mandor_id>/edit` | HTTP 200 |
| PASS | `master.edit_supplier` | `/master/suppliers/<int:supplier_id>/edit` | HTTP 200 |
| PASS | `master.edit_worker` | `/master/workers/<int:worker_id>/edit` | HTTP 200 |
| PASS | `dashboard.module_placeholder` | `/module/<module_name>` | HTTP 200 |
| PASS | `operational.create_revision` | `/operational/order-details/<int:detail_id>/revision` | HTTP 200 |
| PASS | `operational.order_detail` | `/operational/orders/<int:order_id>` | HTTP 200 |
| PASS | `operational.add_order_detail` | `/operational/orders/<int:order_id>/add-detail` | HTTP 302 |
| PASS | `operational.add_increase_after_lock_route` | `/operational/orders/<int:order_id>/add-increase-after-lock` | HTTP 200 |
| PASS | `operational.update_order_hpp_defaults_route` | `/operational/orders/<int:order_id>/hpp-defaults` | HTTP 200 |
| PASS | `operational.order_hpp_snapshot_detail` | `/operational/orders/<int:order_id>/hpp-snapshot/<int:snapshot_id>` | HTTP 200 |
| PASS | `operational.order_hpp_stock_consumption_detail` | `/operational/orders/<int:order_id>/hpp-snapshot/<int:snapshot_id>/stock-consumption/<int:consumption_id>` | HTTP 200 |
| PASS | `operational.order_hpp_snapshot_stock_dry_run` | `/operational/orders/<int:order_id>/hpp-snapshot/<int:snapshot_id>/stock-dry-run` | HTTP 200 |
| PASS | `operational.create_order_hpp_snapshot_route` | `/operational/orders/<int:order_id>/hpp-snapshot/create` | HTTP 200 |
| PASS | `production.detail` | `/production/<int:production_id>` | HTTP 200 |
| PASS | `settings.audit_log_detail` | `/settings/audit-logs/<int:log_id>` | HTTP 200 |
| PASS | `settings.digital_attachment_detail` | `/settings/digital-attachments/<int:attachment_id>` | HTTP 200 |
| PASS | `settings.download_digital_attachment` | `/settings/digital-attachments/<int:attachment_id>/download` | HTTP 200 |
| PASS | `settings.view_digital_attachment` | `/settings/digital-attachments/<int:attachment_id>/view` | HTTP 200 |
| PASS | `settings.edit_user_page` | `/settings/users/<int:user_id>/edit` | HTTP 200 |
| PASS | `settings.reset_user_password_page` | `/settings/users/<int:user_id>/reset-password` | HTTP 200 |
| PASS | `sop.role_sop` | `/sop/<slug>` | HTTP 200 |
