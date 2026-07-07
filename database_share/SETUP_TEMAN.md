# Panduan Setup Sistem Idha Boga di Laptop Baru

Panduan ini untuk menjalankan sistem ERP Idha Boga di laptop lain (misal laptop teman),
lengkap dengan data yang sama persis.

---

## A. Prasyarat (Install Dulu)

1. **Python 3.11+** — https://www.python.org/downloads/
2. **PostgreSQL** — disarankan versi yang sama (PostgreSQL 11 via Laragon, atau PostgreSQL standalone)
3. **Git** — https://git-scm.com/downloads

---

## B. Clone Project dari GitHub

```cmd
git clone <URL_REPO_GITHUB>
cd idha_boga_pangan_mandiri_POSTGRES_ONLY_UI_SCOPED_VISUAL_CLEANUP
```

---

## C. Buat Database Kosong

Buka terminal PostgreSQL (psql) sebagai superuser (user `postgres`), lalu jalankan:

```sql
-- 1. Buat user aplikasi
CREATE USER idha_boga_user WITH PASSWORD 'IdhaBoga2026local';

-- 2. Buat database kosong
CREATE DATABASE idha_boga_staging OWNER idha_boga_user;

-- 3. Beri hak akses penuh
GRANT ALL PRIVILEGES ON DATABASE idha_boga_staging TO idha_boga_user;
```

Cara cepat lewat command line (sesuaikan path PostgreSQL):

```cmd
"C:\laragon\bin\postgresql\postgresql-11.0-1\bin\psql.exe" -U postgres -c "CREATE USER idha_boga_user WITH PASSWORD 'IdhaBoga2026local';"
"C:\laragon\bin\postgresql\postgresql-11.0-1\bin\psql.exe" -U postgres -c "CREATE DATABASE idha_boga_staging OWNER idha_boga_user;"
```

---

## D. Restore Data

Setelah database kosong dibuat, jalankan script restore:

```cmd
cd database_share
restore_database.bat
```

Atau manual:

```cmd
"C:\laragon\bin\postgresql\postgresql-11.0-1\bin\psql.exe" -U idha_boga_user -d idha_boga_staging -f idha_boga_staging_dump.sql
```

---

## E. Buat File .env

File `.env` TIDAK ikut di GitHub (alasan keamanan). Buat sendiri dengan menyalin contoh:

```cmd
copy .env.example .env
```

Isi `.env` minimal harus ada:

```
APP_ENV=development
FLASK_ENV=development
APP_DEBUG=1
SECRET_KEY=ganti-dengan-string-acak
DATABASE_URL=postgresql+psycopg://idha_boga_user:IdhaBoga2026local@localhost:5432/idha_boga_staging
```

---

## F. Install Dependencies & Jalankan

```cmd
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
flask run
```

Buka browser: http://127.0.0.1:5000

---

## Troubleshooting

| Masalah | Solusi |
|---------|--------|
| `pg_dump`/`psql` tidak dikenali | Sesuaikan path `PGBIN` di file .bat dengan lokasi PostgreSQL teman |
| Restore gagal "database does not exist" | Pastikan langkah C (buat database kosong) sudah dijalankan |
| Login gagal | User & data login ikut di dump, gunakan kredensial yang sama dengan laptop asal |
| Port 5432 bentrok | Ganti port di .env jika PostgreSQL teman pakai port lain |
