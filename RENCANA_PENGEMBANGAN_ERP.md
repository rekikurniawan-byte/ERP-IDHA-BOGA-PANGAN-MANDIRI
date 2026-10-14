# Rencana Pengembangan ERP PT Idha Boga Pangan Mandiri

Dokumen acuan tunggal untuk semua fase berikutnya. Isinya adalah **keputusan owner** dari diskusi 5–7 Oktober 2026, ditulis selengkap mungkin supaya setiap fase (dikerjakan Claude maupun Gemini) konsisten.

- **Kalau ada yang bertentangan dengan dokumen ini, dokumen ini yang benar.** Perubahan keputusan harus ditulis di sini dulu (bagian "Riwayat perubahan" paling bawah).
- Status terakhir diperbarui: **7 Oktober 2026**.

---

## 1. Prinsip umum (berlaku untuk semua fase)

1. **Semua fitur harus terintegrasi ke semua lini**:
   Kontrak → Pesanan → Operasional/Dapur → Pengiriman → Invoice → Jurnal → Portal kedua pihak.
   Tidak boleh ada fitur yang berdiri sendiri atau mengharuskan input dua kali.
2. **Akuntansi otomatis, nol toleransi salah.** Setiap transaksi uang langsung dijurnal di service yang mencatatnya, dalam satu transaksi database (gagal satu langkah → batal semua).
3. **Istilah netral bisnis.** "Mandor" hanya label yang bisa diganti untuk **Sub Client** (`app/utils/terms.py`). Sistem dipakai untuk proyek, sekolah, kantor, RS, event, dan pelanggan umum. Aturan kontrak berlaku untuk **semua Client dan Sub Client yang punya kontrak**, termasuk client yang memesan langsung tanpa sub client.
4. **Syariat Islam dalam penagihan**: tidak ada riba (tidak ada denda persen/bunga per hari yang masuk ke pendapatan). Tidak menzalimi pelanggan maupun PT.
5. **Waktu memakai WIB** (`now_wib()` / `today_wib()` di `app/utils/clock.py`), bukan jam server.
6. **Bahasa antarmuka Indonesia sederhana**; pengguna bukan orang IT.
7. **Konfirmasi alur dulu sebelum membangun fitur baru**; owner menjawab keputusan, baru dikerjakan.

### 1.1 Aturan teknis wajib (untuk Claude dan Gemini)
- Tidak ada `db.session.commit()` / `rollback()` di route. Commit lewat `atomic_business_action` di service. Service yang memanggil fungsi publik yang bisa commit wajib mengirim `commit=False` (dijaga `tests/test_db_commit_audit_tool.py`).
- Tidak ada `except Exception: pass` atau except luas yang diam (`tests/test_exception_hygiene.py`).
- Uang memakai `Decimal`, kolom `Numeric(18,2)`. Semua query dibatasi `branch_id`.
- Migrasi baru: `down_revision` = head saat itu; daftarkan di `tests/test_numeric_migration_coverage.py` / `tests/test_optimistic_locking_models.py` bila diminta test.
- File upload disimpan lewat `digital_attachment_service` (di luar `static`), disajikan lewat route yang mengecek hak akses.
- Jangan disentuh: `.env`, `storage/`, `instance/`, `app.zip`, `tools/reset_staging_demo.py`, tabel `ml_*` / `research_dataset_*` (sistem prediksi ML — **jangan diganggu**, jangan DROP/TRUNCATE).
- Tidak `git add -A`; commit hanya file fitur, tidak push kecuali diminta.
- **Dilarang `git clean`, `git checkout -- .`, `git reset --hard`, atau menghapus file yang belum di-commit** (mis. `app/static/uploads/`). Pada 7 Okt 2026 `git clean` oleh AI menghapus permanen logo perusahaan yang sedang dipakai.
- Setiap fase: test fitur + `pytest -q` lengkap harus lulus sebelum commit.
- **Skrip debug/uji coba wajib memakai `test_db`, tidak boleh menulis ke database dev** (`idha_boga_staging`). Pada 7 Okt 2026 skrip debug fitur reminder membuat 10 cabang "Branch Reminder …" + 18 user uji di database dev; dinonaktifkan 9 Okt 2026.

### 1.2 Aturan UI wajib
- **Ikuti UI yang sudah ada**; tiru struktur & kelas halaman sejenis sebelum membuat yang baru.
- Framework: **Bootstrap 5** + Bootstrap Icons; CSS sendiri di 8 file sumber `app/static/css/app/*.css`, digabung otomatis ke `style.css` oleh `tools/build_css.py` (jangan edit `style.css` langsung).
- **Radius pakai token**: card/panel `var(--radius-lg)` (14px); input/tombol/badge `var(--radius)` / `var(--radius-sm)`; pill `var(--radius-pill)`. **Card tidak boleh siku.**
- Warna/bayangan/spasi pakai token; tidak menambah hex baru (batas build: 40 hex di luar token, 12 `!important`).
- Kelas standar: `app-btn-primary`, `app-btn-secondary`, `status-badge`, `form-control`, `form-select`. Tombol aksi berjajar horizontal, tanpa garis bawah saat hover, **tanpa dark mode**, oranye kalem, rapi di HP lebar 390px, kartu bergaya dashboard.
- UI tidak dianggap selesai hanya dari angka/test — harus dilihat langsung.

### 1.3 Cara kerja dengan Gemini (hemat token Claude)
- Claude membuat prompt **ringkas** (tujuan, keputusan, file utama, aturan, test) — Gemini membaca kode sendiri.
- Satu prompt per sesi Gemini; selesai → test → Claude cek bagian penting → commit → prompt berikutnya.
- Bagian **uang & jurnal** (invoice otomatis, kredit syariah, pajak) dikerjakan **Claude sendiri**.

---

## 2. Status fase

| Fase | Isi | Pelaksana | Status |
|---|---|---|---|
| 0 | Verifikasi pembayaran 1 klik ("Pembayaran Masuk") | Gemini + cek Claude | ✅ `2c845d4` |
| 1 | Perbaikan cepat (batas pesan, notifikasi & SOP per role, lupa password, tulisan publik, ubah alamat) | Gemini + cek Claude | ✅ `0fd751e` |
| 1+ | Email wajib akun portal | Gemini + cek Claude | ✅ `0fd751e` |
| 2 | Rekap dapur & label wadah | Gemini + cek Claude | ✅ `0fd751e` |
| 2+ | Tombol Scan Label untuk pengantar | Gemini + perbaikan Claude (izin kamera) | ✅ `c61ee41` |
| T1 | "Akun Saya" semua role + menu harian dengan foto | Gemini | ✅ `af92cf4` |
| T2 | Reminder sesuai role | Gemini | ✅ `b18465f` |
| 3 | Pengaturan kontrak | Gemini + cek Claude | ✅ |
| 4 | Penjadwal otomatis | Gemini + perbaikan Claude | ✅ (799 test lulus) |
| 5 | Pesanan otomatis | Gemini + perbaikan Claude | ✅ (799 test lulus) |
| 6 | Invoice otomatis | **Claude** | ✅ `78d5c47` |
| 7 | Kontrol kredit syariah + ta'zir | **Claude** | ✅ `78d5c47` |
| 8 | Pajak | **Claude** | ✅ `e3f5f8d` (semua pajak mati sampai diisi di Pengaturan Pajak) |
| WIB | Semua tanggal bisnis pakai WIB | Gemini + cek Claude | ✅ |
| Gladi | Gladi pilot ulang Fase 3–7 + SDM/kasbon/penggajian/PPh 21 | Claude | ✅ 217/217 langkah, 64/64 cek (2026-10-12) |
| 9 | Surat kontrak otomatis | Gemini + perbaikan Claude | ✅ `e3f5f8d` |
| SDM | Tenaga kerja (kontrak, apel, izin, mangkir, denda, keluar), slip & kwitansi, aturan potongan sesuai UU, PPh 21, kasbon, draf Peraturan Perusahaan | Claude (+ PPh 21 Opus, diperbaiki Claude) | ✅ (belum commit; migrasi `j8…`–`o3f4a5b6c7d8`) |
| BPJS | BPJS Ketenagakerjaan & Kesehatan | — | ⏸ ditunda owner (2026-10-12) |
| Go-live | Daftar periksa go-live | Gemini | ✅ deployment/GO_LIVE_PILOT.md |
| Warung | Kasir cepat (3 ketukan) + tab Warung di HP Admin Operasional | Claude | ✅ (belum commit) |
| UI-1 | UI desktop internal gaya biru (contoh: kerangka + Dashboard Owner/Admin + 360° Pelanggan) | Gemini → dikerjakan ulang Claude | ✅ contoh disetujui owner 2026-10-13 (belum commit) |
| UI-2 | Sebar UI biru ke semua halaman desktop (7 batch per folder) | Gemini, audit Claude | ⏳ `PROMPT_GEMINI_UI_TAHAP2.md` |

**Alasan urutan:** kontrak (3) adalah fondasi aturan; penjadwal (4) dibutuhkan pesanan jam 18.00 dan invoice jam 06.00; invoice (6) harus ada sebelum kontrol kredit (7) bisa menghitung tunggakan; pajak (8) mengubah isi invoice; surat kontrak (9) terakhir karena menjelaskan **semua** aturan fase 3–8 — kalau dibuat lebih awal isinya bisa tidak cocok dengan sistem.

