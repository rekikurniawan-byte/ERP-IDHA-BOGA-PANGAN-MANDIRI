# Tugas: sempurnakan 4 modul (Operasional, Produksi, Pengiriman, Warung) — tahap 3

ERP Flask/Jinja PT Idha Boga Pangan Mandiri. Teks Bahasa Indonesia. Tujuan owner: UI yang hanya masuk akal untuk bisnis katering ini (jam kunci, sesi Siang/Sore, dapur, armada, jam ramai warung) — BUKAN kartu generik ber-ikon + kalimat deskripsi panjang. Kerjakan A → G berurutan, lalu lapor. Jangan riset web.

Pola UI yang sudah disetujui (baca dulu): `app/templates/dashboard/owner.html`, `dashboard/_pulse.html`, `components/row_modal.html`, `operational/orders.html`, CSS blok "Komponen dasbor desktop internal" dan "Kolom aksi tabel" di `app/static/css/app/components.css`.

## FAKTA DATA (pakai ini, jangan menebak)
- Jam kunci per kontrak: `app/services/contract_rules_service.py` → `lock_time_for(client_id, meal_type, on_date=..., branch_id=...)` (meal_type `"LUNCH"`/`"DINNER"`). Waktu sekarang: `now_wib()`, `today_wib()` dari `app.utils.clock` (JANGAN `datetime.now()`/`date.today()`).
- Order: `DailyOrder(order_date, status, is_locked, locked_at)`, `DailyOrderDetail(mandor_id, delivery_location_id, lunch_qty, dinner_qty, total_qty)`.
- Produksi: `Production(production_date, production_type, status DRAFT/IN_PROGRESS/COMPLETED, target_ready_time, actual_completed_time, late_tolerance_minutes)`. Cek nilai `production_type` di `app/services/production_service.py` sebelum memetakan ke Siang/Sore.
- Pengiriman: `Delivery(delivery_date, status, target_dispatch_time, target_arrival_time, actual_departure_time, late_tolerance_minutes)`, `DeliveryDetail(daily_order_detail_id, delivery_location_id, planned_qty, delivered_qty)`, waktu terima `receive_time` (model penerimaan di `app/models/delivery.py`). Jenis sesi pengiriman: helper `get_delivery_type_from_notes` di `app/routes/delivery_routes.py`.
- Lokasi: `DeliveryLocation.latitude`, `.longitude` (Numeric, bisa kosong).
- Wadah: `get_kitchen_max_portions_per_container(branch_id)` di `app/services/kitchen_recap_service.py`; label wadah: endpoint `operational.container_labels` (order_id, sesi).
- Warung: `CanteenSale(created_at UTC, sale_date, payment_method CASH/QRIS/TRANSFER/DEBT, total_amount)`; saldo hutang per pekerja: `worker_balances(branch_id)` di `app/services/canteen_pos_service.py`; kas harian warung SUDAH ADA: model `CashDaily(cash_date, status, opening_balance, cash_sales, debt_payments, closing_balance, actual_cash, cash_difference)` + halaman `finance.daily_cash`. JANGAN buat fitur tutup kas baru.
- Tile peta: sama dengan `app/static/js/controls.js` (`https://tile.openstreetmap.org/{z}/{x}/{y}.png` + atribusi OpenStreetMap). Leaflet lokal: `app/static/vendor/leaflet/`.

## A. Uji dobel tagih (TES SAJA — jangan ubah logika uang)
Ada dua jalur ubah porsi: lama `revise_order_detail` (app/services/operational_service.py; mengubah porsi detail + baris invoice `ORDER_REVISION`) dan baru `update_order_qty_from_admin` (app/services/auto_order_service.py; mengubah porsi detail + `OrderQtyChange`). Invoice memakai `billable_base_quantities` (app/services/mandor_invoice_helper_service.py) + baris revisi (app/services/auto_invoice_service.py `plan_invoices`).
Buat `tests/test_invoice_qty_paths.py` (pola fixture: `tests/test_prepaid_orders.py` `_setup`, `ctx`) dengan 4 skenario pada order TERKUNCI, lalu hitung total porsi yang ditagih `plan_invoices`:
1. hanya Revisi tambah +5 → total ditagih = porsi akhir detail;
2. hanya Ubah Porsi (naik +5, dengan alasan) → total = porsi akhir;
3. Revisi +5 lalu Ubah Porsi turun −3 → total = porsi akhir;
4. Ubah Porsi +4 lalu Revisi +2 → total = porsi akhir.
Kalau ada yang GAGAL: JANGAN perbaiki service; tandai `@pytest.mark.xfail(reason="dobel tagih — perlu keputusan")` dan tulis angka harapan vs aktual di laporan.

