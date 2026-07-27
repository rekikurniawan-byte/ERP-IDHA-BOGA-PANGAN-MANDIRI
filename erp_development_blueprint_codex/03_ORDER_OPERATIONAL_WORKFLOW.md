# 03 — Order and Operational Workflow

## Alur utama
```text
Login → Pilih Lokasi → Tanggal → Shift → Menu → Porsi
→ Catatan → Konfirmasi → Validasi → Admin Konfirmasi
→ Produksi → Packing → Pengiriman → Selesai
→ Pembayaran/Invoice sesuai metode
```

## Status
Gunakan status existing terlebih dahulu. Penambahan/rename enum wajib compatibility mapping dan dapat memerlukan persetujuan.

Konsep minimum:
- Draft;
- Pending Confirmation;
- Approved;
- Hold;
- Production;
- Packing;
- Delivery;
- Completed;
- Cancelled.

## Cut-off
Setelah cut-off, order memerlukan approval atau ditolak sesuai konfigurasi. Codex tidak boleh menentukan policy default tanpa persetujuan.

## Perubahan order
- sebelum produksi: dapat diubah;
- setelah produksi: wajib approval;
- setelah packing: pembatalan tidak diperbolehkan;
- semua perubahan menyimpan before/after dan alasan.

## Pembatalan
Tidak boleh hard delete. Dampak payment, stock, production, dan journal harus atomik dan diaudit.

## Subscription order
Subscription hanya konfigurasi. Setiap occurrence harus menghasilkan order normal melalui service existing, bukan jalur transaksi paralel.

## Credit hold
Jika exposure + order baru melebihi limit, order menjadi HOLD. Threshold escalation tidak boleh ditentukan Codex tanpa persetujuan.

## Integrity
- nomor order immutable;
- tidak boleh delete setelah produksi;
- double-submit/retry tidak boleh membuat order ganda;
- lokasi order adalah snapshot/reference yang valid;
- perubahan harga tidak boleh mengubah order historis.
