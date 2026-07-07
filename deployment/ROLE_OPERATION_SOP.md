# SOP Operasional Harian Per Role

**Project:** PT Idha Boga Pangan Mandiri  
**Status:** Sinkron dengan Tahap 10.31 — SOP Resync After System Changes  
**Berlaku untuk:** Realtime order, manual backfill, invoice/piutang, warung, logistics, payroll, accounting, settings, recovery, dan atomic UI.

---

## Prinsip Utama Sistem

1. Sistem punya dua jalur penagihan yang harus dipisahkan:
   - **REALTIME:** order harian → lock → produksi/delivery → invoice → piutang → pembayaran.
   - **MANUAL_BACKFILL:** input rekap dari buku → draft → edit bila perlu → lock → invoice/piutang → pembayaran.
2. Jalur REALTIME tidak dipakai untuk memaksa kasus buku lama, sarapan/pagi, pihak bebas, atau penyesuaian manual.
3. Jalur MANUAL_BACKFILL mendukung pihak ditagih fleksibel:
   - Mandor Existing
   - Client Existing
   - Kelompok
   - Perorangan
   - Client Lain
4. Pihak bebas manual backfill cukup memakai snapshot nama/no HP/alamat/catatan; tidak wajib membuat master mandor/client baru.
5. Keputusan proyek: **tidak membuat tabel `manual_book_recaps`** karena berisiko membuat jalur paralel yang tidak perlu.
6. Piutang sekarang dibaca melalui **Piutang Finance existing**, bukan modul piutang baru.
7. Pembayaran invoice tidak boleh bertanggal sebelum tanggal invoice.
8. Rekap manual tidak boleh dibuat invoice jika periode belum selesai atau ada tanggal catering dobel.
9. Atomic UI tidak mengubah flow bisnis; UI hanya memperjelas input, confirm, toast, loading, tabel, print, dan export.

---

## 1. OWNER — Pemilik / Direktur

### Tugas Harian
1. Buka `/dashboard/owner` untuk cek KPI order, invoice, payment, piutang, stok, payroll, warung, dan reminder.
2. Buka Finance → Piutang untuk memantau piutang gabungan realtime/manual backfill.
3. Cek invoice yang sebagian bayar, overdue, atau belum ada follow up.
4. Cek Data Health jika ada angka yang terasa janggal.
5. Cek Audit Log untuk transaksi penting: lock, void, invoice, payment, backup, restore, user change.

### Tugas Mingguan/Bulanan
1. Review laporan akuntansi: Trial Balance, General Ledger, Income Summary.
2. Review supplier bill, AP aging, fixed asset, cicilan aset, payroll, dan HPP.
3. Pastikan backup terbaru status VERIFIED sebelum patch besar.
4. Minta finance mencetak/export laporan Piutang Finance bila diperlukan.

### Catatan Penting
- Omzet invoice tidak sama dengan kas masuk.
- Mandor di realtime adalah PIC lapangan; mandor di manual backfill bisa menjadi pihak ditagih jika sumber buku memang begitu.
- Jangan restore sistem tanpa backup verified.

---

## 2. ADMIN — Operator Catering Realtime

### Tugas Harian
1. Login → buka `/dashboard/admin`.
2. Input order harian dari client/mandor/lokasi melalui Operasional → Order.
3. Pastikan detail porsi, batch, lokasi, harga, dan catatan benar.
4. Lock order yang sudah final.
5. Generate produksi setelah order locked.
6. Buat delivery setelah produksi selesai.
7. Pastikan bukti terima delivery masuk sebelum invoice periode dibuat finance.

### Batasan
- Jangan memasukkan sarapan/pagi ke realtime dengan manipulasi batch.
- Jangan memasukkan rekap buku lama ke realtime.
- Kasus sarapan/pagi, buku lama, warung/kasbon, kelompok/perorangan/client lain diarahkan ke Finance → Manual Backfill.

---

## 3. FINANCE — Invoice, Piutang, Manual Backfill, Kas/Bank

### Alur Realtime Invoice
1. Buka Finance → Invoice dan Pembayaran.
2. Generate invoice dari order/periode yang sudah locked dan valid.
3. Cek client, mandor/PIC, periode, item, total, dan bukti delivery.
4. Simpan invoice bila benar.
5. Cetak/kirim invoice.
6. Catat pembayaran dari detail invoice.
7. Pantau sisa piutang sampai PAID.

