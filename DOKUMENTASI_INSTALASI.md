# Panduan Instalasi dan Setup Lingkungan Pengembangan
## Sistem ERP PT Idha Boga Pangan Mandiri

Dokumentasi ini adalah panduan resmi dan terstandarisasi untuk instalasi, konfigurasi, dan menjalankan sistem ERP PT Idha Boga Pangan Mandiri pada komputer lokal (*development environment*) maupun server *staging*.

---

## 1. Spesifikasi Sistem & Prasyarat

### 1.1 Persyaratan Perangkat Lunak

| Komponen | Versi Minimal | Keterangan |
|---|---|---|
| **Sistem Operasi** | Windows 10/11, Ubuntu 20.04+, macOS | Windows diutamakan menggunakan PowerShell |
| **Python** | 3.11.x (Disarankan 3.11.9) | Wajib centang *Add Python to PATH* |
| **Database** | PostgreSQL 14.x / 15.x / 16.x / 17.x | **Wajib PostgreSQL**. Sistem tidak memiliki fallback SQLite |
| **Git** | 2.30+ | Untuk manajemen versi dan update kode |
| **Browser** | Chrome, Edge, Firefox, Safari (Modern) | Untuk mengakses antarmuka ERP dan Portal |

---

## 2. Langkah Demi Langkah Instalasi

### Langkah 1: Clone Repository

Buka terminal (PowerShell di Windows atau Terminal di Linux/macOS) dan jalankan:

```powershell
# Pindah ke direktori kerja Anda (contoh: folder Projects atau Downloads)
cd $env:USERPROFILE\Downloads

# Clone repositori
git clone https://github.com/rekikurniawan-byte/ERP-BARU-IDHA-BOGA-PANGAN-MANDIRI.git

# Masuk ke direktori proyek
cd ERP-BARU-IDHA-BOGA-PANGAN-MANDIRI
```

---

### Langkah 2: Pembuatan Virtual Environment Python

Gunakan Python 3.11 untuk membuat lingkungan terisolasi (`.venv`):

#### Di Windows (PowerShell):
```powershell
# Jika muncul peringatan script execution policy, jalankan ini sekali:
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

# Buat virtual environment
py -3.11 -m venv .venv

# Aktifkan virtual environment
.\.venv\Scripts\Activate.ps1
```

> **Indikator Berhasil:** Di sisi kiri baris perintah terminal akan muncul label `(.venv)`.

#### Di Windows (Command Prompt / CMD):
```cmd
py -3.11 -m venv .venv
.\.venv\Scripts\activate.bat
```

#### Di Linux / macOS (Bash):
```bash
python3.11 -m venv .venv
source .venv/bin/activate
```

---

### Langkah 3: Instalasi Dependensi Python

Pastikan virtual environment telah aktif, lalu perbarui `pip` dan pasang seluruh paket yang tercantum pada `requirements.txt`:

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

#### Paket Utama yang Terpasang:
- **`Flask==3.1.1`**: Core web framework.
- **`Flask-SQLAlchemy==3.1.1`** & **`Flask-Migrate==4.1.0`**: ORM database dan migration manager.
- **`psycopg[binary]==3.2.4`**: Driver PostgreSQL generasi terbaru untuk Python.
- **`Flask-Login==0.6.3`**: Manajemen sesi autentikasi dan kontrol peran pengguna.
- **`Flask-WTF==1.2.2`**: Validasi form dan proteksi CSRF.
- **`Flask-Limiter==3.10.1`**: Pengamanan rate limiting endpoint otentikasi.
- **`python-dotenv==1.0.1`**: Loader variabel konfigurasi lingkungan `.env`.
- **`segno==1.6.1`**: Generator QR code pengiriman & pelacakan mandor.

---

### Langkah 4: Konfigurasi File Lingkungan (`.env`)

Sistem membaca konfigurasi runtime dari file `.env`. Salin template konfigurasi dari `.env.example`:

#### Di Windows (PowerShell):
```powershell
Copy-Item .env.example .env
notepad .env
```

#### Di Linux / macOS:
```bash
cp .env.example .env
nano .env
```

