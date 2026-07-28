# Batch 2A - Financial Visibility Impact Plan

Status: READY_FOR_BATCH_2B

Tanggal: 2026-07-28

Batch ini adalah dokumen impact plan saja. Tidak ada perubahan kode fitur, route, template, service, model, migration, atau data.

## 1. Baseline Yang Dipakai

Baseline aktif:

- tag `stage-1h-1o-complete`;
- Stage 1H sampai 1O sudah selesai;
- perubahan Batch 2A sampai 2F lama sudah dicabut dan tidak boleh dihidupkan ulang;
- portal eksternal memakai auth existing;
- portal ownership memakai `PortalUserMapping` dan `build_portal_external_scope`;
- draft order portal belum menyentuh invoice, payment, journal, stock, cash/bank, receivable, payable, closing, procurement, atau supplier.

Referensi penting:

- `storage/final_reports/BATCH_2_SCOPE_ROLLBACK_REPORT.md`;
- `storage/final_reports/STAGE_1H_TO_1O_EXECUTION_SUMMARY.md`;
- `erp_development_blueprint_codex/roadmap.md`.

## 2. Tujuan Stage 2

Stage 2 hanya membuka financial visibility secara read-only sesuai ownership portal.

Stage 2 bukan:

- payment gateway;
- upload bukti pembayaran;
- create payment;
- allocation payment;
- posting jurnal;
- perubahan piutang;
- perubahan invoice;
- perubahan closing;
- cash/bank reconciliation;
- profit/HPP visibility;
- procurement atau supplier visibility.

## 3. Existing Data Source

Data yang dapat dipakai ulang:

| Area | Existing Source | Catatan |
| --- | --- | --- |
| Invoice header | `Invoice` | Memiliki `client_id`, `mandor_id`, `bill_to_type`, `total_amount`, `paid_amount`, `remaining_amount`, `status`. |
| Invoice item | `InvoiceItem` | Untuk detail dasar jika nanti disetujui tampil. Batch awal cukup summary. |
| Payment | `Payment` | Terkait langsung ke `Invoice`; hanya read-only. |
| Receivable display | `finance_receivables_service.py` | Sudah punya helper bill-to identity. Harus dipakai hati-hati agar tidak bocor antar user. |
| Manual backfill | `ManualBillingBatch` dan `ManualBillingBatchItem` | Tidak otomatis dianggap visible sampai invoice final dan ownership jelas. |
| Manual receivable | `ManualReceivable` | Perlu validasi ownership sebelum masuk portal. |
| Worker debt | `WorkerDebt` | Masuk Batch 2C, bukan 2B. Harus diikat ke mandor/PT secara eksplisit. |
| Portal ownership | `PortalUserMapping`, `build_portal_external_scope` | Sumber kebenaran akses eksternal. |

## 4. Data Yang Boleh Ditampilkan

Untuk Batch 2B awal, data yang boleh tampil hanya summary read-only:

- nomor invoice;
- tanggal invoice;
- jatuh tempo;
- status invoice;
- tipe pihak ditagih;
- nama pihak snapshot yang memang milik user;
- total invoice;
- total sudah dibayar;
- sisa tagihan;
- jumlah payment terkait;
- status overdue sederhana.

Payment history Batch 2D boleh menampilkan:

- tanggal payment;
- metode;
- nominal;
- nomor referensi non-sensitif;
- nomor invoice terkait.

## 5. Data Yang Tidak Boleh Ditampilkan

Data berikut tidak boleh dibuka ke portal pada Stage 2 awal:

- jurnal akuntansi;
- COA;
- kas/bank ledger;
- rekening internal yang tidak perlu;
- HPP;
- margin/profit;
- payroll;
- supplier bill;
- procurement;
- stock valuation;
- dokumen bukti bayar fisik;
- nomor rekening lengkap jika bukan memang data instruksi pembayaran yang sudah disetujui;
- data invoice client/mandor lain;
- data branch lain tanpa ownership eksplisit;
- invoice cancelled/void sebagai piutang aktif.

## 6. Ownership Rules

Financial visibility wajib memakai ownership eksplisit dari `build_portal_external_scope`.

Aturan per role portal:

| Role | Scope Yang Boleh | Catatan |
| --- | --- | --- |
| `PORTAL_CLIENT` | Invoice dengan `client_id` dalam `scope.client_ids`. | Termasuk mandor di bawah client hanya jika scope resolver memasukkannya eksplisit. |
| `PORTAL_MANDOR` | Invoice dengan `mandor_id` dalam `scope.mandor_ids`. | Jangan tampilkan invoice client-level jika tidak ada `mandor_id` yang jelas. |
| `PORTAL_DELEGATE` | Hanya client/mandor/lokasi yang ada pada mapping aktif. | Akses harus dibatasi `access_level`; default read-only. |
| `PORTAL_CUSTOMER` | Belum boleh melihat financial detail penuh pada Stage 2. | Prepayment actual masuk Stage 3 dan perlu guard tersendiri. |
| Internal role | Tidak memakai portal financial read model kecuali untuk preview/testing. | Internal ERP existing tetap pakai route finance existing. |

Larangan ownership:

- tidak boleh memakai `branch_id` saja sebagai bukti ownership eksternal;
- tidak boleh menebak ownership dari nama snapshot bebas;
- tidak boleh menampilkan invoice tanpa `client_id`/`mandor_id` yang dapat dipetakan;
- tidak boleh menampilkan data `ManualReceivable` tanpa principal yang jelas;
- tidak boleh menampilkan worker debt ke client/PT jika relasi pekerja-mandor-client tidak terbukti.

