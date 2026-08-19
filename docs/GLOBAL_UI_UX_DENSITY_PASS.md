# Global UI UX Density Pass

Tanggal: 2026-08-04

## Tujuan

Merapikan UI ERP dan portal secara global tanpa mengubah logic bisnis. Fokus utama adalah keterbacaan, konsistensi ukuran card/form/table/button, dan menghapus kesan halaman yang terlalu ramai.

## Prinsip Final

- Tidak memakai tampilan warna bertingkat sebagai fondasi visual.
- Surface utama putih atau slate sangat muda.
- Teks utama selalu gelap.
- Teks pendukung tetap gelap-sedang, bukan abu terlalu pucat.
- Primary action memakai orange solid.
- Secondary action memakai surface putih dengan border jelas.
- Disabled action tetap terlihat, bukan hilang.
- Card memakai radius dan padding konsisten.
- Table selalu punya header tegas, scroll horizontal, dan row hover halus.
- Form memakai label tebal, input tinggi konsisten, dan focus state jelas.

## Area Yang Dikunci

- Base shell internal ERP.
- Sidebar dan topbar.
- Page header.
- Card, panel, section, metric card.
- Button primary/secondary/danger/disabled.
- Dropdown/action menu.
- Form, select, input date, textarea, checkbox.
- Table dan responsive table wrapper.
- Badge, alert, empty state.
- Login/auth page.
- Portal customer, mandor, PT.
- Portal topbar, nav, hero, flow, metric, action card, panel, list, ledger.
- Portal register dan feature pages.
- Modal, toast, accordion, tabs, pagination.
- Mobile responsive layout.

## File Utama

- `app/static/css/src/147_global_ui_ux_density_lock.css`
- `app/static/css/src/148_portal_executive_polish_lock.css`
- `app/static/css/src/149_portal_topbar_compact_lock.css`
- `app/static/css/src/150_portal_topbar_single_row_lock.css`
- `app/static/css/src/151_portal_topbar_collision_fix.css`
- `app/static/css/src/152_portal_topbar_structural_grid_fix.css`
- `app/static/css/src/153_portal_topbar_no_avatar_lock.css`
- `app/static/css/src/154_global_calm_interface_lock.css`
- `app/static/css/src/155_global_layout_balance_lock.css`
- `app/static/css/src/156_global_minimal_clarity_lock.css`
- `app/static/css/src/157_dark_card_contrast_rescue_lock.css`
- `app/static/css/src/158_portal_feature_dark_summary_contrast_lock.css`
- `app/static/css/src/159_portal_summary_grid_spacing_lock.css`
- `app/static/css/src/160_global_typography_weight_slim_lock.css`
- `app/static/css/src/161_portal_component_precision_lock.css`
- `app/static/css/src/162_portal_neutral_metric_card_lock.css`
- `app/static/css/src/163_portal_active_button_inner_box_lock.css`
- `app/static/css/src/164_global_flash_toast_compact_lock.css`
- `app/static/css/src/165_global_flash_toast_redesign_lock.css`
- `app/static/css/style.css`
- `tools/build_css.py`
- `scripts/verify_recovered_css_lock.py`
- `tests/test_recovered_css_lock.py`
- `app/templates/layouts/base.html`
- `app/templates/layouts/portal_mobile.html`

## Verifikasi

Jalankan:

```powershell
.\.venv\Scripts\python.exe tools\build_css.py
.\.venv\Scripts\python.exe scripts\verify_recovered_css_lock.py
.\.venv\Scripts\python.exe scripts\portal_regression_smoke.py
.\.venv\Scripts\python.exe -m compileall -q app tests scripts tools
.\.venv\Scripts\python.exe -m pytest tests\test_recovered_css_lock.py -q
```

## Catatan

Perubahan ini hanya UI/CSS. Tidak ada perubahan schema database, transaksi, invoice, stok, posting akuntansi, atau constraint ERP.

## Portal Executive Polish

Pass lanjutan `148_portal_executive_polish_lock.css` mengurangi outline orange berlebihan, memperlebar workspace portal, menstabilkan hero, membuat flow pelanggan lebih bersih, dan merapikan card/action/metric agar dashboard portal terasa lebih profesional.

Pass topbar `149_portal_topbar_compact_lock.css` dan `150_portal_topbar_single_row_lock.css` mengubah header portal menjadi satu baris desktop: brand di kiri, navigasi di tengah, user/logout di kanan. Ini mengurangi tinggi topbar dan menghilangkan area kosong besar di bagian atas halaman portal.

## Global Calm Interface Lock

Pass lanjutan `154_global_calm_interface_lock.css` mengunci tampilan global agar lebih tenang dan konsisten: background utama netral, card/panel lebih rapi, form dan table lebih seragam, tombol lebih jelas, catatan visual berkurang, dan elemen utama tidak lagi memakai background bertingkat. Pass ini tetap murni CSS/template cache dan tidak mengubah workflow atau logic bisnis.