#### Nilai Parameter Kunci pada `.env`:
```ini
# Status Lingkungan
APP_ENV=development
FLASK_ENV=development
APP_DEBUG=1
PORTAL_ENABLED=1

# Kunci Keamanan Sesi (ganti dengan string acak untuk produksi)
SECRET_KEY=dev-local-idha-boga-secret-key-2026

# Koneksi PostgreSQL (Format: postgresql+psycopg://USER:PASSWORD@HOST:PORT/DBNAME)
DATABASE_URL=postgresql+psycopg://idha_boga_user:IdhaBoga2026local@localhost:5432/idha_boga_staging

# Folder Penyimpanan File Upload & Lampiran Digital
UPLOAD_ROOT=instance/uploads
DIGITAL_ATTACHMENT_UPLOAD_DIR=instance/uploads/digital_attachments
DIGITAL_ATTACHMENT_MAX_BYTES=5242880
DIGITAL_ATTACHMENT_ALLOWED_EXTENSIONS=jpg,jpeg,png,webp,pdf

# Folder Backup & Log
BACKUP_ROOT=instance/backups
BACKUP_STORAGE_DIR=instance/backups
LOG_ROOT=instance/logs
APP_LOG_FILE=instance/logs/app.log
ERROR_LOG_FILE=instance/logs/error.log

# Alamat Aplikasi Lokal
APP_BASE_URL=http://127.0.0.1:5000
SESSION_COOKIE_SECURE=0
LOGIN_RATE_LIMIT=5 per minute
RATELIMIT_STORAGE_URI=memory://
```

---

### Langkah 5: Persiapan Database PostgreSQL

Sistem memerlukan database PostgreSQL aktif dengan pengguna (*user role*) khusus. Anda dapat menyiapkannya melalui **Terminal `psql`** atau **pgAdmin 4**.

#### Cara A: Menggunakan Command Line `psql` (Direkomendasikan)

Buka terminal dan masuk ke konsol PostgreSQL dengan user administratif default (`postgres`):

```powershell
psql -U postgres
```
*(Masukkan password user postgres yang dibuat saat instalasi PostgreSQL)*

Setelah masuk ke prompt `postgres=#`, jalankan perintah SQL berikut:

```sql
-- 1. Buat user aplikasi
CREATE USER idha_boga_user WITH PASSWORD 'IdhaBoga2026local';

-- 2. Buat database staging dengan kepemilikan user tersebut
CREATE DATABASE idha_boga_staging OWNER idha_boga_user;

-- 3. Berikan hak akses penuh
GRANT ALL PRIVILEGES ON DATABASE idha_boga_staging TO idha_boga_user;

-- 4. Keluar dari psql
\q
```

> **Catatan:** Jika port PostgreSQL di komputer Anda bukan `5432` (misalnya port `5433` karena port default dipakai aplikasi lain), sesuaikan port pada perintah `psql -p 5433 -U postgres` dan di variabel `DATABASE_URL` pada file `.env`.

#### Cara B: Menggunakan GUI pgAdmin 4
1. Buka **pgAdmin 4** dan login ke server PostgreSQL Anda.
2. Klik kanan pada **Login/Group Roles** > **Create** > **Login/Group Role...**
   - General: Name = `idha_boga_user`
   - Definition: Password = `IdhaBoga2026local`
   - Privileges: Aktifkan `Can login?` = Yes.
   - Klik **Save**.
3. Klik kanan pada **Databases** > **Create** > **Database...**
   - General: Database = `idha_boga_staging`, Owner = `idha_boga_user`
   - Klik **Save**.

---

### Langkah 6: Eksekusi Migrasi Skema Database

Dengan virtual environment aktif, jalankan migrasi Alembic/Flask-Migrate untuk memastikan seluruh tabel, relasi, constraint, dan indeks terbuat secara valid:

```powershell
# Set environment variable untuk Flask
$env:FLASK_APP="run.py"

# Jalankan migrasi ke versi terkini
flask db upgrade
```

> **Verifikasi:** Jika tidak ada pesan error berwarna merah dan terminal kembali ke prompt, skema database berhasil dibuat.

---

### Langkah 7: Restore Data Awal / Staging Dump

Agar sistem memiliki data referensi awal (cabang, akun pengguna, menu, master data, dan alur kontrak), impor file dump staging yang telah disediakan:

```powershell
psql "postgresql://idha_boga_user:IdhaBoga2026local@localhost:5432/idha_boga_staging" -f database_share/idha_boga_staging_dump.sql
```

