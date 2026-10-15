# TUGAS: Email wajib untuk semua akun portal (agar Lupa Password berfungsi)

Repo Flask ERP PT Idha Boga (Python 3.11, Flask, Jinja2, SQLAlchemy, Alembic, PostgreSQL, Windows PowerShell, `venv\`).
Fitur Lupa Password sudah ada (`app/services/password_reset_service.py`) dan mengirim link ke `User.email`. Masalah: akun portal tidak punya email karena form daftar tidak memintanya. **Baca kode yang relevan sendiri dulu**; kalau fakta di bawah tidak cocok, berhenti dan laporkan.

Fakta: `User.email` di `app/models/master.py` (String 150, nullable, **unique**). Daftar pelanggan: route `portal.register` (`/portal/register`, `app/routes/portal_routes.py`) → `register_portal_customer()` di `app/services/portal_customer_registration_service.py`, template portal `register.html`. Profil portal: route `/portal/profile`. Akun staf/portal dibuat admin lewat `create_user()` di `app/services/user_management_service.py` + `app/templates/settings/users.html`.

## Aturan wajib
- Tidak ada commit/rollback di route; tidak ada except luas yang diam (`tests/test_db_commit_audit_tool.py`, `tests/test_exception_hygiene.py`).
- Email selalu dinormalisasi: `strip().lower()`, validasi format sederhana, cek unik **case-insensitive** (`func.lower(User.email)`); pesan bentrok: "Email ini sudah dipakai akun lain."
- **Ikuti UI yang sudah ada** (kelas & token yang sama; card pakai `var(--radius-lg)`, input/tombol `var(--radius)`; tanpa hex baru). CSS di `app/static/css/app/*.css` lalu `venv\Scripts\python.exe tools\build_css.py`.
- Teks Bahasa Indonesia sederhana. Jangan sentuh `.env`, `storage/`, `app.zip`, `tools/reset_staging_demo.py`, tabel `ml_*`. Jangan git add/commit/push. Jangan jalankan server.

## Yang dikerjakan
1. **Form daftar pelanggan umum**: tambah field **Email (wajib)**, `type="email"`, dengan petunjuk "Dipakai untuk reset password dan kirim tagihan". Validasi di service (wajib, format, unik). Test lama yang memanggil register tanpa email: tambahkan email di test (jangan jadikan email opsional).
2. **Admin membuat akun portal** (role `PORTAL_CUSTOMER`, `PORTAL_CLIENT`, `PORTAL_SUBCLIENT`) di `create_user`/edit user: email **wajib** untuk role portal; untuk staf internal tetap opsional (jangan ubah perilaku staf). Validasi format + unik juga saat edit.
3. **Profil portal** (`/portal/profile`): user portal bisa menambah/mengubah emailnya sendiri (form + POST route baru, wajib isi password saat ini untuk konfirmasi bila mekanisme cek password sudah ada). Catat ke audit log.
4. **Pengingat**: user portal yang `email` kosong melihat banner di dashboard portal: "Lengkapi email Anda agar bisa reset password jika lupa." + tombol ke Profil. Banner hilang setelah email terisi.
5. **Admin reset password** dari menu Pengguna harus bisa dipakai untuk akun portal juga (bukan hanya staf) — cek; kalau belum, aktifkan. Ini cadangan untuk pelanggan tanpa email.
6. **Data demo**: di `tools/seed_demo_data.py` beri email unik ke akun demo portal (mis. `customer.demo@idhaboga.local`) supaya data demo konsisten.

## Test (file baru `tests/test_portal_account_email.py`)
- Daftar tanpa email ditolak; email format salah ditolak; email dipakai akun lain (beda huruf besar/kecil) ditolak; daftar valid menyimpan email lowercase.
- Admin buat akun portal tanpa email ditolak; akun staf tanpa email tetap boleh.
- User portal ubah email di profil berhasil; email bentrok ditolak.
- Banner muncul bila email kosong, hilang bila terisi.
- Lupa password untuk akun portal yang punya email → token dibuat & email dikirim (SMTP di-mock).

## Verifikasi
```powershell
venv\Scripts\python.exe tools\build_css.py
venv\Scripts\python.exe -m pytest tests/test_portal_account_email.py tests/test_password_reset.py tests/test_db_commit_audit_tool.py tests/test_exception_hygiene.py -q
venv\Scripts\python.exe -m pytest -q
```
Semua harus lulus. Laporan akhir: file diubah/baru, hasil test, asumsi, langkah uji manual singkat. Tidak perlu migrasi (kolom email sudah ada); kalau ternyata perlu, jelaskan alasannya dulu.
