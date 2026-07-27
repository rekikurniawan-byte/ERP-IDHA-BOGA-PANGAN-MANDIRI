# Audit db.session.commit ERP Idha Boga

Laporan ini dibuat dari parsing AST `app/**/*.py`. Tidak ada perubahan perilaku aplikasi. Parser hanya menghitung call nyata, sehingga string/komentar yang memuat teks `db.session.commit()` tidak dihitung.

## Ringkasan

| Metrik | Nilai |
| --- | --- |
| Total db.session.commit() | 101 |
| Total db.session.rollback() | 47 |
| Fungsi dengan commit | 101 |
| Fungsi commit tanpa rollback di fungsi yang sama | 72 |
| Commit di route | 0 |
| Rollback di route | 0 |
| Commit di service | 101 |
| Fungsi dengan lebih dari satu commit | 0 |
| Service call ke fungsi ber-commit | 0 |
| Call eksplisit commit=True | 32 |
| P0 | 0 |
| P1 | 66 |
| P2 | 35 |

## Sebaran Commit Per File

| File | Jumlah commit |
| --- | --- |
| app/services/accounting_service.py | 15 |
| app/services/field_transaction_service.py | 8 |
| app/services/manual_backfill_billing_service.py | 7 |
| app/services/notification_service.py | 7 |
| app/services/user_management_service.py | 5 |
| app/services/approval_service.py | 4 |
| app/services/delivery_service.py | 4 |
| app/services/field_transaction_settlement_service.py | 4 |
| app/services/operational_service.py | 4 |
| app/services/advance_service.py | 3 |
| app/services/field_transaction_bridge_service.py | 3 |
| app/services/fixed_asset_depreciation_service.py | 3 |
| app/services/accounts_payable_service.py | 2 |
| app/services/digital_attachment_service.py | 2 |
| app/services/finance_collection_service.py | 2 |
| app/services/fixed_asset_installment_service.py | 2 |
| app/services/fixed_asset_purchase_service.py | 2 |
| app/services/idempotency_service.py | 2 |
| app/services/operational_expense_service.py | 2 |
| app/services/stock_service.py | 2 |
| app/services/transport_expense_service.py | 2 |
| app/services/audit_log_service.py | 1 |
| app/services/canteen_service.py | 1 |
| app/services/cash_bank_service.py | 1 |
| app/services/company_settings_service.py | 1 |
| app/services/costing_transaction_service.py | 1 |
| app/services/daily_cash_service.py | 1 |
| app/services/field_transaction_posting_service.py | 1 |
| app/services/hpp_stock_consumption_service.py | 1 |
| app/services/hr_service.py | 1 |
| app/services/invoice_identity_service.py | 1 |
| app/services/logistics_transaction_service.py | 1 |
| app/services/manual_billing_service.py | 1 |
| app/services/master_data_service.py | 1 |
| app/services/order_hpp_snapshot_service.py | 1 |
| app/services/period_closing_service.py | 1 |
| app/services/production_service.py | 1 |

## Kandidat P0

P0 berarti commit langsung di route atau fungsi dengan lebih dari satu commit pada area berisiko. Target refactor: route memanggil service use-case, lalu satu boundary commit/rollback membungkus semua efek bisnis.

| Priority | Lokasi | Fungsi | Commit/Fungsi | Rollback/Fungsi | Alasan |
| --- | --- | --- | --- | --- | --- |

## Rollback Langsung Di Route

| Lokasi | Fungsi | Dalam Atomic |
| --- | --- | --- |

## Fungsi Dengan Lebih Dari Satu Commit

| File | Class | Fungsi | Jumlah Commit |
| --- | --- | --- | --- |

## Service Yang Memanggil Fungsi Ber-Commit

Daftar ini berbasis pencocokan nama fungsi AST, jadi wajib ditinjau manual. Audit log, helper privat, dan call `commit=False` dikeluarkan agar daftar lebih fokus pada potensi service helper yang diam-diam membuka transaction boundary sendiri.

| Lokasi | Fungsi Pemanggil | Fungsi Dipanggil | Arg Commit |
| --- | --- | --- | --- |

## Call Eksplisit commit=True

