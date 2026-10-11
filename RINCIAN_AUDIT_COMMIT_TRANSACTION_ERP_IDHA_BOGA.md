# Audit db.session.commit ERP Idha Boga

Laporan ini dibuat dari parsing AST `app/**/*.py`. Tidak ada perubahan perilaku aplikasi. Parser hanya menghitung call nyata, sehingga string/komentar yang memuat teks `db.session.commit()` tidak dihitung.

## Ringkasan

| Metrik | Nilai |
| --- | --- |
| Total db.session.commit() | 112 |
| Total db.session.rollback() | 71 |
| Fungsi dengan commit | 112 |
| Fungsi commit tanpa rollback di fungsi yang sama | 71 |
| Commit di route | 0 |
| Rollback di route | 0 |
| Commit di service | 112 |
| Fungsi dengan lebih dari satu commit | 0 |
| Service call ke fungsi ber-commit | 0 |
| Call eksplisit commit=True | 23 |
| P0 | 0 |
| P1 | 61 |
| P2 | 51 |

## Sebaran Commit Per File

| File | Jumlah commit |
| --- | --- |
| app/services/accounting_service.py | 11 |
| app/services/field_transaction_service.py | 8 |
| app/services/manual_backfill_billing_service.py | 7 |
| app/services/notification_service.py | 6 |
| app/services/user_management_service.py | 6 |
| app/services/approval_service.py | 4 |
| app/services/delivery_service.py | 4 |
| app/services/field_transaction_settlement_service.py | 4 |
| app/services/operational_service.py | 4 |
| app/services/advance_service.py | 3 |
| app/services/field_transaction_bridge_service.py | 3 |
| app/services/fixed_asset_depreciation_service.py | 3 |
| app/services/pricing_service.py | 3 |
| app/services/accounts_payable_service.py | 2 |
| app/services/credit_account_service.py | 2 |
| app/services/digital_attachment_service.py | 2 |
| app/services/finance_collection_service.py | 2 |
| app/services/fixed_asset_installment_service.py | 2 |
| app/services/fixed_asset_purchase_service.py | 2 |
| app/services/idempotency_service.py | 2 |
| app/services/operational_expense_service.py | 2 |
| app/services/partnership_service.py | 2 |
| app/services/transport_expense_service.py | 2 |
| app/services/audit_log_service.py | 1 |
| app/services/bootstrap_service.py | 1 |
| app/services/canteen_service.py | 1 |
| app/services/cash_bank_service.py | 1 |
| app/services/company_settings_service.py | 1 |
| app/services/costing_transaction_service.py | 1 |
| app/services/daily_cash_service.py | 1 |
| app/services/field_transaction_posting_service.py | 1 |
| app/services/geo_service.py | 1 |
| app/services/hpp_stock_consumption_service.py | 1 |
| app/services/hr_service.py | 1 |
| app/services/invoice_identity_service.py | 1 |
| app/services/location_photo_service.py | 1 |
| app/services/logistics_transaction_service.py | 1 |
| app/services/manual_billing_service.py | 1 |
| app/services/master_data_service.py | 1 |
| app/services/opening_balance_service.py | 1 |
| app/services/order_hpp_snapshot_service.py | 1 |
| app/services/owner_capital_service.py | 1 |
| app/services/period_closing_service.py | 1 |
| app/services/portal_address_service.py | 1 |
| app/services/portal_customer_registration_service.py | 1 |
| app/services/portal_order_draft_service.py | 1 |
| app/services/production_service.py | 1 |
| app/services/stock_service.py | 1 |
| app/services/tax_service.py | 1 |

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
| app/routes/accounting/closing_routes.py:64 | route | post_period_closing_route | post_period_closing |
| app/routes/accounting/closing_routes.py:73 | route | post_period_closing_route | mark_idempotency_completed |
| app/routes/customer_success_routes.py:180 | route | update_contract_rules | update_customer_contract_rules |
| app/routes/field_transaction_routes.py:443 | route | create | create_field_transaction |
| app/routes/field_transaction_routes.py:542 | route | edit | update_field_transaction_draft |
| app/routes/field_transaction_routes.py:675 | route | link_attachment | attach_existing_digital_attachment_to_field_transaction |
| app/routes/field_transaction_routes.py:697 | route | verify_attachment | verify_field_transaction_attachment |
| app/routes/field_transaction_routes.py:809 | route | update_review_status | update_field_transaction_review_status |
| app/routes/field_transaction_routes.py:833 | route | post | post_field_transaction |
| app/routes/field_transaction_routes.py:857 | route | create_manual_receivable_doc | create_manual_receivable_for_field_transaction |
| app/routes/field_transaction_routes.py:885 | route | create_manual_payable_doc | create_manual_payable_for_field_transaction |
| app/routes/field_transaction_routes.py:930 | route | create_manual_receivable_payment | record_manual_receivable_payment |
| app/routes/field_transaction_routes.py:967 | route | create_manual_payable_payment | record_manual_payable_payment |
| app/routes/field_transaction_routes.py:1003 | route | bridge_operational_expense | bridge_to_operational_expense |
| app/routes/field_transaction_routes.py:1037 | route | bridge_transport_expense | bridge_to_transport_expense |
| app/routes/field_transaction_routes.py:1069 | route | bridge_advance | bridge_to_advance_transaction |
| app/routes/finance/manual_billing_routes.py:862 | route | lock_manual_billing_batch_route | mark_idempotency_completed |
| app/routes/finance/manual_billing_routes.py:962 | route | create_manual_backfill_invoice_route | mark_idempotency_completed |
| app/routes/logistics/item_request_routes.py:316 | route | fulfill_item_request | mark_idempotency_completed |
| app/routes/settings/approval_routes.py:31 | route | approve_approval_request | approve_request |
| app/routes/settings/approval_routes.py:46 | route | reject_approval_request | reject_request |
| app/routes/settings/notification_routes.py:128 | route | generate_notifications_route | generate_notifications_from_live_reminders |
| app/routes/settings/pricing_routes.py:160 | route | pricing_set_distance_fee | save_distance_fee_settings |