---

## 3. Yang sudah selesai (ringkasan perilaku, untuk acuan)

### 3.1 Pembayaran Masuk (Fase 0)
- Satu halaman `/finance/payment-inbox`: foto bukti, nama pelanggan, HP, lokasi, pesanan, tabel Total / Sudah bayar / Sisa / Kode unik / **Harus ditransfer** / **Diklaim pelanggan**, badge Cocok/Kurang/Lebih.
- Tombol **"Terima & Konfirmasi"** = verifikasi bukti + catat uang muka (2008) + konfirmasi pesanan ke Operasional, **satu transaksi**.
- Kurang bayar → uang dicatat, pesanan **ditahan**, pelanggan diberi tahu sisanya. Lebih bayar (di luar kode unik) → **diblok**.
- **Kode unik 3 digit** (1–999) ditambahkan ke transfer pertama; selisihnya otomatis → penyesuaian kas/bank kategori `KODE_UNIK` → **4004 Pendapatan Lain-Lain** (tidak muncul di form manual).
- Anti dobel: file bukti sama (sha256) atau no. referensi sama ditolak; satu bukti aktif per pesanan; checkbox "sudah cek mutasi" wajib; nominal berbeda wajib catatan; tolak wajib alasan.
- Yang boleh menyetujui: OWNER dan ADMIN.

