# Tugas: perbaikan modul Operasional, Produksi, Pengiriman, Warung (desktop) — tahap 2

ERP Flask/Jinja PT Idha Boga Pangan Mandiri. Teks Bahasa Indonesia. Folder: `app/templates/{operational,production,delivery,canteen}` + route terkait. JANGAN sentuh `ops/`, `driver*`, `portal/`, `canteen/pos.html`. Kerjakan berurutan A → E, lalu lapor.

## A. Modal tidak bisa diklik (bug lapisan) — WAJIB pertama
Gejala: modal "Ubah Porsi" di `/operational/orders/<id>` tampil tapi tertutup latar gelap, tidak bisa diklik. Penyebab: `.content-area` diberi `view-transition-name`, sehingga jadi lapisan tersendiri di bawah latar modal Bootstrap.
1. `app/static/css/app/layout.css`:
   - HAPUS baris `body.shell-internal .content-area { view-transition-name: app-content; }`.
   - Ganti 4 baris `::view-transition-old(app-content)…`, `::view-transition-new(app-content)…`, `::view-transition-old(root),` + `::view-transition-new(root) { animation: none; }` menjadi:
     ```
     ::view-transition-old(root) { animation: app-fade-out 120ms ease-in both; }
     ::view-transition-new(root) { animation: app-fade-in 200ms var(--ease-out) both; }
     ```
   - Di blok `@media (prefers-reduced-motion: reduce)` ganti `app-content` menjadi `root`.
2. Semua `<div class="modal …">` di folder lingkup: pindahkan ke LUAR `<table>`, `.panel`, dan elemen ber-`data-rise` — letakkan di akhir `{% block content %}` (pakai loop yang sama bila per baris). Tombol pemicu tetap di baris tabel (`data-bs-target` sama).

## B. Teks mentah (data tampil tidak diterjemahkan)
1. Dropdown filter status di `/production/` (DRAFT, IN_PROGRESS, …) dan `/delivery/history` (DRAFT, DISPATCHED, DELIVERED, …): labelnya pakai `status_label(kode)` dari `app.utils.labels` di route yang membuat `status_options` (nilai `value` tetap kode).
2. `operational/revision_form.html`: "Status Order" menampilkan `LOCKED` → pakai filter `|status_label`.
3. Periksa semua `{{ … .status }}`, `meal_type`, `sesi` yang tampil sebagai teks di folder lingkup → `|status_label` (LUNCH/DINNER → Siang/Sore).

## C. Tombol beda nama tapi tujuan sama (hasil audit) — satukan
Aturan: **satu tujuan = satu tombol = satu nama**, dan nama harus menjelaskan apa yang TERJADI. Tautan yang hanya membuka halaman tidak boleh bernama aksi (Berangkat/Mulai/Realisasi).
| File | Tujuan | Nama sekarang | Jadikan |
|---|---|---|---|
| delivery/index.html | `delivery.receiving` (per tanggal) | Penerimaan / Lembar Penerimaan | satu: "Penerimaan" (tombol utama). Hapus duplikat di menu ⋯ |
| delivery/index.html | `delivery.detail` | Berangkat / Buka Manifest | No. pengiriman jadi tautan; di menu ⋯ satu "Buka Manifest". "Berangkat" hanya boleh ada bila memanggil route POST keberangkatan yang SUDAH ada (cek `grep -n "def depart\|dispatch" app/routes/delivery_routes.py`); kalau tidak ada, hapus |
| delivery/receive.html | `delivery.detail` | Buka Detail Pengiriman / Detail Delivery | "Buka Manifest" (satu) |
| delivery/scan.html | `delivery.receiving` | Pilih dari Daftar / Pilih dari Daftar Penerimaan Hari Ini | "Pilih dari daftar penerimaan" (satu) |
| production/index.html | `production.detail` | Buka Detail Batch / Mulai / Realisasi | No. batch = tautan; tombol utama sesuai langkah HANYA jika ada route POST-nya; selain itu satu "Buka Batch" |
| production/detail.html | `operational.order_detail` | Buka Order Harian / Lihat Order | "Buka Order" (satu) |
| operational/order_form, revision_form, order_hpp_* (5 file) | kembali ke order/snapshot | Kembali / Batal / Buka Detail Order / Kembali ke Order / Rincian Order / Buka Snapshot / Kembali ke Snapshot | Kepala halaman: satu tautan "‹ Kembali ke Order" (atau "‹ Kembali ke Snapshot"). Bawah form: hanya "Batal" (ke tujuan yang sama) + tombol simpan |
| operational/order_hpp_snapshot_detail.html | `order_hpp_stock_consumption_detail` | Detail Pemakaian / Pemakaian Stok | "Pemakaian Stok" (satu) |
Setelah selesai, pastikan di setiap baris tabel & kepala halaman tidak ada dua tombol menuju `url_for` + argumen yang sama.

