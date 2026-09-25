# Blueprint V2 — Kontrol Kredit Sub Client (Mandor) yang Ditagih Langsung

Kasus yang harus ditangani: **client kontrak, tapi mandornya tidak di-backup
pembayarannya oleh PT pemilik proyek.** Order tetap jalan kredit, tagihan lari
ke mandor pribadi. Risikonya: telat bayar → numpuk → ngabur tanpa melunasi.

Dokumen ini isinya dua hal: kondisi sistem hari ini (dengan bukti), dan alur
yang harus dibangun.

---

## 1. Kondisi sistem hari ini

Saya telusuri seluruh jalur kredit. Ringkasnya: **tidak ada satu pun rem yang
benar-benar mengerem.**

| # | Temuan | Bukti |
|---|---|---|
| 1 | `credit_limit` cuma dibaca di **satu** tempat: gerbang draft order portal. Tidak ada di tempat lain. | `app/services/portal_order_draft_service.py` → `_credit_gate_for_draft()` |
| 2 | Jalur order **internal (ADMIN)** sama sekali tidak punya gerbang kredit. Admin bisa input order berapa pun untuk mandor yang nunggak berapa pun. | `grep credit\|limit\|outstanding app/routes/operational*` → kosong |
| 3 | Gerbang portal pun **tidak memblokir**. Lewat limit → `APPROVAL_REQUIRED`. Tanpa kontrak → cuma warning *"Admin boleh lanjut jika kebijakan kredit perusahaan mengizinkan"*. | `_credit_gate_for_draft()` |
| 4 | Jatuh tempo invoice **di-hardcode 7 hari**, tidak pernah baca termin kontrak. | `app/routes/finance/period_invoice_routes.py:618` → `due_date = invoice_date + timedelta(days=7)` |
| 5 | `payment_terms` cuma teks bebas, tidak pernah diurai jadi angka. Isi DB sekarang: `"net 30"` dan `"NET 14"` — beda kapitalisasi, tidak dipakai menghitung apa pun. | `customer_contracts.payment_terms` String(120) |
| 6 | Semua invoice otomatis **dipaksa `bill_to_type="CLIENT"`**. Menagih mandor langsung cuma bisa lewat billing manual — persis skenario yang Bapak khawatirkan justru tidak punya jalur sistematis. | `period_invoice_routes.py:627`, `realtime_invoice_routes.py:237` |
| 7 | **Mandor tidak punya field kredit sama sekali.** Master mandor cuma: branch, client, nama, telepon, aktif. Limit kredit menempel di kontrak, dan kontrak milik *client* — bukan mandor. | `app/models/master.py` → `class Mandor` |
| 8 | Gerbang hanya mengukur **jumlah** outstanding, tidak pernah mengukur **umur**. Mandor yang masih di bawah limit tapi telat 90 hari: lolos tanpa peringatan. | `_active_outstanding_for_scope()` |
| 9 | Bucket umur tunggakan (`days_overdue`, 30/60/90) hanya ada di laporan **hutang ke supplier**, tidak ada di piutang. | `app/services/accounts_payable_report_service.py:63` |
| 10 | Exposure yang dihitung **cuma invoice terbit**. Makanan yang sudah dikirim tapi belum masuk invoice periode tidak terlihat sama sekali oleh gerbang. Untuk katering harian dengan invoice per periode, ini bisa senilai satu periode penuh. | `_active_outstanding_for_scope()` hanya query `Invoice` |
| 11 | Yang sudah bagus: `invoice_collection_logs` sudah lengkap — ada `promise_date`, `collection_status`, `channel`. Tapi tidak menggerakkan apa-apa; murni catatan. | `app/models/finance.py` |

**Kesimpulan:** semua mesin *pencatat* sudah ada. Mesin *pencegah* belum ada
satu pun. Dan justru kasus paling berisiko — mandor ditagih langsung tanpa
backup PT — adalah kasus yang paling tidak terlindungi: tanpa limit, tanpa
termin, tanpa gerbang.

---

## 2. Prinsip: kenapa mandor langsung beda kelas

Client kontrak yang di-backup PT: kalau telat, ada badan usaha, ada kontrak,
ada aset, ada reputasi yang bisa ditagih. Mandor pribadi tanpa backup PT: kalau
ngabur, yang tersisa cuma nomor HP.