| Lokasi | Layer | Fungsi Pemanggil | Fungsi Dipanggil |
| --- | --- | --- | --- |
| app/routes/accounting/closing_routes.py:478 | route | post_period_closing_route | post_period_closing |
| app/routes/accounting/closing_routes.py:487 | route | post_period_closing_route | mark_idempotency_completed |
| app/routes/accounting/journal_routes.py:235 | route | generate_period_invoice_journals | mark_idempotency_completed |
| app/routes/accounting/journal_routes.py:293 | route | generate_payment_journals | mark_idempotency_completed |
| app/routes/accounting/posting_routes.py:286 | route | opening_balance | _generate_accounting3b_opening_balance_journal |
| app/routes/accounting/posting_routes.py:545 | route | generate_hpp_production_journals | _generate_accounting4b_hpp_journals |
| app/routes/accounting/posting_routes.py:574 | route | generate_hpp_production_journals | mark_idempotency_completed |
| app/routes/accounting/posting_routes.py:786 | route | generate_warung_payment_correction_journals | _generate_accounting7c_warung_payment_correction_journals |
| app/routes/accounting/posting_routes.py:807 | route | generate_warung_payment_correction_journals | mark_idempotency_completed |
| app/routes/accounting/report_routes.py:764 | route | generate_procurement_journals | _generate_accounting2e_procurement_journals |
| app/routes/accounting/report_routes.py:792 | route | generate_procurement_journals | mark_idempotency_completed |
| app/routes/field_transaction_routes.py:440 | route | create | create_field_transaction |
| app/routes/field_transaction_routes.py:539 | route | edit | update_field_transaction_draft |
| app/routes/field_transaction_routes.py:672 | route | link_attachment | attach_existing_digital_attachment_to_field_transaction |
| app/routes/field_transaction_routes.py:694 | route | verify_attachment | verify_field_transaction_attachment |
| app/routes/field_transaction_routes.py:806 | route | update_review_status | update_field_transaction_review_status |
| app/routes/field_transaction_routes.py:830 | route | post | post_field_transaction |
| app/routes/field_transaction_routes.py:854 | route | create_manual_receivable_doc | create_manual_receivable_for_field_transaction |
| app/routes/field_transaction_routes.py:882 | route | create_manual_payable_doc | create_manual_payable_for_field_transaction |
| app/routes/field_transaction_routes.py:927 | route | create_manual_receivable_payment | record_manual_receivable_payment |
| app/routes/field_transaction_routes.py:964 | route | create_manual_payable_payment | record_manual_payable_payment |
| app/routes/field_transaction_routes.py:1000 | route | bridge_operational_expense | bridge_to_operational_expense |
| app/routes/field_transaction_routes.py:1034 | route | bridge_transport_expense | bridge_to_transport_expense |
| app/routes/field_transaction_routes.py:1066 | route | bridge_advance | bridge_to_advance_transaction |
| app/routes/finance/manual_billing_routes.py:859 | route | lock_manual_billing_batch_route | mark_idempotency_completed |
| app/routes/finance/manual_billing_routes.py:959 | route | create_manual_backfill_invoice_route | mark_idempotency_completed |
| app/routes/logistics/item_request_routes.py:318 | route | fulfill_item_request | mark_idempotency_completed |
| app/routes/logistics/stock_routes.py:288 | route | stock_opening_balances | mark_idempotency_completed |
| app/routes/logistics/stock_routes.py:296 | route | stock_opening_balances | mark_idempotency_failed |
| app/routes/settings/approval_routes.py:31 | route | approve_approval_request | approve_request |
| app/routes/settings/approval_routes.py:46 | route | reject_approval_request | reject_request |
| app/routes/settings/notification_routes.py:120 | route | generate_notifications_route | generate_notifications_from_live_reminders |

## Rekomendasi Hardening

- Jangan refactor semua commit sekaligus; mulai dari route P0 yang menyentuh invoice, payment, cash/bank, stock, posting jurnal, payroll, dan backup.

- Jadikan helper bawah bebas commit. Helper sebaiknya hanya `add`, validasi, atau return object; commit dilakukan service use-case.

- Untuk use case kritis, pakai satu boundary: `try -> semua mutasi -> commit`, `except -> rollback -> raise/return error` atau `atomic_business_action`.

- Tambahkan regression test untuk partial failure: invoice dibuat tetapi jurnal gagal, payment masuk tetapi piutang gagal, stok bergerak tetapi HPP gagal.

- Commit audit log boleh menjadi boundary tersendiri jika memang didesain begitu, tetapi jangan menutupi kegagalan transaksi bisnis utama.

## Semua Commit

