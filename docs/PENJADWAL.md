# Panduan Pemasangan Penjadwal Otomatis (Scheduler Engine)
## PT Idha Boga Pangan Mandiri

Dokumen ini menjelaskan cara memasang dan mengonfigurasi pemicu penjadwal otomatis sistem ERP PT Idha Boga Pangan Mandiri.

---

## 1. Arsitektur & Prinsip Kerja

1. **Tanpa Background Thread di Flask**: Sistem sengaja tidak menggunakan thread/APScheduler di dalam aplikasi web agar tidak terjadi eksekusi dobel saat reload worker dan tidak mati saat server restart.
2. **Pemicu CLI Tunggal (`flask jobs tick`)**: Penjadwal sistem operasi (Windows Task Scheduler di laptop/PC lokal atau Cron/Systemd di server Linux) memanggil perintah `flask jobs tick` setiap 5 menit.
3. **Mengejar Ketinggalan (Catch-Up Otomatis)**: Setiap kali `tick` dijalankan, mesin akan memeriksa semua tugas yang jatuh tempo dan yang sempat terlewat (misal saat komputer mati), maksimal hingga 7 hari ke belakang. **Tugas yang baru pertama kali dipasang hanya menjalankan periode terbaru** (tidak mundur 7 hari), supaya tidak membuat pesanan/invoice untuk tanggal yang sudah lewat. Tugas yang terputus di tengah jalan (status *RUNNING* lebih dari 60 menit) otomatis diulang.
4. **Idempoten & Kunci Advisory**: Setiap periode tugas dilindungi oleh kunci periode unik di database dan *PostgreSQL Advisory Lock*, sehingga tidak akan pernah berjalan dobel meskipun dua proses berjalan bersamaan.
5. **Detak Sistem (`heartbeat`)**: Terdapat tugas bawaan detak sistem tiap 5 menit untuk memastikan penjadwal hidup. Jika detak mati lebih dari 15 menit, sistem akan menampilkan peringatan merah di dashboard Owner dan Admin.

---

## 2. Pemasangan di Windows (Windows Task Scheduler)

Untuk laptop/komputer operasional Owner/Admin berbasis Windows:

### Langkah-langkah:
1. Tekan tombol **Windows + R**, ketik `taskschd.msc`, lalu tekan **Enter** untuk membuka **Task Scheduler**.
2. Di panel sebelah kanan, klik **Create Task...** (Buat Tugas).
3. **Tab General (Umum)**:
   - **Name (Nama)**: `ERP Idha Boga - Penjadwal Otomatis`
   - **Description (Deskripsi)**: `Menjalankan tick penjadwal otomatis ERP PT Idha Boga setiap 5 menit.`
   - Pilih opsi: **Run whether user is logged on or not** (Jalankan baik pengguna sedang login maupun tidak).
   - Centang: **Run with highest privileges** (Jalankan dengan hak akses tertinggi).
4. **Tab Triggers (Pemicu)**:
   - Klik **New...** (Baru).
   - **Begin the task**: `At startup` (Saat sistem menyala) atau `On a schedule` (Harian, mulai jam 00:00).
   - Di bagian *Advanced settings*:
     - Centang **Repeat task every**: Pilih atau ketik `5 minutes` (5 menit).
     - **For a duration of**: `Indefinitely` (Tanpa batas waktu).
     - Centang **Enabled**.
   - Klik **OK**.
5. **Tab Actions (Tindakan)**:
   - Klik **New...** (Baru).
   - **Action**: `Start a program` (Mulai program).
   - **Program/script**: Path lengkap ke executable Python di virtual environment:
     ```text
     C:\Users\Acer\Downloads\ERP_PT_IDHA_BOGA_PANGAN_MANDIRI\venv\Scripts\python.exe
     ```
     *(Sesuaikan dengan folder proyek jika dipindahkan)*
   - **Add arguments (optional)**:
     ```text
     -m flask jobs tick
     ```
   - **Start in (optional)**: Path lengkap ke folder root proyek:
     ```text
     C:\Users\Acer\Downloads\ERP_PT_IDHA_BOGA_PANGAN_MANDIRI
     ```
   - Klik **OK**.
6. **Tab Conditions (Kondisi)**:
   - Hapus centang pada: *Start the task only if the computer is on AC power* (agar tetap jalan bila memakai baterai laptop).
7. **Tab Settings (Pengaturan)**:
   - Centang: *Allow task to be run on demand* (Bisa dijalankan manual kapan saja).
   - Centang: *Run task as soon as possible after a scheduled start is missed* (Jalankan secepatnya jika jadwal terlewat).
   - Klik **OK**. Masukkan password Windows akun Anda jika diminta.

---

## 3. Pemasangan di Server Linux (Cron atau Systemd Timer)

Bila nanti ERP dideploy ke server produksi (Ubuntu / Debian Linux):

### Opsi A: Menggunakan Cron (Sederhana)
Buka crontab:
```bash
crontab -e
```
Tambahkan baris berikut di baris paling bawah:
```cron
# Jalankan tick penjadwal otomatis ERP PT Idha Boga tiap 5 menit
*/5 * * * * cd /var/www/erp-idha-boga && /var/www/erp-idha-boga/venv/bin/python -m flask jobs tick >> /var/log/erp-jobs-tick.log 2>&1
```

### Opsi B: Menggunakan Systemd Timer (Standar Produksi Modern)
1. Buat file service `/etc/systemd/system/erp-scheduler.service`:
```ini
[Unit]
Description=ERP Idha Boga Penjadwal Otomatis Tick
After=network.target postgresql.service

[Service]
Type=oneshot
User=www-data
WorkingDirectory=/var/www/erp-idha-boga
ExecStart=/var/www/erp-idha-boga/venv/bin/python -m flask jobs tick
StandardOutput=journal
StandardError=journal
```

2. Buat file timer `/etc/systemd/system/erp-scheduler.timer`:
```ini
[Unit]
Description=Pemicu ERP Idha Boga Penjadwal Tiap 5 Menit

[Timer]
OnBootSec=1min
OnUnitActiveSec=5min
Persistent=true

[Install]
WantedBy=timers.target
```

3. Aktifkan timer:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now erp-scheduler.timer
```

---

## 4. Cara Memeriksa Keberhasilan Pemasangan

1. Masuk ke aplikasi web ERP sebagai **OWNER** atau **ADMIN**.
2. Buka menu **Pengaturan** di sidebar sebelah kiri, lalu klik **Tugas Otomatis** (`/settings/jobs`).
3. Periksa panel status di bagian atas:
   - **Jika Berhasil**: Tampil kotak hijau *"Penjadwal Otomatis Berjalan Normal"* dengan keterangan waktu detak terakhir kurang dari 15 menit.
   - **Jika Belum Berjalan**: Tampil kotak merah peringatan *"Penjadwal tidak berjalan — tugas otomatis (pesanan 18.00, invoice 06.00) tidak akan jalan."*.
4. Pada tabel **Daftar Tugas Terdaftar**, Anda dapat menekan tombol **"Jalankan Sekarang"** untuk menguji eksekusi manual kapan saja.
5. Tabel **Riwayat Eksekusi (50 Terakhir)** akan mencatat setiap kali tugas dieksekusi dengan status `SUCCESS` atau `FAILED` beserta detail pesannya.
