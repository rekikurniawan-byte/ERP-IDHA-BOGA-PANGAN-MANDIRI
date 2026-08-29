# RINCIAN AUDIT UI/UX & CSS — ERP PT IDHA BOGA PANGAN MANDIRI

Tanggal audit: 18 Agustus 2026
Cakupan: end-to-end — arsitektur CSS, sistem token, markup template, komponen, aksesibilitas, responsive, dark mode, print, dependensi front-end.
Metode: analisis statis atas 94 file `app/static/css/src/*.css`, 260 template Jinja, `app/static/js/main.js`, dan `tools/build_css.py`.

---

## 1. Ringkasan Eksekutif

Masalah UI proyek ini **bukan masalah selera desain, tapi masalah arsitektur CSS**. Selama ~2 bulan pengembangan, setiap keluhan visual diselesaikan dengan menambah file CSS baru di akhir cascade, bukan memperbaiki sumbernya. Hasilnya:

| Metrik | Nilai | Catatan |
|---|---|---|
| Ukuran `style.css` (hasil build) | **1.366.565 byte (1,37 MB)** | Tidak diminify |
| Jumlah file sumber | **94 file** | 53 di antaranya bernama `_lock` / `_fix` / `_override` / `_polish` / `_repair` |
| Total baris CSS sumber | **48.765 baris** | |
| Total rule block | **6.192** | |
| Total `!important` | **8.499** | Rata-rata 1,4 per rule block |
| File terbesar | `143_erp_ui_system_final_override.css` | 297 KB, 12.163 baris, 1.436 selector, 2.225 `!important` |
| Class CSS tidak terpakai | **532 dari 1.929 (28%)** | Tidak muncul di template maupun `main.js` |

**Diagnosis inti:** tidak ada satu pun komponen yang punya satu sumber kebenaran. Contoh `.app-table` didefinisikan **403 kali tersebar di 36 file**. Setiap perubahan tampilan tabel berarti menebak file mana yang menang di cascade — inilah kenapa perbaikan UI selalu memicu regresi di halaman lain.

**Kabar baiknya:** lapisan markup justru sehat (inline `style=` hanya 44, inline event handler 0, 214 dari 260 template konsisten `extends layouts/base.html`), dan sudah ada rintisan design system yang benar di `30_ui_primitives.css` + `31_ui_patterns.css`. Artinya redesain menyeluruh **tidak perlu menulis ulang template dari nol** — cukup mengganti lapisan CSS dan mengangkat komponen jadi macro.

---

## 2. Akar Masalah (Root Cause)

### 2.1 Arsitektur "tumpukan tambalan"

Urutan build (`tools/build_css.py` → `SOURCE_ORDER`) menempatkan file 100–167 setelah semua file dasar. Nama-namanya menceritakan sendiri sejarahnya:

```
105_final_visual_browser_qa_lock.css
106_visual_emergency_alignment.css
108_final_ui_system_consolidation_regression_repair.css
109_final_targeted_ui_regression_cleanup.css
...
151_portal_topbar_collision_fix.css
152_portal_topbar_structural_grid_fix.css
153_portal_topbar_no_avatar_lock.css
```

Tiga file berturut-turut (151, 152, 153) hanya untuk memperbaiki satu topbar portal — masing-masing menimpa yang sebelumnya, dan ketiganya tetap ikut ter-build.

Build script **sudah sadar** akan pola ini. Di [tools/build_css.py](tools/build_css.py) ada:

```python
FORBIDDEN_CSS_FILENAME_WORDS = ("final", "lock", "fix", "override", "repair", "cleanup", "polish")
IMPORTANT_BASELINE_COUNT = 8728
```

Tetapi 53 file lama di-whitelist lewat `LEGACY_FORBIDDEN_CSS_SOURCE_NAMES`, dan jumlah `!important` dijadikan *baseline* yang boleh dipertahankan. Jadi pagarnya sudah dipasang, tapi hutang teknisnya dibekukan, bukan dilunasi.

### 2.2 Perang specificity per komponen