### Alur Manual Backfill dari Buku
1. Buka Finance → Manual Billing → Buat Rekap Manual dari Buku.
2. Pilih cabang, periode, kategori tagihan, dan tipe pihak ditagih.
3. Untuk Mandor Existing gunakan mandor master; untuk Client Existing gunakan client master.
4. Untuk Kelompok/Perorangan/Client Lain cukup isi snapshot nama pihak ditagih; PIC/master tidak wajib.
5. Isi baris catering. Baris mengikuti tanggal mulai-selesai.
6. Baris pertama boleh menjadi pola untuk sarapan/siang/sore/harga/catatan ke baris berikutnya, tetapi setiap baris tetap bisa diedit.
7. Gunakan Tambah Baris Catering atau Tambah Baris Warung jika ada penyesuaian.
8. Simpan DRAFT.
9. Edit draft jika ada salah input sebelum lock.
10. Void rekap jika salah dan belum punya invoice/piutang.
11. Lock rekap setelah benar.
12. Buat Invoice/Piutang dari rekap yang sudah locked.
13. Cetak rekap manual atau invoice bila perlu.
14. Catat pembayaran sebagian/lunas lewat flow invoice lama.

### Validasi Wajib
- Tanggal catering dobel dalam satu rekap ditolak.
- Invoice manual ditolak jika periode belum selesai.
- Payment ditolak jika tanggal bayar lebih awal dari tanggal invoice.
- Rekap VOID tidak boleh dibuat invoice.
- Rekap sudah invoice tidak boleh diedit/void.

### Piutang Finance
1. Buka Finance → Piutang.
2. Gunakan filter tipe pihak: Mandor, Client, Kelompok, Perorangan, Client Lain.
3. Gunakan filter cabang, periode, status, dan asal invoice realtime/manual backfill.
4. Baca grouping total per pihak ditagih.
5. Gunakan Print/Export CSV dari halaman existing.

---

## 4. ACCOUNTING — Jurnal, COA, Closing

### Tugas Harian
1. Buka Dashboard Accounting.
2. Cek Posting Status untuk invoice, payment, procurement, payroll, HPP, warung, dan transaksi manual.
3. Generate/post jurnal sesuai transaksi yang sudah final.
4. Buka Data Health untuk cek balance, FK, dan source trace.

### Dampak Jurnal Utama
- Invoice realtime/manual backfill: Dr Piutang Usaha / Cr Pendapatan.
- Payment invoice: Dr Kas/Bank / Cr Piutang Usaha.
- Warung cash/transfer: Dr Kas/Bank / Cr Pendapatan Warung.
- Hutang pekerja warung: Dr Piutang Karyawan / Cr Pendapatan Warung.
- Piutang warung eksternal: Dr Piutang Usaha / Cr Pendapatan Warung.
- Payroll posted: Dr Beban Gaji / Cr Hutang Gaji.
- Payroll paid: Dr Hutang Gaji / Cr Kas/Bank.
- HPP: Dr HPP / Cr Persediaan.

### Larangan
- Jangan closing sebelum transaksi penting diposting.
- Jangan hapus jurnal otomatis tanpa telusur sumber.
- Jangan membaca manual backfill sebagai jalur akuntansi terpisah; invoice tetap masuk Piutang Usaha existing.

---

## 5. WARUNG / CANTEEN

### Tugas Harian
1. Buka Warung/Canteen.
2. Input Quick Sale atau Penjualan Warung.
3. Pilih item, qty, harga, metode pembayaran, dan rekening jika QRIS/transfer.
4. Untuk hutang pekerja, wajib pilih pekerja.
5. Untuk piutang eksternal, isi pihak eksternal dengan jelas.
6. Saat pembayaran diterima, buka Hutang & Piutang Warung lalu catat pembayaran.

### Catatan
- Hutang pekerja tidak sama dengan piutang invoice catering.
- Piutang eksternal warung tidak dicampur ke manual backfill catering kecuali memang sumber tagihan perlu direkap manual oleh finance.

---

## 6. LOGISTICS — Stok, Pembelian, Supplier, HPP

### Tugas Harian
1. Cek stok menipis di Dashboard Logistics.
2. Proses permintaan barang dari dapur: approve/reject/fulfill.
3. Input pembelian bahan, qty, harga, supplier, dan bukti nota.
4. Catat stok keluar/pemakaian dapur.
5. Cek prediksi bahan sebagai referensi, bukan perintah final.
6. Audit stok berkala dan catat selisih.

