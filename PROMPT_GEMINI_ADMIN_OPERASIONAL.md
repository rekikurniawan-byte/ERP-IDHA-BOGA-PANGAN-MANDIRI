# Tugas: Role baru ADMIN_OPERASIONAL + aplikasi HP operasional

Kamu bekerja di repo ERP Flask ini. Baca dulu `RENCANA_PENGEMBANGAN_ERP.md` → "Riwayat perubahan" 2026-10-10 s.d. 2026-10-11 (aturan portal & pengantar: data asli, Tailwind lokal, satu pintu per halaman). Contoh yang SUDAH BENAR dan harus kamu tiru polanya:
- layout `app/templates/layouts/driver_mobile.html`, template `app/templates/driver/`, `app/services/driver_navigation_service.py`, `tests/test_driver_navigation.py`.

## Keputusan owner (jangan diubah)
1. Role baru `ADMIN_OPERASIONAL` (label "Admin Operasional"): hanya operasional, **dikunci di server** — tidak bisa membuka halaman keuangan/akuntansi/HR/gudang/pengaturan sama sekali (tolak 403/redirect seperti role lain).
2. Boleh MELIHAT nominal (harga porsi, total pesanan, status bayar) tapi tidak boleh mengubah/memverifikasi pembayaran atau membuat invoice.
3. Boleh sendiri: tambah porsi setelah dikunci (dengan alasan seperti sekarang), konfirmasi & **tolak** draf pesanan portal, buat/berangkatkan/**batalkan** pengiriman.
4. TIDAK boleh: meloloskan pesanan sebelum lunas — tetap khusus OWNER (cek `portal_order_draft_service.py` sekitar "diloloskan OWNER"; jangan longgarkan).
5. OWNER & ADMIN tetap pakai tampilan desktop lama; mereka juga BOLEH membuka aplikasi HP operasional ini.

## Lingkup halaman (ambil dari route yang sekarang dipakai ADMIN)
- `operational_routes.py`: pesanan harian (daftar, buat, detail, tambah detail, tambah setelah lock, revisi), `order-qty-changes`, `menu-schedule`, rekap dapur & label wadah per sesi, daily-log.
- `portal_routes.py`: `admin_order_drafts` + konfirmasi/tolak.
- `production_routes.py`: daftar, detail, realisasi.
- `delivery_routes.py`: semua yang dipakai ADMIN (buat dari order, dispatch, batal, terima, kurang kirim/pengganti, today/receiving/history/scan, lampiran).
- Komplain pelanggan (bila ada halaman admin komplain di `customer_success_routes.py`): lihat & tanggapi saja.
- KELUARKAN: HPP snapshot/stock consumption, monthly-recap keuangan, warung/kasir, apa pun di finance/accounting/settings/master (kecuali Akun Saya & notifikasi).
Tambahkan `ADMIN_OPERASIONAL` ke `role_required(...)` HANYA di route lingkup di atas. Daftarkan role di `user_management_service.py` (konstanta, `ROLE_LABELS`, pilihan role saat owner membuat user), `INTERNAL_ROLES` di `app/__init__.py`, dan tempat lain yang mendaftar role internal (cari `"PENGANTAR"` di app/ untuk menemukan daftar-daftar itu: dashboard redirect setelah login, notifikasi target_role, SOP, reminder).

## Aplikasi HP (layout `layouts/ops_mobile.html`, template `templates/ops/`)
Tab bawah: **Beranda · Pesanan · Dapur · Antar · Akun**
- Beranda: kondisi hari ini (jumlah pesanan & porsi per sesi, draf portal menunggu, produksi, pengiriman berjalan, kendala kurang kirim/komplain) — tanpa tombol pintasan.
- Pesanan: sub-tab Hari Ini · Draf Portal · Perubahan Porsi · Jadwal Menu.
- Dapur: sub-tab Produksi · Rekap Dapur.
- Antar: sub-tab Pengiriman · Serah Terima.
- Akun: Akun Saya, ganti password, SOP, Keluar (Keluar hanya di sini). Notifikasi hanya lewat lonceng.
- Detail/form memakai panah kembali, sub-tab disembunyikan di halaman rincian. Isi halaman hanya boleh link ke rincian satu baris.
- Pemilihan template di route: `driver/...` untuk PENGANTAR (sudah ada, jangan rusak), `ops/...` untuk ADMIN_OPERASIONAL, template lama untuk lainnya. OWNER/ADMIN membuka versi HP lewat satu pintu: `/ops` (route baru, redirect ke beranda ops) — beri satu tautan "Mode HP Operasional" di sidebar desktop mereka.
- Peta navigasi `app/services/ops_navigation_service.py` + context processor seperti driver.

## Aturan UI/UX & integritas (pelajaran dari kesalahan sebelumnya)
- DILARANG data contoh/hardcode, gambar internet, CDN. Semua dari variabel template. Library yang sudah lokal: `static/vendor/*` (termasuk `html5-qrcode`).
- Setiap form: `action`, `method`, nama field, `csrf_token`, `enctype`, atribut `data-*` HARUS sama dengan template lama; jangan ada fitur hilang (alasan wajib, konfirmasi `data-app-confirm`, upload foto, pilih pengantar, kunci order).
- Form filter GET pakai kelas `app-filter`. Flash pakai `alert alert-<kategori>`. Waktu UTC pakai `|wib`. Label Bahasa Indonesia + `term()`. Tanpa `hover:underline`. Tombol ≥44px, aksi utama besar di bawah.
- Tambah `./app/templates/ops/**/*.html` + layout ke `tools/portal_tailwind/tailwind.config.js`, lalu jalankan `tools\portal_tailwind\build.ps1`.
- Jangan ubah logika bisnis/service/model/migrasi. Role baru TIDAK butuh migrasi (kolom role string) — kalau ternyata ada constraint enum di DB, BERHENTI dan laporkan.

## Larangan keras
- JANGAN `git clean`, `git checkout -- .`, `git reset --hard`, hapus file untracked, `git add -A`, commit, push.
- JANGAN sentuh `.env`, `storage/`, `instance/`, `app/static/uploads/`, `tools/reset_staging_demo.py`.
- JANGAN jalankan pytest, `flask db ...`, job, atau skrip ke DB dev.

## Tes yang wajib kamu tulis
- `tests/test_ops_navigation.py`: satu pintu per halaman; halaman ops render 200 dengan `ops-mobile-shell` untuk ADMIN_OPERASIONAL; `/ops` bisa dibuka OWNER/ADMIN.
- `tests/test_admin_operasional_permissions.py`: ADMIN_OPERASIONAL DITOLAK di contoh halaman keuangan (mis. `/finance/...` invoice, pembayaran, kas), akuntansi, master, pengaturan; DIIZINKAN di halaman lingkup; tidak bisa meloloskan pesanan sebelum lunas.
- Tes pengantar & portal yang ada harus tetap lulus.
Akhiri laporan dengan daftar file diubah/dibuat dan perintah untuk owner:
`venv\Scripts\python.exe -m pytest -q tests/test_ops_navigation.py tests/test_admin_operasional_permissions.py tests/test_driver_navigation.py tests/test_portal_navigation.py tests/test_delivery_scan_flow.py`
