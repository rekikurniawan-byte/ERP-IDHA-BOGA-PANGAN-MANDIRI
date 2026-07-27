# 05 — Delivery, Location, Contract, Complaint, and Documents

## Lokasi
Satu PT/customer dapat memiliki banyak lokasi proyek. Order menyimpan lokasi yang dipilih, bukan selalu lokasi utama.

Data minimum:
- nama;
- alamat;
- latitude/longitude;
- patokan;
- catatan;
- kontak;
- status aktif.

## Delivery
Kurir melihat order hari ini, lokasi, Google Maps, status, cash, dan riwayat. Gunakan Google Maps deep link; jangan membuat navigasi sendiri.

## WhatsApp
Tidak membuat chat internal. Gunakan WhatsApp deep link dengan pesan terisi otomatis untuk komunikasi kurir-pelanggan.

## Contract
- PT, PIC, nomor, mulai, selesai, termin, limit, dokumen, status, versi;
- tidak dihapus;
- perpanjangan membuat versi/contract baru;
- contract lama expired;
- notifikasi sebelum berakhir;
- perubahan limit/termin diaudit.

## Complaint
Kategori awal: makanan kurang/rusak, salah menu, terlambat, kurang porsi. Status: Open → In Progress → Resolved → Closed.

## Return/Correction
Mencatat penyebab, tindakan, nilai koreksi, order/delivery, approval, dan audit. Tidak boleh menimpa histori transaksi asli.

## Arsip dokumen
- contract;
- invoice;
- bukti transfer/payment;
- surat jalan;
- bukti serah terima;
- complaint/return.

Aturan:
- version history;
- file lama tidak ditimpa;
- private access;
- uploader dan timestamp;
- delete fisik perlu retention policy dan persetujuan.
