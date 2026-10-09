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
| T1 | "Akun Saya" semua role + menu harian dengan foto | Gemini | ⏳ `PROMPT_GEMINI_AKUN_MENU.md` |
| T2 | Reminder sesuai role | Gemini | ⏳ `PROMPT_GEMINI_REMINDER_ROLE.md` |
| 3 | Pengaturan kontrak | Gemini + cek Claude | ✅ (belum commit) |
| 4 | Penjadwal otomatis | Gemini + perbaikan Claude | ✅ (799 test lulus) |
| 5 | Pesanan otomatis | Gemini + perbaikan Claude | ✅ (799 test lulus) |
| 6 | Invoice otomatis | **Claude** | ✅ (belum commit) |
| 7 | Kontrol kredit syariah + ta'zir | **Claude** | ✅ (belum commit; migrasi `g5b6c7d8e9f0`) |
| 8 | Pajak | **Claude** | 🔜 (tunggu konsultan pajak) |
| 9 | Surat kontrak otomatis | Gemini + cek Claude | 🔜 (paling akhir) |

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

## 10. Fase 8 — Pajak (Claude, setelah konsultan pajak)

- **PBJT** (pajak daerah makan/minum, dulu PB1): persentase bisa diatur, opsional muncul di invoice.
- **PPh 23 (2%)** yang dipotong pelanggan PT: admin mencatat bukti potong, sisa piutang berkurang, jurnal otomatis.
- Laporan pajak bulanan.
- PPN/e-Faktur **tidak** dibuat kecuali PT sudah PKP.
- **Syarat mulai**: tarif dan kewajiban dikonfirmasi konsultan pajak.

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
- 2026-10-09: **Audit integrasi keuangan end-to-end** (atas permintaan owner, sebelum fitur berikutnya). Cocok: buku besar = buku pembantu (kas, bank, piutang, hutang supplier, persediaan, aset), semua pembayaran berjurnal & tercatat di buku kas, tidak ada jurnal tidak seimbang / tagihan dobel. Diperbaiki: (1) **potong DP/deposit ke invoice dihitung sebagai pelunasan** di satu sumber riwayat (`invoice_payment_history_service`) — janji bayar ditepati, riwayat di detail kredit/detail & cetak invoice/portal, log penagihan otomatis; (2) invoice periode manual, Tagihan Manual, dan input susulan **batal total bila jurnal gagal**; (3) invoice per pesanan **menolak pesanan yang sudah ditagih** di invoice lain; (4) **semua client kontrak** masuk Kontrol Kredit sejak awal; (5) bayar manual & bayar dari bukti portal **satu fungsi** (`customer_payment_service.apply_customer_payment`), validasi tanggal bayar pakai WIB. **Aturan ke depan:** setiap jalur baru yang mengubah sisa invoice wajib lewat salah satu dari dua pintu itu (pembayaran kas/bank atau potongan DP/deposit), dan setiap invoice baru wajib `post_invoice_journal_or_raise`.
- 2026-10-09: Fase 7 — keputusan owner: ta'zir ditagih sebagai **tagihan terpisah** (bukan baris di invoice makanan); selama **kelonggaran** (tidak mampu) utang lama ditangguhkan tanpa ta'zir tetapi **pesanan baru wajib bayar di muka**; **penyaluran Dana Sosial hanya dicatat Owner** (dengan bukti); **ta'widh dibuat sekarang** (biaya penagihan riil + bukti, diputuskan Owner, tagihan terpisah). Tambahan: pemeriksaan kredit masuk penjadwal harian, client kontrak ikut diperiksa, peringatan status sampai ke portal pihak yang ditagih.
