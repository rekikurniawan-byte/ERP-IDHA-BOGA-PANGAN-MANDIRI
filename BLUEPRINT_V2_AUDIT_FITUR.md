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

Satu konsekuensi yang perlu diketahui: role Client/PT gabungan **tidak memakai form order pribadi** — aturan itu sudah ada untuk PT, karena pesanan berasal dari sub-client, bukan dari perusahaan.

### Kompatibilitas client tanpa sub-client — BELUM

Saat ini **tidak bisa**. `daily_order_details.mandor_id`, `delivery_locations.mandor_id`, dan `workers.mandor_id` semuanya `NOT NULL`, dan `mandors.client_id` juga `NOT NULL` — jadi rantai order selalu lewat mandor. Sisi penagihan sudah siap (`invoices.mandor_id` nullable).

Dua pilihan: (a) buat satu mandor yang mewakili client itu sendiri — jalan tanpa ubah kode, tapi kotor secara konsep; (b) jadikan baris order menunjuk client **atau** sub-client — `mandor_id` nullable + `client_id`, menyentuh ~100 file, tepat dikerjakan saat merancang domain V2.

Keputusan bisnis yang menentukan: client tanpa mandor itu **client kontrak yang pesan langsung (kredit)** atau **customer umum (bayar di muka)**?

### Sisa pekerjaan

- Kode jalur PORTAL_DELEGATE (39 referensi) masih ada meski role-nya tak bisa diberikan lagi — pembersihan lanjutan.

---

*Bukti di dokumen ini diambil langsung dari aplikasi yang berjalan: matriks akses dibaca dari closure `role_required` pada 422 route teregistrasi; jumlah baris dari DB `idha_boga_staging`; deskripsi role dari `ROLE_DESCRIPTIONS`.*
