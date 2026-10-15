# Tugas: UI desktop internal tahap 1 (CONTOH) — gaya biru seperti gambar referensi

ERP Flask/Jinja PT Idha Boga Pangan Mandiri (catering). Semua teks Bahasa Indonesia. Gambar referensi (dashboard "MediCore", biru) dilampirkan owner. Ambil **polanya**, jangan salin teks/medisnya, dan **jangan pakai label "AI"** (sistem tidak punya AI).

Tujuan: owner merasa UI sekarang datar, membosankan, tidak interaktif, "template AI". Ini **contoh** dulu; setelah owner setuju baru disebar ke semua halaman (jangan sentuh halaman lain di luar daftar ini).

## Batas wilayah (wajib)
- Hanya **desktop role internal** (OWNER, ADMIN, DAPUR) yang memakai `app/templates/layouts/base.html`.
- **Jangan ubah**: portal (role PORTAL_*/`app/templates/portal*`, `portal.css`, `portal_tailwind.css`), halaman publik/landing/login (`public.css`), aplikasi HP pengantar (`layouts/driver_mobile.html`) dan HP Admin Operasional (`layouts/ops_mobile.html`), cetakan (`print.css`).
- Halaman portal juga extends `base.html` → warna biru **di-scope** dengan class body, mis. `<body class="... shell-internal">` hanya bila `current_user.role` ∈ OWNER/ADMIN/DAPUR, lalu override token di `body.shell-internal { --brand-*: biru }`. Portal tetap oranye.

## Aturan CSS (ada tes penjaga)
- CSS hanya di sumber `app/static/css/app/{tokens,base,layout,components,pages}.css`, lalu jalankan `venv\Scripts\python.exe tools\build_css.py` (menghasilkan `app/static/css/style.css`). Jangan buat file CSS baru, jangan nama file "fix/override/patch".
- Warna hex hanya di `tokens.css` (anggaran hex di luar token ≤ 40), `!important` jangan bertambah. Tanpa mode gelap. Tanpa CDN (ApexCharts, Tom Select, Flatpickr sudah ada di `app/static/vendor`).
- Tes `tests/test_ui_ux_static_contracts.py::test_primary_orange_passes_contrast_with_white_text` → sesuaikan (nama & warna) agar memeriksa biru utama internal tetap kontras ≥ 4.5 dengan teks putih; tes lain di file itu jangan dilemahkan.
- `main.js` hanya perilaku; gaya di CSS.

## A. Kerangka (shell)
1. **Sidebar terang** (putih, garis tipis), item aktif = pil biru solid teks putih, sub-menu dengan garis vertikal tipis seperti gambar. Struktur menu & izin role **tidak berubah** (`layouts/sidebar.html`).
2. **Topbar**: kotak cari besar di tengah dengan petunjuk `Ctrl K`, lonceng notifikasi (sudah ada), kartu user (foto/inisial, nama, role).
3. **Pencarian global Ctrl+K**: route JSON baru `GET /search?q=` (login + branch-scoped, maks 5 hasil per jenis) → Pelanggan/Client, Sub client (Mandor), Invoice (nomor), Pesanan (nomor), Karyawan. Hasil berupa tautan ke halaman yang sudah ada. Panel hasil dengan navigasi panah atas/bawah + Enter. Hanya baca, tanpa ubah data.

## B. Dashboard OWNER & ADMIN (`dashboard/owner.html`, `dashboard/admin.html`)
Pakai data yang sudah ada di `dashboard_service.get_owner_dashboard_data` / `get_admin_dashboard_data` (+ `dashboard_analytics_service`, `credit_control_service`, `finance_receivables_service`, `data_health_service` bila perlu). **Jangan ubah logika uang.**
1. **4 kartu KPI** berikon: angka besar, panah naik/turun % vs bulan lalu, **sparkline 30 hari** (ApexCharts), kartu bisa diklik ke daftar terfilter. OWNER: uang masuk bulan ini, piutang berjalan, porsi terkirim, laba kotor. ADMIN: pesanan hari ini, pembayaran menunggu verifikasi, invoice jatuh tempo, pengiriman berjalan.
2. **3 kartu "Saran Sistem"** (pengganti kartu AI, berbasis aturan nyata), mis.: client tunggakan > 14 hari → tombol "Kirim pengingat"; porsi besok naik/turun > 20% vs rata-rata → "Cek stok"; Cek Kesehatan Data ada RISIKO → "Buka". Satu tombol aksi per kartu, tautan ke halaman yang sudah ada.
3. Grafik utama (donut/area) dari data yang sudah ada.
4. **Kolom kanan** (hanya di dashboard & halaman 360°): **Aktivitas terbaru** (dari `AuditLog`, 8 baris, ikon per jenis, jam WIB) dan **Peringatan** (kartu berwarna: merah/kuning, angka + tombol "Buka"), mis. pembayaran menunggu, pesanan belum dikunci, kontrak hampir habis, piutang jatuh tempo.

## C. Halaman 360° Pelanggan (BARU)
Route `GET /master/clients/<id>` (OWNER/ADMIN, branch-scoped) seperti kartu profil pasien di gambar. Dari daftar client (`master/clients`) nama client jadi tautan ke sini.
- Kartu profil: nama, jalur pelanggan, PIC, telepon, alamat, status kredit (`credit_control_service`), tombol "Ubah" (route edit yang sudah ada).
- Kartu: Kontrak aktif (`CustomerContract`, masa berlaku), Ringkasan tagihan (total piutang, terakhir bayar), Sub client/Mandor + lokasi.
- Timeline riwayat (pesanan, invoice, pembayaran, komplain) urut tanggal.
- Tab/tabel kecil: Pesanan terakhir, Invoice terakhir (status badge), Pembayaran terakhir, Hutang warung pekerja (bila modul aktif). Masing-masing "Lihat semua" ke halaman yang sudah ada.
- Kolom kanan: Aktivitas client ini + Peringatan client ini.
- Service baca-saja baru `app/services/client_360_service.py` (tanpa commit).

## Larangan keras
- JANGAN `git clean`, `git checkout -- .`, `git reset --hard`, `git add -A`, commit, push; jangan hapus file untracked.
- JANGAN sentuh `.env`, `storage/`, `instance/`, `app.zip`, `tools/reset_staging_demo.py`, tabel `ml_*`/`research_dataset_*`.
- JANGAN jalankan pytest, `flask db ...`, job, atau skrip ke database dev. Tanpa migrasi database.
- Jangan ubah logika uang/jurnal/izin role. Tanpa `except Exception: pass`.

## Selesai → laporkan singkat
Daftar file diubah/baru + perintah untuk owner:
```
venv\Scripts\python.exe tools\build_css.py
venv\Scripts\python.exe -m pytest -q tests/test_ui_ux_static_contracts.py tests/test_route_endpoint_references.py tests/test_exception_hygiene.py tests/test_admin_operasional_permissions.py tests/test_ops_navigation.py tests/test_portal_navigation.py
```
Sertakan juga: 3 screenshot yang perlu owner lihat (Dashboard Owner, Dashboard Admin, 360° Pelanggan).