| Priority | Lokasi | Layer | Class | Fungsi | Commit/Fungsi | Rollback/Fungsi | Dalam Atomic | Alasan |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P1 | app/services/accounting_service.py:29 | service | - | commit_accounting_transaction | 1 | 1 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah |
| P1 | app/services/accounting_service.py:319 | service | - | create_invoice_journal_for_invoice | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/accounting_service.py:420 | service | - | create_payment_journal_for_payment | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/accounting_service.py:457 | service | - | generate_period_invoice_journals_batch | 1 | 1 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah |
| P1 | app/services/accounting_service.py:491 | service | - | generate_payment_journals_batch | 1 | 1 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah |
| P1 | app/services/accounting_service.py:658 | service | - | generate_procurement_journals_batch | 1 | 1 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah |
| P1 | app/services/accounting_service.py:765 | service | - | create_warung_cash_sale_journal | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/accounting_service.py:845 | service | - | create_warung_debt_accrual_journal | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/accounting_service.py:934 | service | - | create_warung_debt_payment_journal | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/accounting_service.py:1015 | service | - | create_payroll_journal_for_payroll | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/accounting_service.py:1120 | service | - | create_payroll_payment_journal_for_payroll | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/accounting_service.py:1224 | service | - | create_supplier_payment_journal_for_payment | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/accounting_service.py:1288 | service | - | create_warung_direct_sale_journal | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/accounting_service.py:1342 | service | - | create_warung_external_debt_accrual_journal | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/accounting_service.py:1395 | service | - | create_warung_external_receivable_payment_journal | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/accounts_payable_service.py:129 | service | - | create_supplier_bill_for_procurement | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/accounts_payable_service.py:270 | service | - | create_supplier_payment_for_bill | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P2 | app/services/advance_service.py:34 | service | - | _run_in_transaction | 1 | 1 | tidak | commit berada di service non-kritis atau perlu review manual |
| P2 | app/services/advance_service.py:415 | service | - | create_advance_transaction | 1 | 0 | tidak | commit berada di service non-kritis atau perlu review manual; tidak ada rollback eksplisit di fungsi yang sama |
| P2 | app/services/advance_service.py:700 | service | - | create_advance_settlement | 1 | 0 | tidak | commit berada di service non-kritis atau perlu review manual; tidak ada rollback eksplisit di fungsi yang sama |
| P2 | app/services/approval_service.py:68 | service | - | ensure_action_has_approval | 1 | 1 | tidak | commit berada di service non-kritis atau perlu review manual |
| P2 | app/services/approval_service.py:103 | service | - | create_approval_request | 1 | 1 | tidak | commit berada di service non-kritis atau perlu review manual |
| P2 | app/services/approval_service.py:122 | service | - | approve_request | 1 | 1 | tidak | commit berada di service non-kritis atau perlu review manual |
| P2 | app/services/approval_service.py:144 | service | - | reject_request | 1 | 1 | tidak | commit berada di service non-kritis atau perlu review manual |
| P2 | app/services/audit_log_service.py:241 | service | - | record_audit_log | 1 | 1 | tidak | commit berada di service infrastruktur/audit; tetap perlu boundary jelas tetapi bukan alur bisnis utama |
| P1 | app/services/canteen_service.py:33 | service | - | _commit_or_rollback | 1 | 1 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah |
| P1 | app/services/cash_bank_service.py:13 | service | - | _commit_or_rollback | 1 | 1 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah |
| P2 | app/services/company_settings_service.py:145 | service | - | save_company_settings | 1 | 0 | tidak | commit berada di service non-kritis atau perlu review manual; tidak ada rollback eksplisit di fungsi yang sama |
| P2 | app/services/costing_transaction_service.py:10 | service | - | _commit_or_rollback | 1 | 1 | tidak | commit berada di service non-kritis atau perlu review manual |
| P1 | app/services/daily_cash_service.py:160 | service | - | save_daily_cash | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/delivery_service.py:351 | service | - | create_delivery_from_order | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/delivery_service.py:412 | service | - | update_delivery_receipt | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/delivery_service.py:524 | service | - | create_shortage_replacement_delivery | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/delivery_service.py:568 | service | - | cancel_delivery | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P2 | app/services/digital_attachment_service.py:207 | service | - | save_digital_attachment | 1 | 0 | tidak | commit berada di service non-kritis atau perlu review manual; tidak ada rollback eksplisit di fungsi yang sama |
| P2 | app/services/digital_attachment_service.py:355 | service | - | soft_delete_attachment | 1 | 0 | tidak | commit berada di service non-kritis atau perlu review manual; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/field_transaction_bridge_service.py:200 | service | - | bridge_to_operational_expense | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/field_transaction_bridge_service.py:283 | service | - | bridge_to_transport_expense | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/field_transaction_bridge_service.py:362 | service | - | bridge_to_advance_transaction | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/field_transaction_posting_service.py:276 | service | - | post_field_transaction | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/field_transaction_service.py:371 | service | - | create_field_counterparty | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/field_transaction_service.py:566 | service | - | create_field_transaction | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/field_transaction_service.py:669 | service | - | create_system_linked_field_transaction | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/field_transaction_service.py:825 | service | - | update_field_transaction_draft | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/field_transaction_service.py:910 | service | - | update_field_transaction_review_status | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/field_transaction_service.py:1002 | service | - | attach_existing_digital_attachment_to_field_transaction | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/field_transaction_service.py:1083 | service | - | verify_field_transaction_attachment | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/field_transaction_service.py:1177 | service | - | link_field_transaction | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/field_transaction_settlement_service.py:432 | service | - | create_manual_receivable_for_field_transaction | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/field_transaction_settlement_service.py:538 | service | - | create_manual_payable_for_field_transaction | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/field_transaction_settlement_service.py:718 | service | - | record_manual_receivable_payment | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/field_transaction_settlement_service.py:898 | service | - | record_manual_payable_payment | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/finance_collection_service.py:7 | service | - | _commit_or_rollback | 1 | 1 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah |
| P1 | app/services/finance_collection_service.py:16 | service | - | _run_in_transaction | 1 | 1 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah |
| P1 | app/services/fixed_asset_depreciation_service.py:31 | service | - | _run_in_transaction | 1 | 1 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah |
| P1 | app/services/fixed_asset_depreciation_service.py:276 | service | - | configure_asset_depreciation | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/fixed_asset_depreciation_service.py:473 | service | - | post_asset_depreciation | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/fixed_asset_installment_service.py:455 | service | - | create_asset_financing_contract | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/fixed_asset_installment_service.py:616 | service | - | pay_installment_schedule | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/fixed_asset_purchase_service.py:25 | service | - | _run_in_transaction | 1 | 1 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah |
| P1 | app/services/fixed_asset_purchase_service.py:369 | service | - | create_fixed_asset_purchase | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/hpp_stock_consumption_service.py:433 | service | - | commit_hpp_stock_consumption | 1 | 6 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah |
| P1 | app/services/hr_service.py:75 | service | - | _commit_or_rollback | 1 | 1 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah |
| P2 | app/services/idempotency_service.py:81 | service | - | mark_idempotency_completed | 1 | 1 | tidak | commit berada di service non-kritis atau perlu review manual |
| P2 | app/services/idempotency_service.py:94 | service | - | mark_idempotency_failed | 1 | 1 | tidak | commit berada di service non-kritis atau perlu review manual |
| P1 | app/services/invoice_identity_service.py:13 | service | - | _run_in_transaction | 1 | 1 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah |
| P1 | app/services/logistics_transaction_service.py:9 | service | - | _commit_or_rollback | 1 | 1 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah |
| P2 | app/services/manual_backfill_billing_service.py:94 | service | - | _run_in_transaction | 1 | 1 | tidak | commit berada di service non-kritis atau perlu review manual |
| P2 | app/services/manual_backfill_billing_service.py:314 | service | - | create_manual_backfill_batch | 1 | 0 | tidak | commit berada di service non-kritis atau perlu review manual; tidak ada rollback eksplisit di fungsi yang sama |
| P2 | app/services/manual_backfill_billing_service.py:412 | service | - | update_manual_backfill_batch | 1 | 0 | tidak | commit berada di service non-kritis atau perlu review manual; tidak ada rollback eksplisit di fungsi yang sama |
| P2 | app/services/manual_backfill_billing_service.py:566 | service | - | lock_manual_backfill_batch | 1 | 0 | tidak | commit berada di service non-kritis atau perlu review manual; tidak ada rollback eksplisit di fungsi yang sama |
| P2 | app/services/manual_backfill_billing_service.py:644 | service | - | void_manual_backfill_batch | 1 | 0 | tidak | commit berada di service non-kritis atau perlu review manual; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/manual_backfill_billing_service.py:956 | service | - | create_invoice_from_manual_backfill_batch | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/manual_backfill_billing_service.py:1042 | service | - | sync_manual_backfill_batch_status_from_invoice | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P2 | app/services/manual_billing_service.py:36 | service | - | _run_in_transaction | 1 | 1 | tidak | commit berada di service non-kritis atau perlu review manual |
| P2 | app/services/master_data_service.py:77 | service | - | _commit_or_rollback | 1 | 1 | tidak | commit berada di service non-kritis atau perlu review manual |
| P2 | app/services/notification_service.py:312 | service | - | create_or_update_notification | 1 | 0 | tidak | commit berada di service non-kritis atau perlu review manual; tidak ada rollback eksplisit di fungsi yang sama |
| P2 | app/services/notification_service.py:321 | service | - | mark_notification_read | 1 | 0 | tidak | commit berada di service non-kritis atau perlu review manual; tidak ada rollback eksplisit di fungsi yang sama |
| P2 | app/services/notification_service.py:331 | service | - | mark_notification_unread | 1 | 0 | tidak | commit berada di service non-kritis atau perlu review manual; tidak ada rollback eksplisit di fungsi yang sama |
| P2 | app/services/notification_service.py:339 | service | - | mark_notification_dismissed | 1 | 0 | tidak | commit berada di service non-kritis atau perlu review manual; tidak ada rollback eksplisit di fungsi yang sama |
| P2 | app/services/notification_service.py:347 | service | - | mark_notification_resolved | 1 | 0 | tidak | commit berada di service non-kritis atau perlu review manual; tidak ada rollback eksplisit di fungsi yang sama |
| P2 | app/services/notification_service.py:376 | service | - | resolve_generated_notifications_not_in | 1 | 0 | tidak | commit berada di service non-kritis atau perlu review manual; tidak ada rollback eksplisit di fungsi yang sama |
| P2 | app/services/notification_service.py:445 | service | - | generate_notifications_from_live_reminders | 1 | 0 | tidak | commit berada di service non-kritis atau perlu review manual; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/operational_expense_service.py:22 | service | - | _run_in_transaction | 1 | 1 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah |
| P1 | app/services/operational_expense_service.py:302 | service | - | create_operational_expense | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/operational_service.py:10 | service | - | _commit_or_rollback | 1 | 1 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah |
| P1 | app/services/operational_service.py:47 | service | - | get_or_create_daily_order | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/operational_service.py:84 | service | - | add_or_update_order_detail | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/operational_service.py:351 | service | - | update_order_hpp_defaults | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/order_hpp_snapshot_service.py:439 | service | - | create_order_hpp_snapshot | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/period_closing_service.py:303 | service | - | post_period_closing | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/production_service.py:148 | service | - | generate_production_from_order | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/stock_service.py:77 | service | - | save_stock_opening_balance | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/stock_service.py:222 | service | - | create_stock_movement | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P2 | app/services/transport_expense_service.py:23 | service | - | _run_in_transaction | 1 | 1 | tidak | commit berada di service non-kritis atau perlu review manual |
| P2 | app/services/transport_expense_service.py:302 | service | - | create_transport_vehicle_expense | 1 | 0 | tidak | commit berada di service non-kritis atau perlu review manual; tidak ada rollback eksplisit di fungsi yang sama |
| P2 | app/services/user_management_service.py:190 | service | - | create_user | 1 | 0 | tidak | commit berada di service non-kritis atau perlu review manual; tidak ada rollback eksplisit di fungsi yang sama |
| P2 | app/services/user_management_service.py:205 | service | - | update_user | 1 | 0 | tidak | commit berada di service non-kritis atau perlu review manual; tidak ada rollback eksplisit di fungsi yang sama |
| P2 | app/services/user_management_service.py:218 | service | - | toggle_user_active | 1 | 0 | tidak | commit berada di service non-kritis atau perlu review manual; tidak ada rollback eksplisit di fungsi yang sama |
| P2 | app/services/user_management_service.py:234 | service | - | reset_user_password | 1 | 0 | tidak | commit berada di service non-kritis atau perlu review manual; tidak ada rollback eksplisit di fungsi yang sama |
| P2 | app/services/user_management_service.py:250 | service | - | change_own_password | 1 | 0 | tidak | commit berada di service non-kritis atau perlu review manual; tidak ada rollback eksplisit di fungsi yang sama |