## 7. Risiko Khusus

| Risiko | Dampak | Mitigasi |
| --- | --- | --- |
| Flexible bill-to snapshot tanpa ID master | Data bisa tampil ke pihak salah. | Hide dari portal sampai ada mapping eksplisit. |
| Invoice client-level dan mandor-level tercampur | Mandor bisa melihat invoice PT/client. | Query 2B harus memisahkan `client_id` dan `mandor_id`. |
| Cancelled/void masuk outstanding | Angka hutang salah. | Filter status aktif dan test cancelled/void. |
| Payment partial/overpayment | Outstanding salah. | Reconcile `remaining_amount = total - paid` dan payment sum. |
| Manual backfill duplikat | Outstanding terlihat dobel. | Batch 2B read-only harus pakai invoice final, bukan batch draft. |
| Batch 2 lama pernah menyentuh procurement/supplier | Scope melenceng. | Stage 2 baru eksplisit menolak procurement/supplier visibility. |

## 8. Batch 2B Yang Paling Aman

Batch 2B berikutnya harus dibatasi ke read model saja.

Scope 2B:

- tambah service read-only, misalnya `portal_financial_visibility_service.py`;
- service mengembalikan invoice/outstanding summary berdasarkan `build_portal_external_scope`;
- tidak membuat route/template jika read model belum lulus test;
- tidak melakukan commit/rollback;
- tidak membuat migration;
- tidak mengubah invoice/payment existing;
- tidak membaca jurnal/cash bank/procurement/supplier.

Target test 2B:

- unauthenticated tidak relevan karena service-level;
- authorized `PORTAL_CLIENT` hanya melihat invoice client miliknya;
- authorized `PORTAL_MANDOR` hanya melihat invoice mandor miliknya;
- delegate hanya melihat mapping eksplisit;
- customer umum menerima empty/blocked financial scope;
- invoice user lain tidak muncul;
- invoice branch sama tetapi bukan miliknya tidak muncul;
- cancelled/void tidak masuk outstanding aktif;
- payment sum sesuai paid amount;
- no database mutation;
- route commit/rollback tetap 0;
- full pytest lulus.

## 9. Batch 2C Sampai 2E

2C Mandor debt and worker debt detail:

- hanya setelah 2B lulus;
- worker debt harus punya relasi mandor/client yang jelas;
- tidak membuat invoice coverage baru;
- tidak mengubah hutang pekerja.

2D Payment history read-only:

- hanya payment yang terkait invoice visible;
- tidak membuka file bukti bayar;
- tidak membuat payment.

2E Closing visibility:

- hanya ringkasan read-only;
- tidak menjalankan closing;
- tidak mengubah status closing;
- tidak membuka jurnal detail.

## 10. Approval Required

Perubahan berikut tetap `APPROVAL REQUIRED` walaupun user sudah menyetujui roadmap umum:

- menampilkan dokumen bukti pembayaran/upload fisik;
- menampilkan detail item invoice yang bisa membuka harga internal sensitif;
- menampilkan jurnal, cash/bank, HPP, margin, procurement, supplier bill;
- mengubah schema atau migration;
- mengubah lifecycle invoice/payment/receivable;
- membuat payment, allocation, settlement, atau journal;
- menambah role/permission baru;
- mengubah business rule credit/prepayment.

## 11. Rollback Plan

Rollback Batch 2A:

```text
git revert <commit Batch 2A>
git tag -d batch-2a-financial-visibility-impact-plan
```

Karena batch ini dokumen saja, tidak ada rollback database.

## 12. Acceptance Criteria 2A

- impact plan tersedia;
- roadmap status tidak lagi mundur ke 1G;
- scope financial visibility jelas;
- procurement/supplier/stock/journal/cash bank/HPP tetap out of scope;
- next batch 2B dibatasi ke read model;
- tidak ada perubahan kode fitur;
- compile tetap lulus;
- full pytest lulus setelah PostgreSQL lokal aktif.

## 13. Verification

Hasil yang sudah dijalankan:

```text
.venv\Scripts\python.exe -m compileall app tests
PASS
```

Full pytest awalnya sempat blocked karena PostgreSQL lokal tidak reachable:

```text
DATABASE_URL=postgresql+psycopg://<user>:****@localhost:5432/idha_boga_staging
Test-NetConnection localhost:5432 => TcpTestSucceeded False
pg_isready/psql tidak tersedia di PATH
service PostgreSQL Windows tidak ditemukan
docker tidak tersedia di PATH
```

Gejala:

- pytest berjalan sampai area runtime database lalu tertahan;
- standalone query count ke app/database juga tertahan;
- proses dihentikan manual agar tidak menggantung terminal.

Kesimpulan verifikasi:

- perubahan Batch 2A adalah dokumen saja dan compile aman;
- setelah PostgreSQL lokal aktif kembali, database gate cleared.

Hasil verifikasi ulang setelah PostgreSQL aktif:

```text
Test-NetConnection localhost:5432 => TcpTestSucceeded True
tests/test_period_invoice_route_runtime.py => 1 passed, 3 warnings
.venv\Scripts\python.exe -m pytest -q => 309 passed, 32 warnings in 73.54s
```

## 14. Putusan

READY_FOR_BATCH_2B

Batch berikutnya yang aman adalah `2B - Invoice/hutang read model`, dimulai dari service read-only dan test ownership, bukan route/template penuh.