| Selector | Jumlah file yang menyentuh | Total kemunculan |
|---|---|---|
| `.app-table` | 36 | 403 |
| `.app-card` | 36 | 173 |
| `.page-header` | 34 | 172 |
| `.app-btn-primary` | 21 | 122 |
| `.app-stat-card` | 18 | 112 |
| `.sidebar-link` | 14 | 109 |
| `.app-input` | 12 | 53 |
| `.status-badge` | 19 | 44 |

Selector paling sering didefinisikan ulang: `:root` (**47×**), `body` (20×), `.auth-card` (20×), `.app-sidebar` (18×), `.app-topbar` (15×).

### 2.3 Token ada, tapi bukan kontrak

[app/static/css/src/00_tokens.css](app/static/css/src/00_tokens.css) hanya berisi 12 warna, 2 radius, 2 shadow. Sementara di seluruh sumber:

| Properti | Nilai unik | Bukti tidak ada skala |
|---|---|---|
| Warna hex literal | **2.375 kemunculan** | `#ffffff` 410×, `#fff` 116×, `#64748b` 108×, `#111827` 101× |
| `border-radius` | **89 nilai berbeda** | 999px, 10px, 12px, 13px, 14px, 15px, 16px, 18px, 20px, 22px, 24px… |
| `box-shadow` | **201 nilai berbeda** | |
| `padding` | **249 nilai berbeda** | |
| `font-size` | **154 nilai berbeda** | termasuk 12.5px, 17px, 23px, 26px |

`var(--…)` dipakai 4.140 kali — jadi niat memakai token ada, tapi berjalan paralel dengan 2.375 nilai literal. Dua sistem hidup bersamaan.

### 2.4 Tipografi terlalu berat

Distribusi `font-weight` di seluruh CSS:

```
950 → 127×     850 → 109×     800 → 107×     900 → 85×
700 →  57×     750 →  36×     650 →  33×     600 →  9×
```

Bobot dominan adalah 800–950. Inilah penyebab teknis kenapa antarmuka terasa "tebal", "ramai", dan melelahkan untuk layar data-heavy seperti ERP. Ukuran font pun bertumpuk di 11–13px (109× `12px`, 88× `13px`, 61× `11px`) — kecil tapi tebal, kombinasi terburuk untuk keterbacaan tabel panjang.

---

## 3. Lapisan Markup & Komponen

### 3.1 Yang sudah benar

- 260 template; **214 `extends "layouts/base.html"`**, 18 `extends "layouts/portal_mobile.html"`. Struktur pewarisan konsisten.
- Inline `style="…"` hanya **44 kemunculan** di seluruh proyek — sangat bersih.
- **0 inline event handler** (`onclick`, `onchange`, dst). Semua perilaku terpusat di `main.js`.
- Hanya 7 template punya blok `<style>` sendiri.
- CSRF, skip-link (`Lewati ke konten utama`), dan `data-endpoint` sudah ada di base layout.

### 3.2 Yang jadi sumber inkonsistensi

Komponen bersama **sudah ditulis tapi hampir tidak dipakai**:

| Komponen | Tersedia di | Dipakai | Ditulis manual di |
|---|---|---|---|
| Macro `page_header()` | `components/page_header.html` | **2 template** | **175 template** menulis `<div class="page-header">` sendiri |
| `components/ui_macros.html` | ada, lengkap | **1 template** (`master/items.html`) | — |
| Kartu statistik | — | — | **102 template** menyalin `app-stat-card` |
| Tabel | — | — | **149 template** menyalin markup `app-table` |
| Form | — | — | **143 template** |

Akibatnya: satu perubahan desain header halaman = menyunting 175 file, atau (yang selama ini terjadi) menambah satu file CSS override lagi.

### 3.3 Rintisan design system yang sudah ada — pertahankan

[app/static/css/src/30_ui_primitives.css](app/static/css/src/30_ui_primitives.css) dan [31_ui_patterns.css](app/static/css/src/31_ui_patterns.css) adalah satu-satunya bagian CSS yang ditulis dengan benar: token bernamespace (`--ui-*`), tinggi kontrol tunggal (`--ui-control-height: 42px`), radius tunggal (`--ui-radius: 8px`), semua di bawah `.ui-scope` sehingga **opt-in dan tidak bocor**.

