# TUGAS: Fase 1 (perbaikan cepat) + Fase 2 (rekap dapur & label wadah)

Repo Flask ERP PT Idha Boga Pangan Mandiri (Python 3.11, Flask, Jinja2, SQLAlchemy, Alembic, PostgreSQL, Windows PowerShell, `venv\`).
Baca seluruh prompt dulu. Kerjakan **per bagian, berurutan (1.1 → 2)**. Setelah tiap bagian: jalankan test terkait, laporkan singkat (file diubah + hasil test). **Baca kode yang relevan sendiri sebelum mengubah** — jangan menebak nama fungsi/field; kalau fakta di prompt tidak cocok dengan kode, berhenti dan laporkan.

## ATURAN WAJIB (sama seperti tugas sebelumnya)
1. Tidak ada `db.session.commit()/rollback()` di route; commit lewat `atomic_business_action` di service. Service yang memanggil fungsi publik ber-commit wajib kirim `commit=False`. (`tests/test_db_commit_audit_tool.py`)
2. Tidak ada `except Exception: pass` / except luas yang diam. (`tests/test_exception_hygiene.py`)
3. Uang pakai Decimal. Query dibatasi `branch_id`. Waktu pakai `now_wib()` / `today_wib()` dari `app/utils/clock.py`, **bukan** `datetime.now()` / `date.today()`.
4. Jangan sentuh: `storage/`, `instance/`, `.env`, `app.zip`, `tools/reset_staging_demo.py`, tabel `ml_*` / `research_dataset_*`. Jangan DROP/TRUNCATE. Jangan `git add -A`, commit, atau push. Jangan jalankan/matikan server dev user.
5. Teks UI Bahasa Indonesia sederhana. Jangan hapus route lama yang dipakai test.
6. Pertahankan line ending CRLF pada file yang sudah CRLF.

## ATURAN UI (WAJIB — hasil sebelumnya ada kesalahan sudut card terlalu siku)
- **Ikuti UI yang sudah ada.** Sebelum membuat halaman/komponen baru, buka halaman sejenis yang sudah ada (mis. `app/templates/portal/_home_kit.html` + kelas `ph-*` di `portal.css`, atau halaman finance lain) dan tiru struktur & kelasnya.
- **Radius wajib pakai token** dari `app/static/css/app/tokens.css`: card/panel/kotak besar `var(--radius-lg)` (14px); input, tombol, badge kecil `var(--radius)` / `var(--radius-sm)`; pill `var(--radius-pill)`. **Dilarang** `border-radius: 0` atau angka px mentah untuk card.
- Warna, bayangan, spasi juga pakai token yang ada; jangan hex baru.
- Kelas yang dipakai: `app-btn-primary`, `app-btn-secondary`, `status-badge`, `form-control`, `form-select`. Tombol aksi berjajar horizontal, tanpa garis bawah saat hover, tanpa dark mode, layout rapi di HP (lebar 390px).
- **Sekalian perbaiki**: kartu di halaman `finance/payment_inbox.html` (kelas `pin-*` di `pages.css`) yang sudutnya siku → pakai `var(--radius-lg)`; cek juga elemen `pin-*` lain (tabel uang, kotak peringatan, form) supaya radiusnya konsisten dengan kartu dashboard.
- CSS ditulis di `app/static/css/app/*.css`, lalu WAJIB `venv\Scripts\python.exe tools\build_css.py`. Jangan edit `style.css` langsung.

---

## FASE 1 — Perbaikan cepat

### 1.1 Bug: pelanggan bisa memesan sesi yang sudah tutup (PALING PENTING)
Masalah: `_validate_draft_payload()` di `app/services/portal_order_draft_service.py` tidak mengecek batas jam (`PORTAL_CUTOFF_TIMES`: LUNCH 10:00, DINNER 15:00) maupun `DailyOrder.is_locked` untuk tanggal itu. Pemeriksaan baru terjadi saat admin konfirmasi → pelanggan telanjur transfer.
Perbaiki:
- Buat satu helper `session_closed_reason(branch_id, order_date, meal_type) -> str | None` (pakai WIB). Tutup bila: tanggal lampau; tanggal = hari ini dan jam WIB > cutoff sesi; atau `DailyOrder` cabang+tanggal itu `is_locked`.
- `_validate_draft_payload` menolak dengan pesan dari helper.
- Form pesan portal (`app/templates/portal/draft_order.html`, langkah tanggal & sesi): sesi yang tutup **disabled, abu-abu, label "Sudah tutup"**. Data tutup/buka dikirim dari server (bukan dihitung JS saja).
- Upload bukti bayar draft (`upload_portal_order_draft_payment_proof` di `portal_payment_proof_service.py`) ditolak bila sesi draft sudah tutup: "Pesanan ini sudah lewat batas waktu dan tidak bisa diproses. Hubungi admin." Di daftar "menunggu pembayaran" portal, draft seperti ini tampil dengan tanda itu dan tanpa form upload.
- Ganti `datetime.now()` di `_cutoff_gate_for_draft` dengan `now_wib()`.
- Test: pesan sesi tutup ditolak; pesan sesi buka diterima; tanggal yang di-lock ditolak; upload bukti untuk draft tutup ditolak; pakai waktu yang di-mock.

### 1.2 Bug: notifikasi & SOP tercampur antar role
- Cari semua tempat notifikasi ditampilkan/dihitung (`app/services/notification_service.py`: `list_notifications`, `count_unread_notifications`, badge di layout/sidebar/portal) dan semua tempat SOP ditampilkan (cari "SOP" di templates/services/routes).
- Aturan: user hanya melihat notifikasi dengan `target_user_id == user.id`, atau `target_role == role user` (perhatikan pemetaan role lama → baru di `app/utils/roles.py`), atau notifikasi umum cabang yang memang untuk semua (kalau ada konsep itu). User portal **tidak boleh** melihat notifikasi internal, dan sebaliknya. SOP yang tampil hanya untuk role yang login.
- Test: akun ADMIN, DAPUR, PENGANTAR, dan portal masing-masing hanya melihat miliknya (list + jumlah badge).

### 1.3 Lupa password
- Link "Lupa password?" di halaman login → form email → kirim link reset (token acak `secrets.token_urlsafe`, simpan **hash**-nya, berlaku 30 menit, sekali pakai) → halaman set password baru (validasi kekuatan password memakai aturan yang sudah ada di sistem).
- Pesan setelah submit selalu sama ("Kalau email terdaftar, link reset sudah dikirim") — jangan bocorkan email terdaftar/tidak. Batasi permintaan (rate limit yang sudah ada di app, kalau ada).
- Kirim email pakai `smtplib` (stdlib) dengan konfigurasi dari environment: `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_USE_TLS`, `MAIL_FROM` (baca lewat `config.py`). Jangan tulis kredensial ke file. Kalau konfigurasi kosong: jangan crash, catat ke log + tampilkan pesan yang sama ke user.
- Admin/Owner bisa reset password user staf dari halaman manajemen pengguna (kalau belum ada) — password sementara, user wajib ganti saat login berikutnya bila mekanisme itu sudah ada.
- Migrasi baru bila perlu tabel token (down_revision = head saat ini; cek dengan `flask db heads`). Tambahkan migrasi ke `tests/test_numeric_migration_coverage.py`/`tests/test_optimistic_locking_models.py` jika test itu memintanya (lihat cara tugas sebelumnya untuk `a7b8c9d0e1f2`).
- Test: token valid/kadaluarsa/sekali pakai; email tidak terdaftar memberi pesan sama; SMTP di-mock.
- Di laporan, beri tahu owner baris `.env` yang perlu diisi (Gmail: `smtp.gmail.com`, port 587, TLS, pakai **App Password** Gmail).

### 1.4 Tulisan halaman publik
- Halaman login: ganti "Satu sistem untuk pesanan, dapur, pengiriman, dan tagihan." menjadi teks untuk pelanggan, mis. "Pesan catering harian, lacak pengiriman, dan bayar tagihan — semua dalam satu tempat."
- Periksa juga landing page, halaman daftar pelanggan, dan halaman kerja sama: ganti kalimat yang terkesan sistem internal (kata seperti "internal", "ERP", "modul", "operasional dapur") dengan bahasa pelanggan. Jangan ubah alur/form-nya.
- Update test yang mengecek teks lama (sebutkan di laporan).

### 1.5 Ubah titik alamat + foto di portal
- Cek halaman Alamat portal (`/portal/addresses`, `portal_address_service.py`, `addresses.html`). Pastikan user portal (pelanggan umum, sub client, client) bisa: tambah alamat (sudah ada), **ubah** nama/patokan/titik peta alamat miliknya, serta tambah/hapus foto (komponen `components/location_photos.html` sudah ada; minimal 1 foto tetap wajib).
- Kalau "ubah" belum ada, buat dengan peta Leaflet yang sama seperti saat tambah. Hanya alamat dalam akses akun itu (`orderable_location_ids` / scope portal). Perubahan dicatat di audit log.
- Test: user bisa ubah alamat miliknya; ditolak untuk alamat milik akun lain.

---

## FASE 2 — Rekap dapur & label wadah

Berlaku untuk **SEMUA pesanan di satu tanggal + sesi**, termasuk pelanggan portal umum (bayar di muka), bukan hanya client kontrak. Sumber data: `DailyOrder` + `DailyOrderDetail` (pelajari modelnya dan halaman Operasional yang sudah ada).

### 2.1 Pengaturan
- Pengaturan cabang `kitchen.max_portions_per_container`, bawaan **20**, hanya boleh 15–20. Ikuti pola pengaturan cabang yang sudah ada (contoh: `DEFAULT_THRESHOLDS` + `branch_settings` di `credit_control_service.py`). Tampilkan di halaman pengaturan yang relevan.
- Pembagian wadah **rata**: `n_wadah = ceil(porsi / max)`, isi dibagi rata, sisa ditaruh di wadah awal. Contoh max 20: 45 → 15,15,15; 50 → 17,17,16; 12 → 12. Buat fungsi murni `split_containers(qty, max_per)` + unit test.

### 2.2 Halaman & tombol cetak
- Di halaman order harian Operasional untuk tanggal itu: tombol **"Cetak Rekap Dapur"** dan **"Cetak Label Wadah"** per sesi (Siang/Malam). **Hanya muncul bila order hari itu sudah di-lock.** Role: OWNER, ADMIN, DAPUR (PENGANTAR boleh label saja).
- Simpan riwayat cetak (siapa, kapan, sesi, ukuran) + sidik isi (hash dari daftar detail+porsi). Kalau isi pesanan berubah setelah dicetak → tampil tanda **"Cetak ulang — data berubah sejak dicetak"** dan label lama dianggap tidak berlaku.

### 2.3 Rekap Dapur (A4)
- Kop PT (pakai data perusahaan yang sudah ada), tanggal, sesi, jam lock.
- **Total porsi besar** di atas + total wadah.
- Tabel per pemesan: no, nama pemesan (client/sub client/pelanggan), lokasi, porsi, jumlah wadah, catatan.
- Kolom paraf: Kepala Dapur, Pengecek. Pakai `app/static/css/app/print.css` (`@media print`).

### 2.4 Label per wadah
- Pilihan ukuran saat cetak: **Thermal 58mm**, **Thermal 80mm**, **Stiker A4** (beberapa label per lembar, grid rapi, garis potong). Pakai `@page` size yang sesuai per pilihan.
- Isi tiap label: nama pemesan (besar), **porsi wadah ini** (besar), "Wadah 1/3", lokasi + patokan, nama & HP penerima (dari data lokasi/pesanan; kosong → "-"), tanggal + sesi, urutan antar (pakai urutan rute pengiriman kalau sudah ada di modul Delivery; kalau belum ada, urut nama lokasi dan **jangan** tampilkan nomor urut), dan **QR code**.
- QR: buat route baru `GET /delivery/scan/<daily_order_detail_id>/<sesi>` yang (login pengantar/admin) mencari detail pengiriman terkait dan redirect ke halaman serah terima yang sudah ada (`delivery_routes.receive`, ±baris 260). Kalau pengiriman belum dibuat, tampilkan pesan jelas. Generate QR di server sebagai SVG inline dengan library **`segno`** (tambahkan ke `requirements.txt`, pure Python) — jangan pakai CDN untuk QR.
- Teks label harus terbaca setelah dicetak hitam-putih.

### 2.5 Test Fase 2
- `split_containers` (kasus di atas + 1, 15, 20, 21, 40).
- Tombol cetak tidak tampil/ditolak sebelum lock; tampil setelah lock.
- Rekap & label memuat pesanan pelanggan umum (prabayar) dan client kontrak.
- Tanda "Cetak ulang" muncul setelah porsi diubah pasca-cetak.
- Route scan QR: redirect benar; role tanpa akses ditolak.

---

## VERIFIKASI AKHIR
```powershell
venv\Scripts\python.exe tools\build_css.py
venv\Scripts\python.exe -m pytest tests/test_db_commit_audit_tool.py tests/test_exception_hygiene.py tests/test_numeric_migration_coverage.py -q
venv\Scripts\python.exe -m pytest -q
```
Semua harus lulus. Perbaiki kodemu, jangan melemahkan test lama (kecuali test teks UI yang sengaja diganti — sebutkan).

## LAPORAN AKHIR
1. File baru & diubah. 2. Hasil test per perintah. 3. Asumsi/ketidaksesuaian. 4. Baris `.env` untuk email yang harus owner isi. 5. Perintah migrasi untuk owner (jangan kamu jalankan di database dev): `venv\Scripts\python.exe -m flask db upgrade`. 6. Langkah uji manual singkat per bagian.
