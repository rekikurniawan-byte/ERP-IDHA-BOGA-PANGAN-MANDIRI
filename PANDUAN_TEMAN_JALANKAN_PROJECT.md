# Panduan Lengkap Menjalankan ERP IDHA Boga di Laptop Teman

Panduan ini dibuat untuk teman yang belum terlalu paham Git, Python, PostgreSQL, atau Flask. Ikuti urutannya dari atas sampai bawah.

Repository GitHub:

```text
https://github.com/rekikurniawan-byte/ERP-BARU-IDHA-BOGA-PANGAN-MANDIRI.git
```

Project ini memakai:

- Python 3.11
- Flask
- PostgreSQL
- Database dump yang sudah disediakan di folder `database_share`

SQLite tidak dipakai.

## 1. Install Aplikasi yang Dibutuhkan

Install ini dulu satu per satu.

### 1.1 Install Git

Download:

```text
https://git-scm.com/downloads
```

Saat install, pilihan default boleh langsung Next sampai selesai.

Cek Git sudah terinstall:

```powershell
git --version
```

Kalau muncul versi Git, berarti aman.

### 1.2 Install Python 3.11

Download:

```text
https://www.python.org/downloads/release/python-3119/
```

Penting saat install:

- Centang `Add python.exe to PATH`.
- Lalu klik Install.

Cek Python:

```powershell
py -3.11 --version
```

Kalau muncul `Python 3.11.x`, berarti aman.

### 1.3 Install PostgreSQL

Download:

```text
https://www.postgresql.org/download/windows/
```

Saat install PostgreSQL:

- Catat password user `postgres`.
- Port biarkan default `5432`.
- Pastikan komponen PostgreSQL Server dan Command Line Tools ikut terinstall.

Cek PostgreSQL tools:

```powershell
psql --version
```

Kalau `psql` tidak dikenali, biasanya folder PostgreSQL belum masuk PATH. Coba cek lokasi ini:

```text
C:\Program Files\PostgreSQL\16\bin
C:\Program Files\PostgreSQL\15\bin
C:\Program Files\PostgreSQL\14\bin
C:\laragon\bin\postgresql\postgresql-11.0-1\bin
```

Kalau pakai Laragon, path PostgreSQL biasanya ada di `C:\laragon\bin\postgresql\...`.

## 2. Clone Project dari GitHub

Buka PowerShell.

Masuk ke folder tempat project ingin disimpan. Contoh di Downloads:

```powershell
cd $env:USERPROFILE\Downloads
```

Clone project:

```powershell
git clone https://github.com/rekikurniawan-byte/ERP-BARU-IDHA-BOGA-PANGAN-MANDIRI.git
```

Masuk ke folder project:

```powershell
cd ERP-BARU-IDHA-BOGA-PANGAN-MANDIRI
```

Cek isi folder:

```powershell
dir
```

Harus terlihat file seperti:

```text
README.md
requirements.txt
run.py
app
migrations
database_share
```

## 3. Buat Virtual Environment Python

Masih di folder project, jalankan:

```powershell
py -3.11 -m venv .venv
```

Aktifkan virtual environment:

```powershell
.\.venv\Scripts\Activate.ps1
```

Kalau muncul error `running scripts is disabled`, jalankan ini dulu:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Lalu ulangi:

```powershell
.\.venv\Scripts\Activate.ps1
```

Kalau berhasil, di depan baris terminal akan muncul `(.venv)`.

Install library Python:

```powershell
pip install -r requirements.txt
```

Tunggu sampai selesai.

## 4. Buat File Konfigurasi `.env`

File `.env` memang tidak diupload ke GitHub karena berisi konfigurasi lokal dan rahasia.

Buat dari contoh:

```powershell
Copy-Item .env.example .env
```

Buka file `.env`:

```powershell
notepad .env
```

Pastikan isinya minimal seperti ini:

```text
APP_ENV=development
FLASK_ENV=development
APP_DEBUG=1
SECRET_KEY=dev-local-idha-boga
DATABASE_URL=postgresql+psycopg://idha_boga_user:IdhaBoga2026local@localhost:5432/idha_boga_staging
UPLOAD_ROOT=instance/uploads
DIGITAL_ATTACHMENT_UPLOAD_DIR=instance/uploads/digital_attachments
SESSION_COOKIE_SECURE=0
```

Simpan file `.env`.

Catatan penting:

- `idha_boga_user` adalah user database aplikasi.
- `IdhaBoga2026local` adalah password database lokal untuk panduan ini.
- `idha_boga_staging` adalah nama database.
- Kalau password atau nama database diganti, `DATABASE_URL` juga harus ikut diganti.

## 5. Buat User dan Database PostgreSQL

Ada 2 cara. Pilih salah satu.

## Cara A: Lewat psql di PowerShell

Jalankan:

```powershell
psql -U postgres
```

Masukkan password user `postgres` yang dibuat saat install PostgreSQL.