Adopsinya baru **1 dari 260 template**. Ini adalah fondasi redesain yang sudah dibayar — strategi bertahap harus dibangun di atasnya, bukan memulai sistem ketiga.

---

## 4. Aksesibilitas

| Temuan | Bukti | Dampak |
|---|---|---|
| **Tombol bukan elemen tombol** | `ui_button()` merender `<span tabindex="0" data-ui-navigate="…">` untuk link dan submit | Hilang semantik native, Enter/Space, status `:disabled`, dan announce screen reader. Ini regresi a11y paling serius. |
| **Gambar tanpa alt** | `alt=` hanya **1 kemunculan** di 260 template | Logo perusahaan & bukti bayar tak terbaca screen reader |
| **Notifikasi tidak diumumkan** | `aria-live` **0 kemunculan** | Flash message dan toast (`164_`, `165_`) tidak terdengar oleh pengguna screen reader |
| **Fokus keyboard rawan hilang** | 26 deklarasi `outline: none` / `outline: 0` vs 39 `:focus-visible` | Navigasi keyboard bisa "buta" di sebagian komponen |
| **Landmark minim** | `role=` hanya 10 kemunculan | |
| **Motion tidak dihormati** | 64 `transition` + 16 `@keyframes`, tapi `prefers-reduced-motion` hanya **5×** | |

### Dark mode timpang

Ada **625 rule** `[data-theme="dark-mono"]`, tapi sebarannya tidak merata per komponen:

```
app-table    9 rule      empty-state  9 rule      app-btn      6 rule
app-card     4 rule      modal        4 rule      status-badge 3 rule
app-stat-card 2 rule     app-input    2 rule      page-header  1 rule
```

Komponen dengan 1–2 rule tetap mewarisi warna terang literal (`#ffffff`, `#f8fafc`) dari 2.375 hex hardcode di atas — inilah sumber "kotak putih menyilaukan" di mode gelap. Sisa tema lama (`azure-calm` 40 rule, `dark-enterprise` 26, `clear-focus` 5, `light-clean` 4) masih ter-build padahal `base.html` sudah memetakannya ke `light-mono`/`dark-mono` — murni bobot mati.

---

## 5. Responsive

- `90_responsive.css` = **95 KB** dengan 282 `!important`.
- Breakpoint tidak disiplin — terdeteksi 13+ nilai `max-width` berbeda:
  `520, 560, 620, 640, 720, 760, 768, 820, 900, 920, 980, 992, 1180, 1200`
  Sementara Bootstrap yang dipakai memakai `576 / 768 / 992 / 1200 / 1400`. Dua grid sistem bertabrakan.
- Portal mobile punya jalur CSS terpisah (`142_portal_responsive_web.css`, `149`–`153`, `159`, `161`–`163`) — total ~120 KB hanya untuk portal.

---

## 6. Dependensi & Build

| Temuan | Detail | Risiko |
|---|---|---|
| Bootstrap dari CDN | `cdn.jsdelivr.net/npm/bootstrap@5.3.3` + `bootstrap-icons@1.11.3`, **tanpa fallback lokal** | ERP internal jadi tidak bisa dipakai bila jaringan/DNS keluar diblokir. Ini masalah operasional, bukan hanya estetika. |
| CSS melawan Bootstrap | Sebagian besar dari 1,37 MB adalah override terhadap Bootstrap yang dimuat lebih dulu | Ongkos ganda: bayar Bootstrap, lalu bayar lagi untuk membatalkannya |
| Cache-busting manual | `v='20260810-public-auth-register-clean'` di `base.html` di-hardcode | Mudah lupa diperbarui → user lihat CSS basi |
| Bundle tidak diminify | 1,37 MB terkirim apa adanya | ~200–300 KB setelah minify+gzip realistis |
| Riwayat git tipis | Hanya 3 commit menyentuh `css/src` | Tidak ada jejak untuk membedakan aturan yang masih perlu vs sisa eksperimen |

---

## 7. Kode Mati

