# Blueprint V2 — Audit Fitur & Penyederhanaan Role

Dokumen kerja untuk menyederhanakan ERP **di dalam aplikasi yang sekarang**, sebelum keputusan stack apa pun.
Target: **4 role internal + 3 portal eksternal + 2 jalur transaksi.**

**Cara pakai:** kolom `Keputusan` di setiap tabel diisi oleh pemilik bisnis — `WAJIB`, `PERLU`, `TIDAK DIPAKAI`, atau `BELUM JELAS`.
Kolom `Usulan awal` adalah tebakan berbasis bukti dari kode, bukan keputusan.

---

## 1. Temuan kunci

### 1.1 Data tidak bisa membuktikan fitur mana yang dipakai

Database yang terhubung adalah `idha_boga_staging`. Hampir semua tabel operasional kosong:

| Domain | Tabel utama | Baris |
|---|---|---|
| Order | `daily_orders` | 1 |
| Invoice / pembayaran | `invoices`, `payments` | 1 / 1 |
| Jurnal | `journals` | 1 |
| Produksi | `productions` | 1 |
| Pengiriman | `deliveries`, `delivery_receipts` | 0 / 0 |
| Stok & pembelian | `stock_movements`, `procurements`, `suppliers` | 0 / 0 / 0 |
| SDM | `employees`, `payrolls` | 0 / 0 |
| Resep & HPP | `recipe_headers`, `menus`, `order_hpp_snapshots` | 0 / 0 / 0 |
| Kas lapangan | `field_transactions` | 0 |

Semua data dibuat dalam rentang ~1 bulan pengembangan (28 Jun – 30 Jul 2026). **Satu-satunya modul dengan data yang benar-benar terkumpul adalah prediksi/ML** (`ml_catering_historical` 5.243 baris, `research_dataset_*` 4.720 baris).

**Konsekuensi:** keputusan "fitur ini dipakai atau tidak" hanya bisa datang dari pemilik bisnis. Kode bisa menunjukkan apa yang *ada* dan *siapa yang bisa membukanya*, tapi tidak bisa menunjukkan apa yang *dikerjakan bisnisnya*.

### 1.2 Kode sendiri mengakui sebagian besar role itu spekulatif

Dari `ROLE_DESCRIPTIONS` di `app/services/user_management_service.py`:

| Role | Deskripsi di kode |
|---|---|
| ADMIN | "Role lama tetap dipertahankan agar tidak memutus akses existing." |
| FINANCE | "**Disiapkan untuk** invoice, pembayaran, kas/bank, piutang..." |
| ACCOUNTING | "**Disiapkan untuk** jurnal, laporan akuntansi, COA mapping..." |
| LOGISTICS | "**Disiapkan untuk** stok, prediksi bahan, pembelian, supplier..." |
| HR | "**Disiapkan untuk** karyawan internal dan payroll." |
| PORTAL_CUSTOMER | "Role **reservasi** pelanggan umum; akses transaksi tetap menunggu mapping..." |

Sistem ini awalnya berpusat di ADMIN. Role departemen ditambahkan di atasnya untuk departemen yang direncanakan, bukan yang ada.

### 1.3 Mekanisme akses sederhana — penyederhanaan bisa dihitung persis

Seluruh akses dikendalikan satu decorator, `role_required(*allowed_roles)` di `app/utils/decorators.py`, dipakai di 404 route. **OWNER melewati semua pengecekan.** Karena daftar role yang diizinkan tersimpan di closure setiap view, matriks akses 422 route bisa dibaca langsung dari aplikasi yang berjalan — tidak perlu menebak.

---

## 2. Pemetaan role: 14 → 4 + 3

"Route eksklusif" = route yang bisa dibuka role itu (dan OWNER), tapi tidak oleh role lain mana pun.
Kolom **Perubahan akses** menunjukkan berapa route yang *bertambah* bagi role tujuan setelah peleburan.

### 2.1 Internal

