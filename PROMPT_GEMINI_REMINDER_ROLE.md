# TUGAS: Reminder hanya tampil sesuai role akun yang login

Repo Flask ERP PT Idha Boga (Python 3.11, Flask, Jinja2, SQLAlchemy, PostgreSQL, Windows PowerShell, `venv\`). **Baca kode terkait dulu**; kalau tidak cocok dengan prompt, berhenti dan laporkan.

Masalah: pusat reminder (`app/services/live_reminder_service.py`: `build_live_reminder_center(branch_id, ...)`, `build_live_reminder_badge_summary(branch_id, ...)`, dipakai di `app/__init__.py` `inject_live_reminder_badge` dan `app/routes/settings/notification_routes.py`, juga `notification_service.py` ±baris 441) hanya disaring per **cabang**, tidak per **role/akun**. Semua akun melihat semua reminder. (Notifikasi sudah benar per role — jangan diubah.)

## Aturan tampil (keputusan owner)
Seksi yang ada di `SECTION_LABELS`: `receivable`, `payable`, `stock`, `hpp_order`, `delivery`, `digital_proof`, `cash_bank`.

| Role | Seksi yang boleh dilihat |
|---|---|
| OWNER | semua |
| ADMIN (termasuk role lama FINANCE dsb. yang dipetakan ke ADMIN lewat `app/utils/roles.py`) | semua |
| DAPUR | `stock`, `hpp_order` |
| PENGANTAR | `delivery` **hanya pengiriman yang ditugaskan ke dia** (kalau model Delivery punya kolom pengantar/driver; kalau tidak ada, semua delivery cabangnya) + `digital_proof` **hanya bukti serah terima** pengirimannya |
| Akun portal (PORTAL_CUSTOMER / PORTAL_CLIENT / PORTAL_SUBCLIENT) | **tidak ada** reminder internal; badge & halaman reminder internal tidak tampil/ditolak |

## Yang dikerjakan
1. Tambah parameter `user` (atau `role` + `user_id`) ke `build_live_reminder_center` dan `build_live_reminder_badge_summary`; satu fungsi `allowed_reminder_sections(user)` sebagai satu-satunya sumber aturan tabel di atas. Seksi yang tidak diizinkan **tidak dihitung sama sekali** (jangan query lalu disembunyikan — supaya badge benar dan lebih cepat).
2. Badge reminder di layout/topbar/sidebar memakai hasil yang sudah disaring; cache-nya (`get_cached_value` di `app/__init__.py`) harus berkunci per role **dan** per user bila hasilnya bergantung user (pengantar).
3. Halaman/route reminder: role tanpa seksi apa pun (portal) → link tidak tampil dan route menolak (403/redirect).
4. Dashboard per role yang menampilkan ringkasan reminder ikut memakai aturan yang sama.
5. Aturan wajib: tidak ada commit/rollback di route, tidak ada except luas yang diam, ikuti UI yang ada (token radius/warna), CSS lewat `tools/build_css.py` bila ada perubahan CSS. Jangan sentuh `.env`, `storage/`, `app.zip`, `tools/reset_staging_demo.py`, tabel `ml_*`. Jangan git add/commit/push. Jangan jalankan server. **Dilarang `git clean`, `git checkout -- .`, `git reset --hard`, atau menghapus file apa pun yang belum di-commit (termasuk `app/static/uploads/`).** Baca juga `RENCANA_PENGEMBANGAN_ERP.md` bagian 1 sebelum mulai.

## Test (file baru `tests/test_reminder_role_scope.py`)
- Siapkan data yang memicu tiap seksi (piutang jatuh tempo, hutang supplier, stok kritis, delivery belum diterima, dll.).
- OWNER & ADMIN melihat semua seksi; DAPUR hanya `stock` + `hpp_order`; PENGANTAR hanya delivery miliknya (pengiriman pengantar lain tidak terhitung); akun portal: badge 0/tidak tampil dan halaman reminder ditolak.
- Jumlah di badge = jumlah item yang terlihat di halaman untuk role yang sama.

## Verifikasi
```powershell
venv\Scripts\python.exe -m pytest tests/test_reminder_role_scope.py tests/test_role_notification_sop_isolation.py tests/test_db_commit_audit_tool.py tests/test_exception_hygiene.py -q
venv\Scripts\python.exe -m pytest -q
```
Semua harus lulus. Laporan akhir: file diubah/baru, hasil test, asumsi (terutama: apakah delivery punya kolom pengantar), langkah uji manual per role.