**532 dari 1.929 class CSS (28%)** tidak pernah muncul di template maupun `main.js`. Sebagian adalah override Bootstrap yang memang tak terpakai (`col-sm-2`, `d-inline-flex`, `modal-content`, `flatpickr-days`, `form-switch`), sisanya sisa eksperimen desain:

```
accounting-flow-panel     accounting-precision-grid    analytics-card
app-atomic-dialog-*       app-atomic-select-*          app-atomic-time-*
dashboard-command-link-card-3/4                        dashboard-donut-metric-success
portal-contract-card      portal-focus-grid            portal-payment-instruction-card
op-prod-delivery-flow-steps                            quick-action-grid
```

Catatan: kelompok `app-atomic-*` sebagian dibuat dinamis oleh `main.js`; sudah diverifikasi lewat pemindaian string `main.js`, dan yang tersisa di daftar ini memang tidak direferensikan di mana pun.

> **Koreksi (dikerjakan di Fase 4).** Angka 532 dan daftar di atas terlalu longgar. Pemindaian string saja tidak menangkap nama class yang dirakit saat runtime, dan tiga nama di daftar ini ternyata **hidup**: `dashboard-command-link-card-3`, `dashboard-command-link-card-4` (dirakit dari `loop.index` di template) dan `dashboard-donut-metric-success` (dirakit dari kunci metrik). Setelah ditambah dua sumber bukti — prefiks yang diikuti interpolasi, dan kehadiran nyata di DOM 27 halaman yang di-render — angka sebenarnya **404**, dan 105 class terselamatkan dari penghapusan keliru. Lihat `tools/css_dead_classes.py`.

---

## 8. Rencana Perbaikan Bertahap

Prinsip: **jangan menyentuh cascade lama sampai penggantinya terbukti.** Setiap fase harus bisa dirilis sendiri dan bisa di-rollback.

### Fase 0 — Jaring pengaman (prasyarat, 1–2 hari)
Tanpa ini, semua fase berikutnya buta terhadap regresi.
1. Tambah *visual regression baseline*: screenshot ~30 halaman perwakilan (dashboard, invoice index/detail, tabel panjang, form panjang, portal mobile, login, print) di light + dark.
2. Turunkan Bootstrap & bootstrap-icons ke `app/static/vendor/` — hilangkan ketergantungan CDN sekaligus mengunci versi.
3. Otomatiskan cache-busting (hash isi file) di `build_css.py`, hapus string versi manual di `base.html`.

### Fase 1 — Kontrak token tunggal (3–5 hari)
1. Perluas `00_tokens.css` jadi sistem penuh: skala warna (surface/text/border/status × light+dark), skala spasi 4px (4/8/12/16/24/32/48), radius (4/8/12/999), 3 shadow, tangga font (11/12/13/14/16/20/24/32), bobot font **hanya 400/500/600/700**.
2. Definisikan dark mode sebagai *override token saja* di satu tempat, bukan 625 rule tersebar.
3. Turunkan bobot font global dari 800–950 ke 500–700. Ini satu perubahan dengan dampak visual terbesar dan biaya paling murah.
4. Belum menghapus apa pun — hanya menambah kontrak.

### Fase 2 — Angkat komponen jadi macro (1–2 minggu)
Sasaran: memutus rantai "1 perubahan desain = 175 file".
1. Perluas `ui_macros.html` menjadi set lengkap: `page_header`, `stat_card`, `stat_grid`, `data_table`, `filter_bar`, `form_field`, `empty_state`, `status_badge`, `row_actions`.
2. **Perbaiki dulu `ui_button`**: ganti `<span tabindex="0">` jadi `<a>` untuk navigasi dan `<button type="submit">` untuk submit. Ini bug aksesibilitas, harus beres sebelum macro disebarkan ke 260 template.
3. Migrasi per modul, urut dari yang paling banyak halamannya: `finance` (55) → `portal` (36) → `accounting` (23) → `master` (22) → `settings` (21) → sisanya.
4. Setiap modul selesai = satu commit + satu putaran visual regression.

