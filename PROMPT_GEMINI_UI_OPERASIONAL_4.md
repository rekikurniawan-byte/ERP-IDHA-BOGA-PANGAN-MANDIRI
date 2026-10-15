# Tugas: rapikan 4 hal kecil di modul Operasional & Pengiriman — tahap 4

ERP Flask/Jinja PT Idha Boga Pangan Mandiri. Teks Bahasa Indonesia. Kerjakan 1 → 4, lalu lapor. Jangan riset web. Jangan sentuh `ops/`, `driver/`, `portal/`.

## FAKTA (pakai ini, jangan menebak)
- `OrderRevision` (jalur lama, `app/models/operational.py`): `daily_order_detail_id, revision_time, revision_type, revision_direction (INCREASE/DECREASE), lunch_qty_change, dinner_qty_change, price_per_portion, reason, created_by` — relasi `detail.revisions`.
- `OrderQtyChange` (jalur baru "Ubah Porsi"): `daily_order_detail_id, meal_type (LUNCH/DINNER), old_qty, new_qty, reason_code, note, source (AUTO/PORTAL/ADMIN), changed_by → user, changed_at` (disimpan WIB). Relasi dari detail: lihat `backref` di model (`daily_order_detail = db.relationship("DailyOrderDetail", backref=db.backref("qt…`) — pakai nama backref itu persis.
- Jalur pelanggan: `Client.customer_path` = `"KONTRAK"` atau `"UMUM"`; mandor → `mandor.client`.
- Berangkat: route SUDAH ADA `POST delivery.mark_dispatch(delivery_id)` (role ADMIN, PENGANTAR, ADMIN_OPERASIONAL; menolak CANCELLED/DELIVERED; mengisi jam berangkat + status `ON_THE_WAY`). Contoh pemakaian form: `app/templates/delivery/index.html` (cari `mark_dispatch`).

## 1. Satu riwayat perubahan porsi di Detail Order
`app/templates/operational/order_detail.html` sekarang punya tabel "Riwayat Revisi" (hanya `OrderRevision`). Ganti menjadi SATU panel **"Riwayat Perubahan Porsi"** berisi gabungan kedua sumber untuk semua detail order ini, urut waktu terbaru di atas. Kolom: Waktu · Mandor/Lokasi · Sesi · Perubahan (mis. "Siang 10 → 15" untuk OrderQtyChange; "Siang +5" untuk OrderRevision) · Sumber (Revisi lama / Ubah Porsi Admin / Portal / Otomatis 18.00) · Oleh · Alasan.
- Gabungkan di route `operational.order_detail` (baca saja) menjadi list dict yang sudah diurutkan; template hanya menampilkan.
- Waktu `OrderRevision.revision_time`: cek cara simpannya (`grep -n "revision_time=" app/services/operational_service.py`). Bila `datetime.utcnow()` → tampilkan via `to_wib`; bila `now_wib()` → apa adanya. Sebut temuanmu di laporan.
- Kosong → "Belum ada perubahan porsi." Halaman `operational.order_qty_changes` (lintas order) TETAP ada.
- Ganti juga teks deskripsi tabel "Detail Mandor & Lokasi" yang menyebut "lihat Riwayat Revisi" → "lihat Riwayat Perubahan Porsi".

## 2. Pop-up Input Order lebih pendek (`app/templates/operational/_order_form_fields.html`)
a. **Default HPP** (alert info + 4 pilihan menu/kemasan/overhead): bungkus dengan `<details class="ops-more">` + `<summary>Lainnya: default menu & HPP (opsional)</summary>`, tertutup secara bawaan. Nama field TIDAK berubah.
b. **Pembayaran di muka**: hanya tampil bila mandor yang dipilih berjalur UMUM — TANPA JS:
   - di `<option>` mandor tambahkan `data-path="{{ mandor.client.customer_path if mandor.client else 'KONTRAK' }}"`;
   - beri kotak pembayaran kelas `ops-prepay`;
   - CSS di `pages.css`: `.ops-prepay { display: none; }` dan `form:has(select[name="mandor_id"] option[data-path="UMUM"]:checked) .ops-prepay { display: block; }`.
   - Pastikan pilihan Tom Select tetap menyetel `<select>` asli (cek dengan memilih mandor UMUM di browser: kotak muncul; mandor KONTRAK: kotak hilang). Kalau ternyata tidak muncul, JANGAN tambah JS — laporkan saja.
