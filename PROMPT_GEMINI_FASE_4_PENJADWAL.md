# TUGAS: Fase 4 — Penjadwal otomatis (fondasi tugas terjadwal)

Repo Flask ERP PT Idha Boga (Python 3.11, Flask, Jinja2, SQLAlchemy, Alembic, PostgreSQL, Windows PowerShell, `venv\`).
**Wajib baca dulu `RENCANA_PENGEMBANGAN_ERP.md` bagian 1 (aturan) dan bagian 6 (Fase 4).** Baca kode terkait sendiri; kalau tidak cocok dengan prompt, berhenti dan laporkan.

Sistem belum punya penjadwal. Fase ini membangun **mesinnya saja** + halaman status. Tugas bisnis yang memakainya (pesanan otomatis 18.00 = Fase 5, invoice 06.00 & pengingat bayar = Fase 6) **belum** dibuat — cukup sediakan cara mendaftarkannya.

## Aturan wajib
- Tidak ada commit/rollback di route; commit lewat `atomic_business_action` di service; service yang memanggil fungsi publik ber-commit kirim `commit=False`. Tidak ada except luas yang diam (except luas hanya di runner, wajib `logger.exception` + simpan error ke catatan run). Waktu `now_wib()/today_wib()`.
- Ikuti UI yang sudah ada (card `var(--radius-lg)`, tombol `var(--radius)`, tanpa hex baru, rapi di HP). CSS lewat `tools\build_css.py`.
- Migrasi baru: `down_revision` = head sekarang; daftarkan di test migrasi bila diminta.
- Jangan sentuh `.env`, `storage/`, `instance/`, `app.zip`, `tools/reset_staging_demo.py`, tabel `ml_*`/`research_dataset_*`. Jangan git add/commit/push. Jangan jalankan server. **Dilarang `git clean`, `git checkout -- .`, `git reset --hard`, atau menghapus file yang belum di-commit.**

## Desain (keputusan)
- **Tidak** memakai thread/APScheduler di dalam proses Flask (bisa jalan dobel saat reloader/beberapa worker, dan mati saat server restart).
- Satu perintah CLI **`flask jobs tick`** yang dipanggil **setiap 5 menit** oleh penjadwal sistem operasi (Windows Task Scheduler di laptop, cron/systemd timer di server). Setiap `tick` menjalankan semua tugas yang **sudah jatuh tempo** termasuk yang **terlewat** (catch-up).
- Idempoten: setiap tugas punya **kunci periode** (mis. `2026-10-08` untuk tugas harian, `2026-10-08T18:00` untuk tugas jam tertentu). Satu kunci periode hanya boleh berhasil **sekali** per cabang — dijaga **unique constraint** di database, bukan hanya cek di Python.
- Tidak boleh jalan bersamaan: pakai PostgreSQL advisory lock (`pg_try_advisory_lock`) per tugas; kalau sedang dipegang proses lain, lewati.

## Yang dikerjakan
1. **Model + migrasi** `scheduled_job_runs`: `job_key` (String 80), `branch_id` (nullable), `period_key` (String 40), `status` (`RUNNING`/`SUCCESS`/`FAILED`/`SKIPPED`), `started_at`, `finished_at`, `attempts` (int), `message` (Text), `result_json` (Text). Unique `(job_key, branch_id, period_key)`. Index pada `status`, `started_at`.
2. **`app/services/scheduler_service.py`**:
   - Registry: `register_job(key, label, schedule, handler, per_branch=True, enabled=True)`. `schedule` mendukung: `daily_at("18:00")` (WIB) dan `every_minutes(n)`.
   - `due_periods(job, now, last_success)` → daftar periode yang jatuh tempo, **maksimal 7 hari ke belakang** (catch-up dibatasi agar tidak membanjiri), urut lama → baru.
   - `run_due_jobs(now=None)` → untuk tiap tugas aktif dan tiap cabang aktif (bila `per_branch`): ambil periode jatuh tempo, kunci, buat baris `RUNNING`, panggil handler **dalam transaksinya sendiri**, set `SUCCESS` + `result_json`, atau `FAILED` + pesan error (rollback hanya pekerjaan handler, catatan run tetap tersimpan). Gagal di satu tugas/cabang **tidak menghentikan** yang lain.
   - Run `FAILED` dicoba ulang pada tick berikutnya, maksimal 3 percobaan per periode; setelah itu tetap `FAILED` sampai dijalankan manual.
   - `run_job_now(key, branch_id, period_key, user)` untuk tombol manual (OWNER/ADMIN), tetap menghormati idempotensi (periode yang sudah `SUCCESS` tidak dijalankan ulang kecuali dipaksa OWNER dengan alasan → tercatat di audit log).
3. **CLI** di `app/__init__.py` (ikuti pola perintah CLI yang sudah ada, mis. readiness): `flask jobs tick`, `flask jobs list`, `flask jobs run <key> [--branch ID] [--period KEY]`. Output ringkas Bahasa Indonesia; exit code ≠ 0 bila ada tugas `FAILED` pada tick itu.
4. **Tugas contoh** (hanya ini dulu): `heartbeat` — `every_minutes(5)`, tidak per cabang, mencatat waktu tick terakhir. Dipakai halaman status untuk tahu penjadwal hidup.
5. **Halaman "Tugas Otomatis"** (OWNER, ADMIN) di menu Pengaturan: daftar tugas (nama, jadwal, terakhir sukses, status terakhir, berikutnya), riwayat 50 run terakhir dengan filter status, tombol "Jalankan sekarang", dan **peringatan merah** bila `heartbeat` terakhir > 15 menit lalu: "Penjadwal tidak berjalan — tugas otomatis (pesanan 18.00, invoice 06.00) tidak akan jalan." Peringatan yang sama tampil ringkas di dashboard OWNER & ADMIN.
6. **Petunjuk pemasangan** (file baru `docs/PENJADWAL.md`, Bahasa Indonesia sederhana): langkah membuat tugas di **Windows Task Scheduler** (tiap 5 menit, perintah lengkap dengan path `venv\Scripts\python.exe -m flask jobs tick`, folder kerja proyek, jalan walau user tidak login), dan contoh **cron** / **systemd timer** untuk server Linux nanti. Sertakan cara cek berhasil (halaman Tugas Otomatis).

## Test (file baru `tests/test_scheduler_service.py`)
- Tugas harian 18:00: tick jam 17:59 → tidak jalan; 18:01 → jalan sekali; tick kedua 18:06 → tidak jalan lagi.
- Catch-up: tick terakhir 3 hari lalu → 3 periode dijalankan berurutan; lebih dari 7 hari → hanya 7 terakhir.
- Unique constraint mencegah dobel walau dua runner berjalan bersamaan (simulasikan insert kedua).
- Handler gagal → status `FAILED`, pekerjaan handler di-rollback, catatan run tersimpan; tugas lain tetap jalan; dicoba ulang maks 3 kali.
- `per_branch`: tiap cabang aktif dapat satu run.
- `run_job_now` menolak periode yang sudah `SUCCESS` kecuali OWNER memaksa dengan alasan (tercatat audit).
- Halaman Tugas Otomatis: OWNER/ADMIN bisa buka, DAPUR/PENGANTAR/portal ditolak; peringatan heartbeat muncul bila > 15 menit.
- CLI `flask jobs tick` jalan lewat `app.test_cli_runner()`.
Waktu di test di-mock (jangan bergantung jam asli).

## Verifikasi
```powershell
venv\Scripts\python.exe tools\build_css.py
venv\Scripts\python.exe -m pytest tests/test_scheduler_service.py tests/test_db_commit_audit_tool.py tests/test_exception_hygiene.py tests/test_numeric_migration_coverage.py -q
venv\Scripts\python.exe -m pytest -q
```
Semua harus lulus. Laporan akhir: file baru/diubah, hasil test **termasuk hasil `pytest -q` lengkap**, asumsi, perintah migrasi untuk owner (`venv\Scripts\python.exe -m flask db upgrade` — jangan dijalankan di database dev), langkah memasang Task Scheduler di laptop owner, langkah uji manual. Perbarui status Fase 4 di `RENCANA_PENGEMBANGAN_ERP.md` menjadi "✅ (belum commit)" dan tambah satu baris di "Riwayat perubahan".