## Rekomendasi Hardening

- Jangan refactor semua commit sekaligus; mulai dari route P0 yang menyentuh invoice, payment, cash/bank, stock, posting jurnal, payroll, dan backup.

- Jadikan helper bawah bebas commit. Helper sebaiknya hanya `add`, validasi, atau return object; commit dilakukan service use-case.

- Untuk use case kritis, pakai satu boundary: `try -> semua mutasi -> commit`, `except -> rollback -> raise/return error` atau `atomic_business_action`.

- Tambahkan regression test untuk partial failure: invoice dibuat tetapi jurnal gagal, payment masuk tetapi piutang gagal, stok bergerak tetapi HPP gagal.

- Commit audit log boleh menjadi boundary tersendiri jika memang didesain begitu, tetapi jangan menutupi kegagalan transaksi bisnis utama.

## Semua Commit

| Priority | Lokasi | Layer | Class | Fungsi | Commit/Fungsi | Rollback/Fungsi | Dalam Atomic | Alasan |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P1 | app/services/accounting_service.py:31 | service | - | commit_accounting_transaction | 1 | 1 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah |
| P1 | app/services/accounting_service.py:422 | service | - | create_invoice_journal_for_invoice | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/accounting_service.py:539 | service | - | create_payment_journal_for_payment | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/accounting_service.py:730 | service | - | create_warung_debt_accrual_journal | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/accounting_service.py:825 | service | - | create_warung_debt_payment_journal | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/accounting_service.py:906 | service | - | create_payroll_journal_for_payroll | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/accounting_service.py:1029 | service | - | create_payroll_payment_journal_for_payroll | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/accounting_service.py:1128 | service | - | create_supplier_payment_journal_for_payment | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/accounting_service.py:1192 | service | - | create_warung_direct_sale_journal | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/accounting_service.py:1246 | service | - | create_warung_external_debt_accrual_journal | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/accounting_service.py:1301 | service | - | create_warung_external_receivable_payment_journal | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/accounts_payable_service.py:129 | service | - | create_supplier_bill_for_procurement | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/accounts_payable_service.py:270 | service | - | create_supplier_payment_for_bill | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P2 | app/services/advance_service.py:39 | service | - | _run_in_transaction | 1 | 1 | tidak | commit berada di service non-kritis atau perlu review manual |
| P2 | app/services/advance_service.py:511 | service | - | create_advance_transaction | 1 | 0 | tidak | commit berada di service non-kritis atau perlu review manual; tidak ada rollback eksplisit di fungsi yang sama |
| P2 | app/services/advance_service.py:911 | service | - | create_advance_settlement | 1 | 0 | tidak | commit berada di service non-kritis atau perlu review manual; tidak ada rollback eksplisit di fungsi yang sama |
| P2 | app/services/approval_service.py:97 | service | - | ensure_action_has_approval | 1 | 1 | tidak | commit berada di service non-kritis atau perlu review manual |
| P2 | app/services/approval_service.py:134 | service | - | create_approval_request | 1 | 1 | tidak | commit berada di service non-kritis atau perlu review manual |
| P2 | app/services/approval_service.py:158 | service | - | approve_request | 1 | 1 | tidak | commit berada di service non-kritis atau perlu review manual |
| P2 | app/services/approval_service.py:180 | service | - | reject_request | 1 | 1 | tidak | commit berada di service non-kritis atau perlu review manual |
| P2 | app/services/audit_log_service.py:241 | service | - | record_audit_log | 1 | 1 | tidak | commit berada di service infrastruktur/audit; tetap perlu boundary jelas tetapi bukan alur bisnis utama |
| P2 | app/services/bootstrap_service.py:121 | service | - | bootstrap_company | 1 | 1 | tidak | commit berada di service non-kritis atau perlu review manual |
| P1 | app/services/canteen_service.py:35 | service | - | _commit_or_rollback | 1 | 1 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah |
| P1 | app/services/cash_bank_service.py:13 | service | - | _commit_or_rollback | 1 | 1 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah |
| P2 | app/services/company_settings_service.py:239 | service | - | save_company_settings | 1 | 0 | tidak | commit berada di service non-kritis atau perlu review manual; tidak ada rollback eksplisit di fungsi yang sama |
| P2 | app/services/costing_transaction_service.py:10 | service | - | _commit_or_rollback | 1 | 1 | tidak | commit berada di service non-kritis atau perlu review manual |
| P2 | app/services/credit_account_service.py:199 | service | - | _in_transaction | 1 | 2 | tidak | commit berada di service non-kritis atau perlu review manual |
| P2 | app/services/credit_account_service.py:774 | service | - | _sweep_once_and_commit | 1 | 1 | tidak | commit berada di service non-kritis atau perlu review manual |
| P1 | app/services/daily_cash_service.py:159 | service | - | save_daily_cash | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/delivery_service.py:462 | service | - | create_delivery_from_order | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/delivery_service.py:523 | service | - | update_delivery_receipt | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/delivery_service.py:633 | service | - | create_shortage_replacement_delivery | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/delivery_service.py:674 | service | - | cancel_delivery | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P2 | app/services/digital_attachment_service.py:250 | service | - | save_digital_attachment | 1 | 1 | tidak | commit berada di service non-kritis atau perlu review manual |
| P2 | app/services/digital_attachment_service.py:398 | service | - | soft_delete_attachment | 1 | 0 | tidak | commit berada di service non-kritis atau perlu review manual; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/field_transaction_bridge_service.py:201 | service | - | bridge_to_operational_expense | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/field_transaction_bridge_service.py:284 | service | - | bridge_to_transport_expense | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/field_transaction_bridge_service.py:363 | service | - | bridge_to_advance_transaction | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/field_transaction_posting_service.py:276 | service | - | post_field_transaction | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/field_transaction_service.py:360 | service | - | create_field_counterparty | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/field_transaction_service.py:555 | service | - | create_field_transaction | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/field_transaction_service.py:658 | service | - | create_system_linked_field_transaction | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/field_transaction_service.py:814 | service | - | update_field_transaction_draft | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/field_transaction_service.py:899 | service | - | update_field_transaction_review_status | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/field_transaction_service.py:991 | service | - | attach_existing_digital_attachment_to_field_transaction | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/field_transaction_service.py:1072 | service | - | verify_field_transaction_attachment | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/field_transaction_service.py:1166 | service | - | link_field_transaction | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/field_transaction_settlement_service.py:472 | service | - | create_manual_receivable_for_field_transaction | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/field_transaction_settlement_service.py:590 | service | - | create_manual_payable_for_field_transaction | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/field_transaction_settlement_service.py:770 | service | - | record_manual_receivable_payment | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/field_transaction_settlement_service.py:950 | service | - | record_manual_payable_payment | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/finance_collection_service.py:8 | service | - | _commit_or_rollback | 1 | 1 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah |
| P1 | app/services/finance_collection_service.py:17 | service | - | _run_in_transaction | 1 | 1 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah |
| P1 | app/services/fixed_asset_depreciation_service.py:31 | service | - | _run_in_transaction | 1 | 1 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah |
| P1 | app/services/fixed_asset_depreciation_service.py:269 | service | - | configure_asset_depreciation | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/fixed_asset_depreciation_service.py:466 | service | - | post_asset_depreciation | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/fixed_asset_installment_service.py:458 | service | - | create_asset_financing_contract | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/fixed_asset_installment_service.py:619 | service | - | pay_installment_schedule | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/fixed_asset_purchase_service.py:25 | service | - | _run_in_transaction | 1 | 1 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah |
| P1 | app/services/fixed_asset_purchase_service.py:371 | service | - | create_fixed_asset_purchase | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P2 | app/services/geo_service.py:203 | service | - | save_distance_fee_settings | 1 | 1 | tidak | commit berada di service non-kritis atau perlu review manual |
| P1 | app/services/hpp_stock_consumption_service.py:437 | service | - | commit_hpp_stock_consumption | 1 | 6 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah |
| P1 | app/services/hr_service.py:77 | service | - | _commit_or_rollback | 1 | 1 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah |
| P2 | app/services/idempotency_service.py:81 | service | - | mark_idempotency_completed | 1 | 1 | tidak | commit berada di service non-kritis atau perlu review manual |
| P2 | app/services/idempotency_service.py:94 | service | - | mark_idempotency_failed | 1 | 1 | tidak | commit berada di service non-kritis atau perlu review manual |
| P1 | app/services/invoice_identity_service.py:14 | service | - | _run_in_transaction | 1 | 1 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah |
| P2 | app/services/location_photo_service.py:250 | service | - | _commit | 1 | 1 | tidak | commit berada di service non-kritis atau perlu review manual |
| P1 | app/services/logistics_transaction_service.py:25 | service | - | _commit_or_rollback | 1 | 1 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah |
| P2 | app/services/manual_backfill_billing_service.py:97 | service | - | _run_in_transaction | 1 | 1 | tidak | commit berada di service non-kritis atau perlu review manual |
| P2 | app/services/manual_backfill_billing_service.py:317 | service | - | create_manual_backfill_batch | 1 | 0 | tidak | commit berada di service non-kritis atau perlu review manual; tidak ada rollback eksplisit di fungsi yang sama |
| P2 | app/services/manual_backfill_billing_service.py:415 | service | - | update_manual_backfill_batch | 1 | 0 | tidak | commit berada di service non-kritis atau perlu review manual; tidak ada rollback eksplisit di fungsi yang sama |
| P2 | app/services/manual_backfill_billing_service.py:569 | service | - | lock_manual_backfill_batch | 1 | 0 | tidak | commit berada di service non-kritis atau perlu review manual; tidak ada rollback eksplisit di fungsi yang sama |
| P2 | app/services/manual_backfill_billing_service.py:647 | service | - | void_manual_backfill_batch | 1 | 0 | tidak | commit berada di service non-kritis atau perlu review manual; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/manual_backfill_billing_service.py:964 | service | - | create_invoice_from_manual_backfill_batch | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/manual_backfill_billing_service.py:1050 | service | - | sync_manual_backfill_batch_status_from_invoice | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P2 | app/services/manual_billing_service.py:38 | service | - | _run_in_transaction | 1 | 1 | tidak | commit berada di service non-kritis atau perlu review manual |
| P2 | app/services/master_data_service.py:77 | service | - | _commit_or_rollback | 1 | 1 | tidak | commit berada di service non-kritis atau perlu review manual |
| P2 | app/services/notification_service.py:374 | service | - | create_or_update_notification | 1 | 0 | tidak | commit berada di service non-kritis atau perlu review manual; tidak ada rollback eksplisit di fungsi yang sama |
| P2 | app/services/notification_service.py:383 | service | - | mark_notification_read | 1 | 0 | tidak | commit berada di service non-kritis atau perlu review manual; tidak ada rollback eksplisit di fungsi yang sama |
| P2 | app/services/notification_service.py:393 | service | - | mark_notification_unread | 1 | 0 | tidak | commit berada di service non-kritis atau perlu review manual; tidak ada rollback eksplisit di fungsi yang sama |
| P2 | app/services/notification_service.py:401 | service | - | mark_notification_dismissed | 1 | 0 | tidak | commit berada di service non-kritis atau perlu review manual; tidak ada rollback eksplisit di fungsi yang sama |
| P2 | app/services/notification_service.py:430 | service | - | resolve_generated_notifications_not_in | 1 | 0 | tidak | commit berada di service non-kritis atau perlu review manual; tidak ada rollback eksplisit di fungsi yang sama |
| P2 | app/services/notification_service.py:499 | service | - | generate_notifications_from_live_reminders | 1 | 0 | tidak | commit berada di service non-kritis atau perlu review manual; tidak ada rollback eksplisit di fungsi yang sama |
| P2 | app/services/opening_balance_service.py:157 | service | - | run_opening_action | 1 | 1 | tidak | commit berada di service non-kritis atau perlu review manual |
| P1 | app/services/operational_expense_service.py:24 | service | - | _run_in_transaction | 1 | 1 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah |
| P1 | app/services/operational_expense_service.py:315 | service | - | create_operational_expense | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/operational_service.py:13 | service | - | _commit_or_rollback | 1 | 1 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah |
| P1 | app/services/operational_service.py:50 | service | - | get_or_create_daily_order | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/operational_service.py:106 | service | - | add_or_update_order_detail | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/operational_service.py:439 | service | - | update_order_hpp_defaults | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/order_hpp_snapshot_service.py:440 | service | - | create_order_hpp_snapshot | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P2 | app/services/owner_capital_service.py:101 | service | - | record_owner_capital | 1 | 1 | tidak | commit berada di service non-kritis atau perlu review manual |
| P2 | app/services/partnership_service.py:202 | service | - | submit_partnership_request | 1 | 0 | tidak | commit berada di service non-kritis atau perlu review manual; tidak ada rollback eksplisit di fungsi yang sama |
| P2 | app/services/partnership_service.py:293 | service | - | update_partnership_request | 1 | 0 | tidak | commit berada di service non-kritis atau perlu review manual; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/period_closing_service.py:305 | service | - | post_period_closing | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P2 | app/services/portal_address_service.py:114 | service | - | _commit | 1 | 1 | tidak | commit berada di service non-kritis atau perlu review manual |
| P2 | app/services/portal_customer_registration_service.py:197 | service | - | register_portal_customer | 1 | 3 | tidak | commit berada di service non-kritis atau perlu review manual |
| P2 | app/services/portal_order_draft_service.py:113 | service | - | _commit_or_rollback | 1 | 1 | tidak | commit berada di service non-kritis atau perlu review manual |
| P2 | app/services/pricing_service.py:207 | service | - | set_portion_price | 1 | 1 | tidak | commit berada di service non-kritis atau perlu review manual |
| P2 | app/services/pricing_service.py:279 | service | - | set_general_min_portions | 1 | 1 | tidak | commit berada di service non-kritis atau perlu review manual |
| P2 | app/services/pricing_service.py:478 | service | - | _commit | 1 | 1 | tidak | commit berada di service non-kritis atau perlu review manual |
| P1 | app/services/production_service.py:152 | service | - | generate_production_from_order | 1 | 0 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah; tidak ada rollback eksplisit di fungsi yang sama |
| P1 | app/services/stock_service.py:186 | service | - | create_stock_movement | 1 | 1 | tidak | commit berada di service domain kritis; pastikan menjadi satu use-case boundary, bukan helper bawah |
| P2 | app/services/tax_service.py:971 | service | - | run_tax_reminders | 1 | 0 | tidak | commit berada di service non-kritis atau perlu review manual; tidak ada rollback eksplisit di fungsi yang sama |
| P2 | app/services/transport_expense_service.py:25 | service | - | _run_in_transaction | 1 | 1 | tidak | commit berada di service non-kritis atau perlu review manual |
| P2 | app/services/transport_expense_service.py:319 | service | - | create_transport_vehicle_expense | 1 | 0 | tidak | commit berada di service non-kritis atau perlu review manual; tidak ada rollback eksplisit di fungsi yang sama |
| P2 | app/services/user_management_service.py:297 | service | - | create_user | 1 | 0 | tidak | commit berada di service non-kritis atau perlu review manual; tidak ada rollback eksplisit di fungsi yang sama |
| P2 | app/services/user_management_service.py:323 | service | - | update_user | 1 | 0 | tidak | commit berada di service non-kritis atau perlu review manual; tidak ada rollback eksplisit di fungsi yang sama |
| P2 | app/services/user_management_service.py:336 | service | - | toggle_user_active | 1 | 0 | tidak | commit berada di service non-kritis atau perlu review manual; tidak ada rollback eksplisit di fungsi yang sama |
| P2 | app/services/user_management_service.py:352 | service | - | reset_user_password | 1 | 0 | tidak | commit berada di service non-kritis atau perlu review manual; tidak ada rollback eksplisit di fungsi yang sama |
| P2 | app/services/user_management_service.py:369 | service | - | change_own_password | 1 | 0 | tidak | commit berada di service non-kritis atau perlu review manual; tidak ada rollback eksplisit di fungsi yang sama |
| P2 | app/services/user_management_service.py:389 | service | - | update_portal_user_email | 1 | 0 | tidak | commit berada di service non-kritis atau perlu review manual; tidak ada rollback eksplisit di fungsi yang sama |

