# Tugas: Rombak UI/UX role PENGANTAR (kurir) jadi aplikasi HP, satu gaya dengan portal

Kamu bekerja di repo ERP Flask ini. Baca dulu `RENCANA_PENGEMBANGAN_ERP.md` bagian "Riwayat perubahan" tanggal 2026-10-10 dan 2026-10-11 (aturan portal: data asli, Tailwind lokal, satu pintu per halaman).

## Tujuan
Pengantar selalu pakai HP. Semua halaman yang dibuka role `PENGANTAR` harus tampil sebagai aplikasi mobile, persis gaya portal (`app/templates/layouts/portal_mobile.html` + `app/static/css/portal_tailwind.css`). Role lain (OWNER/ADMIN) yang membuka halaman yang sama TETAP memakai tampilan internal lama — jangan diubah.

## Halaman pengantar (sumber: route di bawah, template lama sebagai acuan isi & form)
- `dashboard.pengantar` → `dashboard/pengantar.html` (role_required PENGANTAR saja → template lama boleh diganti langsung)
- `delivery.today` → `delivery/today.html`, `delivery.receiving` → `delivery/receiving.html`, `delivery.history` → `delivery/history.html`
- `delivery.scan` + `delivery/scan/<id>/<sesi>` → `delivery/scan.html`
- `delivery.detail` → `delivery/detail.html`, `delivery.receive` → `delivery/receive.html`
- Notifikasi (`settings` notifications), ganti password, dan halaman "Akun Saya" yang dipakai role internal.
(Cek nama endpoint persisnya di `app/routes/delivery_routes.py`, `dashboard_routes.py`, `settings/*`.)

## Struktur navigasi (WAJIB persis, satu pintu per halaman)
Layout baru `app/templates/layouts/driver_mobile.html` (salin pola portal_mobile: header logo+nama perusahaan+lonceng, tab bawah, sub-tab di header). Tab bawah 5:
1. **Beranda** = dashboard pengantar (ringkasan hari ini, TANPA tombol pintasan ke halaman lain).
2. **Antar** = sub-tab: *Hari Ini* (delivery.today) · *Serah Terima* (delivery.receiving).
3. **Scan** (tombol tengah menonjol) = delivery.scan.
4. **Riwayat** = delivery.history.
5. **Akun** = Akun Saya + ganti password + tombol Keluar (Keluar HANYA di sini).
Notifikasi hanya lewat lonceng di header. Halaman rincian (detail pengiriman, form terima, label) memakai panah kembali ke daftar asalnya — bukan pintu baru. Isi halaman hanya boleh link ke rincian SATU baris (kartu pengiriman → detailnya). Buat peta navigasi di `app/services/driver_navigation_service.py` (contoh: `portal_navigation_service.py`) + `tests/test_driver_navigation.py` yang memastikan tiap endpoint hanya satu pintu.

## Cara memisah tampilan (jangan ubah logika bisnis)
- Buat template baru di `app/templates/driver/` untuk tiap halaman di atas, extends `layouts/driver_mobile.html`.
- Di route, hanya ubah PEMILIHAN template: bila `current_user.role == "PENGANTAR"` render `driver/xxx.html` dengan context yang SAMA PERSIS; selain itu template lama. Tidak boleh mengubah query, service, validasi, status, transaksi.
- Setiap form di template baru: `action`, `method`, nama field, `csrf_token`, `enctype`, atribut `data-*` yang dipakai JS (`app/static/js/controls.js`, `main.js`, JS scan kamera) HARUS sama dengan template lama. Bandingkan baris per baris. Jangan ada fitur yang hilang: foto bukti, jumlah diterima/kurang, pengganti kekurangan, petunjuk arah/GPS, scan kamera, label wadah, batal kirim, dispatch.

## Aturan UI/UX
- DILARANG data contoh/hardcode (nama, angka, tanggal, menu, plat nomor, nomor WA), DILARANG gambar dari internet, DILARANG CDN. Semua dari variabel template.
- Tambah `./app/templates/driver/**/*.html` dan layout baru ke `content` di `tools/portal_tailwind/tailwind.config.js`, lalu jalankan `tools\portal_tailwind\build.ps1` (boleh: ini hanya kompilasi CSS).
- Muat script bersama seperti portal_mobile (bootstrap.bundle, tom-select, flatpickr, controls.js dengan data-leaflet-*, main.js) + script khusus scan yang dipakai `delivery/scan.html`.
- Mobile-first 360–480px: tombol ≥ 44px, aksi utama (Kirim/Terima/Simpan) di bawah layar dan besar, teks kontras untuk di luar ruangan, angka porsi besar, satu tangan.
- Label Bahasa Indonesia, istilah dari `term()`; waktu UTC tampil pakai filter `|wib`.
- Flash pesan pakai kelas `alert alert-<kategori>` (dibaca skrip gladi).
- Tanpa underline saat hover; kartu gaya dashboard seperti portal.

## Larangan keras
- JANGAN `git clean`, `git checkout -- .`, `git reset --hard`, hapus file untracked, `git add -A`, commit, atau push.
- JANGAN sentuh `.env`, `storage/`, `instance/`, `app/static/uploads/`, migrasi, model, atau `tools/reset_staging_demo.py`.
- JANGAN jalankan pytest, `flask db ...`, job, atau skrip apa pun terhadap DB dev.

## Tes
- Tulis/ubah tes: halaman pengantar render 200 untuk PENGANTAR memakai `driver_mobile` (cek ada `driver-mobile-shell`), halaman yang sama untuk ADMIN tetap layout internal, tes satu pintu (`tests/test_driver_navigation.py`). Ubah tes lama hanya bila ia mengecek markup lama, jangan melemahkan tes perilaku.
- Akhiri laporanmu dengan perintah untuk owner:
  `venv\Scripts\python.exe -m pytest -q tests/test_driver_navigation.py tests/test_delivery_scan_flow.py tests/test_delivery_fees.py tests/test_portal_navigation.py`
  dan daftar file yang kamu ubah/buat.
