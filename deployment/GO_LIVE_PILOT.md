# Panduan & Daftar Periksa Go-Live Pilot ERP
**PT Idha Boga Pangan Mandiri**

Dokumen ini disusun sebagai panduan langkah-demi-langkah bagi **Owner / Direksi** (bukan programmer) untuk memastikan kesiapan sistem sebelum dan saat memulai operasional perdana (Go-Live Pilot).

Setiap langkah dilengkapi kotak centang `[ ]`. Jangan melangkah ke tahap berikutnya sebelum tahap sebelumnya selesai diverifikasi.

---

## 1. Kesiapan Server & Infrastruktur

Bagian ini memastikan fondasi teknis server hosting production telah aman, stabil, dan siap pakai.

- [ ] **Domain & Sertifikat HTTPS Aktif**
  - Pastikan domain resmi (misal: `https://erp.idhabogapanganmandiri.com`) sudah dapat diakses dengan gembok hijau HTTPS yang valid.
  - HTTPS mutlak diperlukan agar fitur **kamera scan label wadah pengantar** di HP dapat berfungsi di dalam peramban web.
  - Konfigurasi Nginx mengacu pada `deployment/nginx/idha-boga.conf`.

- [ ] **Aplikasi & Database PostgreSQL Siap**
  - Pastikan database production PostgreSQL telah dimigrasikan ke versi terbaru:
    ```bash
    flask --app run db upgrade
    ```
  - Pastikan struktur direktori upload bukti digital (`instance/uploads/digital_attachments/`) memiliki izin akses yang aman (tidak disajikan langsung oleh web server, hanya via aplikasi).
  - Layanan Gunicorn berjalan stabil di latar belakang (`deployment/gunicorn.conf.py` dan `deployment/systemd/idha-boga.service`).

- [ ] **Pemeriksaan Kesiapan Operasional (0 FAIL)**
  - Jalankan perintah pemeriksaan mandiri runtime:
    ```bash
    flask --app run ops-check
    ```
  - **Syarat mutlak**: Hasil pemeriksaan harus menunjukkan **0 FAIL** sebelum sistem dibuka untuk pengguna.

- [ ] **Penjadwal Tugas Otomatis (Scheduler) Berjalan**
  - Pastikan `systemd timer` aktif di server Linux (atau Windows Task Scheduler bila memakai Windows Server):
    - `idha-boga-backup.timer` (pukul 02.00 WIB)
    - `idha-boga-ops-check.timer` (pukul 06.00 WIB)
    - `idha-boga-credit-sweep.timer` (pukul 00.30 WIB)
  - Buka menu web **Pengaturan → Tugas Otomatis** (`/settings/jobs`):
    - Pastikan banner hijau **"Penjadwal Otomatis Berjalan Normal"** aktif.
    - Pastikan detak terakhir (Heartbeat) tercatat kurang dari 15 menit yang lalu.

- [ ] **Backup Harian Otomatis & Uji Pulihkan (Restore Drill)**
  - Pastikan skrip backup harian berjalan sesuai `deployment/BACKUP_RESTORE_RECOVERY_SOP.md`.
  - Lakukan 1 kali simulasi uji pulihkan file backup di lingkungan uji/staging untuk memastikan file dump tidak rusak dan bisa direstore utuh.