### Catatan
- Pembelian kredit harus nyambung ke supplier bill/hutang supplier jika flow digunakan.
- HPP baru valid jika pemakaian stok/HPP diposting sesuai accounting.

---

## 7. DAPUR — Produksi

### Tugas Harian
1. Buka Dashboard Dapur atau Produksi Dapur.
2. Cek order locked untuk tanggal/batch terkait.
3. Mulai produksi sesuai data locked.
4. Jika bahan kurang, buat permintaan barang ke logistics.
5. Catat realisasi produksi setelah selesai.
6. Isi catatan jika realisasi berbeda dari rencana.

### Catatan
- Jangan masak berdasarkan order belum locked.
- Sarapan/pagi dari buku lama bukan flow dapur realtime; itu masuk manual backfill finance bila perlu ditagihkan.

---

## 8. DELIVERY / PENGANTAR

### Tugas Harian
1. Buka Pengiriman Hari Ini.
2. Pilih tugas sesuai lokasi/batch.
3. Update status dispatch/on the way sesuai proses.
4. Setelah diterima, isi jumlah diterima, waktu terima/SLA, dan catatan.
5. Upload bukti terima.
6. Catat shortage/replacement jika ada.

### Catatan
- Bukti terima adalah dasar penagihan.
- Delivery selesai bukan berarti invoice sudah dibayar.

---

## 9. HR — Payroll

### Tugas Bulanan
1. Buka Dashboard HR.
2. Pastikan data karyawan internal aktif dan gaji lengkap.
3. Generate payroll periode berjalan.
4. Cek detail payroll saat DRAFT.
5. Finalize payroll.
6. Post journal payroll.
7. Bayar payroll dan cek riwayat pembayaran.

### Catatan
- Mandor bukan karyawan payroll internal.
- Payroll FINAL belum berarti dibayar.

---

## 10. MASTER DATA

### Tugas
1. Cek data sebelum membuat master baru agar tidak dobel.
2. Pisahkan client/perusahaan, PIC client, mandor lapangan, pekerja warung, supplier, rekening, item, lokasi, driver, dan aset tetap.
3. Nonaktifkan data lama, jangan hapus jika pernah dipakai transaksi.
4. Untuk kelompok/perorangan/client lain manual backfill, tidak wajib dibuat master jika snapshot sudah cukup.

---

## 11. SETTINGS / SYSTEM

### Tugas
1. Kelola profil perusahaan dan user.
2. Reset/ganti password sesuai kebutuhan.
3. Cek Backup & Restore sebelum patch besar.
4. Cek System Health dan Audit Log.
5. Cek Lampiran Digital jika ada bukti yang tidak terbaca.
6. Cek Notifikasi/Reminder Live.
7. Jalankan Visual Sweep/Final Browser QA setelah update UI besar.

### Recovery
- Restore hanya manual-assisted.
- Stop server sebelum restore aktif.
- DB dan uploads harus dari backup timestamp yang sama.
- Gunakan hanya backup VERIFIED.

---

## 12. SOP UI OPERASIONAL

### Komponen UI yang Sudah Atomic
- Select/dropdown.
- Date input/date picker.
- Time input.
- Password show/hide.
- Confirm modal.
- Alert/toast.
- Flash notification tengah.
- Loading submit dan double-submit guard.
- File upload.
- Checkbox.
- Number input anti scroll accident.
- Text input dan textarea autosize.
- Table scroll/density.
- Print/export feedback.
- Page header/sidebar context.
- Badge/KPI/card/progress.

### Cara Pakai
1. Baca pesan modal sebelum konfirmasi aksi berisiko.
2. Jangan klik tombol simpan/bayar/invoice berkali-kali; tunggu loading selesai.
3. Perhatikan toast/flash tengah untuk sukses/error.
4. Jika field invalid, cek pesan validasi di dekat field.
5. Saat print/export, tunggu status proses.
6. Jika tampilan rusak, catat URL, role, screenshot, ukuran layar, dan langkah reproduksi.

---

## Aturan Umum Semua Role

1. Jangan share password.
2. Logout setelah selesai jika pakai device bersama.
3. Jangan edit database langsung.
4. Jangan buat jalur/tabel baru untuk transaksi yang sudah punya flow existing.
5. Jangan gunakan data DRAFT/VOID sebagai tagihan aktif.
6. Setiap perubahan angka penting harus bisa ditelusuri ke audit/source.
7. Jika ada error/bug, screenshot dan laporkan halaman, role, langkah, dan data contoh.