Maka aturannya satu kalimat:

> **Kerugian maksimum = limit kredit − deposit.**
> Kalau deposit nol, kerugian maksimum = limit penuh.

Ini bukan soal software. Software cuma bisa menegakkan angka yang Bapak
tetapkan. Tapi software **harus** bikin angka itu mustahil dilanggar diam-diam.

---

## 3. Alur: lima gerbang

Setiap mandor yang ditagih langsung harus lewat lima gerbang berurutan.

### Gerbang 1 — Status penagihan ditetapkan di depan (bukan belakangan)

Setiap mandor wajib punya **mode penagihan** yang eksplisit:

- `VIA_CLIENT` — ditagih ke PT pemilik proyek. *(default semua mandor yang ada
  sekarang — migrasi tidak boleh diam-diam memberi kredit ke siapa pun)*
- `DIRECT` — ditagih langsung ke mandor, kredit. **Ini kasus yang dibahas.**
- `CASH` — bayar di muka, tanpa kredit.

Mandor `DIRECT` tidak bisa dibuat tanpa mengisi: limit kredit, termin (hari),
deposit, identitas (NIK/KTP), dan penjamin bila ada. Tanpa itu limit = 0 →
efektif `CASH`.

### Gerbang 2 — Deposit dulu, kredit belakangan

Mandor `DIRECT` setor deposit sebelum kredit menyala. Deposit dicatat sebagai
**kewajiban perusahaan** (uang mandor yang dititipkan), bukan pendapatan, dan
dipotongkan di pelunasan terakhir.

Limit kredit diturunkan dari **kebutuhan order**, deposit dari limit
(keputusan owner 2026-09-25):

```
limit_kredit      = nilai order selama termin + 7 hari cadangan   (usulan sistem, OWNER menetapkan)
syarat_deposit    = 20% x limit                                   (OWNER bisa ubah per mandor)
kerugian_maksimum = limit - deposit
```

Versi awal memakai limit = deposit × 2. Terlalu kecil: mandor 50 porsi × 2
kali makan (±Rp 2 juta/hari) dengan termin 14 hari wajar berhutang ±Rp 28 juta;
dengan deposit Rp 5 juta dan limit Rp 10 juta dia sudah tertahan di hari ke-5
padahal belum telat apa pun — tidak ada mandor yang mau kerja sama dengan itu.
Perlindungan utama bukan besarnya deposit, tapi kecepatan rem: telat 8 hari
ditahan, 22 hari diblokir, ingkar janji 2× langsung diblokir. Mandor baru
sebaiknya mulai dari limit kecil dan naik setelah 2–3 siklus bayar tepat waktu.

### Gerbang 3 — Exposure dihitung lengkap, bukan setengah

Sebelum order baru diterima, sistem menghitung:

```
exposure = invoice belum lunas
         + sudah dikirim tapi belum di-invoice    <-- ini yang hilang sekarang
         + nilai order baru yang sedang diminta
         - deposit
```

Poin kedua kritis. Invoice periode terbit belakangan; tanpa memasukkannya,
mandor bisa menumpuk satu periode penuh sebelum gerbang sadar.

### Gerbang 4 — Tangga eskalasi otomatis

Status kredit bergerak **sendiri** setiap hari berdasarkan umur tunggakan dan
exposure. Tidak menunggu admin ingat.

| Status | Pemicu | Akibat pada order baru |
|---|---|---|
| **AKTIF** | Lancar, exposure < 75% limit | Jalan normal |
| **PANTAU** | Telat 1–7 hari, **atau** exposure ≥ 75% limit | Jalan, tapi ADMIN wajib isi log penagihan; muncul banner merah |
| **TAHAN** | Telat 8–21 hari, **atau** exposure > limit, **atau** janji bayar meleset 1× | **Order baru butuh persetujuan OWNER**, dengan alasan tertulis |
| **BLOKIR** | Telat > 21 hari, **atau** janji bayar meleset 2× | **Order baru ditolak keras.** Portal maupun internal. Hanya OWNER yang bisa buka |
| **HAPUS BUKU** | Telat > 60 hari | Piutang pindah ke pos piutang macet, mandor dinonaktifkan, identitas masuk daftar cekal |