Setelah masuk ke prompt `postgres=#`, jalankan SQL ini satu per satu:

```sql
CREATE USER idha_boga_user WITH PASSWORD 'IdhaBoga2026local';
```

```sql
CREATE DATABASE idha_boga_staging OWNER idha_boga_user;
```

```sql
GRANT ALL PRIVILEGES ON DATABASE idha_boga_staging TO idha_boga_user;
```

Keluar dari psql:

```sql
\q
```

Kalau user sudah pernah dibuat dan muncul error `role already exists`, tidak apa-apa. Lanjut saja.

Kalau database sudah pernah dibuat dan muncul error `database already exists`, lihat bagian reset database di bawah.

## Cara B: Lewat pgAdmin

1. Buka pgAdmin.
2. Login pakai password PostgreSQL.
3. Klik kanan `Login/Group Roles`, pilih `Create`, lalu `Login/Group Role`.
4. Isi Name:

```text
idha_boga_user
```

5. Tab Definition, isi Password:

```text
IdhaBoga2026local
```

6. Save.
7. Klik kanan `Databases`, pilih `Create`, lalu `Database`.
8. Isi Database:

```text
idha_boga_staging
```

9. Owner pilih:

```text
idha_boga_user
```

10. Save.

## 6. Buat Struktur Tabel dari Migration

Pastikan virtual environment masih aktif. Kalau belum, aktifkan lagi:

```powershell
.\.venv\Scripts\Activate.ps1
```

Set Flask app:

```powershell
$env:FLASK_APP="run.py"
```

Jalankan migrasi:

```powershell
flask db upgrade
```

Kalau berhasil, tidak ada error merah.

Kalau error koneksi database:

- Pastikan PostgreSQL menyala.
- Pastikan database `idha_boga_staging` sudah dibuat.
- Pastikan user `idha_boga_user` dan password sesuai dengan `.env`.
- Pastikan port PostgreSQL benar, biasanya `5432`.

## 7. Restore Database Terbaru

Database terbaru sudah ada di file:

```text
database_share/idha_boga_staging_dump.sql
```

Restore lewat PowerShell:

```powershell
psql "postgresql://idha_boga_user:IdhaBoga2026local@localhost:5432/idha_boga_staging" -f database_share/idha_boga_staging_dump.sql
```

Penting:

- Untuk aplikasi, URL memakai `postgresql+psycopg://`.
- Untuk command `psql`, URL memakai `postgresql://`.
- Jadi bagian `+psycopg` memang tidak dipakai saat restore lewat `psql`.

Kalau restore berhasil, biasanya muncul banyak tulisan `COPY`, `TRUNCATE TABLE`, dan `COMMIT`.

## 8. Jalankan Aplikasi

Pastikan masih di folder project dan virtual environment aktif.

Jalankan:

```powershell
python run.py
```

Buka browser:

```text
http://127.0.0.1:5000
```

Kalau berhasil, halaman login ERP akan muncul.

## 9. Cara Login

Data user login ikut dari database dump.

Gunakan akun yang biasa dipakai di laptop asal. Kalau tidak tahu passwordnya, minta ke pemilik project.

Beberapa username yang mungkin ada di database:

```text
owner
admin
finance
dapur
hr
pengantar
```

Password tidak ditulis di panduan ini supaya tidak bocor di GitHub.

## 10. Kalau Besok Mau Menjalankan Lagi

Tidak perlu clone ulang dan tidak perlu restore ulang database.

Cukup:

```powershell
cd $env:USERPROFILE\Downloads\ERP-BARU-IDHA-BOGA-PANGAN-MANDIRI
.\.venv\Scripts\Activate.ps1
python run.py
```

Buka:

```text
http://127.0.0.1:5000
```

## 11. Kalau Ada Update dari GitHub

Kalau pemilik project upload perubahan baru, jalankan:

```powershell
cd $env:USERPROFILE\Downloads\ERP-BARU-IDHA-BOGA-PANGAN-MANDIRI
git pull
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:FLASK_APP="run.py"
flask db upgrade
```

Kalau ada dump database terbaru dan ingin data ikut sama, restore ulang:

```powershell
psql "postgresql://idha_boga_user:IdhaBoga2026local@localhost:5432/idha_boga_staging" -f database_share/idha_boga_staging_dump.sql
```

## 12. Reset Database Kalau Mau Ulang dari Nol

Hati-hati: langkah ini menghapus database lokal di laptop teman.

Masuk psql sebagai postgres:

```powershell
psql -U postgres
```

Jalankan:

```sql
DROP DATABASE IF EXISTS idha_boga_staging;
```

```sql
DROP USER IF EXISTS idha_boga_user;
```

```sql
CREATE USER idha_boga_user WITH PASSWORD 'IdhaBoga2026local';
```

```sql
CREATE DATABASE idha_boga_staging OWNER idha_boga_user;
```

```sql
GRANT ALL PRIVILEGES ON DATABASE idha_boga_staging TO idha_boga_user;
```

