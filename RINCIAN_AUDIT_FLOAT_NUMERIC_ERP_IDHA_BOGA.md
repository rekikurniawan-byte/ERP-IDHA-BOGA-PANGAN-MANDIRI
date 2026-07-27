# Audit Float ke Numeric ERP Idha Boga

Laporan ini dibuat dari parsing AST `app/models/*.py`. Tidak ada perubahan schema atau migration.

## Ringkasan

| Metrik | Nilai |
| --- | --- |
| Total Float di model | 0 |
| Money / rupiah | 0 |
| Quantity / stok / porsi | 0 |
| Ratio / persen | 0 |
| Perlu review manual | 0 |
| P0 kandidat migrasi uang | 0 |
| P1 kandidat migrasi qty/ratio | 0 |

## Sebaran Per File

| File | Jumlah Float |
| --- | --- |

## Gelombang Migrasi Bertahap

| Gelombang | Jumlah Field | Catatan |
| --- | --- | --- |
| P0A - uang finance/accounting | 0 | Ubah ke db.Numeric(18, 2), lalu rekonsiliasi jurnal, invoice, payment, AP/AR, cash/bank. |
| P0B - uang operasional/domain lain | 0 | Ubah ke db.Numeric(18, 2) setelah P0A stabil; cek biaya, HPP, aset, payroll, warung. |
| P1A - kuantitas/stok/porsi | 0 | Ubah ke db.Numeric(18, 4); cek stok, resep, porsi, procurement, konversi unit. |
| P1B - rasio/persen | 0 | Ubah ke db.Numeric(8, 4); tetapkan skala persen 0-100 atau 0-1 sebelum migrasi. |
| P2 - review manual | 0 | Klasifikasikan manual sebelum dibuat migration. |

## Kandidat P0

Prioritas pertama adalah field uang pada modul accounting, finance, field transaction, canteen, dan HR. Field ini paling dekat dengan invoice, payment, jurnal, kas, hutang/piutang, salary, dan closing.

| Priority | Lokasi | Model | Field | Kategori | Rekomendasi | Gelombang |
| --- | --- | --- | --- | --- | --- | --- |

## Rekomendasi Migrasi

- Jangan edit migration lama yang sudah pernah dipakai. Buat migration koreksi baru.

- Buat migration per gelombang, bukan satu migration raksasa. Setiap gelombang wajib punya snapshot nilai sebelum/sesudah dan laporan selisih.

- Konversi P0 lebih dulu ke `db.Numeric(18, 2)`, lalu rekonsiliasi invoice, payment, jurnal, kas, payable, receivable, dan payroll.

- Konversi quantity ke `db.Numeric(18, 4)` setelah alur uang stabil, terutama stok, porsi, recipe, dan procurement.

- Konversi ratio/persentase ke `db.Numeric(8, 4)` dengan normalisasi jelas: simpan 30.0000 untuk 30 persen bila sistem saat ini memakai skala 0-100.

- Ubah kalkulasi service kritis agar memakai `Decimal`, bukan `float`, sebelum/bersamaan dengan migration.

- Tambahkan regression test untuk pembulatan, partial payment, outstanding nol, debit-kredit balance, dan stock balance.

## Semua Field Float

| Priority | Lokasi | Model | Field | Kategori | Rekomendasi | Gelombang |
| --- | --- | --- | --- | --- | --- | --- |

