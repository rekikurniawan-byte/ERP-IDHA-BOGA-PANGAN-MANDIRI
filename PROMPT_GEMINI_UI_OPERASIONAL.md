# Tugas: rapikan UI modul OPERASIONAL (desktop) — fokus "hari ini" & kolom aksi

ERP Flask/Jinja PT Idha Boga Pangan Mandiri. Teks Bahasa Indonesia. Baca dulu pola yang sudah disetujui owner: `app/templates/dashboard/owner.html`, `dashboard/_pulse.html`, `master/client_360.html`, dan CSS blok "Komponen dasbor desktop internal" di `app/static/css/app/components.css`. Tiru polanya. Jangan riset web.

Keluhan owner (screenshot `/operational/orders`): halaman polos; pesanan HARI INI tidak beda dengan hari lain sehingga rawan salah pencet; kolom Aksi berisi 3 tombol berbeda lebar, tidak rata, dan tombol "Kunci" (tidak bisa dibatalkan) bersebelahan dengan tombol biasa.

## Ruang lingkup
`app/templates/operational/*.html`, `production/*.html`, `delivery/*.html` (desktop). Kecuali file cetak/label (`container_labels.html`, nama berisi `print`/`cetak`/`label`). JANGAN sentuh `ops/`, `driver*`, `portal/`, `layouts/`.

## A. Pola kolom aksi (berlaku di SEMUA tabel di ruang lingkup)
1. Maksimal **1 tombol utama** per baris = langkah berikutnya sesuai status (mis. Konsep → "Kunci"; Terkunci & produksi belum ada → "Sinkron Produksi"; selain itu → "Lihat Produksi"). Tombol lain masuk **menu ⋯**: `<div class="dropdown">` + `button.btn.btn-sm.app-btn-secondary` berikon `bi-three-dots-vertical` + `aria-label="Aksi lain"` + `data-bs-toggle="dropdown" data-bs-popper-config='{"strategy":"fixed"}'` + `ul.dropdown-menu.dropdown-menu-end.app-action-menu`.
2. Kolom aksi: rata kanan, lebar tetap, tidak membungkus (`white-space: nowrap`), semua tombol `btn-sm` tinggi sama.
3. Aksi yang tidak bisa dibatalkan (Kunci, Hapus, Batalkan) WAJIB minta konfirmasi memakai atribut konfirmasi yang SUDAH ada: `data-app-confirm="…"` (contoh pemakaian: `grep -rn "data-app-confirm" app/templates | head`; ikuti persis, termasuk atribut pendampingnya). Isi pesan memuat tanggal + total porsi, mis. "Kunci order 13-10-2026 (151 porsi)? Setelah dikunci, perubahan harus lewat revisi." Aksi hapus/batal di menu ⋯ diberi kelas `text-danger` dan dipisah `dropdown-divider`.
4. Nomor dokumen (No Order, No Pengiriman, dll.) jadi tautan ke halaman detail; tombol "Kelola Order" dipindah ke menu ⋯.
5. Form POST di dalam menu ⋯: tetap `<form method="POST" …>` dengan csrf yang sama, tombolnya `button.dropdown-item`.
6. Panel yang berisi menu ⋯ JANGAN diberi `data-rise` (menu akan tertutup panel lain).

