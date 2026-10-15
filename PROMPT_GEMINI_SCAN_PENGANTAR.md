# TUGAS: Tombol "Scan Label" untuk pengantar → langsung ke serah terima order

Repo Flask ERP PT Idha Boga (Python 3.11, Flask, Jinja2, SQLAlchemy, PostgreSQL, Windows PowerShell, `venv\`).
Label wadah sudah punya QR yang menunjuk ke route scan buatan tugas sebelumnya (`/delivery/scan/<daily_order_detail_id>/<sesi>` di `app/routes/delivery_routes.py`) yang redirect ke halaman serah terima `delivery_routes.receive`. Sekarang pengantar harus bisa scan **dari dalam aplikasi**. **Baca kode terkait dulu** (route scan, `receive`, `receiving`, dashboard pengantar, `kitchen_recap_service.py`); kalau tidak cocok dengan prompt, berhenti dan laporkan.

## Aturan wajib
- Tidak ada commit/rollback di route; tidak ada except luas yang diam (`tests/test_db_commit_audit_tool.py`, `tests/test_exception_hygiene.py`). Waktu pakai `now_wib()`.
- **Ikuti UI yang sudah ada**: kelas & token yang sama, card `var(--radius-lg)`, tombol/input `var(--radius)`, tanpa hex baru, rapi di HP 390px. CSS di `app/static/css/app/*.css` lalu `venv\Scripts\python.exe tools\build_css.py`. JS di `app/static/js/controls.js` (pola `setupXxx()` yang ada).
- Script eksternal hanya dari cdnjs.cloudflare.com / cdn.jsdelivr.net/npm / unpkg.com, dengan versi dikunci.
- Jangan sentuh `.env`, `storage/`, `app.zip`, `tools/reset_staging_demo.py`, tabel `ml_*`. Jangan git add/commit/push. Jangan jalankan server.

## Yang dikerjakan
1. **Dashboard pengantar**: tombol besar **"Scan Label Wadah"** (ikon kamera) paling atas, juga tetap terlihat di HP (sticky di bawah layar boleh). Tampilkan juga di halaman Penerimaan/Antar (`receiving`).
2. **Halaman scan** `GET /delivery/scan` (role PENGANTAR, ADMIN, OWNER):
   - Buka kamera belakang dan baca QR. Pakai `BarcodeDetector` bawaan browser bila tersedia; kalau tidak, library `html5-qrcode` dari CDN (versi dikunci).
   - Begitu terbaca: pastikan isinya URL **origin yang sama** dan path diawali `/delivery/scan/` → langsung pindah ke URL itu (bunyi/getar singkat kalau didukung). QR lain → pesan "Ini bukan label Idha Boga."
   - Cadangan tanpa kamera: input manual kode label + tombol "Buka"; dan tombol "Pilih dari daftar" ke halaman `receiving`.
   - Kalau kamera ditolak/tidak tersedia, tampilkan penjelasan singkat. **Catatan**: kamera browser hanya jalan di HTTPS atau `localhost`; tampilkan petunjuk ini bila `window.isSecureContext` false, dan sebutkan bahwa kamera bawaan HP juga bisa dipakai untuk scan QR label.
3. **Setelah scan** (halaman `receive`), buat cepat:
   - Header jelas: nama pemesan, lokasi, sesi, **porsi dipesan**, info "Wadah 2/3 — pesanan ini punya 3 wadah" (ambil nomor wadah dari QR/parameter jika ada; kalau QR belum memuat nomor wadah, tambahkan parameter opsional `?w=2&n=3` ke URL QR di label).
   - **Realisasi porsi** sudah terisi = porsi dipesan (bisa diubah), **foto bukti** langsung buka kamera (`capture="environment"`), tombol besar **"Selesai Diantar"**.
   - Kalau order ini **sudah diterima**: jangan tampilkan form; tampilkan "Sudah diantar jam HH:MM oleh ..." + foto, dan tombol "Scan berikutnya".
   - Setelah simpan sukses → kembali ke halaman scan dengan pesan "Tersimpan. Scan label berikutnya." supaya pengantar bisa lanjut tanpa mencari menu.
   - Kalau pengiriman untuk order itu belum dibuat admin: pesan jelas "Pengiriman belum dibuat admin untuk pesanan ini" + tombol hubungi/kembali (jangan buat data pengiriman diam-diam).
4. Akses: pengantar hanya bisa membuka order cabangnya; role lain ditolak seperti route scan yang ada.

## Test (file baru `tests/test_delivery_scan_flow.py`)
- Dashboard pengantar memuat tombol "Scan Label Wadah" dan link ke `/delivery/scan`.
- `/delivery/scan` bisa dibuka PENGANTAR/ADMIN, ditolak role portal.
- Route scan QR → redirect ke `receive` yang benar; order sudah diterima → halaman menampilkan status, bukan form.
- Simpan serah terima dari halaman hasil scan → redirect ke `/delivery/scan` dengan pesan sukses.
- Label yang dicetak memuat URL QR dengan nomor wadah (bila ditambahkan).

## Verifikasi
```powershell
venv\Scripts\python.exe tools\build_css.py
venv\Scripts\python.exe -m pytest tests/test_delivery_scan_flow.py tests/test_kitchen_recap_container_labels.py tests/test_db_commit_audit_tool.py tests/test_exception_hygiene.py -q
venv\Scripts\python.exe -m pytest -q
```
Semua harus lulus. Laporan akhir: file diubah/baru, hasil test, asumsi, langkah uji manual di HP.