## B. Garis waktu sesi hari ini (Operasional + Produksi + Pengiriman)
Buat service baca-saja `app/services/ops_timeline_service.py` → `build_session_timeline(branch_id, day)` dan partial `app/templates/operational/_session_timeline.html`. Tampilkan dua baris: **Siang** dan **Sore**. Tiap baris = jalur horizontal sumbu jam 05.00–20.00 dengan 4 titik:
- **Kunci**: jam kunci paling awal dari `lock_time_for` semua client yang punya order hari itu (sebut client-nya di tooltip); selesai bila order terkunci.
- **Masak**: `target_ready_time` vs `actual_completed_time` produksi sesi itu.
- **Berangkat**: `target_dispatch_time` vs `actual_departure_time` pengiriman sesi itu.
- **Tiba**: `target_arrival_time` vs `receive_time` terakhir.
Warna titik: abu = belum, biru = berjalan, hijau = tepat, merah = telat (aktual > target + `late_tolerance_minutes`). Garis **"Sekarang"** = posisi `now_wib()` (hanya untuk hari ini). Posisi dihitung di server sebagai persen → `style="left: NN%"` (satu-satunya inline style yang boleh). Data tidak ada → titik tanpa jam + teks "belum dijadwalkan"; JANGAN isi jam karangan.
Pasang partial di bagian atas: `operational/orders.html` (di dalam/di bawah kartu Hari Ini), `production/index.html`, `delivery/today.html`. Route masing-masing cukup menambah `timeline=build_session_timeline(current_user.branch_id, today_wib())`.

## C. Hitung mundur jam kunci
Di kartu Hari Ini/Besok `operational/orders.html` dan kepala `operational/order_detail.html` (bila order belum terkunci): "Kunci siang dalam 01:24:10" per sesi dari `lock_time_for`. Warna: normal > 60 menit, kuning ≤ 60 menit, merah ≤ 15 menit, "Lewat jam kunci" setelah lewat. Server mengirim waktu target ISO (WIB) di `data-countdown-to`; teks awal dihitung server. JS: `main.js` sudah 899/900 baris → JANGAN tambah di main.js; boleh satu `<script>` kecil (≤ 25 baris) di dalam partial `operational/_countdown.html` yang meng-update setiap elemen `[data-countdown-to]` tiap detik.

## D. Papan dapur (Produksi)
`production/index.html`: tambah tampilan **Papan** (default) + tautan "Tabel" (`?view=tabel`, tabel lama tetap). Papan = 3 kolom: Belum Mulai (DRAFT) · Dimasak (IN_PROGRESS) · Siap Kirim (COMPLETED), dikelompokkan per sesi hari ini. Kartu: sesi, porsi (dari order hari itu), **jumlah wadah** = ceil(porsi / `get_kitchen_max_portions_per_container`), target siap vs aktual, tombol aksi yang SUDAH ada di tabel (endpoint & form sama) + "Cetak Label" (`operational.container_labels`). Tanpa drag-drop (tanpa JS).

## E. Peta pengiriman hari ini
`delivery/today.html`: panel peta (tinggi 360px) berisi penanda tiap lokasi tujuan hari ini dari `DeliveryLocation.latitude/longitude`. Warna penanda: abu belum berangkat, biru di jalan, hijau diterima, merah telat (aturan B). Popup penanda: nama lokasi, mandor, porsi direncanakan/diterima, tautan ke detail pengiriman. Data dikirim route sebagai JSON (`<script type="application/json">`); muat `vendor/leaflet/leaflet.css` + `leaflet.js` langsung di template; script inisialisasi ≤ 40 baris inline. Lokasi tanpa koordinat → daftar kecil "Belum ada titik GPS (N)" di bawah peta dengan tautan ubah lokasi. Tidak ada koordinat sama sekali → peta tidak dirender, hanya daftar itu.