## B. Halaman Order Harian (`operational/orders.html` + route `operational.orders`)
Susunan dari atas:
1. `header.dash-head`: "Order Harian" + tanggal hari ini (format "Selasa, 13 Oktober 2026") + tombol utama "Input Order".
2. **Kartu HARI INI** (paling menonjol): panel dengan garis kiri biru 3px + chip "Hari ini". Isi: No Order (tautan), langkah status (Konsep → Terkunci → Produksi → Dikirim; langkah aktif biru, selesai hijau — hanya dari data yang ada), porsi Siang / Sore / Total besar, jumlah lokasi, tombol utama besar sesuai status. Tidak ada order hari ini → keadaan kosong + tombol "Input Order hari ini".
3. **Kartu BESOK** di sebelahnya (lebih kecil, chip "Besok"), isi sama. Ingat: pesanan otomatis dibuat jam 18.00 untuk besok.
4. **Peringatan**: order bertanggal < hari ini yang masih belum dikunci → `a.alert-row.is-warn` "N order lewat tanggal belum dikunci" (tautan ke filter tabel). Hanya tampil kalau N > 0.
5. **Tabel Riwayat** di panel: filter tanggal memakai pola filter global yang sudah ada (contoh pemakaian: `app/routes/canteen_routes.py` → `resolve_date_filter`, `apply_date_range_to_query`, `build_filter_bar_context`; bawaan "bulan ini") + pembagian halaman 20 baris (belum ada komponen paginasi: pakai `query.paginate(page=…, per_page=20, error_out=False)` di route, lalu tautan "‹ Sebelumnya · Halaman x dari y · Berikutnya ›" sederhana di bawah tabel yang mempertahankan parameter filter). Kolom: Tanggal (dengan nama hari + chip "Hari ini"/"Besok"), No Order (tautan), **Status (satu kolom — gabungkan Status + Kunci)**, Lokasi, Siang, Sore, Total, Aksi (pola A).
   - Baris hari ini: latar `var(--brand-50)` + garis kiri biru. Baris lewat tanggal & belum dikunci: latar `var(--warning-bg)`.

Perubahan route yang BOLEH (hanya baca): kirim `today`, `tomorrow`, order hari ini & besok, jumlah siang/sore per order (dari `DailyOrderDetail.lunch_qty`/`dinner_qty`), jumlah order lewat tanggal belum dikunci, filter & paginasi. Data produksi/pengiriman hanya bila relasinya memang ada di model (cek `app/models/operational.py`, `production`, `delivery`); kalau tidak ada, langkah itu tidak ditampilkan. Pakai `today_wib()` dari `app.utils.clock`, BUKAN `date.today()`. Jangan ubah route POST.

## C. Halaman lain di ruang lingkup
Terapkan pemetaan yang sama seperti tahap 2 (`page-header`→`dash-head`, `app-card`→`panel`, judul kartu→`panel-head`, tabel dalam `panel-body flush`, kartu angka→`kpi` tanpa angka baru). Untuk setiap daftar berbasis tanggal (produksi, pengiriman, rekap dapur, jadwal menu, perubahan porsi): baris/kartu hari ini ditandai sama seperti B5, dan bagian "Hari ini" diletakkan paling atas bila halamannya sudah memisahkan hari ini.

## CSS
Hanya di `app/static/css/app/pages.css`, hanya `var(--…)` (tanpa hex, tanpa `!important`, sudut `var(--radius)`), lalu `venv\Scripts\python.exe tools\build_css.py`. Kelas baru diberi awalan `ops-` (mis. `.ops-day-card`, `.ops-row-today`, `.ops-row-overdue`, `.ops-steps`, `.ops-actions`). `main.js` sudah di batas 900 baris: JANGAN tambah JS.

## Larangan keras
- JANGAN mengarang angka/status/data; hanya dari query/model yang ada. Angka statis = dilarang.
- JANGAN ubah/hapus atribut `name`, `id`, `action`, `method`, `value`, `data-*`, csrf, input hidden, `url_for`, cek izin role; JANGAN ubah teks yang dicek tes (`grep -rn "<teks>" tests/` sebelum mengubah teks).
- JANGAN ubah service/model/migrasi/JS; JANGAN `git add/commit/checkout/reset/clean`, hapus file, pytest, `flask db`, skrip ke database dev; JANGAN sentuh `.env`, `storage/`, `instance/`.

## Periksa sendiri sebelum lapor (tempel hasil ringkas)
```
git diff --stat
git diff --stat -- app/services app/models app/static/js
git diff -U0 -- app/templates | findstr /R "^-.*name= ^-.*action= ^-.*method= ^-.*csrf ^-.*url_for ^-.*data-"
```
Perintah 2 harus kosong. Setiap baris hasil perintah 3 wajib punya pasangan `+` yang sama; kalau hilang, kembalikan.

## Lapor singkat
File diubah, file dilewati + alasan, hasil 3 perintah, lalu perintah untuk owner:
```
venv\Scripts\python.exe tools\build_css.py
venv\Scripts\python.exe -m pytest -q tests/test_ui_ux_static_contracts.py tests/test_route_endpoint_references.py tests/test_exception_hygiene.py tests/test_admin_operasional_permissions.py tests/test_ops_navigation.py
```