| Role sekarang | Route dijangkau | Eksklusif | → Target | Perubahan akses | Keputusan |
|---|---|---|---|---|---|
| OWNER | 421 | 29 | **OWNER** | — | |
| ADMIN | 275 | 74 | **ADMIN** | — | |
| CUSTOMER_SUCCESS | 36 | **0** | ADMIN | **Tidak ada** — ADMIN sudah menjangkau semuanya | |
| FINANCE | 146 | 9 | ADMIN | ADMIN sudah menjangkau 91/91 route `finance`; tambahan kecil | |
| HR | 37 | 1 | ADMIN *atau dihapus* | ADMIN sudah menjangkau 13/13 route `hr` | |
| LOGISTICS | 62 | 25 | ADMIN | **ADMIN +24 route** (`logistics` saat ini 0 untuk ADMIN) | |
| ACCOUNTING | 89 | 34 | ADMIN *atau* OWNER *atau dihapus* | **ADMIN +35 route** (`accounting` saat ini 0 untuk ADMIN) | |
| DAPUR | 32 | 2 | **DAPUR** | — | |
| PENGANTAR | 37 | 1 | **PENGANTAR** | — | |

Tiga baris pertama di bawah OWNER/ADMIN adalah peleburan gratis. **LOGISTICS dan ACCOUNTING adalah keputusan sungguhan**: meleburnya berarti ADMIN mendapat akses ke area yang hari ini tertutup baginya.

### 2.2 Portal

| Role sekarang | Deskripsi di kode | Eksklusif | → Target | Keputusan |
|---|---|---|---|---|
| PORTAL_CLIENT | "portal read-only untuk Client/PIC" | 1 | **CLIENT / PT** | |
| PORTAL_PT | "portal read-only untuk PT/perusahaan" | 8 | **CLIENT / PT** | |
| PORTAL_MANDOR | "portal read-only untuk Mandor" | 9 | **SUB CLIENT / MANDOR** | |
| PORTAL_DELEGATE | "read-only terbatas untuk delegasi Client/PIC/lokasi" | 1 | ? | |
| PORTAL_CUSTOMER | "Role reservasi pelanggan umum" | 9 | **CUSTOMER UMUM** | |

PORTAL_CLIENT dan PORTAL_PT hampir identik deskripsinya — kandidat kuat untuk dilebur. PORTAL_DELEGATE perlu keputusan: apakah ada orang yang login *atas nama* Client/PT dengan akses lebih sempit?

---

## 3. Inventaris modul

Kolom **Akses sekarang** = role yang disebut di allowlist (jumlah route). OWNER menjangkau semua.
**Data** = baris di tabel utama pada DB staging (lihat 1.1 — bukan bukti pemakaian).

| Modul | Route | Akses sekarang | Data | Usulan awal | Pertanyaan | Keputusan |
|---|---|---|---|---|---|---|
| `operational` (order harian) | 16 | ADMIN | order 1 | **WAJIB** | Inti jalur kontrak & umum | |
| `production` | 3 | ADMIN, DAPUR | produksi 1 | **WAJIB** | — | |
| `delivery` | 15 | ADMIN, PENGANTAR | 0 | **WAJIB** | — | |
| `finance` | 91 | ADMIN, FINANCE, ACCOUNTING(14) | invoice 1 | **WAJIB** sebagian | 91 route itu besar — mana yang dipakai: invoice, piutang, kas/bank, hutang supplier, aset tetap, uang muka, tagihan manual? | |
| `portal` | 59 | 5 role portal, ADMIN(29) | draft 5 | **WAJIB** | Disederhanakan ke 3 portal | |
| `master` | 45 | ADMIN, LOGISTICS, FINANCE | client 6, mandor 6 | **WAJIB** | — | |
| `settings` | 36 | OWNER, ADMIN(14) | — | **WAJIB** | Banyak halaman QA/visual sweep internal — bisa dipangkas | |
| `dashboard` | 11 | per role | — | **WAJIB** | Tinggal 4 dashboard internal | |
| `logistics` (stok, pembelian, supplier) | 25 | LOGISTICS, DAPUR(5) | **0** | PERLU | Apakah stok & pembelian dicatat di sistem ini? | |
| `costing` (HPP, resep) | 16 | ADMIN | **0** | BELUM JELAS | Apakah HPP per porsi dihitung di sistem? | |
| `accounting` (jurnal, COA, neraca saldo, tutup buku) | 35 | ACCOUNTING | jurnal 1 | BELUM JELAS | Pembukuan double-entry di sistem ini, atau pakai akuntan / aplikasi luar? | |
| `hr` (karyawan, payroll) | 13 | ADMIN, HR | **0** | BELUM JELAS | Tidak ada di model bisnis yang diusulkan. Payroll di sistem ini? | |
| `field_transactions` (kas lapangan) | 18 | FINANCE, ACCOUNTING, ADMIN(7) | **0** | BELUM JELAS | Apa proses bisnisnya, dan dipakai? | |
| `customer_success` (kontrak, komplain, koreksi, retur) | 20 | ADMIN, CUSTOMER_SUCCESS | kontrak 2 | BELUM JELAS | **Kontrak** kemungkinan WAJIB (jalur kontrak). Komplain/koreksi/retur? | |
| `canteen` (warung, hutang pekerja) | 6 | ADMIN | penjualan 2 | BELUM JELAS | Terkait pekerja mandor — bagian dari bisnis? | |
| `prediction` (ML prediksi permintaan) | 5 | semua user login | **5.243 + 4.720** | BELUM JELAS | Fitur bisnis, atau komponen riset/skripsi? | |
| `sop` | 4 | semua user login | — | PERLU | Dokumentasi — cukup dipertahankan | |
| `auth`, `health` | 4 | publik | — | **WAJIB** | — | |