## Global Layout Balance Lock

Pass `155_global_layout_balance_lock.css` memusatkan perbaikan pada keseimbangan halaman: topbar portal memakai grid brand-nav-user yang stabil, nav portal tidak lagi menabrak avatar/logout karena bisa scroll horizontal, card dan form memakai ukuran seragam, table memakai wrapper yang konsisten, dan spacing halaman dibuat lebih padat namun tetap terbaca. Pass ini juga menegaskan warna solid tanpa background bertingkat untuk elemen utama.

## Global Minimal Clarity Lock

Pass `156_global_minimal_clarity_lock.css` menurunkan intensitas visual global: header dibuat lebih kecil, tombol dan input lebih compact, card/panel lebih sederhana, table lebih padat, topbar portal lebih rendah, hero portal lebih ringan, dan teks dipaksa tetap kontras pada semua role portal. Pass ini menjaga warna solid tanpa gradasi dan tidak mengubah logic aplikasi.

## Dark Card Contrast Rescue

Pass `157_dark_card_contrast_rescue_lock.css` memperbaiki kartu metrik/status gelap yang sebelumnya memakai teks gelap akibat global text lock. Semua varian dark/highlight/success/warning/danger/info sekarang memaksa teks, angka, label, dan ikon menjadi putih/terang. Kartu putih tetap memakai teks gelap agar kontras konsisten.

## Portal Feature Dark Summary Contrast

Pass `158_portal_feature_dark_summary_contrast_lock.css` memperbaiki kartu ringkasan gelap di halaman fitur portal seperti Pembayaran dan Komplain. Target utamanya adalah `.portal-ledger-total` dan `.portal-service-summary article.primary`, karena dua kartu ini tidak memakai class dark/highlight umum tetapi tetap memiliki background gelap.

## Portal Summary Grid Spacing

Pass `159_portal_summary_grid_spacing_lock.css` memperbaiki akar clipping di kartu ringkasan portal. Masalahnya bukan warna, tetapi grid/card spacing lama yang membuat konten kartu pertama terlalu mepet ke sisi kiri. Pass ini mengunci grid summary, padding article, `box-sizing`, dan wrapping teks untuk halaman Pembayaran/Komplain/fitur portal sejenis.

## Global Typography Weight Slim

Pass `160_global_typography_weight_slim_lock.css` menurunkan ketebalan font global yang sebelumnya terlalu banyak memakai `900/950`. Heading, label, badge, tombol, metric value, dan flow card dibuat lebih ringan. Tombol juga tidak lagi terlalu gemuk/pill besar; radius dan tinggi kontrol dibuat lebih proporsional.

## Portal Component Precision

Pass `161_portal_component_precision_lock.css` memperbaiki langsung komponen yang terlihat berantakan pada portal customer: flow "Alur pelanggan umum", tombol kecil seperti Buka/Retur, mini ledger Komplain/Terbuka, action card, dan primary action seperti Order Baru. Fokusnya adalah menghapus tombol kapsul di dalam kapsul, menurunkan ketebalan teks, mengurangi radius berlebihan, dan membuat spacing komponen lebih presisi.

## Portal Neutral Metric Card

Pass `162_portal_neutral_metric_card_lock.css` menyatukan kartu angka/status portal yang sebelumnya berbeda warna antar halaman. Kartu ringkasan customer, pembayaran, komplain, precheck, ledger, dan feature portal sekarang memakai surface putih, border netral, spacing seragam, dan tipografi lebih ringan. Warna penuh hanya dipakai untuk aksi aktif seperti tombol primary/nav aktif, bukan sebagai background besar pada kartu metrik.

## Portal Active Button Inner Box

Pass `163_portal_active_button_inner_box_lock.css` menghapus kotak warna sekunder yang muncul di belakang ikon dan teks pada tombol/nav aktif portal. Tombol aktif sekarang menjadi satu bidang warna solid; elemen anak seperti `i`, `span`, dan `svg` dipaksa transparan agar tidak muncul blok warna berbeda di dalam pill.

## Global Flash Toast Compact

Pass `164_global_flash_toast_compact_lock.css` mengubah flash message login/logout/dashboard menjadi toast modern yang lebih compact. Alert tidak lagi tampil seperti banner besar lonjong; lebar dibatasi, radius sedang, ikon lebih kecil, tombol close tidak menjadi kotak kosong besar, dan warna status tetap solid serta lembut.

## Global Flash Toast Redesign

Pass `165_global_flash_toast_redesign_lock.css` mengganti bentuk flash runtime `.app-flash-centered` secara penuh: toast menjadi kartu putih kecil dengan accent kiri tipis, ikon status kecil, close control ringan, shadow halus, posisi bawah-kanan di desktop agar tidak menutup topbar/nav, dan animasi slide/fade. Ini mengoverride host lama `.app-flash-center-host` yang sebelumnya membuat alert terasa seperti banner besar di tengah layar.