c. Berlaku untuk pop-up di `operational/orders.html` DAN halaman penuh `operational/order_form.html` (partial sama).

## 3. Tombol "Berangkat" di Pengiriman Hari Ini (`app/templates/delivery/today.html`)
Di kolom aksi tiap baris pengiriman berstatus `PREPARING`: tombol utama **"Berangkat"** = form POST `delivery.mark_dispatch` (csrf, `data-app-confirm="Catat {{ no pengiriman }} berangkat sekarang ({{ jam sekarang }} WIB)?"`). Status lain: tidak ada tombol Berangkat. Ikuti pola kolom aksi yang ada (1 tombol utama + menu ⋯, `.dropdown-item` untuk sisanya). Tanpa route baru.

## 4. Nama bulan Indonesia di Jadwal Menu
`app/templates/operational/menu_schedule.html` memakai `strftime('%d %b %Y')` (bulan Inggris: Oct/May/Aug/Dec). Ganti dengan `{{ d.day }} {{ BULAN[d.month - 1] }} {{ d.year }}` (definisikan `{% set BULAN = ['Jan','Feb','Mar','Apr','Mei','Jun','Jul','Agu','Sep','Okt','Nov','Des'] %}` sekali di atas). Cek juga `%A`/`%B`/`%b` lain di `app/templates/{operational,production,delivery,canteen}` dan ganti dengan cara yang sama.

## Larangan keras
- JANGAN mengarang data; hanya dari model/route yang ada. JANGAN ubah service/model/migrasi/uang/jurnal.
- JANGAN ubah/hapus atribut `name`, `id`, `action`, `method`, `value`, `data-*` yang sudah ada, csrf, input hidden, `url_for`; JANGAN ubah teks yang dicek tes (`grep -rn "<teks>" tests/`).
- Modal tetap di luar panel/tabel; tidak ada `data-rise` di elemen berisi dropdown.
- JANGAN tambah JS. CSS hanya `app/static/css/app/pages.css` dengan `var(--…)` (tanpa hex/`!important` baru), lalu rakit: `powershell -ExecutionPolicy Bypass -File tools\build_css_runner.ps1`. Setelah rakit, pastikan jumlah `{` = `}` di `pages.css`.
- JANGAN `git add/commit/checkout/reset/clean/stash`, `git show … >`, hapus file, `flask db`, skrip ke database dev; jangan sentuh `.env`, `storage/`, `instance/`.
- JANGAN klaim tes lulus tanpa menjalankannya. Kalau tidak bisa menjalankan, tulis "belum dijalankan".

## Periksa sendiri sebelum lapor (tempel hasil ringkas)
```
git diff --stat
git diff --stat -- app/models migrations app/services app/static/js
git diff -U0 -- app/templates | findstr /R "^-.*name= ^-.*action= ^-.*method= ^-.*csrf ^-.*url_for ^-.*data-"
```
Perintah 2 harus kosong. Baris hasil perintah 3 wajib punya pasangan `+` yang sama.

## Lapor singkat
File diubah per poin 1–4, temuan zona waktu `revision_time`, hasil 3 perintah, lalu perintah untuk owner:
```
venv\Scripts\python.exe -m pytest -q tests/test_route_endpoint_references.py tests/test_exception_hygiene.py tests/test_invoice_qty_paths.py tests/test_admin_operasional_permissions.py tests/test_pilot_dry_run_regressions.py
```