Keluar:

```sql
\q
```

Lalu ulangi:

```powershell
$env:FLASK_APP="run.py"
flask db upgrade
psql "postgresql://idha_boga_user:IdhaBoga2026local@localhost:5432/idha_boga_staging" -f database_share/idha_boga_staging_dump.sql
```

## 13. Troubleshooting

### Error: `git is not recognized`

Git belum terinstall atau belum masuk PATH.

Solusi:

- Install Git dari `https://git-scm.com/downloads`.
- Tutup PowerShell.
- Buka PowerShell baru.
- Coba lagi `git --version`.

### Error: `py is not recognized`

Python belum terinstall atau belum masuk PATH.

Solusi:

- Install Python 3.11.
- Pastikan centang `Add python.exe to PATH`.
- Tutup PowerShell.
- Buka PowerShell baru.

### Error: `psql is not recognized`

PostgreSQL command line tools belum masuk PATH.

Solusi cepat, jalankan pakai path lengkap. Contoh:

```powershell
& "C:\Program Files\PostgreSQL\16\bin\psql.exe" --version
```

Kalau versi PostgreSQL berbeda, ganti `16` dengan versi yang terinstall.

Restore dengan path lengkap:

```powershell
& "C:\Program Files\PostgreSQL\16\bin\psql.exe" "postgresql://idha_boga_user:IdhaBoga2026local@localhost:5432/idha_boga_staging" -f database_share/idha_boga_staging_dump.sql
```

### Error: `password authentication failed`

Password database salah.

Solusi:

- Cek password di `.env`.
- Cek password user PostgreSQL `idha_boga_user`.
- Samakan keduanya.

### Error: `database "idha_boga_staging" does not exist`

Database belum dibuat.

Solusi:

- Ulangi langkah 5.

### Error: `relation does not exist`

Tabel belum dibuat.

Solusi:

```powershell
$env:FLASK_APP="run.py"
flask db upgrade
```

Lalu restore ulang database.

### Error: port 5432 sudah dipakai

PostgreSQL mungkin pakai port lain.

Solusi:

- Cek port PostgreSQL di pgAdmin atau file `postgresql.conf`.
- Ubah port di `.env`.
- Ubah port di command restore.

Contoh port 5433:

```text
DATABASE_URL=postgresql+psycopg://idha_boga_user:IdhaBoga2026local@localhost:5433/idha_boga_staging
```

```powershell
psql "postgresql://idha_boga_user:IdhaBoga2026local@localhost:5433/idha_boga_staging" -f database_share/idha_boga_staging_dump.sql
```

### Error saat `pip install`

Coba update pip:

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### Aplikasi jalan tapi browser tidak bisa buka

Pastikan terminal masih menjalankan:

```powershell
python run.py
```

Lalu buka:

```text
http://127.0.0.1:5000
```

Kalau port 5000 dipakai aplikasi lain, tutup aplikasi lain atau jalankan dengan port lain kalau project mendukung.

## 14. Checklist Cepat

Sebelum bilang gagal, pastikan semua ini sudah OK:

```text
[ ] Git sudah bisa: git --version
[ ] Python 3.11 sudah bisa: py -3.11 --version
[ ] PostgreSQL sudah nyala
[ ] psql bisa dipakai
[ ] Project sudah di-clone
[ ] .venv sudah dibuat
[ ] pip install -r requirements.txt sukses
[ ] .env sudah dibuat dari .env.example
[ ] DATABASE_URL di .env sudah benar
[ ] Database idha_boga_staging sudah dibuat
[ ] flask db upgrade sukses
[ ] restore dump sukses
[ ] python run.py sukses
[ ] browser buka http://127.0.0.1:5000
```

## 15. Urutan Command Ringkas

Kalau semua aplikasi sudah terinstall dan `psql` sudah bisa dipakai, ini versi ringkasnya:

```powershell
cd $env:USERPROFILE\Downloads
git clone https://github.com/rekikurniawan-byte/ERP-BARU-IDHA-BOGA-PANGAN-MANDIRI.git
cd ERP-BARU-IDHA-BOGA-PANGAN-MANDIRI

py -3.11 -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

Copy-Item .env.example .env
notepad .env
```

Buat database:

```powershell
psql -U postgres
```

Di dalam psql:

```sql
CREATE USER idha_boga_user WITH PASSWORD 'IdhaBoga2026local';
CREATE DATABASE idha_boga_staging OWNER idha_boga_user;
GRANT ALL PRIVILEGES ON DATABASE idha_boga_staging TO idha_boga_user;
\q
```

Lanjut:

```powershell
$env:FLASK_APP="run.py"
flask db upgrade
psql "postgresql://idha_boga_user:IdhaBoga2026local@localhost:5432/idha_boga_staging" -f database_share/idha_boga_staging_dump.sql
python run.py
```

Buka browser:

```text
http://127.0.0.1:5000
```