> **PENTING TENTANG PROTOKOL URL:**
> - Di file `.env` (Python SQLAlchemy), gunakan: `postgresql+psycopg://...`
> - Di terminal `psql` (CLI PostgreSQL), gunakan protokol standar: `postgresql://...` (tanpa `+psycopg`).

#### Alternatif Batch Script (Windows):
Tersedia script otomatis di `database_share\restore_database.bat`. Jika menggunakan script ini, buka file terlebih dahulu untuk memastikan variabel `PGBIN` sesuai dengan direktori instalasi PostgreSQL di komputer Anda (misal `C:\Program Files\PostgreSQL\16\bin`).

---

### Langkah 8: Kompilasi Aset CSS (Opsional / Developer)

Proyek ini menggunakan sistem CSS modular yang dikompilasi secara otomatis ke `app/static/css/style.css`. Jika Anda melakukan modifikasi token atau file CSS individual, jalankan generator CSS:

```powershell
# Menggunakan Python runner
python tools/build_css.py

# Atau menggunakan PowerShell script
powershell -ExecutionPolicy Bypass -File tools/build_css_runner.ps1
```

---

### Langkah 9: Menjalankan Server Aplikasi

Jalankan server aplikasi Flask:

```powershell
python run.py
```

Output pada terminal akan menampilkan:
```text
 * Serving Flask app 'run.py'
 * Debug mode: on
 * Running on http://127.0.0.1:5000 (Press CTRL+C to quit)
 * Restarting with stat
 * Debugger is active!
```

Buka peramban (browser) dan akses:
👉 **`http://127.0.0.1:5000`**

---

## 3. Akun Pengguna untuk Pengujian

Setelah data dump staging berhasil di-restore, Anda dapat login menggunakan akun yang tersedia pada database:

### Akun Internal ERP
| Username | Peran (*Role*) | Deskripsi Akses |
|---|---|---|
| `owner` | OWNER | Akses penuh seluruh modul bisnis, keuangan eksekutif, dan konfigurasi. |
| `admin` | ADMIN | Operasional katering harian, input order, master data, dan pelaporan. |
| `finance` | FINANCE | Keuangan, penagihan invoice, pembayaran, jurnal, dan laporan neraca. |
| `accounting` | ACCOUNTING | Audit akuntansi, rekonsiliasi bank, dan verifikasi buku besar. |
| `dapur` | DAPUR | Monitor porsi produksi, checklist bahan baku, dan SPK dapur. |
| `pengantar` | PENGANTAR | Penjadwalan armada kirim, rute pengantaran, dan konfirmasi bukti serah. |
| `hr` | HR | Manajemen karyawan, presensi, dan payroll / gaji. |
| `logistics` | LOGISTICS | Gudang, kontrol stok bahan baku, purchase order, dan penerimaan barang. |

### Akun Portal Eksternal
| Username | Peran Portal | Akses |
|---|---|---|
| `portal.pt.local` | PORTAL_PT | Portal perwakilan PT Kontrak: rekap porsi mandor & invoice. |
| `portal.mandor.local` | PORTAL_MANDOR | Portal mandor lapangan: perubahan porsi darurat & QR code penerimaan. |
| `portal.customer.local` | PORTAL_CUSTOMER | Portal pelanggan umum: pemesanan catering & upload bukti bayar. |

*Password standar lokal: `IdhaBoga#2026` atau `portal12345` (atau hubungi penanggung jawab proyek untuk kredensial staging khusus).*

---

## 4. Panduan Menjalankan Sehari-hari

Jika instalasi awal telah selesai, untuk menjalankan aplikasi di kemudian hari, Anda cukup menjalankan 2 perintah ini:

```powershell
# 1. Pindah ke folder proyek & aktifkan virtual environment
cd ERP-BARU-IDHA-BOGA-PANGAN-MANDIRI
.\.venv\Scripts\Activate.ps1

# 2. Jalankan server
python run.py
```

---

## 5. Pemeliharaan dan Sinkronisasi Kode Baru

Bila ada pembaruan kode dari repositori Git utama:

```powershell
# 1. Tarik pembaruan
git pull origin main

# 2. Aktifkan virtual environment
.\.venv\Scripts\Activate.ps1

# 3. Perbarui paket dependensi jika ada perubahan
pip install -r requirements.txt

# 4. Jalankan migrasi database skema baru
$env:FLASK_APP="run.py"
flask db upgrade

# 5. Kompilasi ulang CSS bila ada perubahan desain
python tools/build_css.py
```

