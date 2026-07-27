# 02 — Roles and Portals

## Aturan role
Codex wajib memetakan kebutuhan ke role existing sebelum membuat role baru. Jika permission existing cukup, jangan membuat role duplikat.

Target role:
- Administrator/Admin Utama;
- Finance;
- Gudang;
- Produksi;
- Kurir;
- Direktur/Owner viewer;
- PT;
- Mandor;
- Pelanggan Umum.

Perubahan role atau permission existing adalah `APPROVAL REQUIRED`.

## Pelanggan umum
- login dan profil;
- membuat order;
- memilih lokasi;
- melihat status dan riwayat;
- upload bukti pembayaran;
- komplain/retur bila relevan.

Aturan:
- tidak boleh kredit;
- wajib bayar di muka;
- pelanggan baru tidak boleh COD;
- order masuk `menunggu konfirmasi` dan belum diproses sebelum pembayaran terverifikasi.

## Mandor
- membuat order;
- melihat status;
- hutang catering dan warung;
- total hutang, cicilan, sisa;
- invoice dan histori pembayaran;
- detail hutang pekerja;
- multi-lokasi;
- subscription order;
- delegasi terbatas.

Mandor tidak boleh melihat data PT/mandor lain.

## PT
- melihat mandor di bawah PT;
- total piutang;
- invoice aktif/belum lunas;
- kontrak aktif dan masa berlaku;
- histori pembayaran;
- pembayaran sesuai workflow.

## Delegasi
Boleh membuat order dan melihat status. Tidak boleh mengubah kredit, contract, data PT, closing, adjustment, atau data finansial penuh.

## Test wajib
Setiap endpoint portal harus diuji untuk:
- unauthenticated;
- unauthorized;
- authorized;
- ownership/data scope;
- role viewer tidak dapat mutasi.