### Fase 3 — Pindahkan gaya ke `.ui-scope` (paralel dengan Fase 2)
1. Bangun komponen di `30_ui_primitives.css` / `31_ui_patterns.css` memakai token Fase 1.
2. Tandai `<body>` atau shell per modul dengan `ui-scope` begitu modul itu sudah migrasi penuh — sifatnya opt-in, jadi modul yang belum migrasi tidak terganggu.
3. Target: **0 `!important` di file 30/31**. Kalau butuh `!important`, berarti masih ada override lama yang harus dimatikan, bukan ditambah kekuatannya.

### Fase 4 — Pembongkaran (setelah modul terakhir migrasi)
Baru di sini file lama boleh disentuh, dan urutannya dari yang paling aman:
1. Hapus tema mati: `azure-calm`, `dark-enterprise`, `clear-focus`, `light-clean` (~75 rule).
   > **Koreksi (sudah dikerjakan).** Yang boleh dihapus hanya **rule CSS**-nya (24 rule utuh + 6 selector-list dipangkas). Nama tema itu sendiri masih dipakai di `base.html` dan `main.js` sebagai **peta migrasi** yang mengubah nilai lama di `localStorage` pengguna jadi `light-mono`/`dark-mono` — justru peta itulah yang membuat rule CSS-nya tak terjangkau. Menghapus petanya akan membuat pengguna lama terdampar di tema tak dikenal.
2. Hapus 532 class mati. → angka sebenarnya **404**; lihat koreksi di bagian 7.
3. Bongkar file `_lock`/`_fix`/`_override` dari **nomor terbesar ke terkecil** (167 → 143 → …). Nomor besar = tambalan paling akhir dan paling sedikit yang bergantung padanya.
4. Setiap file dihapus → build → visual regression → commit terpisah. Jangan gabung.
5. Turunkan `IMPORTANT_BASELINE_COUNT` di `build_css.py` setiap kali turun, supaya angkanya tidak bisa naik lagi.

**Target akhir yang realistis:** < 200 KB CSS sumber, < 500 `!important`, < 20 file, breakpoint 4 nilai selaras Bootstrap.

### Fase 5 — Redesain visual
Baru dilakukan setelah Fase 1–4. Dengan token tunggal dan komponen macro, redesain menyeluruh menjadi pekerjaan mengubah nilai token + beberapa file komponen — bukan menambah `168_redesign_lock.css`.

---

## 9. Rekomendasi Segera (bisa dikerjakan minggu ini, risiko rendah)

Empat hal berikut memberi perbaikan terasa tanpa menunggu seluruh program selesai:

1. **Turunkan bobot font global** ke 500–700 — memperbaiki kesan "berat" di seluruh aplikasi dalam satu perubahan.
2. **Perbaiki `ui_button`** dari `<span tabindex="0">` ke elemen semantik — bug aksesibilitas nyata, dan hanya menyentuh 1 file macro (adopsi masih 1 template, jadi biaya migrasi ~nol *sekarang*; akan mahal setelah Fase 2).
3. **Turunkan Bootstrap ke lokal** — menghapus satu titik kegagalan operasional.
4. **Tambah `aria-live="polite"`** pada wadah flash message di `base.html` dan host toast di `main.js` — 2 baris, menutup celah a11y.

---

## 10. Lampiran — Perintah Verifikasi

```bash
# ukuran bundel & jumlah !important
wc -c app/static/css/style.css
cat app/static/css/src/*.css | grep -o '!important' | wc -l

# sebaran override per komponen
grep -c '\.app-table' app/static/css/src/*.css | grep -v ':0'

# nilai unik yang menandakan tak ada skala
grep -ho 'border-radius:[^;!]*' app/static/css/src/*.css | sort -u | wc -l
grep -ho 'box-shadow:[^;!]*'    app/static/css/src/*.css | sort -u | wc -l
grep -ho 'font-size:[^;!]*'     app/static/css/src/*.css | sort -u | wc -l

# adopsi komponen
grep -rl 'page_header(' app/templates --include=*.html | wc -l
grep -rl '<div class="page-header"' app/templates --include=*.html | wc -l

# build ulang setelah perubahan
python tools/build_css.py
```
