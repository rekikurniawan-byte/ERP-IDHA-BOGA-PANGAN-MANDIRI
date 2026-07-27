# Audit Rekonsiliasi Invariant ERP Idha Boga

Laporan ini read-only. Tujuannya membuktikan invariant finansial dan stok, bukan memperbaiki data otomatis.

## Ringkasan

| Audit | Jumlah Dicek | Status | Violations |
| --- | --- | --- | --- |
| Debit = Kredit | 14 | PASS | 0 |
| Invoice Payment Outstanding | 4 | PASS | 0 |
| Supplier Bill Payment Outstanding | 1 | PASS | 0 |
| Stock Movement Balance | 1 | PASS | 0 |
| Manual Backfill Duplicate Guard | 2 | PASS | 0 |

## Violations

| Audit | Area | Key | Severity | Masalah | Expected | Actual |
| --- | --- | --- | --- | --- | --- | --- |

## Catatan

| Audit | Catatan |
| --- | --- |
| Stock Movement Balance | Tanpa expected_balances fisik, audit stok belum bisa membandingkan saldo sistem dengan hasil stock opname resmi. |

## Invariant Yang Dicek

- Jurnal: total debit harus sama dengan total kredit.

- Invoice: `remaining_amount = total_amount - paid_amount`, `paid_amount <= total_amount`, dan total row payment sama dengan paid amount.

- Hutang supplier: `remaining_amount = total_amount - paid_amount`, `paid_amount <= total_amount`, dan total supplier payment sama dengan paid amount.

- Stok: qty movement tidak negatif dan movement_type harus dikenali. Expected balance bisa dipasok saat data master saldo tersedia.

- Manual backfill: batch aktif dengan business key sama dan invoice aktif dengan source sama dianggap duplikasi kritis.

