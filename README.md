# Sistem ERP IDHA Boga Pangan Mandiri

Project Flask ERP ini memakai PostgreSQL saja. Tidak ada fallback ke SQLite.

## Panduan Untuk Teman

Kalau mau menjalankan project ini di laptop baru, buka panduan lengkap ini:

```text
PANDUAN_TEMAN_JALANKAN_PROJECT.md
```

File itu berisi langkah detail dari install Git, Python, PostgreSQL, clone repo, restore database, sampai menjalankan aplikasi.

## Isi Repository

- Source code aplikasi Flask ada di `app/`.
- Migrasi database ada di `migrations/`.
- Contoh konfigurasi lokal ada di `.env.example`.
- Dump data terbaru untuk handoff ada di `database_share/idha_boga_staging_dump.sql`.

File `.env`, virtual environment, file log, upload runtime, dan backup lokal tidak ikut di-commit.

## Setup di Laptop Baru

Jalankan dari PowerShell:

```powershell
git clone <URL_REPOSITORY_GITHUB>
cd <NAMA_FOLDER_REPOSITORY>

py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

Copy-Item .env.example .env
```

Edit `.env`, terutama `SECRET_KEY` dan `DATABASE_URL`.

Contoh `DATABASE_URL` aplikasi:

```text
DATABASE_URL=postgresql+psycopg://idha_boga_user:password_database@localhost:5432/idha_boga_staging
```

## Setup PostgreSQL

Buat database kosong terlebih dahulu. Contoh lewat `psql`:

```powershell
createdb idha_boga_staging
```

Lalu buat schema dari migrasi:

```powershell
$env:FLASK_APP="run.py"
flask db upgrade
```

Restore data terbaru:

```powershell
psql "postgresql://idha_boga_user:password_database@localhost:5432/idha_boga_staging" -f database_share/idha_boga_staging_dump.sql
```

Catatan: `psql` memakai URL PostgreSQL standar, jadi hilangkan bagian `+psycopg` dari `DATABASE_URL`.

## Menjalankan Aplikasi

```powershell
.\.venv\Scripts\Activate.ps1
python run.py
```

Aplikasi berjalan di:

```text
http://127.0.0.1:5000
```

## Export Ulang Database

Kalau database lokal sudah berubah dan perlu dibagikan ulang:

```powershell
.\.venv\Scripts\Activate.ps1
python tools/export_database_share.py
```

File yang diperbarui:

```text
database_share/idha_boga_staging_dump.sql
```