Tidak ada modul yang saya tandai `TIDAK DIPAKAI`. Menghapus fitur tanpa bukti pemakaian adalah keputusan bisnis, bukan teknis.

---

## 4. Keputusan yang dibutuhkan

Urut dari yang paling menentukan:

1. **Apakah sistem ini sudah dipakai di produksi?** Kalau ada database produksi terpisah dari `idha_boga_staging`, bukti pemakaian ada di sana. Kalau belum pernah dipakai sungguhan, risiko migrasi data hilang dan perhitungan "refactor vs rebuild" berubah.
belum di pakai produksi semuanya data demo
2. **Role mana yang benar-benar dipakai orang untuk login?**
OWNER
ADMIN
DAPUR
PENGANTAR

PORTAL_CLIENT
PORTAL_SUBCLIENT
PORTAL_CUSTOMER
3. **Akuntansi (35 route):** pembukuan dilakukan di sistem ini, atau di luar?
ya harus di lakukan di sistem 
4. **Stok & pembelian (25 route):** dicatat di sistem ini? ya
5. **Payroll / SDM (13 route):** di sistem ini? ya
6. **Finance (91 route):** sub-fitur mana yang dipakai — lihat pertanyaan di tabel. semua nya di pakai
7. **Customer Success:** kontrak jelas bagian dari jalur kontrak; komplain/koreksi/retur? ya
8. **Prediksi ML:** fitur bisnis atau komponen riset? itu sistem terpisah untuk sistem spk jangan di ganggu itu hanya view untuk ngintip data real untuk di olah di sistem terpisah ml prediksi
9. **PORTAL_DELEGATE:** ada yang login atas nama Client/PT dengan akses lebih sempit? tidak
10. **Warung / hutang pekerja:** bagian dari bisnis mandor? kok mandor itukan bisnis saya ngapain jadi bisnis mandor

---

## 5. Setelah keputusan diisi

1. Ciutkan role lewat **migrasi data** (pindahkan user ke role tujuan) + **pemetaan allowlist** di `role_required` — satu tempat, bukan 404 tempat, bila allowlist diganti konstanta grup.
2. Nonaktifkan modul `TIDAK DIPAKAI` (sembunyikan dari navigasi dan tutup route-nya dulu, baru hapus kodenya setelah terbukti tidak ada yang mencarinya).
3. Bentuk dua jalur transaksi di domain order: `order_type` (CONTRACT / GENERAL) dan `payment_mode` (CREDIT / CASH).
4. Semua langkah dijaga oleh 432 test yang sudah ada.
5. **Baru setelah itu** putuskan apakah rebuild masih diperlukan, dan kalau iya, berapa besar.

---

## 6. Status

### Ringkasan keputusan pemilik

- **Semua modul dipakai** — akuntansi, stok & pembelian, SDM & payroll, finance (91 route), customer success, warung. Tidak ada fitur yang dibuang; penyederhanaan murni di lapisan role.
- **Warung adalah lini bisnis PT sendiri**, bukan bisnis mandor.
- **Prediksi ML adalah sistem SPK terpisah** — hanya view untuk mengintip data; tidak disentuh.
- **Belum produksi, semua data demo** — tidak ada risiko migrasi data sungguhan.
- Role yang dipakai: internal **OWNER, ADMIN, DAPUR, PENGANTAR**; portal **CLIENT, SUBCLIENT, CUSTOMER**. PORTAL_DELEGATE tidak dipakai.

