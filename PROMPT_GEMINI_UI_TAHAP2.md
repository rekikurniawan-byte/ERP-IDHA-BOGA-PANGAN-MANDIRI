# Tugas: sebar UI desktop internal (biru) ke halaman lain — PER BATCH

ERP Flask/Jinja PT Idha Boga Pangan Mandiri. Teks Bahasa Indonesia. Owner sudah MENYETUJUI contoh: `app/templates/dashboard/owner.html`, `dashboard/admin.html`, `master/client_360.html`, makro `dashboard/_pulse.html`, CSS di `app/static/css/app/components.css` (blok "Komponen dasbor desktop internal") dan `layout.css` (blok "Desktop internal biru"). **Baca kelima file itu dulu**; tiru polanya persis. Jangan riset web.

Owner akan menulis: **"Kerjakan BATCH n"**. Kerjakan HANYA folder batch itu, lalu berhenti dan lapor.

| Batch | Folder `app/templates/` |
|---|---|
| 1 | `operational/`, `production/`, `delivery/` |
| 2 | `finance/` file berawalan a–i |
| 3 | `finance/` file berawalan j–z |
| 4 | `accounting/`, `costing/` |
| 5 | `master/` (kecuali client_360), `credit/`, `customer_success/`, `contracts/` |
| 6 | `workforce/`, `hr/` |
| 7 | `logistics/`, `settings/`, `sop/`, `field_transactions/`, `prediction/`, `canteen/` (kecuali `pos.html`), `dashboard/` (kecuali owner/admin/_pulse) |

## Pemetaan (wajib sama di semua halaman)
| Lama | Baru |
|---|---|
| `div.page-header` (eyebrow + h1 + p + `.page-actions`) | `header.dash-head` → `<div><h1>…</h1><p>…</p></div>` + `div.dash-head-actions` (tombol utama paling kanan). Hapus eyebrow. |
| `div.app-card` / `section.app-card` | `section.panel` |
| `.section-title` / `.card-header-clean` (h2/h5 + p + tombol) | `div.panel-head` (h2 + p; tautan kanan = `a.panel-link …<i class="bi bi-arrow-right">`) |
| isi kartu | `div.panel-body`; tabel di dalam panel → `div.panel-body.flush` |
| kartu angka (`app-stat-card`, `stat-card`, kpi lama) | `.kpi-row` + `.kpi` seperti makro `kpi_card` TETAPI hanya angka yang SUDAH ada: tanpa `delta`, tanpa `spark` kecuali data seri sudah dikirim route. Ikon `span.kpi-icon.tone-{blue/green/amber/red/violet}`. |
| daftar peringatan/pengingat yang sudah ada | `a.alert-row.is-bad / .is-warn` |

TETAP dipakai apa adanya: `table app-table`, `status-badge`, filter global (`components/global_filter*`, pola filter tunggal), `app-empty-state`, `alert alert-*`, form Bootstrap (`form-control`, `form-select`, Tom Select, Flatpickr), modal, dropdown `app-action-menu`.

Gerak: `data-rise="1..5"` boleh di `.panel`/`.kpi` (urut dari atas). **JANGAN** pasang `data-rise` pada elemen yang berisi dropdown/menu (`.dash-head`, panel dengan `dropdown`), karena menu akan tertutup.

## Larangan anti-ngarang (paling penting)
1. Hanya ubah **template** di folder batch. JANGAN sentuh `app/routes`, `app/services`, `app/models`, migrasi, JS, kecuali poin CSS di bawah.
2. JANGAN menambah angka, persen, tren, grafik, teks status, contoh data, atau variabel Jinja yang tidak dikirim route. Cek `render_template(...)` route-nya bila ragu. Angka statis = DILARANG.
3. JANGAN mengubah/menghapus: atribut `name`, `id`, `action`, `method`, `value`, `data-*`, `csrf`, input hidden, `{% if %}`/`{% for %}`/izin role, `url_for(...)`, form dan tombolnya. Hanya kelas pembungkus & struktur tampilan.
4. Sebelum mengubah TEKS apa pun: `grep -rn "<teks>" tests/` — teks yang dicek tes tidak boleh berubah.
5. Lewati (jangan ubah) file cetak: nama berisi `print`, `cetak`, `_document`, `slip`, `receipt`, `kwitansi`, `1721`, `_pdf`, dan partial yang dipakai portal (`grep -rn "<nama partial>" app/templates/portal`).
6. CSS: tambahan hanya bila benar-benar perlu, di `app/static/css/app/pages.css`, pakai `var(--…)` saja (tanpa hex, tanpa `!important`, sudut hanya `var(--radius)`), lalu `venv\Scripts\python.exe tools\build_css.py`. Jangan buat file CSS baru.
7. JANGAN `git add/commit/checkout/reset/clean`, jangan hapus file, jangan jalankan pytest/`flask db`/skrip ke database dev, jangan sentuh `.env`, `storage/`, `instance/`, portal, `ops/`, `driver*`, `layouts/`.

## Pemeriksaan sendiri sebelum lapor (jalankan, tempel hasil ringkas)
```
git diff --stat
git diff --stat -- app/routes app/services app/models app/static/js
git diff -U0 -- app/templates | findstr /R "^-.*name= ^-.*action= ^-.*method= ^-.*csrf ^-.*url_for ^-.*data-"
```
- Perintah 2 harus kosong.
- Perintah 3: setiap baris yang muncul wajib ada pasangannya (baris `+` yang sama persis). Kalau ada yang hilang, kembalikan.

## Lapor singkat
Daftar file diubah, file yang dilewati + alasan, hasil 3 perintah di atas, lalu perintah untuk owner:
```
venv\Scripts\python.exe tools\build_css.py
venv\Scripts\python.exe -m pytest -q tests/test_ui_ux_static_contracts.py tests/test_route_endpoint_references.py tests/test_exception_hygiene.py
```