## D. Aksi "ubah/isi kecil" → modal seperti "Ubah Porsi" (bukan halaman penuh)
Pola acuan: modal `#modalChangeQty-{{ detail.id }}` di `operational/order_detail.html` (header ikon + judul + subjudul, isi field, kotak peringatan opsional, footer "Batal" + tombol utama "Simpan …").
Ubah jadi modal (tombol pemicu tetap di kolom aksi / menu ⋯):
1. Tambah porsi setelah dikunci — `operational.add_increase_after_lock_route` (dari order_detail).
2. Atur Default HPP — `operational.update_order_hpp_defaults_route` (4 isian, dari order_detail).
3. Buat Snapshot HPP — `operational.create_order_hpp_snapshot_route` (bila isian ≤ 7 dan tanpa tabel).
4. Revisi detail order — `operational.create_revision` (dari tabel detail order).
5. Bayar hutang pekerja — `canteen.debt_payment` dan bayar piutang luar — `canteen.external_receivable_payment` (dari tabel `canteen/debts.html` & `canteen/index.html`).
TETAP halaman penuh (jangan diubah jadi modal): buat order (`orders/create`), Tambah Lokasi (`add_order_detail`, isian bergantung mandor→lokasi), terima pengiriman (`delivery.receive`, ada unggah foto/GPS), transaksi warung manual (`canteen/sale_form.html`).
Aturan modal:
- `<form method="POST">` ke endpoint POST yang SAMA dengan halaman lamanya, nama field SAMA PERSIS, `{% include "components/csrf_token.html" %}`, `enctype` sama bila ada. Konfirmasi tetap `data-app-confirm` bila halaman lama memakainya.
- Isi awal (sisa hutang, porsi saat ini, nilai default) hanya dari data yang sudah ada; bila halaman daftar belum menerima data itu, tambahkan ke `render_template` route GET halaman daftar (query baca saja, cabang `current_user.branch_id`). DILARANG angka statis/karangan.
- Route GET halaman lama JANGAN dihapus (tetap jadi cadangan bila validasi gagal).
- Sesudah simpan, route harus kembali ke halaman asal modal. Bila route sekarang mengarah ke tempat lain, tambah `<input type="hidden" name="next" value="{{ request.full_path }}">` dan di route POST pakai `next` HANYA jika diawali `/` dan bukan `//`; selain itu perilaku lama.
- Satu modal per baris, `id` unik (`modal<Aksi>-{{ id }}`), diletakkan sesuai A2.

## E. Halaman Detail Order (`operational/order_detail.html`) — kurangi kartu yang tidak penting
- Tiga kartu besar "Default Menu & Profil HPP" (Menu Siang / Menu Sore / Overhead "Belum ditentukan") → satu baris ringkas di kepala panel: "Menu siang: … · Menu sore: … · Overhead: …" + tautan "Atur" yang membuka modal D2.
- Kartu angka (Mandor unik, Total lokasi, Total porsi siang/sore, Status kunci) → satu strip ringkas `.kpi-row` berisi 4 angka: Porsi Siang, Porsi Sore, Total, Lokasi. Status kunci sudah terlihat di pipeline — jangan diulang.
- Tabel "Detail Mandor & Lokasi" + pipeline tetap.

## Larangan keras
- JANGAN mengarang angka/status/data; semua dari query/model yang ada. JANGAN ubah service/model/migrasi.
- JANGAN ubah/hapus atribut `name`, `id` yang dipakai JS/tes, `action`, `method`, `value`, `data-*`, csrf, input hidden, `url_for`, cek izin role. JANGAN ubah teks yang dicek tes (`grep -rn "<teks>" tests/` dulu).
- JANGAN tambah JS (main.js sudah 899/900 baris). Modal pakai Bootstrap bawaan (`data-bs-toggle="modal"`).
- CSS hanya `app/static/css/app/pages.css`/`layout.css` sesuai A1, `var(--…)` saja (tanpa hex, tanpa `!important`, sudut `var(--radius)`). Rakit: `venv\Scripts\python.exe tools\build_css.py`. Kalau GAGAL karena isi `components.css` yang sudah ada, rakit dengan `tools\build_css_runner.ps1` seperti sebelumnya, tapi JANGAN menambah hex/`!important` baru.
- JANGAN `git add/commit/checkout/reset/clean`, hapus file, `git show HEAD:… >` (menimpa), pytest, `flask db`, skrip ke database dev; jangan sentuh `.env`, `storage/`, `instance/`.

## Periksa sendiri sebelum lapor (tempel hasil ringkas)
```
git diff --stat
git diff --stat -- app/services app/models app/static/js
git diff -U0 -- app/templates | findstr /R "^-.*name= ^-.*action= ^-.*method= ^-.*csrf ^-.*url_for ^-.*data-"
```
Perintah 2 harus kosong. Setiap baris hasil perintah 3 wajib punya pasangan `+` yang sama (boleh pindah ke modal); kalau hilang, kembalikan. Lalu buka di browser: modal Ubah Porsi, Bayar Hutang, Default HPP — harus bisa diketik & disimpan.

## Lapor singkat
File diubah, apa yang dijadikan modal, tombol yang disatukan, hasil 3 perintah, lalu perintah untuk owner:
```
venv\Scripts\python.exe -m pytest -q tests/test_ui_ux_static_contracts.py tests/test_route_endpoint_references.py tests/test_exception_hygiene.py tests/test_canteen_pos.py tests/test_admin_operasional_permissions.py tests/test_ops_navigation.py tests/test_pilot_dry_run_regressions.py
```
