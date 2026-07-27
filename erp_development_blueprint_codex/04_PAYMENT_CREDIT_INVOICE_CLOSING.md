# 04 — Payment, Credit, Invoice, and Closing

## Dua jalur pembayaran
### Pembayaran langsung
Untuk pelanggan umum: QRIS, transfer, atau cash. Prepayment wajib sebelum pemrosesan.

### Kredit/periodik
Hanya PT/mandor terverifikasi. Admin mengatur limit, periode, status kredit, dan contract.

## QRIS
Tahap awal: QRIS statis + bukti + verifikasi manual. Status tidak boleh otomatis lunas hanya karena bukti diunggah.

Payment gateway/webhook adalah tahap lanjutan dan `APPROVAL REQUIRED`.

## Transfer
```text
Upload bukti → Menunggu Verifikasi → Finance verifikasi
→ Payment dibuat → Allocation → Saldo/invoice diperbarui → Audit
```

## Cash
```text
Kurir menerima → Konfirmasi → Verifikasi internal
→ Kas bertambah → Payment tercatat → Status lunas
```
Kas tidak boleh bertambah hanya karena UI berubah.

## Cicilan
- satu invoice dapat dibayar berkali-kali;
- invoice tetap sama;
- saldo berkurang;
- histori lengkap;
- allocation tidak melebihi payment;
- saldo tidak negatif tanpa mekanisme overpayment resmi.

## Invoice
- tidak digabung antar-periode;
- hanya rekap piutang yang agregat;
- invoice terbit immutable;
- kesalahan diperbaiki melalui adjustment/reversal;
- nomor immutable dan tidak digunakan ulang;
- harga historis tetap.

## Closing periode
Konsep:
```text
OPEN → CLOSING → INVOICED → PARTIALLY_PAID/PAID → ARCHIVED
```
Closing mengunci transaksi periode. Perubahan aturan closing existing wajib persetujuan.

## Invariant wajib
- debit = kredit;
- invoice = subtotal + komponen sah;
- outstanding = invoice - allocation;
- payment/allocation konsisten;
- journal idempotent;
- tidak ada partial commit;
- retry tidak menggandakan invoice/payment/journal;
- void memakai reversal/adjustment, bukan delete.