Dua aturan yang tidak bisa ditawar:

1. **Naik tangga otomatis, turun tangga tidak pernah otomatis.** BLOKIR → AKTIF
   hanya lewat tindakan OWNER, dan hanya setelah ada pembayaran masuk atau
   komitmen tertulis yang tercatat.
2. **Setiap perpindahan status menulis satu baris audit** — siapa, kapan,
   kenapa, angka berapa. Waktu mandor ngabur lalu ribut *"saya tidak pernah
   diperingatkan"*, jejaknya ada.

### Gerbang 5 — Penagihan yang punya gigi

`invoice_collection_logs` sudah ada dan sudah punya `promise_date`. Yang perlu
ditambahkan: **janji bayar yang meleset harus mengakibatkan sesuatu.**

- Lewat `promise_date` tanpa pembayaran → otomatis naik satu anak tangga.
- Meleset 2× → langsung BLOKIR, tanpa menunggu umur tunggakan.

Mandor yang janji lalu ingkar dua kali adalah sinyal paling awal dan paling
akurat dari niat ngabur. Umur tunggakan datangnya belakangan.

---

## 4. Yang benar-benar melindungi dari "ngabur"

Gerbang di atas menahan kerugian supaya tidak membesar. Tapi kalau orangnya
memang sudah niat kabur, yang menyelamatkan uang cuma empat hal:

1. **Deposit** — satu-satunya uang yang sudah di tangan Bapak. Tanpa ini semua
   gerbang cuma mengurangi kerugian, tidak menghilangkannya.
2. **Identitas tercatat** — NIK/KTP di master mandor. Sekarang **tidak ada**,
   jadi mandor yang diblokir bisa mendaftar lagi besok sebagai baris mandor
   baru dengan nama sedikit berbeda, dan sistem tidak akan tahu.
3. **Penjamin** — kalau PT tidak mau menjamin, minta penjamin perorangan.
   Disimpan di master, ikut tertagih.
4. **Limit kecil di awal** — mandor baru mulai dari limit rendah, naik setelah
   rekam jejak bayar terbukti. Kepercayaan dibangun sistem, bukan diberikan di
   muka.

---

## 5. Perubahan sistem yang dibutuhkan

Dipecah bertahap supaya tiap tahap bisa dipakai dan diuji sendiri.

### Tahap A — tempat menyimpan syarat kredit

Tabel baru `credit_accounts`, satu baris per pihak tertagih (client **atau**
mandor):

```
branch_id, party_type ('CLIENT'|'MANDOR'), party_id
billing_mode ('VIA_CLIENT'|'DIRECT'|'CASH')
credit_limit, payment_terms_days, deposit_percent
status ('AKTIF'|'PANTAU'|'TAHAN'|'BLOKIR'|'HAPUS_BUKU')
status_reason, status_changed_at, status_changed_by, release_until
unique (branch_id, party_type, party_id)
```

Deposit yang **sudah diterima** sengaja tidak disimpan di tabel ini: dihitung
dari transaksi deposit di buku besar (akun 2007), supaya angka di layar kredit
tidak mungkin berbeda dengan jurnalnya.

Plus `credit_status_events` — audit append-only tiap perpindahan status.

Plus field identitas di master mandor: NIK, alamat, penjamin.

**Tidak ada baris = tidak ada kredit.** Migrasinya murni DDL dan tidak mengisi
data apa pun. Pihak tanpa baris akun dinilai `VIA_CLIENT`, limit 0, AKTIF —
persis perilaku lama. Baris baru dibuat saat Bapak menyetel kredit seseorang.

> Versi pertama sempat mengisi satu baris per pasangan client × cabang. Karena
> client itu global, jumlahnya meledak: 30 baris di staging, tapi ~7 juta di
> database test yang berisi seed menumpuk. Sudah dibatalkan dan di-rollback
> bersih; mengisi data netral juga tidak menambah keamanan apa pun.

Ambang hari (7/21/60) dan persentase deposit punya nilai bawaan di kode
(`DEFAULT_THRESHOLDS`). Baris `branch_settings` dengan key `credit.*` hanya
menimpa nilai itu untuk satu cabang, jadi bisa diubah tanpa deploy.