### 3.2 Fase 1
- **Batas pesan**: sesi tutup bila tanggal lewat, lewat jam (Siang 10.00, Malam 15.00 WIB), atau order harian tanggal itu sudah di-lock. Sesi tutup abu-abu "Sudah tutup", ditolak server, dan unggah bukti bayar diblok. *(Nanti jam lock dibaca dari kontrak — Fase 3.)*
- Notifikasi & SOP hanya untuk role/akun yang login; portal dan internal terpisah.
- Lupa password: link ke email akun (token hash, 30 menit, sekali pakai, pesan tidak membocorkan email). Pengirim = Gmail PT (App Password di `.env`: `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USE_TLS`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_FROM`). Admin bisa reset password akun mana pun termasuk portal.
- **Email wajib** untuk semua akun portal (daftar, dibuat admin, ubah di profil); banner pengingat bila kosong. Staf internal email opsional.
- Tulisan halaman publik untuk pelanggan, bukan kesan sistem internal.
- Portal bisa ubah nama/patokan/titik peta/foto alamat miliknya (minimal 1 foto).

### 3.3 Fase 2 + Scan
- Setelah order di-lock, per sesi: **Rekap Dapur A4** (total porsi besar, total wadah, per pemesan: nama, lokasi, porsi, wadah, catatan; paraf Kepala Dapur & Pengecek) dan **Label Wadah**.
- Label: nama pemesan, porsi wadah ini, "Wadah 1/3", lokasi + patokan, penerima + HP, tanggal + sesi, urutan antar (bila rute ada), **QR** ke serah terima.
- Ukuran cetak dipilih saat cetak: **Thermal 58mm / 80mm / Stiker A4**.
- Maks porsi per wadah: pengaturan cabang 15–20 (bawaan 20), **dibagi rata** (45 → 15/15/15; 50 → 17/17/16).
- Tombol cetak hanya setelah lock; perubahan setelah cetak → tanda **"Cetak ulang"**.
- Berlaku untuk **semua pesanan** sesi itu, termasuk pelanggan umum prabayar.
- Pengantar: tombol **"Scan Label Wadah"** di dashboard & halaman penerimaan → kamera → halaman serah terima order itu (porsi terisi otomatis, foto langsung kamera, "Selesai Diantar") → kembali ke scan. Order yang sudah diantar menampilkan status, bukan form. Kamera dalam aplikasi butuh **HTTPS atau localhost**; tanpa itu pakai kamera bawaan HP.

---

## 4. Tambahan yang sedang berjalan

### T1 — "Akun Saya" + Menu harian (prompt `PROMPT_GEMINI_AKUN_MENU.md`)
- **Akun Saya untuk semua role** (staf dan portal): foto profil (tampil di topbar menggantikan inisial), nama, no. HP/WA, alamat, email, ganti password (wajib password lama), info baca-saja (username, role, cabang, keterhubungan client/sub client). Username/role/cabang hanya bisa diubah admin. Semua perubahan diaudit.
- **Menu: pelanggan hanya MELIHAT** (keputusan 7 Okt). Dapur menentukan menu per tanggal & sesi; **harga tetap per porsi — tagihan/uang muka/invoice/jurnal tidak berubah**.
  - Menu punya 1–3 foto + deskripsi.
  - Halaman **Jadwal Menu** mingguan (7 hari × Siang/Malam), tombol "Salin minggu lalu".
  - Tampil di: halaman pesan (sesuai tanggal & sesi dipilih; belum dijadwalkan → "Menu akan diinformasikan"), dashboard portal (menu hari ini & besok), landing page (menu minggu ini), judul rekap dapur.

### T2 — Reminder sesuai role (prompt `PROMPT_GEMINI_REMINDER_ROLE.md`)
| Role | Seksi reminder |
|---|---|
| OWNER | semua |
| ADMIN | semua |
| DAPUR | Stok & bahan, Order & HPP |
| PENGANTAR | Pengiriman miliknya + bukti serah terimanya |
| Akun portal | tidak ada reminder internal |

Seksi yang tidak berhak **tidak dihitung** (badge = isi halaman).

---

## 5. Fase 3 — Pengaturan kontrak (fondasi)

Diisi saat membuat kontrak, berlaku untuk pesanan **berikutnya** (tidak mengubah pesanan yang sudah lewat lock):

| Pengaturan | Pilihan / bawaan |
|---|---|
| Jam lock makan siang | bawaan **10.00 WIB**, bisa diatur per kontrak |
| Jam lock makan malam | bawaan **15.00 WIB**, bisa diatur per kontrak |
| Hari libur rutin | pilih hari (mis. Minggu); kosong = kirim setiap hari (proyek umumnya jalan setiap hari) |
| Tanggal libur khusus | daftar tanggal (mis. Lebaran) |
| Pihak yang ditagih | **Client inti** / **Sub Client** / **Bayar di muka** |
| Siklus tagihan | Mingguan / **14 hari (bawaan)** / Bulanan |
| Jatuh tempo | **7 hari (bawaan)** setelah invoice terbit — menggantikan tempo lama 14 hari (`credit.terms_days_direct`) |
| Pengadilan sengketa | **PN Pangkalan Balai** (alamat PT, Kab. Banyuasin) atau **PN Kayuagung** (lokasi OKI) — satu per kontrak |
| Nominal ta'zir | nominal tetap per kejadian (mis. Rp50.000), boleh 0/nonaktif |

**Pihak yang ditagih — aturan wajib:**
- Hanya **satu pihak yang tercatat berutang** (piutang tidak boleh dobel).
- **Kedua pihak selalu melihat semua invoice** di portal dan mendapat notifikasi.
- Ditagih lewat client: invoice atas nama client dengan rincian per sub client; sub client melihat bagiannya.
- Ditagih ke sub client: invoice atas nama sub client; client mendapat salinan/rekap dan tercatat sebagai **penjamin**; bila sub client telat melewati batas, client mendapat peringatan.
- Sistem sudah punya mode tagih per sub client (`BILLING_VIA_CLIENT`, `BILLING_DIRECT`, `BILLING_CASH` di `credit_account_service.py`) — Fase 3 memindahkan pengaturannya ke kontrak dan menyambungkan ke semua lini.

Setelah Fase 3: pengecekan batas pesan (Fase 1) membaca **jam lock dari kontrak**.

---

## 6. Fase 4 — Penjadwal otomatis

- Sistem saat ini **belum punya penjadwal**.
- Dibutuhkan untuk: pesanan otomatis **18.00**, pratinjau invoice **H-1**, invoice terbit **06.00**, pengingat bayar **H-3 / H / H+7**, cek ambang kredit harian.
- Wajib **mengejar ketinggalan** bila server sempat mati (tugas yang terlewat dijalankan saat server hidup lagi, tanpa dobel).
- Setiap tugas idempoten (dijalankan dua kali tidak membuat data dobel) dan tercatat (kapan jalan, berhasil/gagal).

---

## 7. Fase 5 — Pesanan otomatis

### 7.1 Pembuatan
- Setiap hari **jam 18.00 WIB** sistem membuat pesanan **besok** untuk semua kontrak **aktif** (kontrak aktif = sudah ditandatangani, lihat Fase 9).
- Porsi = **porsi hari kemarin** (bukan porsi standar kontrak), per sesi (Siang/Malam).
- Setelah hari libur: porsi diambil dari **hari kerja terakhir**.
- Di **hari libur kontrak** (rutin/khusus) pesanan **tidak dibuat**.
- Angka **0 tidak ikut disalin** ke hari berikutnya kecuali sesuai alasan (lihat 7.3).
- Mandor/client mendapat notifikasi: "Pesanan besok: Siang 40, Malam 35. Ubah sebelum jam 10.00 / 15.00."

### 7.2 Mengubah porsi
- Client/Sub Client membuka portal dari HP → kartu **"Pesanan Hari Ini & Besok"** dengan tombol **+ / −**.
- Bisa naik/turun, termasuk ke **0**, **kapan saja sebelum lock**.
- Perubahan **langsung masuk Operasional tanpa menunggu admin** (sudah berkontrak). Admin & dapur langsung diberi notifikasi, mis. "Mandor Hendra: Siang 40 → 32".
- **Lewat lock**: tombol hilang, sistem menolak — client/sub client **tidak bisa dan tidak diberi izin** sama sekali. Tampil "Sudah dikunci, hubungi admin". Hanya admin yang bisa mengubah, **wajib alasan**.
- **Makanan sudah dalam perjalanan**: **terkunci total untuk semua orang, admin pun tidak bisa**. Aturan tetap, tertulis di kontrak dan di layar portal.
- Setiap perubahan tercatat: **siapa, jam berapa, dari berapa ke berapa** (bukti bila ada sengketa tagihan).

### 7.3 Alasan wajib saat porsi diisi 0
| Alasan | Yang sistem lakukan berikutnya |
|---|---|
| **Libur hari ini saja** | Besok kembali ke porsi terakhir yang bukan 0 |
| **Libur sampai tanggal …** (tanggal wajib) | Pesanan kosong sampai tanggal itu, lalu otomatis lanjut dengan porsi terakhir |
| **Berhenti sementara, saya pesan lagi nanti** | Pesanan otomatis **dimatikan**; hidup lagi saat client menekan **"Mulai pesan lagi"** dan mengisi porsi |
| **Proyek / pekerjaan selesai** | Pesanan otomatis dimatikan **dan admin diberi notifikasi** untuk meninjau kontrak (selesai / diperpanjang) |
| **Pekerja sedang tidak di lokasi** (pindah lokasi, cuaca, dll.) | Seperti "Libur hari ini saja", tetapi tercatat terpisah untuk laporan |
| **Lainnya** (catatan wajib) | Hanya hari ini; besok kembali ke porsi terakhir |

Setiap pilihan langsung memberi notifikasi ke admin dan dapur, dan tercatat di riwayat.

---

## 8. Fase 6 — Invoice otomatis (Claude)

Latar: sekarang invoice kredit **dibuat manual** (per pesanan / rekap periode); hanya pelanggan prabayar yang otomatis (setelah diterima, dilunasi dari uang muka). Manual rawan terlewat → wajib otomatis.

1. Siklus & jatuh tempo dari kontrak (bawaan 14 hari / 7 hari).
2. **H-1 sebelum tanggal potong**: admin menerima pratinjau, mis. "Besok terbit 12 invoice, total Rp…". Bila ada yang janggal, admin memperbaiki hari itu.
3. **Hari H jam 06.00**: invoice **terbit otomatis walaupun admin tidak membuka pratinjau**.
4. Isi hanya **pengiriman yang sudah diterima**. Yang belum dikonfirmasi diterima masuk periode berikutnya — tidak hilang, tidak dobel.
5. Langsung terkirim ke **portal pihak yang ditagih** + notifikasi; **pihak satunya menerima salinan** + notifikasi.
6. **Jurnal piutang otomatis**; pengingat bayar **H-3, H, H+7**; lalu kontrol kredit (Pantau → Tahan → Blokir).
7. Invoice yang **gagal terbit** (mis. harga belum diatur) → **peringatan merah** di dashboard admin & owner sampai diselesaikan.
8. Koreksi invoice lewat fitur koreksi yang sudah ada; admin hanya meninjau, tidak membuat dari nol.

Catatan risiko yang sudah dibahas: siklus 14 + tempo 14 = uang kembali ±28 hari (terlalu lama); dengan tempo 7 → ±21 hari. Bulanan + tempo 7 hanya untuk client besar terpercaya.

---

## 9. Fase 7 — Kontrol kredit syariah (Claude)

### 9.1 Ambang yang dipakai (sudah ada di `credit_control_service.DEFAULT_THRESHOLDS`, tetap dipakai)
| Kondisi | Status | Akibat |
|---|---|---|
| Telat 1 hari | **Pantau** | Peringatan ke admin & client |
| Telat 8 hari | **Tahan** | Pesanan baru ditahan, wajib bayar di muka |
| Telat 22 hari | **Blokir** | Pesanan ditolak |
| Telat 61 hari | Calon **hapus buku** | Hanya OWNER yang memutuskan |
| Ingkar janji bayar 1× / 2× | Tahan / Blokir | |
| Deposit | 20% dari limit kredit | |
| Batas pantau eksposur | 75% | |
| Tempo bawaan | **7 hari** (diubah dari 14) | |

Angka ini masuk pasal kontrak apa adanya supaya surat = perilaku sistem.

### 9.2 Prinsip syariah (fatwa DSN-MUI No. 17/2000 dan No. 43/2004)
- **Tidak ada** denda persen/harian yang menjadi pendapatan PT (riba).
- Yang **benar-benar tidak mampu**: diberi kelonggaran/penangguhan (QS Al-Baqarah 280), **dicatat**.
- Yang **mampu tapi sengaja menunda**: kredit dihentikan & wajib bayar di muka, pesanan ditahan (sudah lewat ambang di atas).
- **Ta'zir (disetujui owner)**:
  - **Nominal tetap** per kejadian, ditulis di kontrak; bukan persen, tidak bertambah per hari.
  - **Tidak otomatis**: sistem hanya **mengusulkan** saat client **ingkar janji bayar** atau status sudah **Blokir**; **OWNER yang memutuskan** dikenakan atau tidak.
  - Uang masuk akun **Dana Sosial** (kewajiban/dana terpisah, **bukan pendapatan**), dengan **laporan penyaluran**.
- **Ta'widh**: hanya ganti biaya penagihan **riil** yang ada buktinya; bukan keuntungan yang hilang.
- Rumusan pasal sebaiknya dikonfirmasi ke ustadz/ahli fiqih muamalah.

### 9.3 Yang dibangun (2026-10-09)
- **Penyapu kredit di penjadwal 07.30 WIB** (`credit_daily_sweep`); client yang punya kontrak aktif ikut tunduk pada tangga kredit (akunnya dibuat otomatis saat status perlu naik). Status naik → notifikasi ke portal pihak yang ditagih.
- **Usulan ta'zir** otomatis (satu per kejadian: janji meleset ≤30 hari terakhir, atau satu kali masuk Blokir), nominal dari kontrak; Owner memilih Kenakan/Tidak (alasan wajib bila tidak). Dikenakan → **invoice terpisah** `source_type=TAZIR`, jurnal Dr 1004 / Cr **2009 Dana Sosial**.
- **Ta'widh**: Owner menerbitkan tagihan terpisah `TAWIDH` dengan bukti wajib; jurnal Dr 1004 / Cr 4004.
- Tagihan ta'zir/ta'widh **tidak dihitung** dalam umur tunggakan/limit (tidak ada denda atas denda); invoice yang ditagih langsung ke sub client tidak dihitung sebagai hutang client-nya.
- **Kelonggaran**: Owner mencatat sampai tanggal + alasan → status maksimal Tahan (pesanan baru bayar di muka), tanpa usulan ta'zir, usulan yang menunggu gugur.
- **Dana Sosial** (menu Keuangan → Dana Sosial): ringkasan ditagihkan/diterima/disalurkan/siap salur, usulan menunggu, catat penyaluran (Owner, bukti wajib, maksimal dana yang sudah diterima; kas/bank keluar + Dr 2009 / Cr kas/bank), laporan penyaluran.
- Hapus buku: sisa tagihan ta'zir didebit ke 2009 (bukan beban 5013).

---

## 10. Fase 8 — Pajak (Claude)

### 10.1 Fakta (Surat Keterangan Terdaftar S-25175/SKT-WP-CT/KPP.0312/2026)
- NPWP **1000000010006690**, WP Badan, terdaftar **19 Juni 2026**, **KPP Pratama Sekayu**; alamat terdaftar Jakabaring Selatan, Rambutan, **Kab. Banyuasin**. **Belum PKP** (katering = objek PBJT, bukan PPN; PKP baru wajib bila omzet setahun > Rp4,8 M).
- Password akun Coretax **tidak boleh** disimpan di ERP; owner diminta menggantinya (sempat terkirim di chat 2026-10-09).

### 10.2 Keputusan owner (2026-10-09)
- **PPh: sistem mendukung DUA rezim, dipilih owner di Pengaturan Pajak setelah konsultan memastikan** (bawaan: belum dipilih → fitur PPh mati). (a) **PP 55 final 0,5%** — boleh untuk tahun pajak 2026–2028 (PT maks. 3 tahun pajak sejak terdaftar), dasar = peredaran bruto usaha per bulan, pelanggan memotong 0,5% final bila PT punya **Surat Keterangan PP 55** (nomor dicetak di invoice); sistem otomatis menolak PP 55 setelah 2028. (b) **Tarif normal** — 22% dari laba (Pasal 31E → efektif 11% bila omzet ≤ Rp4,8 M), pelanggan memotong **PPh 23 2%** yang menjadi kredit pajak. Rezim bisa berbeda per tahun pajak.
- **PBJT ditambahkan di atas harga** (harga per porsi tetap, PBJT baris terpisah), terdaftar di **Kab. OKI** (lokasi dapur, Air Sugihan). Tarif & NPWPD dari Bapenda OKI.
- **Dibangun sekarang, semua pajak MATI bawaan**; aktif setelah owner mengisi pengaturan (Surat Keterangan PP 55, NPWPD, tarif PBJT).

### 10.3 Rancangan
1. Pengaturan pajak perusahaan (NPWP, KPP, tanggal terdaftar, rezim + tahun berlaku PP 55, nomor & masa berlaku Surat Keterangan PP 55, PBJT aktif/tarif/kabupaten/NPWPD, mulai berlaku), pengurus & pemegang saham, dokumen pajak (lampiran + tanggal berlaku).
2. PBJT di semua jalur invoice: baris terpisah, Dr 1004 / Cr **Hutang PBJT** (bukan pendapatan); tidak masuk omzet PPh.
3. Potongan pajak oleh pelanggan saat bayar = **pintu pelunasan ketiga** (selain kas/bank dan potong DP/deposit): jenis (PPh final 0,5% / PPh 23 2%), nomor & file bukti potong; jurnal: final → Cr 1004 / Dr PPh final dibayar; PPh 23 → Dr kredit pajak (aset). Ikut riwayat pelunasan (janji bayar, portal).
4. Laporan pajak bulanan: peredaran bruto (tanpa PBJT & ta'zir), PPh final 0,5% terutang − sudah dipotong pelanggan = wajib setor (tgl 15); PBJT dipungut vs disetor; catat setoran (kas keluar + jurnal + NTPN + bukti); rekonsiliasi invoice–potongan–bank; rekap tahunan untuk SPT (batas 30 April).
5. Pengingat: setor PPh final tgl 15, PBJT sesuai Perda OKI, SPT Tahunan; peringatan omzet mendekati Rp4,8 M dan PP 55 akan habis (akhir 2028).
- PPN/e-Faktur **tidak** dibuat kecuali PT sudah PKP. PPh 21 karyawan & PPh 23 pemasok menyusul.

### 10.4 Yang dibangun (2026-10-09)
- Menu **Keuangan → Pajak** (`/finance/tax`) dan **Pengaturan Pajak** (Owner). Akun baru: **1009** Pajak Dibayar di Muka, **2010** Hutang PBJT, **5014** Beban PPh Final.
- PBJT dipasang di semua jalur invoice penjualan (`tax_service.apply_pbjt_to_invoice`): invoice otomatis + pratinjau, invoice periode manual, invoice per pesanan, input susulan. Ta'zir/ta'widh/saldo awal tidak kena PBJT. Laporan omzet per jalur & laba per invoice mengecualikan PBJT.
- Potongan PPh pelanggan = **pintu pelunasan ketiga** di `invoice_payment_history_service` (janji bayar, portal, cetak invoice, jejak tagihan).
- Peredaran bruto dihitung dari buku besar 4001–4005 (tanpa PBJT & ta'zir). Catatan: jurnal belum per cabang, jadi laporan pajak = seluruh PT (sesuai: NPWP satu untuk PT).
- Pengingat `tax_reminders` 08.30. Pasal pajak surat kontrak (Fase 9) diisi Claude setelah Gemini selesai.

---

## 11. Fase 9 — Surat kontrak otomatis (paling akhir)

### 11.1 Alur
1. Admin/Owner mengisi data kontrak (Fase 3).
2. Klik **"Buat Surat Kontrak"** → sistem menyusun surat lengkap **dari data kontrak** (angka & aturan pasti sama dengan yang dijalankan sistem).
3. Klik **"Cetak"** → A4 rapi: kop PT, nomor kontrak, nomor halaman, kolom paraf setiap halaman.
4. Tanda tangan — **boleh pilih salah satu**:
   - **basah di atas meterai Rp10.000** + admin mengunggah scan, **atau**
   - **klik setuju + OTP** di portal.
5. **Kontrak baru aktif setelah ditandatangani**; sebelum itu pesanan otomatis tidak berjalan.

### 11.2 Pengaman
- Isi surat **dikunci saat dibuat**; perubahan template kemudian tidak mengubah kontrak lama.
- Perubahan di tengah jalan (harga, jam lock, pihak ditagih, dll.) wajib lewat **Adendum** (dicetak, ditandatangani, diunggah).
- Client bisa melihat & mengunduh kontrak di portal.

### 11.3 Penandatangan PT
- **Ida Royani — Direktur**
- **Reki Kurniawan — Komisaris**
- Alamat PT (NIB) masih alamat rumah di Kab. Banyuasin (belum punya kantor tetap).

### 11.4 Isi surat (pasal)
1. Identitas para pihak (PT, client, sub client/perwakilan)
2. Ruang lingkup: catering, lokasi antar, sesi makan
3. Harga per porsi, ongkir, dan cara perubahan harga (harga bisa berubah mengikuti bahan pokok & BBM)
4. Cara pemesanan lewat sistem: pesanan otomatis 18.00, porsi mengikuti hari kemarin
5. Batas lock siang/malam; lewat lock tidak bisa diubah
6. Ubah porsi / jadi 0, alasan-alasannya, beserta akibatnya
7. Hari libur rutin & khusus
8. Makanan dalam perjalanan = terkunci, tidak bisa batal/dikurangi
9. Penerimaan barang: foto titik antar, tanda terima, batas waktu komplain
10. Penagihan: siapa ditagih, siapa penjamin, kedua pihak melihat semua invoice, siklus, tempo, ta'zir
11. Kredit, deposit, pemblokiran pesanan bila menunggak
12. Kualitas makanan & prosedur komplain
13. Data & akun portal: tanggung jawab menjaga password; transaksi dari akun dianggap sah
14. Masa berlaku, perpanjangan, pemutusan
15. Keadaan kahar (force majeure)
16. Penyelesaian sengketa: musyawarah dulu, lalu pengadilan yang dipilih (Pangkalan Balai / Kayuagung)
17. Lampiran: daftar lokasi, harga, jadwal, ringkasan aturan sistem

**Template pasal dicek pengacara/notaris sekali** sebelum dipakai.

---

## 12. Daftar tunggu lain (belum dijadwalkan)
- **Dua tempat tempo di kontrak**: teks lama `payment_terms` ("net 30") dan angka baru `due_days`. Sistem kini memakai `due_days` (kontrak lama sudah diisi dari teksnya saat migrasi). Saat Fase 9 (surat kontrak), teks tempo dibuat otomatis dari `due_days` supaya tidak bisa berbeda.
- **Hubungkan akun pengantar ke data Driver secara pasti** (kolom `drivers.user_id` atau pilihan "Akun login" di master Driver). Sekarang reminder pengantar mencocokkan lewat nama/no. HP — rapuh kalau nama berbeda. Kerjakan bersama Fase 3.
- Lupa password lewat **WhatsApp OTP** (butuh layanan WA berbayar) — nanti.
- **Pembersihan CSS** yang tidak terpakai setelah fitur besar selesai.
- Mengganti `Query.get()` lama (peringatan SQLAlchemy) — tidak mendesak.

- **Zona waktu server wajib `Asia/Jakarta` saat online.** Masih ada ±51 file lama yang memakai `date.today()` / `datetime.now()` (jam server). Di laptop owner benar karena jam laptop WIB; di server UTC tanggal akan meleset antara 00.00–07.00 WIB.
- **Test penjadwal**: database test berisi ribuan cabang sisa test lain. Setiap test yang memanggil `run_due_jobs` wajib membatasi dengan `job_keys=[...]` dan `branch_ids=[...]`, kalau tidak test berjalan puluhan menit.

## 13. Hal yang harus disiapkan owner
- Gmail PT + **App Password** di `.env` (lupa password) — jangan diberikan ke AI.
- **HTTPS/domain** saat online (kamera scan di dalam aplikasi).
- Konfirmasi **konsultan pajak** (Fase 8), **pengacara/notaris** (template kontrak, Fase 9), **ustadz** (rumusan ta'zir, Fase 7).

---

## Riwayat perubahan
- 2026-10-05: verifikasi pembayaran 1 klik disetujui (semua usulan).
- 2026-10-06: seluruh keputusan paket kontrak, pesanan otomatis, invoice otomatis, kredit syariah, surat kontrak, rekap dapur & label; tempo 7 hari; pengadilan Pangkalan Balai/Kayuagung; ta'zir Dana Sosial disetujui.
- 2026-10-07: email wajib akun portal; tombol scan pengantar; menu = pelanggan melihat saja; Akun Saya semua role; reminder per role.
- 2026-10-07: Fase 3 — Fondasi pengaturan kontrak (jam lock, libur rutin & khusus, siklus & anchor tagihan, tempo 7 hari, pengadilan sengketa, nominal ta'zir, mode tagih sub client, Driver.user_id link).
- 2026-10-08: Fase 5 — Pesanan otomatis untuk Client/Sub Client kontrak (tugas 18.00 WIB auto_daily_orders, porsi hari kerja terakhir, standing_order_states, kartu 'Pesanan Hari Ini & Besok' di portal, kontrol kredit & jam lock, 6 alasan porsi 0, riwayat order_qty_changes, dan aksi admin).
- 2026-10-09: Fase 6 — keputusan owner: invoice otomatis **satu per sub client** (atas nama pihak yang ditagih; PT melihat semua + rekap), **hutang warung pekerja ikut ditagih** (bila modul aktif), **pratinjau H-1 jam 07.00**, terbit 06.00 hari potong.
- 2026-10-09: Review Claude Fase 1–5 & perbaikan: kredit TAHAN/BLOKIR benar-benar menahan pesanan otomatis; portal hanya bisa ubah porsi lokasinya sendiri; pesanan manual besok tidak disentuh; tidak ada pesanan Rp0; tugas baru tidak mundur 7 hari; tugas terputus diulang; syarat anti-kabur di halaman kontrak; scan label sesuai sesi; angka terima tidak bisa diubah pengantar; notifikasi admin tampil untuk owner. test_db dibersihkan (test lengkap ±12 menit).
- 2026-10-09: Pihak yang ditagih **satu sumber**: pengaturan kredit per sub client (dibaca pesanan otomatis *dan* invoice; dulu bisa berbeda). Pilihan "Bawaan Kontrak" per sub client dihapus. Bawaan Pihak Ditagih kontrak hanya Owner yang boleh mengubah; saat diubah ke "Bayar di muka" langsung diterapkan ke sub client yang belum punya pengaturan. "Ditagih langsung" tidak bisa dipukul rata — disetel per sub client setelah syarat anti-kabur lengkap.
- 2026-10-10: **Rombakan UI portal (Gemini, frontend saja)** ditemukan berisi mockup mentah: data karangan tampil ke pelanggan (nama kasir, tagihan, saldo, menu, sub client fiktif), tombol palsu (`showToast`), gambar dari server Google (alat desain "stitch"), Tailwind dari CDN, satu tombol ke route yang tidak ada (kalender error 500), tombol "Sembunyikan notifikasi" hilang. Keputusan owner: **desain dipertahankan, Claude membersihkan** — semua data dari variabel template/route, tanpa data/tombol palsu, Tailwind dikompilasi jadi CSS lokal, gambar lokal/dari data, dan setiap halaman portal wajib punya tombol akses yang pas per peran. **Aturan baru untuk prompt UI ke AI lain: dilarang data contoh/hardcode di template; semua angka, nama, tanggal, gambar wajib dari data; dilarang CDN.**
- 2026-10-10: **Pembersihan portal selesai (Claude).** Desain Gemini dipertahankan. Tailwind dikompilasi lokal (`tools/portal_tailwind/build.ps1` → `app/static/css/portal_tailwind.css`, wajib dijalankan ulang setelah ubah template portal). Layout portal: logo/nama dari Profil Perusahaan, lencana notifikasi asli, tombol **Menu** (semua halaman per peran) + **Keluar**, script bersama dikembalikan. Semua halaman portal diisi data asli (kalender kini strip 7 hari dari data; formulir pesan memakai field yang benar — nama penerima/HP/jam kirim sebelumnya terbuang diam-diam, tanpa minimal porsi, tanpa catatan terisi otomatis, tanpa lokasi cadangan id=1). Dikembalikan: tombol Sembunyikan notifikasi, info bukti/selisih di tagihan, rincian proses & komplain di status pesanan, form OTP kontrak. **Navigasi:** PT tidak diberi tombol "Status Pesanan" (halaman itu hanya draf milik akun sendiri) — tab ke-2 PT = Sub Client; menu Kasbon/Cicilan/Pekerja hanya tampil bila modul hutang pekerja aktif; Persetujuan ada di menu semua peran. Route generik lama (`/portal/invoices|payments|debts|orders/draft|client`) tetap ada tanpa tombol (kompatibilitas, dijaga tes). **Dikembalikan ke versi lama:** `admin_order_drafts` (halaman staf, harus layout internal) dan `register` (halaman publik; versi Gemini menyuntik Tailwind CDN ke layout dasar + pilihan cabang palsu id 1–4). Diverifikasi: crawler per peran 0 tombol rusak, smoke 232 route 0 gagal, invarian keuangan gladi 0 pelanggaran.
- 2026-10-11: **Aturan portal "satu pintu per halaman"** (owner): setiap halaman hanya punya satu tombol akses per peran — tidak boleh dobel di Beranda, Akun, menu, tombol "Semua", atau panah kembali ke Beranda. Struktur: tab bawah **Beranda · Pesanan (PT: Operasional) · Tagihan · Akun**; halaman di dalam satu tab jadi sub-tab di atas halaman; halaman pendukung (alamat, kontrak & surat, pekerja, dokumen, persetujuan, komplain) hanya di **Akun**; notifikasi hanya lewat lonceng; tombol Keluar hanya di Akun. **Riwayat bayar ada di tab Tagihan.** Peta navigasi satu sumber di `app/services/portal_navigation_service.py`, dijaga `tests/test_portal_navigation.py`. Halaman kembar ditutup pintunya (Piutang PT = Tagihan, Hutang Katering = Tagihan, Cicilan = Kasbon, Riwayat Pesanan pelanggan = Pesanan Saya). Isi halaman hanya boleh tautan ke **rincian satu baris** (kartu invoice → rinciannya, kontrak → suratnya, notifikasi "Buka"). **Rincian Tagihan** baru: item per baris (porsi × harga), PBJT, total, sudah dibayar, riwayat pelunasan (bayar, potong DP/deposit, potong pajak), lalu cara bayar & unggah bukti. Pelanggan umum: form bayar pesanan di muka pindah dari halaman Pesan ke tab Tagihan, plus riwayat tagihan per pesanan (Lunas / Menunggu bayar / Ditolak · dana dikembalikan).
- 2026-10-11: **Aplikasi HP pengantar (Gemini, direview Claude).** Role PENGANTAR memakai `layouts/driver_mobile.html` (gaya portal, Tailwind lokal) + template `templates/driver/`; route hanya memilih template bila role PENGANTAR — OWNER/ADMIN tetap tampilan internal. Tab bawah: **Beranda · Antar (Hari Ini / Serah Terima) · Scan · Riwayat · Akun**; notifikasi lewat lonceng; Keluar & **SOP Pengiriman** hanya di Akun; detail & form terima pakai panah kembali. Peta di `app/services/driver_navigation_service.py`, dijaga `tests/test_driver_navigation.py`. Diperbaiki saat review: tombol dobel di form terima (Daftar Antar dihapus; "Scan Berikutnya" hanya pada alur scan beruntun), SOP versi HP, sub-tab disembunyikan di halaman rincian, hitungan lonceng di-cache, library scanner QR **disimpan lokal** (`static/vendor/html5-qrcode`, dulu dari unpkg — kurir sering di sinyal lemah), ikon cetak surat kontrak tidak lagi dari CDN.
- 2026-10-11: **Keputusan owner — role baru Admin Operasional (`ADMIN_OPERASIONAL`)** dengan aplikasi HP khusus operasional (Beranda · Pesanan · Dapur · Antar · Akun), dikunci di server: tidak bisa membuka keuangan/akuntansi/HR/gudang/pengaturan. Boleh **melihat** nominal (harga, total, status bayar) tetapi tidak mengubah/memverifikasi pembayaran. Boleh sendiri: tambah porsi setelah dikunci (beralasan), konfirmasi & tolak draf portal, buat/berangkatkan/batalkan pengiriman. **Meloloskan pesanan sebelum lunas tetap khusus OWNER.** OWNER/ADMIN tetap desktop dan boleh membuka versi HP lewat `/ops`. Dikerjakan Gemini (prompt `PROMPT_GEMINI_ADMIN_OPERASIONAL.md`), direview Claude.
- 2026-10-11: **Admin Operasional selesai (Gemini 3 putaran, direview Claude).** Aplikasi HP `layouts/ops_mobile.html` + `templates/ops/`, peta `ops_navigation_service.py`, pemilihan template lewat `uses_ops_ui(user)` (ADMIN_OPERASIONAL, atau OWNER/ADMIN yang menyalakan mode HP di `/ops`; keluar lewat tombol di Akun → `POST /ops/exit`). Koreksi Claude: hapus foto bukti pengiriman tetap **khusus ADMIN**; komplain **belum** dibuka untuk Admin Operasional (belum ada halaman HP-nya — tambahkan bila owner minta); pengingat HPP dibuang dari role ini; form Input Order / Tambah Detail / Tambah Setelah Kunci / Revisi dibuat versi HP; dropdown pencarian tidak lagi kotak-di-dalam-kotak (berlaku juga di portal & pengantar). Dijaga `tests/test_ops_navigation.py` (satu pintu, kecocokan `action` & nama field dengan versi desktop) dan `tests/test_admin_operasional_permissions.py` (ditolak di keuangan/akuntansi/master/pengaturan/warung/komplain/hapus bukti; tidak bisa meloloskan pesanan sebelum lunas). Cetak label wadah & rekap dapur per sesi tetap halaman cetak.
- 2026-10-11: **Keputusan owner — notifikasi hasil proses di tengah layar, seluruh sistem.** Semua pesan berhasil/gagal/peringatan/info (flash & notifikasi JS) tampil instan sebagai kotak di tengah, latar di-blur dan tidak bisa diklik, hanya ditutup dengan tombol "Mengerti" (Esc/klik luar tidak menutup). Satu komponen `components/flash_dialog.html` dipakai semua layout (internal, publik, portal, pengantar, ops). Konfirmasi sebelum aksi (`appConfirm`) tidak berubah. Dikerjakan Gemini (`PROMPT_GEMINI_NOTIFIKASI_TENGAH.md`), direview Claude.
- 2026-10-11: **Keputusan owner — Modul Karyawan & Kontrak Kerja (dibangun Claude sekaligus).** Masalah: karyawan pergi/pulang tiba-tiba tanpa aturan tertulis. Semua karyawan tinggal & kerja di satu lokasi → **tanpa GPS**; absensi = **apel harian** dicentang Admin Operasional/HR di HP (default Hadir), izin & cuti diajukan lewat admin (karyawan tidak wajib punya akun). Kontrak **PKWT dan PKWTT** (PKWT maks 5 tahun + kompensasi akhir otomatis; PKWTT percobaan maks 3 bulan), isi dikunci saat TTD, **karyawan tanda tangan gores di layar HP + foto KTP**, owner TTD digital, pengingat pencatatan PKWT ke Disnaker (3 hari kerja). Pasal wajib: resign **pemberitahuan 30 hari**, izin keluar lokasi, **denda tertulis per pelanggaran** (dicatat **pendapatan lain-lain**, nominal diatur owner), **ganti rugi sisa kontrak PKWT sesuai Pasal 62** dipotong dari hak terakhir **maks 50% per periode upah**, sisanya piutang karyawan. Pergi tanpa izin → hitung mangkir + surat panggilan 1 & 2 (dasar "dikualifikasikan mengundurkan diri" setelah 5 hari kerja). Resign resmi dengan perhitungan hak & potongan. Kebutuhan tenaga per shift dari porsi besok + daftar tenaga cadangan + peringatan kurang tenaga. Dilarang menahan ijazah/dokumen asli. Rujukan hukum dicek ulang ke Disnaker/konsultan sebelum template dipakai.
- 2026-10-11: **Modul Tenaga Kerja selesai dibangun (Claude).** Menu SDM → **Tenaga Kerja** (`/sdm`), tab: Ringkasan · Apel · Izin · Mangkir · Kontrak · Denda & Ganti Rugi · Keluar · Laporan. Migrasi `j8e9f0a1b2c3` (tabel `employment_contracts`, `employee_leaves`, `employee_absence_cases`, `employee_charges`, `payroll_deduction_items`, `employee_exits`; kolom baru di `employees` & `payroll_details`). Keputusan teknis yang diambil Claude: (1) **akun**: denda/ganti rugi disetujui OWNER → Dr 1005 Piutang Karyawan / Cr 4004 Pendapatan Lain-lain; dipotong lewat jurnal penggajian (Dr 5004 bruto / Cr 2003 neto / Cr 1005 potongan); sisa yang dibatalkan owner dibalik Dr 4004 / Cr 1005. Ganti rugi juga dicatat pendapatan lain-lain (sama dengan denda). (2) **Hanya OWNER** yang menyetujui/membatalkan denda & ganti rugi, menandatangani kontrak atas nama perusahaan, dan menetapkan "dikualifikasikan mengundurkan diri"; owner boleh menurunkan nominal usulan, tidak menaikkan. (3) **Apel** di HP Admin Operasional = tab Dapur → sub-tab "Apel Tim" (+ halaman Catat Izin dengan panah kembali); bawaan Hadir; tanpa keterangan otomatis membuka kasus mangkir + notifikasi owner; tenaga **Cadangan** (jenis karyawan baru, harian lepas) hanya ditandai bila dipanggil. Apel boleh diisi/diubah sampai 7 hari ke belakang. (4) **Izin** yang dicatat Admin Operasional menunggu persetujuan ADMIN/OWNER; dicatat ADMIN/OWNER langsung disetujui. Tidak kembali tepat waktu → apel menyarankan "tanpa keterangan" → kasus; saat kembali, denda terlambat per hari diusulkan (bukan denda mangkir, supaya tidak dobel). Kembali dari mangkir biasa → usulan denda mangkir per hari + denda keluar lokasi tanpa izin. (5) **Hari tanpa keterangan tidak dibayar** di penggajian (UU 13/2003 Ps. 93 ayat 1), otomatis saat buat penggajian. (6) Potongan denda/ganti rugi maks 50% upah periode (dibulatkan ke bawah), tertua dulu; tombol "Hitung Ulang Potongan" di penggajian konsep. (7) **Keluar**: resign dicatat dengan tanggal pengajuan & tanggal keluar; kurang dari masa pemberitahuan → denda pemberitahuan + (PKWT) ganti rugi sisa kontrak Ps. 62; wajib centang serah terima; penyelesaian (upah s/d hari kerja terakhir + kompensasi PKWT PP 35/2021 − potongan) dibayar lewat **penggajian periode tanggal keluar**; setelah penggajian dijurnal → karyawan nonaktif & kontrak berakhir. Diberhentikan perusahaan sebelum PKWT selesai → ganti rugi dibayar perusahaan ke karyawan (Ps. 62); pesangon PHK PKWTT dihitung terpisah (di luar sistem). Kontrak habis harus tepat di tanggal selesai. (8) **Mangkir → mengundurkan diri** hanya bila sudah 2 surat panggilan (panggilan 2 paling cepat sehari setelah panggilan 1) dan ≥5 hari tanpa keterangan (angka diatur di Pengaturan); surat panggilan bisa dicetak. (9) **Kontrak**: TTD karyawan = centang setuju + ketik nama persis + gores tanda tangan + foto KTP → isi surat dibekukan; TTD owner (gores) → aktif, jabatan & gaji karyawan ikut kontrak, notifikasi owner tenggat Disnaker 3 hari kerja (Senin–Jumat). Satu karyawan hanya boleh punya satu kontrak berlaku; total PKWT maks 5 tahun; PKWT tanpa masa percobaan. Foto KTP hanya bisa dibuka ADMIN/OWNER. (10) **Pengaturan Perusahaan** bagian baru "Karyawan & Kontrak Kerja": penandatangan, lokasi kerja, hari pemberitahuan (30), denda mangkir/hari, keluar lokasi, terlambat kembali/hari, resign kurang pemberitahuan, batas potongan (maks 50), porsi per pekerja per sesi (60), hari mangkir (5), nomor pengesahan Peraturan Perusahaan (peringatan bila karyawan ≥10 dan belum diisi). (11) **Kebutuhan orang besok** = porsi siang/sore ÷ porsi per pekerja, dibanding karyawan yang tidak izin/mangkir; tampil di Ringkasan SDM, Apel, dan Beranda HP Admin Operasional dengan daftar cadangan (tombol telepon). Belum termasuk: kasbon karyawan, pesangon PHK, BPJS. Rujukan hukum di surat tetap perlu dicek Disnaker/konsultan sebelum dipakai.
- 2026-10-11: **Penataan ulang menu SDM (permintaan owner: "tidak teratur, UI nanggung").** Sidebar SDM kini **4 menu**, isi tiap menu lewat tab (satu sumber: `app/services/hr_navigation_service.py`): (1) **Ringkasan SDM** — satu dashboard gabungan: daftar "Perlu Tindakan" (keputusan owner, keluar, mangkir, telat kembali, izin, Disnaker, kontrak) + apel hari ini + kebutuhan orang besok + status penggajian; dashboard SDM lama (`/hr/`) dialihkan ke sini. (2) **Karyawan & Kontrak** — Daftar Karyawan · Kontrak Kerja · Karyawan Keluar. (3) **Kehadiran & Disiplin** — Apel Harian · Izin · Mangkir · Denda & Ganti Rugi · Laporan. (4) **Penggajian** — Daftar Penggajian · Riwayat Pembayaran. Dropdown "Aksi SDM/Aksi Payroll" di header dihapus (pintu dobel); header hanya memuat aksi halaman itu. Perbaikan integrasi: halaman SDM lama kini **disaring per cabang** (karyawan/penggajian cabang lain tidak terbaca/terbuka); **gaji karyawan berkontrak terkunci** di form karyawan (diubah lewat kontrak baru); karyawan berkontrak **tidak bisa dinonaktifkan langsung** — diarahkan ke Karyawan Keluar; **tenaga cadangan tidak ikut penggajian bulanan**; penggajian menampilkan peringatan karyawan tanpa kontrak berlaku, penanda "Keluar", dan total potongan denda/ganti rugi; tahapan penggajian berlabel Indonesia (Konsep → Terkunci → Hutang Dicatat → Dibayar); semua label Inggris (Payroll, Employee, Toggle) diganti. Kontrak baru dari profil hanya muncul bila belum ada kontrak berlaku atau sisa ≤30 hari (Perpanjang Kontrak).
- 2026-10-11: **Slip gaji & kwitansi (keputusan owner: kwitansi "keduanya", slip "cetak + link WhatsApp", PPh 21/BPJS "nanti saja").** Migrasi `k9f0a1b2c3d4` (kolom `payroll_details.slip_token`, tabel `payroll_receipts`). Slip A4 per karyawan (No. `SG/YYYYMM/xxxxx`): identitas + kontrak, masa periode & hari dihitung, rekap apel (hadir/izin/sakit/cuti/tanpa ket.), pendapatan (gaji pokok sesuai kontrak, bonus, kompensasi akhir), potongan (prorata, hari tanpa keterangan + dasar UU 13/2003 Ps. 93, tiap denda/ganti rugi + dasar pasal kontrak), rincian denda (nilai total vs dipotong bulan ini), sisa piutang dibawa ke bulan depan, gaji bersih + terbilang, tanda tangan, kode verifikasi (HMAC). Slip konsep bertanda "KONSEP". Cetak per orang atau semua sekaligus dari Rincian Penggajian; juga dari profil karyawan (6 slip terakhir) dan Riwayat Pembayaran. **Link WhatsApp** hanya setelah penggajian dikunci: tombol WA membuka wa.me dengan link `/slip/<kode acak>`; karyawan membuka dengan **PIN 4 angka terakhir NIK** (No. HP bila NIK kosong); salah PIN ditolak, dibatasi 10 percobaan/menit, slip penggajian konsep tidak bisa dibuka. **Kwitansi** (No. `KW-GJ/YYYYMM/xxxxx`) hanya setelah hutang gaji dicatat, sekali per karyawan, tidak untuk gaji Rp 0: (a) "TTD Terima" — karyawan cek rincian, ketik nama persis, gores tanda tangan di HP admin (disaksikan admin yang login); (b) "TTD Kertas" — kwitansi dicetak (2 per A4), ditandatangani basah, admin menandai + boleh lampirkan foto. Tidak ada jurnal baru: slip & kwitansi hanya membaca penggajian (pembayaran tetap lewat tombol Bayar Gaji). PPh 21 & BPJS belum dihitung.
- 2026-10-11: **Keputusan owner — setiap hari tidak bekerja dipotong, apa pun alasannya ("bisnis tidak pakai perasaan"); aturan harus bisa diatur owner di layar dan tertulis di kontrak.** Dibuat tab **SDM → Penggajian → Aturan Gaji & Potongan** (hanya OWNER yang mengubah; admin melihat): status apel yang dipotong (Izin/Sakit/Cuti/Tanpa keterangan; bawaan semua dicentang sesuai keputusan owner), pembagi upah harian (hari kalender / 30 / 26) + contoh hitungan, nominal denda, batas potongan ≤50%, hari pemberitahuan resign, hari mangkir, penandatangan, lokasi kerja, No. Peraturan Perusahaan, porsi per pekerja. Bagian "Karyawan & Kontrak Kerja" dipindah keluar dari Pengaturan Perusahaan (satu pintu; nilai lama tetap terbaca). Migrasi `l0a1b2c3d4e5`: kolom `unpaid_statuses` & `daily_wage_divisor` di kontrak — **aturan dikunci per kontrak saat dibuat** dan tertulis di Pasal Upah ("Hari tidak bekerja karena … tidak dibayar; upah per hari = upah sebulan ÷ …"); kontrak lama (sebelum migrasi) tetap hanya memotong "tanpa keterangan". Penggajian & slip memotong sesuai kontrak masing-masing (tanpa kontrak = aturan cabang), slip merinci jumlah hari per status + rumus. **Catatan hukum disampaikan ke owner & ditampilkan di layar:** UU 13/2003 Ps. 93 ayat 2 mewajibkan upah tetap dibayar untuk sakit dengan surat dokter dan cuti tahunan (ancaman Ps. 186); owner tetap memutuskan lewat centang.
- 2026-10-11: **Keputusan owner — potongan hari ikut UU otomatis.** Sakit & cuti tidak lagi bisa dicentang bebas: **sakit dipotong kecuali ada surat dokter** (centang "Surat dokter" di apel desktop/HP; migrasi `m1b2c3d4e5f6` kolom `employee_attendance.medical_note`), **cuti dipotong kecuali masih dalam jatah cuti tahunan 12 hari** bagi yang sudah bekerja 12 bulan (UU 13/2003 Ps. 79; jatah per tahun kerja dihitung otomatis dari tanggal mulai kerja, hari ke-13 dst dan cuti sebelum 1 tahun dipotong). Izin & tanpa keterangan tetap diatur owner (bawaan dipotong). Pasal Upah kontrak baru menyebut pengecualian UU tersebut. Profil karyawan menampilkan sisa cuti tahunan; mencatat izin Cuti langsung memberi tahu apakah dibayar atau dipotong. Slip merinci "sakit tanpa surat dokter" / "cuti di luar jatah".
- 2026-10-11: **PPh 21 karyawan (dikerjakan Opus di Antigravity, direview & diperbaiki Claude).** Tarif & logika di modul pajak pusat (`app/services/tax_pph21_service.py`, pengaturan di Keuangan → Pajak → Pengaturan: aktif mulai tanggal, penanggung KARYAWAN/PERUSAHAAN, centang "tabel TER sudah diverifikasi"); penggajian hanya memanggilnya. Masa Jan–Nov TER bulanan PP 58/2023 (kategori A/B/C dari status PTKP), Desember/masa terakhir karyawan keluar dihitung tahunan Pasal 17 (biaya jabatan 5% maks 500 rb/bln, PTKP, PKP dibulatkan ribuan) dikurangi yang sudah dipotong. Akun baru 2011 Hutang PPh 21 & 5015 Beban PPh 21 ditanggung perusahaan; setoran tipe PPH21 di halaman Pajak; laporan masa & pengingat tgl 15; slip memuat baris PPh 21; cetak 1721-A1 dari profil karyawan. Batas potongan 50% dihitung dari upah setelah PPh 21. Migrasi `n2c3d4e5f6a7` (PTKP/NPWP karyawan, snapshot PPh 21 per baris gaji). **Perbaikan Claude atas hasil Opus:** tabel TER kategori B & C sebagian besar salah (disalin dari A) → diganti tabel resmi; 8 dari 11 tes Opus tidak pernah dijalankan & gagal → ditulis ulang; route cetak 1721-A1 pasti error → diperbaiki; jurnal tidak seimbang saat lebih bayar yang ditanggung perusahaan → diperbaiki; pengajuan keluar yang belum disetujui tidak lagi dianggap masa terakhir; tampilan PPh 21 disembunyikan selama belum aktif.
- 2026-10-12: **Keputusan owner — BPJS ditunda; kasbon karyawan dibuat** (owner setujui, dicicil). Tab **Penggajian → Kasbon**: admin mengajukan, karyawan mengetik nama + menggores tanda tangan persetujuan potong gaji di HP (PP 36/2021), OWNER menyetujui (boleh menurunkan nominal) → uang keluar dari kas/bank (buku kas + jurnal Dr 1005 / Cr kas-bank, cek saldo). Maksimal kasbon berjalan 1× gaji bulanan. Dicicil otomatis per gaji sesuai cicilan yang disepakati, tetap di dalam batas 50%; saat karyawan keluar dipotong sebanyak batas mengizinkan, sisanya piutang. Pelunasan tunai (Dr kas / Cr 1005) dan "hapuskan sisa" oleh owner (Dr 5013 beban piutang tak tertagih, bukan pendapatan). Cetak Surat Pernyataan Kasbon. Migrasi `o3f4a5b6c7d8`. Kasbon tidak tampil di halaman Denda (satu pintu).
- 2026-10-12: **Draf Peraturan Perusahaan otomatis** (tombol di Aturan Gaji & Potongan): bab hubungan kerja, waktu kerja & apel, izin keluar lokasi, cuti & sakit (sesuai UU), upah & potongan (status yang dipotong, pembagi, batas 50%, kasbon), denda tertulis, mangkir, resign & berakhirnya hubungan kerja, perselisihan, penutup (berlaku 2 tahun). Bagian yang wajib diisi manual ditandai (jam kerja, penggunaan uang denda, kota/tanggal). Wajib minta saran wakil pekerja dan disahkan Disnaker sebelum berlaku.
- 2026-10-12: **Gladi diperluas** dengan tahap "O. SDM, kasbon, penggajian & PPh 21" (aturan → karyawan → kontrak TTD karyawan+owner → Disnaker → apel/mangkir/denda → izin → kasbon → PPh 21 aktif → penggajian → bayar → slip/WA/kwitansi → setor PPh 21) dengan pemeriksaan angka pasti per akun. Gladi menemukan Cek Kesehatan Data masih memakai rumus gaji lama (tanpa denda/kasbon/PPh 21/kompensasi) → diperbaiki. Hasil: **217/217 langkah, 64/64 pemeriksaan lulus**.
- 2026-10-09: Fase 9 (Gemini) direview & diperbaiki Claude: ambang kredit tidak terbaca (surat & adendum error, ubah aturan kontrak aktif ikut error); **isi surat di-render ulang saat TTD** → kini snapshot terkunci, cap TTD ditambahkan saat cetak; ongkir "gratis" ditulis mati → dari tarif kontrak; angka eskalasi kredit ditulis mati → dari ambang sistem; libur rutin tampil angka → nama hari; **OTP ditulis ke log bila SMTP kosong** → ditolak tanpa log; OTP tanpa batas percobaan → dibatasi (3 minta/5 coba per 15 menit); adendum dibuat tiap simpan → hanya bila aturan berubah, catatan berisi apa yang berubah; data karangan (email info@idhaboga.co.id, NPWP/alamat cadangan) dihapus → wajib dari Profil Perusahaan; pasal pajak diisi dari Pengaturan Pajak. Kontrak baru aktif hanya setelah surat ditandatangani (basah+scan atau OTP email portal client).
- 2026-10-09: Fase 8 Pajak — keputusan owner: rezim PPh **disiapkan dua-duanya** (PP 55 0,5% atau normal; dipilih di pengaturan setelah konsultan, semula PP 55 lalu diubah owner), PBJT ditambahkan di atas harga, PBJT ke Kab. OKI, dibangun sekarang dengan semua pajak mati bawaan. Urutan kerja: prompt Gemini (jam WIB → gladi pilot → surat kontrak) lalu Claude membangun Fase 8.
- 2026-10-09: **Audit integrasi keuangan end-to-end** (atas permintaan owner, sebelum fitur berikutnya). Cocok: buku besar = buku pembantu (kas, bank, piutang, hutang supplier, persediaan, aset), semua pembayaran berjurnal & tercatat di buku kas, tidak ada jurnal tidak seimbang / tagihan dobel. Diperbaiki: (1) **potong DP/deposit ke invoice dihitung sebagai pelunasan** di satu sumber riwayat (`invoice_payment_history_service`) — janji bayar ditepati, riwayat di detail kredit/detail & cetak invoice/portal, log penagihan otomatis; (2) invoice periode manual, Tagihan Manual, dan input susulan **batal total bila jurnal gagal**; (3) invoice per pesanan **menolak pesanan yang sudah ditagih** di invoice lain; (4) **semua client kontrak** masuk Kontrol Kredit sejak awal; (5) bayar manual & bayar dari bukti portal **satu fungsi** (`customer_payment_service.apply_customer_payment`), validasi tanggal bayar pakai WIB. **Aturan ke depan:** setiap jalur baru yang mengubah sisa invoice wajib lewat salah satu dari dua pintu itu (pembayaran kas/bank atau potongan DP/deposit), dan setiap invoice baru wajib `post_invoice_journal_or_raise`.
- 2026-10-09: Fase 7 — keputusan owner: ta'zir ditagih sebagai **tagihan terpisah** (bukan baris di invoice makanan); selama **kelonggaran** (tidak mampu) utang lama ditangguhkan tanpa ta'zir tetapi **pesanan baru wajib bayar di muka**; **penyaluran Dana Sosial hanya dicatat Owner** (dengan bukti); **ta'widh dibuat sekarang** (biaya penagihan riil + bukti, diputuskan Owner, tagihan terpisah). Tambahan: pemeriksaan kredit masuk penjadwal harian, client kontrak ikut diperiksa, peringatan status sampai ke portal pihak yang ditagih.
- 2026-10-11: **PPh 21 Karyawan terintegrasi penuh ke MODUL PAJAK PUSAT (Fase 8).** Aturan, tarif, PTKP, tabel TER (PP 58/2023), Pasal 17 UU HPP, biaya jabatan (5%, maks Rp500.000/bulan atau Rp6.000.000/tahun), tanggal berlaku, dan pihak penanggung (karyawan vs perusahaan) dipusatkan di modul pajak (`tax_pph21_service.py` & `tax_service.py`), bukan modul HR. Modul HR/penggajian hanya menyimpan data identitas karyawan (`ptkp_status`, `npwp`) dan memanggil modul pajak untuk snapshot baris gaji saat DRAFT. Perhitungan TER Kategori A/B/C untuk Januari–November; perhitungan tahunan Pasal 17 UU HPP untuk Desember atau masa terakhir karyawan keluar (kompensasi akhir PKWT diikutsertakan dalam bruto kena pajak). Jurnal penggajian tetap seimbang sempurna: bila KARYAWAN → Cr 2011 Hutang PPh 21 memotong upah bersih; bila PERUSAHAAN → Dr 5015 Beban PPh 21 Ditanggung Perusahaan / Cr 2011 Hutang PPh 21 tanpa memotong upah bersih. Batas maksimal potongan denda/ganti rugi 50% dihitung dari upah setelah PPh 21 karyawan (PP 36/2021). Penyetoran PPH21 (debit 2011) dan laporan masa pajak PPh 21 terintegrasi di Laporan Pajak Pusat (`/finance/tax`) dengan pengingat jatuh tempo tanggal 15 bulan berikutnya. Tersedia formulir cetak Bukti Pemotongan 1721-A1 tahunan (standar A4).
- 2026-10-13: **Kesiapan Go-Live Pilot, SOP SDM Lengkap & Penyempurnaan Sistem (Gemini).** Dokumen panduan langkah-demi-langkah bagi owner selesai di `deployment/GO_LIVE_PILOT.md` (checklist kesiapan server HTTPS, ops-check 0 FAIL, backup restore SOP, tugas otomatis scheduler, urutan pengisian data asli per menu, dan protokol harian per role). Halaman SOP per role (`app/routes/sop_routes.py`) diperbarui mencakup alur SDM: ADMIN/HR (karyawan, kontrak, izin, mangkir, denda, kasbon, keluar, alur 5 langkah payroll, slip WA, kwitansi), OWNER (Ringkasan SDM, Aturan Gaji & Potongan, persetujuan denda/kasbon, PPh 21), dan ADMIN_OPERASIONAL (apel tim di HP, centang surat dokter, izin). Dua perbaikan kecil diterapkan: (1) isian jam kerja (`hr.working_hours`) & penggunaan uang denda (`hr.fine_fund_usage`) di kartu 4 Aturan Gaji & Potongan diteruskan ke cetak draf Peraturan Perusahaan; (2) tes penjadwal `test_scheduled_jobs_page_and_heartbeat_alert` dijadikan mandiri dengan penyiapan heartbeat segar di awal dan pembersihan cache TTL.
- 2026-10-13: **Kasir Warung cepat** (keputusan owner): satu layar — pilih orang (ketik 2–3 huruf / daftar sering belanja) → ketuk barang (paling laku di atas) → ketuk **TUNAI / QRIS / HUTANG** (sekali ketuk tersimpan, layar langsung siap pembeli berikutnya). Harga selalu dari master barang di server; ketuk dobel/sinyal putus tidak menyimpan dua kali (kunci idempotensi). **Batas hutang per pekerja = peringatan saja** (Pengaturan Perusahaan → Modul → Batas Hutang Warung, bawaan Rp300.000, 0 = tanpa batas), dihitung dari hutang warung yang belum masuk invoice mandor. Pekerja **bisa bayar/cicil langsung di kasir** (dialokasikan ke hutang terlama). **Hutang yang sudah masuk invoice mandor (tidak dibatalkan) ditolak dibayar di warung** — mencegah tertagih dua kali (berlaku juga di halaman Bayar Hutang lama). **ADMIN_OPERASIONAL** mendapat kasir + terima bayar hutang lewat tab bawah baru **Warung** (tampil hanya bila modul Warung aktif); ringkasan, daftar hutang, dan koreksi tetap OWNER/ADMIN.
- 2026-10-13: **UI desktop internal dirombak** (keputusan owner): tampilan sekarang dinilai datar/membosankan/tidak interaktif. Referensi gambar dashboard "MediCore". Diputuskan: warna **biru** seperti referensi, **hanya untuk desktop role internal** (portal, halaman publik/login, aplikasi HP pengantar & Admin Operasional, cetakan tetap); **contoh dulu** (kerangka sidebar terang + topbar + pencarian Ctrl+K, Dashboard Owner/Admin dengan KPI sparkline, Saran Sistem berbasis aturan — tanpa label AI palsu, dan halaman baru 360° Pelanggan); kolom kanan Aktivitas + Peringatan hanya di dashboard & 360°. Setelah owner setuju, disebar ke semua halaman desktop semua role. Dikerjakan Gemini untuk hemat token, direview Claude.
- 2026-10-13: **UI-1 dikerjakan ulang Claude** setelah owner menolak hasil Gemini (sudut kotak beda-beda, sisa bayangan oranye, dropdown tidak seragam, grafik datar, area kosong, tanpa transisi). Temuan serius: dashboard Gemini **mengarang angka** (tren % tertulis mati, grafik kecil dari rumus, nilai cadangan palsu) dan halaman 360° akan error. Aturan baru: (1) **satu sudut 6px untuk semua kotak** desktop internal (token di `body.shell-internal`), (2) netral sejuk + biru, semua token turunan ditulis ulang di body (sumber sisa oranye), (3) sorotan dropdown/menu = biru muda yang sama, (4) KPI, Saran Sistem, Peringatan **hanya dari data asli** (`dashboard_pulse_service.py`; tanpa pembanding → "belum ada pembanding"), kas masuk dari usaha tanpa saldo awal/modal owner/koreksi/pindah buku, (5) gerak: transisi halus antarhalaman (View Transitions), garis progres, isi muncul bertahap, angka KPI menghitung naik, halaman menu dimuat lebih dulu saat kursor berhenti di tautan (bukan `/ops`, unduhan, cetak). 360° Pelanggan dibatasi cabang. Tahap berikutnya (setelah owner setuju): sebar pola `panel`/`kpi`/`mini-table` ke semua halaman desktop semua role.