### Tahap 1 — role internal: SELESAI

FINANCE, ACCOUNTING, LOGISTICS, HR, CUSTOMER_SUCCESS → **ADMIN**.

- Satu tabel peleburan di `app/utils/roles.py`; `role_required()` dan `has_role()` (sidebar) sama-sama membacanya. Allowlist 422 route tidak disentuh.
- ADMIN: 275 → **361** route, dan sama persis dengan gabungan akses ADMIN + kelima role pensiun sebelumnya. Tidak ada role yang kehilangan akses; tidak ada role lain yang bertambah.
- Sidebar ADMIN: 49 → **66** link (+Akuntansi, +Logistik, +Master Klien/Supplier/Rekening Bank). 0 link mengarah ke route yang tidak boleh dibuka.
- Pengingat piutang/hutang/kas/stok yang dulu dikirim ke FINANCE/LOGISTICS kini ke ADMIN — sebelumnya akan tersimpan untuk role yang tidak dimiliki siapa pun.
- Migrasi `96a0a1b2c3d4`: 5 user dipindah ke ADMIN; tidak ada role pensiun tersisa di DB.

### Tahap 2 — portal: SELESAI

Role akhir: **OWNER, ADMIN, DAPUR, PENGANTAR** + **PORTAL_CLIENT, PORTAL_SUBCLIENT, PORTAL_CUSTOMER**.

| Langkah | Hasil |
|---|---|
| 2a `PORTAL_MANDOR` → `PORTAL_SUBCLIENT` | Rename murni. Entitas Mandor, tabel `mandors`, dan URL `/portal/mandor/*` tidak berubah. |
| 2b `PORTAL_PT` → `PORTAL_CLIENT` | Keduanya memang sudah menghasilkan id lingkup yang sama; role gabungan memakai pengalaman PT. |
| 2c `PORTAL_DELEGATE` dipensiunkan | Tidak dipetakan ke penerus — delegate lebih sempit dari client, jadi mempromosikannya berarti melebarkan akses. 2 akun demo dipindah ke PORTAL_CLIENT **dan dinonaktifkan**. |

**Bukti isolasi data**: untuk seluruh 19 akun portal, sebelum dan sesudah tiap langkah, direkam halaman yang menjawab 200 **dan** id client/mandor/PIC/lokasi yang membatasi datanya. **Tidak ada satu akun pun yang lingkup datanya melebar.**

Satu konsekuensi yang perlu diketahui: role Client/PT gabungan **tidak memesan untuk sub-client-nya** — pesanan mandor tetap dibuat mandor itu sendiri. PT hanya memesan untuk unit order langsungnya (lihat bagian berikut).

### Kompatibilitas client tanpa sub-client — SELESAI

Jawaban owner: client tanpa mandor adalah **client kontrak yang pesan langsung (kredit)**.

Masalahnya: `mandor_id` wajib di 6 tabel (detail order, detail pengiriman, lokasi antar, pekerja, draft portal, alokasi HPP) dan dipakai 507 kali di 62 file, jadi client tanpa sub-client tidak bisa order sama sekali.

Keputusan owner 2026-09-25 (semua sesuai saran):

1. **Unit order langsung**, bukan membongkar `mandor_id`. Client yang pesan
   sendiri mendapat satu sub-client khusus **"PT X — Langsung"**
   (`mandors.is_direct_unit`, maksimal satu per client per cabang — dijaga
   index unik di database). Order, produksi, pengiriman, invoice, piutang,
   kontrol kredit, dan portal langsung berlaku tanpa diubah. Migrasi
   `a1b2c3d4e5f6`.
2. **Dari portal, PT hanya memesan untuk unit langsungnya sendiri.** PT tetap
   memantau semua sub-client-nya, tapi lokasi mandor tidak muncul di form
   order PT dan ditolak kalau dikirim paksa.
3. **Rem kredit PT = limit kontrak, sekarang juga di jalur admin.** Dulu limit
   kontrak hanya dicek di draft portal; order yang diinput admin untuk client
   tidak direm sama sekali. Sekarang lewat limit kontrak = hanya OWNER yang
   bisa menginput order untuk client itu. Exposure yang dihitung lengkap
   (invoice belum lunas + order sudah jalan tapi belum ditagih). Berlaku untuk
   semua order yang ditagih ke client, termasuk lewat mandornya.