### Tahap B — satu penilai, dibaca semua jalur

`app/services/credit_control_service.py` — satu fungsi `evaluate_credit()` yang
mengembalikan: boleh/tidak, status, exposure, limit, sisa, umur tunggakan
tertua, butuh approval atau tidak, alasan.

Polanya sama persis dengan `app/utils/roles.py` yang baru kita bangun: **satu
tabel kebenaran, dibaca route dan template sekaligus.** Itu pola yang sudah
terbukti jalan di repo ini, dan itu yang mencegah gerbang portal dan gerbang
internal kembali berbeda pendapat.

### Tahap C — pasang gerbangnya

- Gerbang portal → panggil penilai (menggantikan logika kontrak-client sekarang)
- Jalur order internal ADMIN → panggil penilai yang sama *(sekarang nol gerbang)*
- Jatuh tempo invoice → `invoice_date + payment_terms_days`, jatuh balik ke 7
  hari kalau termin kosong (perilaku lama tetap aman)
- `bill_to_type` invoice otomatis → ikut `billing_mode`, tidak lagi dipaksa
  `"CLIENT"`

### Tahap D — penyapu harian

Job harian: hitung ulang umur, gerakkan status, kirim notifikasi lewat
`notification_service` yang sudah ada ke ADMIN dan OWNER. Tiap pergerakan
menulis `credit_status_events`.

### Tahap E — layar

- Daftar Kontrol Kredit: semua akun, exposure, umur, status — urut dari paling
  berisiko
- Detail per mandor: invoice, pembayaran, log penagihan, riwayat janji,
  linimasa status
- Antrean approval OWNER untuk status TAHAN

---

## 6. Angka yang perlu Bapak tetapkan

Saya pakai default berikut supaya pembangunan bisa jalan. Semua tersimpan di
`branch_settings`, jadi bisa diubah kapan saja tanpa ubah kode:

| Parameter | Default | Catatan |
|---|---|---|
| Termin mandor `DIRECT` | 14 hari | Lebih ketat dari client kontrak |
| Limit | Kebutuhan order selama termin + 7 hari | Usulan dihitung sistem dari order 30 hari terakhir; OWNER yang menetapkan. *(Diubah 2026-09-25: pengali deposit ×2 terlalu kecil — mandor 50 porsi tertahan di hari ke-5.)* |
| Syarat deposit | 20% dari limit | Kredit menyala setelah deposit ini benar-benar diterima |
| Ambang PANTAU | telat 1–7 hari / exposure 75% | |
| Ambang TAHAN | telat 8–21 hari / lewat limit | |
| Ambang BLOKIR | telat > 21 hari / 2x ingkar janji | |
| Ambang HAPUS BUKU | telat > 60 hari | |

Katering itu harian — hutang menumpuk cepat, jadi ambangnya sengaja saya buat
rapat. Kalau menurut Bapak terlalu galak untuk mandor lama yang sudah terbukti,
naikkan angkanya; rekam jejak bayar memang seharusnya membeli kelonggaran.

---

## 7. Status implementasi

### Sudah jalan

**Tahap A — penyimpanan.** Tabel `credit_accounts` dan `credit_status_events`,
NIK/alamat/penjamin di master mandor, dan tiga akun COA baru: 2007 Deposit
Jaminan Mandor, 2008 Uang Muka Pelanggan, 5013 Beban Piutang Tak Tertagih
(hanya ditambahkan kalau kodenya belum ada). Migrasi `a0b1c2d3e4f5`, bisa
dibalik bersih (downgrade → upgrade sudah diuji di staging dan test_db).

**Tahap B — penilai.** `app/services/credit_control_service.py`. Menghitung
invoice belum lunas, umur tunggakan, janji meleset, dan order yang sudah jalan
tapi belum ditagih, dikurangi deposit yang dibaca dari buku besar.

**Tahap C — gerbang dan invoice.**
- Gerbang draft portal memakai penilai untuk pihak yang sudah disetel.
- Jalur order internal ADMIN sekarang punya gerbang — sebelumnya nol. Dipasang
  di service (`add_or_update_order_detail`, `add_increase_after_lock`), bukan
  di route, jadi tidak ada jalan pintas.
