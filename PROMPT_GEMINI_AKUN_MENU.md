# TUGAS: (1) Halaman "Akun Saya" untuk semua role, (2) Menu harian dengan foto

Repo Flask ERP PT Idha Boga (Python 3.11, Flask, Jinja2, SQLAlchemy, Alembic, PostgreSQL, Windows PowerShell, `venv\`).
Kerjakan bagian 1 lalu 2. Setelah tiap bagian jalankan test terkait dan lapor singkat. **Baca kode terkait sendiri dulu**; kalau fakta di bawah tidak cocok, berhenti dan laporkan.

## Aturan wajib
- Tidak ada commit/rollback di route; commit lewat `atomic_business_action` di service; service yang memanggil fungsi publik ber-commit kirim `commit=False` (`tests/test_db_commit_audit_tool.py`). Tidak ada except luas yang diam (`tests/test_exception_hygiene.py`). Waktu pakai `now_wib()/today_wib()`.
- **Ikuti UI yang sudah ada**: kelas & token yang sama; card `var(--radius-lg)`, tombol/input `var(--radius)`; tanpa hex baru; rapi di HP 390px; tombol berjajar horizontal; tanpa dark mode. CSS di `app/static/css/app/*.css` lalu `venv\Scripts\python.exe tools\build_css.py`.
- Upload foto: pakai pola `app/services/location_photo_service.py` (validasi jpg/jpeg/png/webp, maks ukuran yang ada, resize opsional via Pillow kalau tersedia, file disimpan lewat `digital_attachment_service` di luar `static`, disajikan lewat route yang cek hak akses). Jangan simpan file di `app/static/uploads`.
- Migrasi baru: `down_revision` = head sekarang (cek `flask db heads`, seharusnya `b1c2d3e4f5a6`). Kolom uang `Numeric(18,2)`. Daftarkan migrasi di `tests/test_numeric_migration_coverage.py` / `tests/test_optimistic_locking_models.py` bila test itu memintanya (lihat contoh migrasi `a7b8c9d0e1f2`).
- Jangan sentuh `.env`, `storage/`, `instance/`, `app.zip`, `tools/reset_staging_demo.py`, tabel `ml_*`/`research_dataset_*`. Jangan git add/commit/push. Jangan jalankan server.

## BAGIAN 1 — "Akun Saya" (semua role: OWNER, ADMIN, DAPUR, PENGANTAR, dan semua akun portal)
Sekarang: staf punya `settings.change_password` (`app/routes/settings/account_routes.py`), portal punya `/portal/profile` (sudah bisa ubah email). Satukan pengalamannya:
1. **Satu halaman Akun Saya** per jenis akun (staf: route baru di blueprint settings, mis. `/settings/account`; portal: kembangkan `/portal/profile`). Isi, dalam kartu-kartu rapi:
   - **Foto profil**: unggah/ganti/hapus (lingkaran, crop tengah). Tampil di topbar/sidebar menggantikan inisial; tanpa foto → inisial seperti sekarang.
   - **Data diri**: nama lengkap, no. HP/WA, alamat (opsional), email (pakai validasi email yang sudah ada di `user_management_service`: normalisasi lowercase, unik case-insensitive; untuk akun portal tetap wajib).
   - **Ganti password**: password lama + baru + konfirmasi, pakai aturan kekuatan password yang sudah ada. Untuk staf, pakai/arahkan logika `change_password` yang ada (jangan duplikasi aturan).
   - **Info akun (baca saja)**: username, role (label Indonesia), cabang, terhubung ke client/sub client (untuk portal), terakhir login bila ada.
2. Perubahan nama/HP/alamat/email/foto/password menulis audit log. Mengubah email/password wajib isi password saat ini.
3. Username, role, cabang **tidak bisa** diubah sendiri (hanya admin lewat menu Pengguna).
4. Menu topbar (dropdown nama user) dan sidebar: item **"Akun Saya"** untuk semua role; "Ganti Password" lama boleh tetap ada tapi mengarah ke bagian password di Akun Saya.
5. Kolom baru di `users` bila belum ada (cek `app/models/master.py` class User): `phone` (String 30), `address` (Text), `avatar_attachment_id` (FK `digital_attachments.id`, nullable). Buat migrasi.
6. Test baru `tests/test_my_account.py`: tiap role bisa buka Akun Saya; ubah nama/HP; ganti password (salah password lama ditolak); email bentrok ditolak; upload & hapus foto; user lain tidak bisa melihat file foto yang bukan haknya bila route foto dibatasi; username/role tidak bisa diubah lewat form ini.

## BAGIAN 2 — Menu harian dengan foto (pelanggan **melihat saja**, tidak memilih)
Keputusan owner: dapur menentukan menu per tanggal & sesi; pelanggan hanya melihat. **Harga tetap per porsi seperti sekarang — jangan ubah perhitungan harga, tagihan, uang muka, invoice, atau jurnal.**
Sudah ada model `Menu` (`app/models/master.py`: `menu_code`, `menu_name`, `menu_type`, `default_selling_price`, `notes`, `is_active`, relasi resep). Cari halaman master menu yang ada dan kembangkan, jangan buat duplikat.
1. **Foto menu**: tiap menu bisa punya 1–3 foto (foto pertama = foto utama) + deskripsi singkat untuk pelanggan (kolom baru `description` Text). Kelola di halaman master menu (role OWNER, ADMIN, DAPUR).
2. **Jadwal menu**: tabel baru `menu_schedules` (`branch_id`, `menu_date`, `meal_type` LUNCH/DINNER, `menu_id`, `notes`; unik per branch+tanggal+sesi). Halaman "Jadwal Menu" per minggu (grid 7 hari × Siang/Malam) untuk mengisi/mengubah menu; tombol "Salin minggu lalu".
3. **Tampil ke pelanggan**:
   - Halaman pesan portal (`app/templates/portal/draft_order.html`): saat pelanggan memilih tanggal & sesi, tampilkan kartu **"Menu: <nama>"** dengan foto + deskripsi. Belum dijadwalkan → "Menu akan diinformasikan".
   - Dashboard portal: kartu **"Menu hari ini & besok"** (foto, Siang/Malam).
   - Landing page publik: bagian **"Menu minggu ini"** (hanya menu aktif yang dijadwalkan, foto utama + nama).
4. Rekap dapur (`kitchen_recap_service.py` / `operational/kitchen_recap.html`) menampilkan nama menu sesi itu di judul (kalau ada jadwal).
5. Data demo: di `tools/seed_demo_data.py` beri 4–6 menu dengan foto contoh (gambar sederhana dibuat Pillow seperti `location_photo` di seeder) dan jadwal 2 minggu.
6. Test baru `tests/test_menu_schedule.py`: CRUD jadwal + unik per sesi; "salin minggu lalu"; halaman pesan menampilkan menu terjadwal / teks "akan diinformasikan"; landing hanya menampilkan menu aktif; total harga draft **tidak berubah** dengan ada/tidaknya menu; role portal tidak bisa mengubah menu/jadwal.

## Verifikasi
```powershell
venv\Scripts\python.exe tools\build_css.py
venv\Scripts\python.exe -m pytest tests/test_my_account.py tests/test_menu_schedule.py tests/test_db_commit_audit_tool.py tests/test_exception_hygiene.py tests/test_numeric_migration_coverage.py -q
venv\Scripts\python.exe -m pytest -q
```
Semua harus lulus; jangan melemahkan test lama (test lama yang gagal karena aturan baru: sesuaikan datanya, sebutkan di laporan). Laporan akhir: file baru/diubah, hasil test, asumsi, perintah migrasi untuk owner (jangan dijalankan di database dev: `venv\Scripts\python.exe -m flask db upgrade`), langkah uji manual singkat.