4. **Client boleh punya unit langsung dan sub-client biasa sekaligus.**
5. Unit langsung **tidak bisa** disetel "ditagih langsung ke mandor" di
   Kontrol Kredit — itu client sendiri, tagihannya ke PT.

Cara pakai: Master Client → edit client → **Aktifkan Order Langsung** →
tambah lokasi antar (unitnya sudah terpilih). Agar PT bisa memesan dari
portal, akses portal PT-nya juga harus berizin **Draft Order** (diatur di
pemetaan akses portal, seperti sub-client) — aktivasi sengaja tidak menaikkan
izin akses secara otomatis.

### Pembersihan PORTAL_DELEGATE — SELESAI

Kode jalur role PORTAL_DELEGATE dibuang dari 10 file: konstanta dan label
role, cabang lingkup akses, visibilitas invoice/hutang, command center,
persona, dan halaman `/portal/delegate` (sekarang 404). Akun yang masih
memegang role itu bukan role portal lagi: tidak dapat lingkup, halaman, atau
data — ditolak, tidak dipromosikan.

**Yang sengaja dipertahankan:** jenis pemetaan akses `DELEGATE`. Namanya
mirip tapi itu hal lain dan masih hidup — setiap pelanggan umum yang daftar
sendiri mendapat pemetaan jenis ini.

Bukti: lingkup akses (id client, mandor, PIC, lokasi, dan level akses) ke-19
akun portal di staging direkam sebelum dan sesudah — **identik**.

### Istilah bisa diatur — SELESAI

Keputusan owner (2026-09-26): sistem dipakai juga untuk pelanggan katering di
luar proyek — sekolah, kantor, rumah sakit, event. Kata "PT" dan "Mandor"
tidak lagi tertulis mati di tampilan.

1. **Empat istilah**, per cabang, hanya OWNER yang mengubah — Pengaturan
   Perusahaan → **Istilah**:

   | Istilah | Bawaan | Contoh proyek | Contoh sekolah |
   |---|---|---|---|
   | Client | Client | PT | Yayasan |
   | Sub Client | Sub Client | Mandor | Kelas / Unit |
   | Lokasi Antar | Lokasi Antar | Lokasi Proyek | Gedung |
   | Pekerja | Pekerja | Pekerja | Siswa |

   Dikosongkan = pakai bawaan. **Cabang yang sudah berjalan sekarang tampil
   "Client"/"Sub Client"**; isi "PT"/"Mandor" di cabang itu kalau ingin
   tampilan lama.
2. **Nama di kode dan database tidak berubah** (`clients`, `mandors`,
   `PORTAL_SUBCLIENT`, dst.) — hanya teks tampilan. Satu sumber:
   `app/utils/terms.py` (`term()` di template, `T.xxx` di f-string Python,
   `L("…{sub_client}…")` untuk label tingkat modul).
3. **Yang sengaja tidak ikut istilah:** nama akun COA (buku besar harus
   bernama sama di semua cabang). Akun 2007 diganti nama baku menjadi
   **"Deposit Jaminan Pelanggan"** (migrasi `a2b3c4d5e6f7`). "PT" yang berarti
   perusahaan kita sendiri (rekening pembayaran, Pengaturan PT) menjadi
   "Perusahaan".
4. Cakupan: 90 template dan ±70 file Python; menu portal, judul, label
   form, pesan flash, keterangan jurnal, dan halaman SOP.

Bukti: semua halaman GET dirender sebagai OWNER dan tiga role portal dengan
istilah penanda (KLIENKU/SUBKU/LOKASIKU/PEKERJAKU) di staging; sisa kata lama
yang terlihat hanya **data** (nama akun demo seperti "Mandor Portal Demo",
riwayat audit log) dan label pengaturan istilah itu sendiri.

### Modul per cabang: Warung dan Hutang Pekerja — SELESAI

Keputusan owner (2026-09-27): warung masih berguna di luar proyek (kantin
sekolah/kantor), tapi pekerja yang ngutang di warung lalu ditagihkan ke sub
client-nya khas proyek. Jadi dua saklar terpisah per cabang, di Pengaturan
Perusahaan → **Modul**, hanya OWNER:

| Saklar | Isinya | Syarat |
|---|---|---|
| **Warung** | Penjualan kantin, piutang pembeli luar, tutup kas harian warung | — |
| **Hutang Pekerja** | Master pekerja, pekerja ngutang di warung, hutang ditagihkan lewat invoice sub client; menu portal Pekerja / Hutang Warung / Cicilan | Warung nyala |

1. **Cabang baru = mati** (pengaturan tidak ada berarti mati). Cabang yang
   sudah ada **dinyalakan** oleh migrasi `b3c4d5e6f7a8`, jadi tidak ada yang
   berubah bagi mereka.
2. **Modul mati:** menunya hilang (sidebar, master, portal, dashboard, pusat
   komando, tutup harian), halamannya ditolak dengan pesan "Modul … tidak
   aktif di cabang ini" termasuk lewat link langsung, dan layanan penjualan
   warung menolak transaksinya. Berlaku juga untuk OWNER — ini pilihan bisnis
   cabang, bukan hak akses.
3. **Data tidak pernah dihapus.** Jurnal lama tetap di buku besar;
   menyalakan lagi mengembalikan semuanya.
4. **Pengaman uang** — saklar ditolak (dan seluruh form tidak disimpan)
   selama masih ada:
   - Hutang Pekerja: hutang pekerja yang belum lunas **dan** belum masuk
     invoice yang aktif (hutang yang sudah ditagihkan tetap berstatus UNPAID,
     tagihannya pindah ke invoice yang tetap terlihat di Finance; invoice
     yang dibatalkan tidak dihitung menagih);
   - Warung: piutang pembeli luar yang belum lunas, atau kas harian berstatus
     OPEN.

   Halaman pengaturan menampilkan penahannya sebelum OWNER mencoba. Laporan
   Cek Kesehatan Data tetap memeriksa hutang pekerja yang belum masuk
   invoice, apa pun status modulnya.
5. Setiap perubahan saklar tercatat di audit log (lama → baru).

### Dua jalur transaksi — SELESAI

Langkah 3 rencana (bagian 5). Kondisi awal yang ditemukan: pembeda jalur
hanya jenis akun portal; pelanggan umum tersimpan sebagai Client + Sub Client
biasa; tidak ada daftar harga (harga diketik di setiap order, pesanan portal
masuk dengan harga 0); bukti bayar pelanggan umum tanpa nominal dan tanpa
jurnal.

Keputusan owner (2026-09-27):

| Jalur | Siapa | Bayar | Pendapatan |
|---|---|---|---|
| **Kontrak** | client berkontrak | kredit lewat invoice, limit & kontrol kredit | 4001 |
| **Umum** | pelanggan umum (daftar sendiri) | di muka per pesanan | 4002 |

- **Harga:** satu harga per porsi (siang = malam, pilihan A). Harga kontrak per
  client menang atas harga standar cabang. Bisa diubah kapan saja mengikuti
  bahan pokok dan BBM, dengan tanggal berlaku (bisa dijadwalkan). Harga
  dikunci ke pesanan saat dibuat. Admin tidak mengetik harga; hanya OWNER yang
  boleh mengubah harga satu pesanan (audit log). Peringatan kalau di bawah HPP.
- **Minimal pesan pelanggan umum:** 10 porsi per pengiriman (bisa diubah per
  cabang).
- **Ongkir:** kontrak sudah termasuk harga porsi (kecuali kontrak menyebut
  lain); umum per zona, per pengiriman (siang dan malam = dua kali jalan),
  gratis di atas N porsi; akun baru 4005 Pendapatan Ongkos Kirim.
- **Bayar di muka:** total dihitung sistem → bukti bayar bernominal → Finance
  verifikasi → Uang Muka Pelanggan (2008) + jurnal otomatis → baru masuk dapur
  (OWNER boleh meloloskan, tercatat) → invoice lunas otomatis dipotong uang
  muka. Order umum yang diinput admin: pembayaran dicatat saat input. Batal
  setelah bayar: pengembalian atas keputusan OWNER, jurnal otomatis.