- Jatuh tempo invoice (periode dan per order) mengikuti termin: bayar di muka =
  hari itu; lalu termin akun kredit; lalu termin kontrak aktif ("net 30" = 30
  hari); terakhir 7 hari seperti dulu.
- Invoice mandor yang ditagih langsung ditujukan ke mandor itu sendiri
  (`bill_to_type` MANDOR, nama tertagih = mandor).

**Deposit dengan jurnal otomatis.** Jenis uang muka baru "Deposit Jaminan
Mandor": terima (Dr Kas/Bank, Cr 2007), potong ke invoice mandor yang sama
(Dr 2007, Cr 1004), kembalikan (Dr 2007, Cr Kas/Bank + kas keluar). Potong dan
kembalikan hanya OWNER; pengembalian ditolak selama mandor masih punya hutang;
pemotongan ditolak kalau piutang invoice-nya belum dijurnal (supaya 1004 tidak
minus).

**Tahap D — penyapu harian.** Tidak ada penjadwal di aplikasi, jadi permintaan
pertama pengguna internal tiap hari menjalankannya sekali per cabang (dikunci
advisory lock Postgres supaya tidak dobel). Cadangan: tombol "Periksa Kredit
Sekarang" dan perintah `flask credit-sweep` untuk penjadwal server. Status
hanya naik; tiap kenaikan tercatat dan dikirim ke OWNER dan ADMIN.

**Tahap E — layar.** Menu Keuangan → Kontrol Kredit: daftar urut risiko,
detail per mandor (rincian exposure, umur tunggakan, invoice, pembayaran, janji,
riwayat status), form setel kredit (OWNER), deposit, keputusan status dengan
"lepas sampai", dan hapus buku. Portal mandor yang ditagih langsung melihat
kartu kredit: sisa limit, jatuh tempo terdekat, dan peringatan telat.

**Hapus buku.** Hanya OWNER, hanya setelah tunggakan tertua lewat 60 hari.
Deposit dipotong dulu ke invoice tertua, sisanya Dr 5013 / Cr 1004, invoice
ditutup (CLOSED), mandor dinonaktifkan, NIK otomatis masuk daftar cekal. Satu
transaksi: gagal satu langkah, tidak ada yang berubah.

### Keputusan yang berubah saat implementasi

1. **Tangga eskalasi hanya ditegakkan untuk pihak yang sudah Bapak setel.**
   Pihak lain tetap dihitung angkanya sebagai informasi, tapi tidak pernah
   ditahan. Alasannya: jatuh tempo invoice lama di-hardcode 7 hari, jadi
   client kontrak "net 30" yang bayar tepat waktu tampak telat 23 hari dan
   akan terblokir padahal tidak melanggar apa pun.
2. **TAHAN di jalur internal = hanya OWNER yang bisa input order.** Order
   internal belum punya id sebelum dibuat, dan satu approval per mandor akan
   membuka semua ordernya selamanya. Jadi tindakan OWNER itu sendiri yang
   jadi keputusannya. BLOKIR menolak OWNER juga — Bapak harus sengaja
   menurunkan status akunnya dulu.
3. **Approval penahanan kredit di portal sekarang khusus OWNER.** Route
   approval terbuka untuk OWNER dan ADMIN, dan sejak lima role dilebur ke
   ADMIN, satu ADMIN bisa menyetujui penahanan yang diajukan ADMIN lain.
   **Ini juga berlaku untuk gerbang kontrak lama** (outstanding melebihi limit
   kontrak): dulu ADMIN lain bisa menyetujui, sekarang hanya OWNER.
4. **OWNER tunggal boleh memutuskan penahanan yang dia ajukan sendiri.**
   Aturan maker-checker melarang pengaju menyetujui dirinya sendiri; dengan
   satu OWNER, order yang dikonfirmasi OWNER sendiri akan tertahan selamanya.
   Pengecualian ini hanya untuk aksi khusus OWNER; aksi lain tidak berubah.