### Ekspor Ulang Database Lokal (Bila Ingin Berbagi Data Terbaru):
Jika Anda mengubah data lokal dan ingin membagikan dump database terbaru ke anggota tim lain:
```powershell
python tools/export_database_share.py
```
File hasil ekspor otomatis diperbarui di: `database_share/idha_boga_staging_dump.sql`.

---

## 6. Penyelesaian Masalah (Troubleshooting)

### Kendala 1: Perintah `psql` Tidak Dikenali (`psql is not recognized`)
* **Penyebab:** Folder `bin` PostgreSQL belum terdaftar di variabel sistem `PATH` Windows.
* **Solusi Cepat:** Panggil `psql` menggunakan path lengkap (sesuaikan versi PostgreSQL yang terpasang di komputer Anda):
  ```powershell
  & "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U postgres
  ```
* **Solusi Permanen:** Tambahkan `C:\Program Files\PostgreSQL\16\bin` ke System Environment Variables `PATH`.

---

### Kendala 2: PowerShell Menolak Script Virtual Environment (`running scripts is disabled`)
* **Penyebab:** Kebijakan eksekusi (*Execution Policy*) PowerShell Windows membatasi script eksternal.
* **Solusi:** Jalankan perintah ini di sesi PowerShell Anda:
  ```powershell
  Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
  .\.venv\Scripts\Activate.ps1
  ```

---

### Kendala 3: Kesalahan Otentikasi Password Database (`password authentication failed`)
* **Penyebab:** Password user `idha_boga_user` di PostgreSQL berbeda dengan konfigurasi di file `.env`.
* **Solusi:** Buka `psql -U postgres` dan reset password user tersebut:
  ```sql
  ALTER USER idha_boga_user WITH PASSWORD 'IdhaBoga2026local';
  ```
  Pastikan nilai pada `.env` sama persis: `postgresql+psycopg://idha_boga_user:IdhaBoga2026local@localhost:5432/idha_boga_staging`.

---

### Kendala 4: Error `database "idha_boga_staging" does not exist`
* **Penyebab:** Database belum dibuat di PostgreSQL.
* **Solusi:** Buat database melalui `psql -U postgres`:
  ```sql
  CREATE DATABASE idha_boga_staging OWNER idha_boga_user;
  ```

---

### Kendala 5: Port 5000 Bentrok / Sudah Digunakan
* **Penyebab:** Aplikasi lain (misal servis Windows lain atau server web lokal) sedang mendengarkan port 5000.
* **Solusi:** Atur port alternatif melalui variabel lingkungan sebelum menjalankan `python run.py`:
  ```powershell
  $env:APP_PORT="5050"
  python run.py
  ```
  Akses di browser: `http://127.0.0.1:5050`.

---

### Kendala 6: Reset Database Penuh (Mulai dari Nol)
Jika data lokal rusak atau Anda ingin melakukan inisialisasi ulang total:
```powershell
psql -U postgres -c "DROP DATABASE IF EXISTS idha_boga_staging;"
psql -U postgres -c "CREATE DATABASE idha_boga_staging OWNER idha_boga_user;"
$env:FLASK_APP="run.py"
flask db upgrade
psql "postgresql://idha_boga_user:IdhaBoga2026local@localhost:5432/idha_boga_staging" -f database_share/idha_boga_staging_dump.sql
```

---

## 7. Checklist Verifikasi Instalasi

Gunakan checklist ini untuk memastikan seluruh tahapan telah terpenuhi:

- [ ] Python 3.11 terdeteksi (`py -3.11 --version` atau `python --version`)
- [ ] Git terdeteksi (`git --version`)
- [ ] PostgreSQL service aktif & `psql` dapat diakses
- [ ] Virtual environment `.venv` aktif (muncul tanda `(.venv)`)
- [ ] Seluruh dependensi terinstall tanpa error (`pip install -r requirements.txt`)
- [ ] File `.env` sudah dibuat dengan parameter `DATABASE_URL` yang valid
- [ ] Database `idha_boga_staging` dan role `idha_boga_user` telah dibuat
- [ ] Skema database termigrasi (`flask db upgrade`)
- [ ] Data dump staging berhasil di-restore (`idha_boga_staging_dump.sql`)
- [ ] Server berjalan normal (`python run.py`)
- [ ] Halaman login terbuka di browser `http://127.0.0.1:5000` dan dapat login