| Tahap | Isi | Status |
|---|---|---|
| 1 | Jalur di client, halaman Harga & Ongkir, harga otomatis di order dan pesanan portal, harga kontrak, minimal porsi, peringatan HPP | **Selesai** |
| 2 | Zona ongkir, tarif per pengiriman, gratis di atas N porsi, baris ongkir di invoice, akun 4005 | **Selesai** |
| 3 | Pembayaran jalur umum: total, bukti bernominal, uang muka + jurnal, gerbang dapur, pengembalian, invoice lunas otomatis | **Selesai** |
| 4 | Pendapatan per jalur (Kontrak 4001, Umum 4002), jalur dikunci di invoice, filter & subtotal per jalur di Invoice dan Piutang, ringkasan di dashboard OWNER + ongkir vs BBM | **Selesai** |

Catatan tahap 1: client yang terdaftar lewat portal pelanggan umum ditandai
UMUM oleh migrasi `c4d5e6f7a8b9` hanya kalau **semua** akun portal yang
terkait adalah pelanggan umum; client kontrak yang kebetulan dipetakan ke akun
pelanggan (data demo di staging) tetap KONTRAK. Setelah rilis, OWNER perlu
mengisi harga standar di Pengaturan → Harga & Ongkir; sebelum itu pesanan baru
ditolak dengan pesan yang menjelaskannya.

Catatan tahap 2: ongkir dikunci per pengiriman di baris order
(`lunch_delivery_fee`, `dinner_delivery_fee`). Revisi yang memunculkan
pengiriman baru (mis. menambah porsi malam yang tadinya 0) mengenakan tarif
saat itu; pengiriman yang porsinya jadi 0 tidak lagi dikenai ongkir; perubahan
jumlah porsi pada pengiriman yang sudah ada tidak mengubah ongkirnya. Invoice
realtime dan periode memuat baris `ONGKIR` per pengiriman berbayar (tidak bisa
tertagih dua kali), dijurnal ke 4005. Paparan kredit ikut menghitung ongkir.
Lokasi pelanggan umum wajib punya zona: dipilih pelanggan saat mendaftar, dan
bisa dikoreksi admin di data lokasi.

Catatan tahap 3 (semua jurnal lewat layanan yang sudah ada — tidak ada jurnal
baru yang ditulis tangan):

| Kejadian | Jurnal |
|---|---|
| Finance mencatat uang muka dari bukti bayar (nominal & rekening yang benar-benar diterima) | Dr Kas/Bank, Cr 2008 Uang Muka Pelanggan |
| Semua pengiriman pesanan umum diterima → invoice otomatis | Dr 1004, Cr 4002 (+ 4005 ongkir) |
| Invoice itu langsung dipotong uang muka | Dr 2008, Cr 1004 → invoice LUNAS |
| Pesanan ditolak/batal setelah dibayar → OWNER mengembalikan | Dr 2008, Cr Kas/Bank |

- Pelanggan melihat "Bayar Rp X" + rekening/QRIS perusahaan di pesanannya dan
  mengunggah bukti dengan nominal. Nominal pelanggan hanya keterangan; yang
  dijurnal adalah nominal yang dicatat Finance.
- Gerbang dapur: draft jalur UMUM (atau akun pelanggan umum) tertahan sampai
  uang muka tercatat ≥ total. Bukti yang baru diunggah **tidak** meloloskan
  (dulu cukup "ada bukti"). OWNER boleh meloloskan dengan alasan wajib; audit
  log `PREPAYMENT_OVERRIDE`. Sisa yang belum dibayar tetap tertagih sebagai
  piutang di invoice otomatis.
- Pesanan umum yang diinput admin: baris order dan pembayarannya disimpan
  dalam satu transaksi; kurang bayar ditolak kecuali OWNER. Tambah porsi
  pesanan umum (revisi / tambah setelah lock) hanya OWNER.
- Invoice otomatis dibuat saat tanda terima terakhir pesanan itu disimpan;
  kalau gagal, tanda terima tetap tersimpan dan Finance diberi tahu untuk
  membuat invoice manual. Pembuatan invoice realtime dipindah ke
  `order_invoice_service` supaya tombol Finance dan jalur otomatis memakai
  aturan yang sama; invoice yang jurnalnya gagal kini dibatalkan utuh.
- Invoice untuk pelanggan umum tidak lagi mewajibkan PIC client: kontaknya
  pelanggan itu sendiri.