5. **Janji bayar dianggap ditepati kalau ada pembayaran berapa pun** di antara
   tanggal janji dicatat dan tanggal janjinya. Log penagihan tidak mencatat
   nominal yang dijanjikan, jadi sistem tidak bisa menuntut lebih. Janji yang
   sama (invoice dan tanggal sama) yang dicatat dua kali dihitung sekali —
   kalau tidak, admin yang rajin mencatat follow up justru membuat mandor
   langsung terblokir karena "ingkar dua kali".
6. **OWNER bisa "melepas sementara" sampai tanggal tertentu.** Gerbang selalu
   memakai status yang lebih ketat antara keputusan OWNER dan hitungan
   otomatis, jadi tanpa ini OWNER tidak bisa membuka mandor yang diblokir
   selama tunggakannya masih tua — walaupun sudah ada komitmen bayar
   tertulis. Setelah tanggal pelepasan lewat, hitungan otomatis berlaku lagi.
   Pelepasan tidak melewati syarat deposit.
7. **Kode akun beban di empat modul diselaraskan dengan COA database**
   (panjar mandor, biaya operasional, biaya transport, transaksi lapangan).
   Sebelumnya Gas masuk 5006 Beban Air, Perawatan masuk 5007 Beban Gas LPG,
   BBM masuk 5011 Beban Perawatan Kendaraan. Belum ada jurnal di akun-akun
   itu, jadi tidak ada yang perlu dikoreksi mundur. Kategori "Listrik & Air"
   dipecah dua karena COA memisahkannya; perawatan umum masuk 5009 Beban
   Lain-Lain karena COA belum punya akun perawatan umum.
8. **DP client dipindah dari 1008 (aset) ke 2008 Uang Muka Pelanggan
   (kewajiban).** Uang muka yang dibayar ke supplier dan panjar mandor tetap
   di 1008 — itu memang aset.
9. **Rekening bank di mesin uang muka mengikuti COA rekeningnya.** Dulu
   transfer ke rekening mana pun terjurnal ke 1002 Bank 1.

### Batasan yang perlu Bapak tahu

- **Order dari portal masuk dengan harga 0** sampai admin mengisinya. Nilai
  order yang diminta di gerbang portal adalah *estimasi* dari harga per porsi
  terakhir mandor itu (lokasi yang sama lebih dulu). Mandor baru tanpa riwayat
  harga → estimasi 0; gerbang tetap bekerja dari tunggakan dan umurnya.
- **Hutang warung belum masuk hitungan "sudah jalan tapi belum ditagih".**
  Warung ikut ditagih di invoice periode, jadi setelah invoice terbit sudah
  terhitung; yang belum terlihat hanya warung sebelum invoice terbit.
- **Tambahan setelah lock dengan harga berbeda** dihitung memakai harga
  awal detail, bukan harga revisinya.

- **Uang yang kembali setelah hapus buku** harus dicatat manual sebagai
  pendapatan lain-lain (4004); invoicenya sudah ditutup.

### Temuan tambahan yang sudah dibereskan (disetujui owner 2026-09-25)

- **Invoice mandor langsung tidak lagi meminta PIC client.** Kontak yang
  dicetak adalah mandor itu sendiri; invoice lain tetap wajib PIC resmi client.
- **Biaya operasional dan biaya transport** sekarang menjurnal transfer ke COA
  rekening yang dipilih (dulu selalu 1002 Bank 1). Ketiga mesin kas/bank
  (uang muka, biaya operasional, biaya transport) memakai satu resolver.
- **Pemakaian DP client ke invoice** sekarang juga ditolak kalau piutang
  invoice-nya belum dijurnal, sama seperti deposit — supaya 1004 tidak minus.

### Kegagalan test lama (bukan dari pekerjaan ini)

Tiga test sudah gagal di commit `90e4cb1` sebelum pekerjaan ini dimulai
(diperiksa dengan menjalankannya di worktree HEAD):
`test_db_commit_audit_tool` ×2 (angka acuan 102 commit, padahal HEAD sudah
103; dan ada panggilan bersarang lama di `portal_order_draft_service`), dan
`test_finance_portal_payment_proof_routes` (lampiran tidak tampil di antrean).
Pekerjaan ini menambah tepat dua batas transaksi dan tidak menambah commit
di route, fungsi dengan dua commit, atau kandidat P0.