## F. Warung (`canteen/index.html`)
1. Grafik batang **penjualan per jam hari ini** (jam WIB dari `created_at`), dua seri: Tunai+QRIS dan Hutang — pakai komponen grafik yang sudah ada (`<div class="app-chart" data-apex-chart>` + spec JSON, `kind: "bar"`, warna token `brand-600` dan `chart-amber`), hanya jam yang ada transaksinya ± sekitarnya (06.00–23.00).
2. Panel **5 pekerja hutang terbesar** (dari `worker_balances`, hanya bagian warung) dengan tombol "Bayar" yang membuka pop-up bayar hutang yang sudah ada / tautan ke kasir mode Bayar Hutang.
3. Kartu **Kas warung hari ini**: status `CashDaily` tanggal hari ini (Belum dibuka / Terbuka / Ditutup), saldo seharusnya, kas dihitung, selisih (merah bila ≠ 0) + tautan "Tutup kas" ke `finance.daily_cash`. Tidak ada baris hari ini → "Belum dibuka" + tautan yang sama.

## G. Teks & kepadatan (4 modul)
1. Hapus kalimat deskripsi generik di bawah judul halaman/panel (mis. "Kelola data …", "Daftar … berdasarkan …"). Ganti dengan FAKTA hidup bila ada datanya (mis. "3 order belum dikunci · kunci siang 10.00"), atau kosongkan.
2. Tabel daftar berbasis tanggal (Order Harian riwayat, Riwayat Pengiriman, Produksi tabel, Perubahan Porsi): kelompokkan per tanggal dengan baris judul grup ("Selasa, 14 Okt 2026 · 3 order · 412 porsi"), dihitung dari baris yang tampil.
3. Kolom angka rata kanan + `font-variant-numeric: tabular-nums`.

## Larangan keras
- JANGAN mengarang angka/jam/status/koordinat. Semua dari query/model di atas; kosong → tampilkan kosong/"—".
- JANGAN ubah service uang/jurnal/invoice, model, migrasi. Service baru hanya baca, tanpa commit, filter `current_user.branch_id`.
- JANGAN ubah/hapus atribut `name`, `id`, `action`, `method`, `value`, `data-*`, csrf, input hidden, `url_for` yang sudah ada; JANGAN ubah teks yang dicek tes (`grep -rn "<teks>" tests/`).
- JANGAN letakkan modal di dalam tabel/panel/elemen `data-rise`; JANGAN pasang `data-rise` pada elemen berisi dropdown/menu.
- JS: tidak menambah `main.js`; hanya script inline kecil sesuai C & E.
- CSS: hanya `app/static/css/app/pages.css`, `var(--…)` saja (tanpa hex baru, tanpa `!important` baru, sudut `var(--radius)`), kelas berawalan `ops-`. Rakit: `powershell -ExecutionPolicy Bypass -File tools\build_css_runner.ps1`.
- JANGAN `git add/commit/checkout/reset/clean/stash`, `git show … >`, hapus file, pytest, `flask db`, skrip ke database dev; jangan sentuh `.env`, `storage/`, `instance/`, `ops/`, `driver*`, `portal/`, `canteen/pos.html`.

## Periksa sendiri sebelum lapor (tempel hasil ringkas)
```
git diff --stat
git diff --stat -- app/models migrations app/static/js app/services/auto_invoice_service.py app/services/operational_service.py app/services/auto_order_service.py app/services/mandor_invoice_helper_service.py
git diff -U0 -- app/templates | findstr /R "^-.*name= ^-.*action= ^-.*method= ^-.*csrf ^-.*url_for ^-.*data-"
```
Perintah 2 harus kosong. Baris hasil perintah 3 wajib punya pasangan `+` yang sama.

## Lapor singkat
File baru/diubah per bagian A–G, hasil skenario A (lulus/xfail + angka), hasil 3 perintah, lalu perintah untuk owner:
```
venv\Scripts\python.exe -m pytest -q tests/test_invoice_qty_paths.py tests/test_route_endpoint_references.py tests/test_exception_hygiene.py tests/test_canteen_pos.py tests/test_admin_operasional_permissions.py tests/test_pilot_dry_run_regressions.py tests/test_kitchen_recap_container_labels.py
```