- [ ] **Koneksi Email Notifikasi & Reset Password (.env)**
  - Pastikan akun Gmail resmi PT beserta **Google App Password** (16 karakter) sudah terpasang di berkas `.env` server (`MAIL_SERVER`, `MAIL_PORT`, `MAIL_USE_TLS`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_FROM`).
  - **PENTING**: Jangan pernah menuliskan isi kata sandi atau App Password ke dalam dokumen, chat, atau catatan umum.
  - Uji kirim email via fitur "Lupa Password" untuk memastikan email terkirim dengan lancar.

- [ ] **Pemantauan Log Error & Logrotate**
  - Pastikan file log aplikasi di `/var/log/idha-boga/error.log` tidak mencatat galat berulang.
  - Pastikan rotasi berkas log terpasang sesuai `deployment/logrotate/idha-boga`.

---

## 2. Urutan Pengisian Data Asli Perusahaan

Pengisian data awal **wajib mengikuti urutan di bawah ini**. Jangan melompat atau membalik urutan agar relasi antar master data dan pembukuan akuntansi tidak terputus.

- [ ] **Langkah 1: Profil Perusahaan**
  - **Menu**: `Pengaturan → Profil Perusahaan` (`/settings/company`)
  - **Data diisi**: Nama resmi perusahaan, logo resmi, alamat kantor pusat/dapur, nomor telepon/WhatsApp, NPWP perusahaan, nama penandatangan invoice, serta daftar rekening bank resmi PT (BCA/Mandiri/BRI) yang akan tampil di faktur dan invoice pelanggan.

- [ ] **Langkah 2: Pengaturan Pajak**
  - **Menu**: `Keuangan → Pajak → Pengaturan` (`/finance/tax/settings`)
  - **Data diisi**: Konfirmasi tarif PBJT katering (jika berlaku), tarif PPh 21 karyawan (centang tabel TER bulanan & Pasal 17, tentukan pihak penanggung PPh 21: Ditanggung Karyawan atau Perusahaan).

- [ ] **Langkah 3: Saldo Awal Pembukuan**
  - **Menu**: `Akuntansi → Saldo Awal` (`/accounting/opening-balances`)
  - **Data diisi**: Jalankan wizard saldo awal untuk mencatat saldo kas riil, saldo rekening bank operasional, saldo persediaan bahan baku awal, serta modal awal per tanggal cut-off go-live. Pastikan neraca awal seimbang (debit = kredit).

- [ ] **Langkah 4: Pelanggan (Client), Sub Client, Lokasi, dan Kontrak Kerja Sama**
  - **Menu**: `Data Master → Pelanggan` (`/master/clients`), `Sub Client` (`/master/mandors`), dan `Lokasi Pengiriman` (`/master/locations`)
  - **Menu Kontrak**: `Operasional → Kontrak Katering` (`/portal/admin/contracts`)
  - **Data diisi**:
    1. Daftarkan entitas Pelanggan/Perusahaan pemberi kerja (Client).
    2. Daftarkan Sub Client / PIC lapangan yang berhak memesan porsi.
    3. Daftarkan titik lokasi antar (beserta patokan dan nomor kontak penerima lapangan).
    4. Buat Kontrak Katering: tentukan pihak yang ditagih (Client atau Sub Client), siklus penagihan, anchor tagihan, tempo pembayaran (misal 7 hari), serta batas jam penguncian pesanan (Siang 10.00 WIB, Malam 15.00 WIB).

- [ ] **Langkah 5: Penentuan Harga & Sesi Makan**
  - **Menu**: `Pengaturan Kontrak / Data Master`
  - **Data diisi**: Tetapkan harga paket makan per porsi untuk masing-masing kontrak atau pelanggan umum, biaya ongkos kirim (jika ada), serta sesi makan aktif (Makan Siang / Makan Malam).

- [ ] **Langkah 6: Menu Makanan & Jadwal Menu**
  - **Menu**: `Dapur → Menu Makanan` (`/production/menus`)
  - **Data diisi**: Masukkan katalog menu masakan katering harian lengkap dengan foto makanan dan deskripsi lauk/sayur agar pelanggan dapat melihat jadwal sajian mingguan di portal.

- [ ] **Langkah 7: Pembuatan Akun Pengguna (User Per Role)**
  - **Menu**: `Pengaturan → Pengguna` (`/settings/users`)
  - **Data diisi**: Buat akun pengguna untuk masing-masing staf operasional sesuai tugasnya:
    - **OWNER**: Akun pimpinan/direksi dengan akses penuh pengawasan & persetujuan.
    - **ADMIN**: Staf administrasi katering & kasir kantor.
    - **ADMIN_OPERASIONAL**: Staf operasional lapangan/dapur yang memegang tablet/HP.
    - **DAPUR**: Kepala juru masak/koki untuk rekap porsi dan pencetakan label.
    - **PENGANTAR**: Kurir/driver lapangan untuk scan label wadah dan bukti serah terima.

- [ ] **Langkah 8: SDM — Aturan Gaji & Potongan**
  - **Menu**: `SDM → Penggajian → Aturan Gaji & Potongan` (`/sdm/aturan`)
  - **Data diisi**: Tentukan pembagi upah harian (Hari Kalender / 30 / 26), nominal denda pelanggaran kerja (mangkir, keluar lokasi tanpa izin, terlambat kembali, resign mendadak), batas plafon potongan upah bulanan (maks 50%), jam kerja harian, dan ketentuan penggunaan dana denda.

- [ ] **Langkah 9: SDM — Data Karyawan Internal**
  - **Menu**: `SDM → Karyawan & Kontrak → Daftar Karyawan` (`/hr/employees`)
  - **Data diisi**: Tambahkan profil seluruh karyawan dapur dan staf: NIK, nama lengkap sesuai KTP, status PTKP (TK/0, K/1, dll), nomor HP, jabatan, gaji pokok, serta nomor kontak darurat keluarga.

- [ ] **Langkah 10: SDM — Kontrak Kerja (PKWT/PKWTT)**
  - **Menu**: `SDM → Karyawan & Kontrak → Kontrak Kerja` (`/sdm/kontrak/buat`)
  - **Data diisi**: Susun draft kontrak kerja karyawan, minta karyawan menandatangani gores tanda tangan di layar HP + foto KTP, lalu Owner menandatangani kontrak. Isi kontrak akan otomatis dibekukan menjadi dasar perhitungan upah legal.

- [ ] **Langkah 11: Cetak & Pengajuan Peraturan Perusahaan**
  - **Menu**: `SDM → Penggajian → Aturan Gaji & Potongan → Draf Peraturan Perusahaan` (`/sdm/aturan/peraturan-perusahaan`)
  - **Tindakan**: Cetak dokumen draf Peraturan Perusahaan yang telah terisi parameter jam kerja dan denda, minta saran perwakilan pekerja, lalu ajukan pengesahan ke instansi ketenagakerjaan setempat (Disnaker).

- [ ] **Langkah 12: Apel Hari Pertama**
  - **Menu**: `Dapur → Apel Tim` (`/sdm/kehadiran/apel` di HP Admin Operasional / Desktop)
  - **Tindakan**: Jalankan pencatatan kehadiran apel pagi tim dapur dan pengantar hari pertama. Pastikan semua karyawan aktif tercatat berstatus Hadir.

---

## 3. Protokol Hari Pertama & Minggu Pertama

Pembagian tanggung jawab per peran (*Role*) untuk menjaga operasional berjalan lancar tanpa kendala:

### Pembagian Tugas Harian
| Peran (*Role*) | Tugas Utama Harian | Waktu Rutin |
|---|---|---|
| **ADMIN_OPERASIONAL** | • Buka HP menu **Dapur → Apel Tim**, centang apel seluruh tim (centang "Surat dokter" jika ada yang sakit).<br>• Cek order hari ini dan pastikan draf order pelanggan terkunci tepat waktu.<br>• Generate tiket produksi dapur dan buat daftar tugas pengiriman. | Pagi (06.30 - 08.00)<br>Batas Lock Siang (10.00)<br>Batas Lock Sore (15.00) |
| **DAPUR** | • Cek total porsi di **Rekap Dapur A4**.<br>• Masak sesuai rekap porsi dan nomor wadah.<br>• Cetak **Label Wadah** (Thermal / Stiker A4) dan tempelkan ke masing-masing wadah/rantang. | Sesi Siang (09.00 - 11.00)<br>Sesi Sore (14.00 - 16.30) |
| **PENGANTAR** | • Buka menu **Antar** di aplikasi HP pengantar.<br>• Muat wadah ke kendaraan dan klik **Berangkat**.<br>• Di lokasi client: buka tombol **Scan Label Wadah**, pindai QR label, ambil foto titik antar, minta tanda tangan penerima, lalu klik **Selesai Diantar**. | Menjelang jam makan siang & makan malam |
| **ADMIN** | • Pantau menu **Pembayaran Masuk** (`/finance/payment-inbox`), verifikasi mutasi rekening bank, klik **Terima & Konfirmasi** bukti bayar pelanggan.<br>• Tangani komplain atau perubahan porsi resmi bila ada permohonan tertulis.<br>• Cetak invoice periode katering untuk pelanggan korporat sesuai jadwal kontrak. | Sepanjang hari kerja |
| **OWNER** | • Pantau ringkasan bisnis di **Dashboard Owner**.<br>• Periksa **Ringkasan SDM** (kasus mangkir, permohonan izin, atau pengajuan kasbon).<br>• Lakukan persetujuan denda/kasbon bila diajukan.<br>• Lakukan pemeriksaan kesehatan data keuangan di akhir hari. | Pagi & Sore hari |

---

## 4. Rutinitas Cek Harian Owner (Wajib 0 Risiko)

Setiap sore atau malam sebelum operasional ditutup, **Owner** wajib melakukan 4 pemeriksaan singkat ini:

- [ ] **1. Cek Ringkasan SDM (`/sdm`)**
  - Pastikan tidak ada kasus mangkir yang belum ditindaklanjuti.
  - Pastikan apel seluruh staf telah terisi 100%.
  - Periksa peringatan kebutuhan tenaga kerja esok hari: pastikan jumlah pekerja cukup untuk memasak estimasi porsi besok.

- [ ] **2. Cek Pembayaran Masuk (`/finance/payment-inbox`)**
  - Pastikan tidak ada bukti transfer pelanggan yang tertahan atau belum diverifikasi lebih dari 2 jam.
  - Pastikan nominal pembayaran cocok dengan mutasi kas/bank riil.

- [ ] **3. Cek Tutup Harian Kasir / Warung (`/canteen/daily-close`)**
  - Jika modul warung/kantin aktif: pastikan kasir telah melakukan tutup kas harian dan fisik uang tunai cocok dengan catatan sistem.

- [ ] **4. Cek Kesehatan Data Akuntansi (`/accounting/health`)**
  - Buka menu **Akuntansi → Cek Kesehatan Data**.
  - **Syarat Mutlak**: Hasil diagnosa integritas pembukuan harus menunjukkan **0 RISIKO** (semua jurnal seimbang, saldo piutang klop dengan buku besar, tidak ada transaksi gantung tanpa jurnal).
