# Tugas: Semua notifikasi hasil proses jadi dialog di TENGAH layar (seluruh sistem, tanpa kecuali)

Keputusan owner: pesan hasil proses (berhasil/gagal/peringatan/info) sekarang mudah terlewat. Mulai sekarang di SEMUA halaman semua role:
- muncul **instan saat halaman terbuka**, berupa **kotak di tengah layar**;
- latar belakang **di-blur & digelapkan**, halaman di belakang **tidak bisa diklik/di-scroll**;
- hanya bisa ditutup dengan tombol **"Mengerti"** (Esc dan klik di luar kotak TIDAK menutup);
- isi pesan besar & jelas dibaca; ikon + warna sesuai jenis (Berhasil hijau, Gagal merah, Perhatian kuning, Info biru); judul mengikuti jenis terparah bila ada beberapa pesan; beberapa pesan tampil sebagai daftar dalam satu kotak.

## Cara (satu komponen untuk semua — jangan bikin versi per halaman)
1. Buat `app/templates/components/flash_dialog.html`: satu-satunya tempat yang memanggil `get_flashed_messages(with_categories=true)`. Isi: `<dialog id="appFlashDialog" role="alertdialog" aria-modal="true" aria-labelledby=...>` + daftar pesan + tombol "Mengerti" (`<form method="dialog">`). Script kecil inline di komponen: `showModal()` saat `DOMContentLoaded`, cegah event `cancel` (Esc), kunci scroll `body` selama terbuka, fokus ke tombol. Harus jalan walau `main.js` tidak dimuat.
   - **Wajib** tiap pesan berbentuk `<div class="alert alert-{{ 'danger' if category == 'error' else category }} app-flash-item" role="alert">TEKS</div>` — teks polos tanpa `<div>` bersarang (dibaca skrip gladi `tools/pilot_dry_run.py` lewat regex `alert-(success|info|warning|danger|error)`).
2. CSS di file baru `app/static/css/flash_dialog.css` (CSS biasa, bukan Tailwind/Bootstrap, karena dipakai di dua dunia CSS): `::backdrop` gelap + `backdrop-filter: blur(6px)`, kotak tengah lebar `min(92vw, 440px)`, tombol tinggi ≥ 48px, teks ≥ 15px, warna token oranye tenang yang sudah dipakai (`#a33900`). Komponen memuat CSS ini sendiri lewat `<link>` dengan `v=css_asset_version`.
3. Ganti blok flash lama dengan `{% include "components/flash_dialog.html" %}` di SEMUA tempat ini (cari ulang dengan `grep -rn get_flashed_messages app/templates` — hasil akhir harus hanya komponen baru):
   - `layouts/base.html` (semua halaman internal + halaman publik yang memakai `public_view`),
   - `components/public_flashes.html` (dipakai login, lupa/reset password, daftar portal, landing, kerja sama) — isinya cukup meng-include komponen baru,
   - `layouts/portal_mobile.html`, `layouts/driver_mobile.html`, `layouts/ops_mobile.html`.
   Template cetak (`finance/invoice_print.html`, `finance/receivables_print.html`, `contracts/contract_document_print.html`) tidak memakai flash — biarkan.
4. JS `app/static/js/main.js`: buat `window.appNotify(message, tone)` yang membuka dialog yang SAMA (buat elemennya bila belum ada), lalu jadikan `window.appToast` alias `appNotify` agar 4 pemanggil lama (`main.js` ×3, `portal/payment_instruction.html` ×1) ikut tampil di tengah. Jangan ubah `appConfirm` (konfirmasi sebelum aksi tetap seperti sekarang).
5. Jangan ubah satu pun pemanggilan `flash(...)` di Python. Jangan ubah pesan validasi yang tampil di samping kolom form (itu bukan notifikasi hasil proses).
6. Jalankan `python tools/build_css.py` HANYA bila kamu mengubah file di `app/static/css/app/`; jalankan `tools\portal_tailwind\build.ps1` bila mengubah template Tailwind.

## Tes (tulis, JANGAN jalankan)
`tests/test_flash_dialog.py`:
- tidak ada template selain `components/flash_dialog.html` yang memanggil `get_flashed_messages`;
- kelima layout + `components/public_flashes.html` meng-include `components/flash_dialog.html`;
- setelah aksi yang mem-flash (contoh: login gagal di `/login`, dan satu halaman internal, satu portal, satu pengantar, satu ops) HTML berisi `id="appFlashDialog"`, `role="alertdialog"`, kelas `alert alert-<kategori>`, dan teks pesannya;
- `main.js` mendefinisikan `appNotify` dan `appToast` memakai fungsi yang sama.
Ubah tes lama HANYA bila ia mengecek markup flash lama (mis. `alert-dismissible`), jangan melemahkan tes perilaku.

## Larangan keras
- JANGAN `git clean`, `git checkout -- .`, `git reset --hard`, hapus file untracked, `git add -A`, commit, push.
- JANGAN sentuh `.env`, `storage/`, `instance/`, `app/static/uploads/`, `tools/reset_staging_demo.py`.
- JANGAN jalankan pytest, `flask db ...`, job, atau skrip ke DB dev.
- Kerjakan per file kecil; kalau percakapan sudah panjang, berhenti dan laporkan apa yang sudah/ belum selesai.

Selesai → daftar file + perintah owner:
`venv\Scripts\python.exe -m pytest -q tests/test_flash_dialog.py tests/test_portal_navigation.py tests/test_driver_navigation.py tests/test_ops_navigation.py tests/test_ui_ux_static_contracts.py tests/test_portal_account_email.py`