Catatan tahap 4: jalur dikunci di `invoices.customer_path` saat invoice
disimpan (satu kait `before_insert`, jadi keempat jalan pembuatan invoice
tercakup). Invoice lama diberi label dari jalur client-nya sekarang — hanya
label; jumlah dan jurnal lamanya tidak berubah. Jurnal pendapatan catering
**mulai sekarang** mengikuti jalur: client kontrak yang ditagih harian kini
masuk 4001, bukan 4002. Invoice tanpa client master (tagihan manual ke
kelompok/perorangan) tetap memakai aturan lama.

### Langkah 5 — Bangun ulang atau lanjut? (penilaian 2026-09-27)

**Kesimpulan: tidak perlu dibangun ulang.** Lanjutkan sistem yang sekarang,
dengan satu putaran pengerasan sebelum dipakai produksi.

Bukti (diukur dari kode, bukan perkiraan):

| Ukuran | Angka |
|---|---|
| Kode Python | 214 file, ±74.000 baris |
| Template | 267 file, ±42.000 baris |
| Tabel database / migrasi | 127 / 64 |
| Halaman (route) / dijaga role | 438 / 420 (sisanya publik: login, daftar, health) |
| Tes | 626 — lulus 623; 3 gagal karena tesnya usang, bukan bug |

Alasan tidak membangun ulang:
1. Isinya aturan bisnis yang sudah dikunci dan dites — akuntansi otomatis,
   kontrol kredit, dua jalur transaksi, harga & ongkir, portal tiga peran.
   Membangun ulang berarti menulis ulang semuanya dari nol (berbulan-bulan)
   dan mengulang risiko salah hitung uang yang sudah ditutup tes.
2. Fondasinya benar: teknologi umum (Flask + PostgreSQL + Alembic), semua
   halaman lewat satu penjaga role, batas transaksi atomik, idempotensi,
   audit log, optimistic locking di semua tabel, jurnal hanya lewat layanan.
3. Terbukti bisa diubah dengan aman: role 14→7, istilah per cabang, modul
   per cabang, dan dua jalur transaksi selesai tanpa merusak fitur lain.
4. Belum produksi — tidak ada data nyata yang dipertaruhkan, tapi juga tidak
   ada alasan membuang yang sudah bekerja.

Pengerasan sebelum produksi (urut risiko):

| # | Temuan | Risiko | Wajib sebelum produksi |
|---|---|---|---|
| 1 | Angka "cutover" tertanam di akuntansi (`ACCOUNTING9B/9D_CUTOVER_*` = 2 atau 4): di database produksi baru, penjualan warung #1–2 dan hutang pekerja #1–2 **tidak dijurnal**, invoice #1–2 diperlakukan sebagai data lama | Buku besar kurang | **Ya** |
| 2 | Uang masih dihitung dengan `float` di ±56 tempat jalur invoice/uang muka/akuntansi | Selisih pembulatan | **Ya** (jalur uang) |
| 3 | 259 tempat mencatat "Suppressed unexpected exception" / 326 `except Exception` | Kegagalan lolos tanpa terlihat | **Ya** untuk jalur uang; sisanya bertahap |
| 4 | Kesiapan operasional: migrasi harus dengan user aplikasi (izin tabel), penyapu kredit harian masih menumpang permintaan pertama (perlu penjadwal), backup & pemulihan diuji, pemantauan error | Operasional | **Ya** |
| 5 | 3 tes usang (hitungan audit commit, teks antrean bukti bayar) | Suite tidak hijau penuh | Ya |
| 6 | CSS ±82.000 baris dengan 94 file override bertumpuk | Perubahan tampilan lambat | Bertahap |
| 7 | Kode mati & tambalan: pembuat jurnal lama yang tak dipanggil, 86 penanda PATCH/PRODUCTION, 41 modul rute `import *`, dua pembuat nomor invoice | Pemeliharaan | Bertahap |
| 8 | Uji coba satu cabang dengan data nyata sebelum semua cabang | Validasi | **Ya** |

### Sisa pekerjaan

- Pengerasan sebelum produksi (tabel di atas), mulai dari #1.

---

*Bukti di dokumen ini diambil langsung dari aplikasi yang berjalan: matriks akses dibaca dari closure `role_required` pada 422 route teregistrasi; jumlah baris dari DB `idha_boga_staging`; deskripsi role dari `ROLE_DESCRIPTIONS`.*
