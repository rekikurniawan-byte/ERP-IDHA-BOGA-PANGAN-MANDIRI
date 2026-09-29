# Uji Coba Satu Cabang (Pilot) — ERP Idha Boga

Tujuan: membuktikan sistem benar dengan **data nyata** di satu cabang sebelum
dipakai semua cabang. Selama uji coba, pembukuan lama (Excel/buku) tetap
berjalan berdampingan sebagai pembanding.

Durasi yang disarankan: **2 minggu**, minimal satu siklus tagihan kontrak
(invoice periode) dan puluhan pesanan pelanggan umum.

Peran:

| Siapa | Tugas selama pilot |
|---|---|
| OWNER | Mengisi harga, ongkir, modul; memutuskan hal yang diloloskan; membaca rekonsiliasi mingguan |
| ADMIN | Input pesanan, konfirmasi pesanan portal, verifikasi bukti bayar, invoice |
| DAPUR / PENGANTAR | Produksi dan tanda terima pengiriman di sistem, bukan di kertas |
| Petugas IT | Server, penjadwal, backup, `ops-check` harian |

---

## 1. Sebelum hari pertama

**Server (petugas IT)** — ikuti `deployment/README_PRODUCTION_SERVER.md`:

- [ ] Database produksi **baru** (bukan salinan staging/demo).
- [ ] `ACCOUNTING_LEGACY_CUTOVER` **kosong** di `.env.production`.
- [ ] Migrasi dijalankan sebagai user aplikasi.
- [ ] `flask --app run bootstrap` → COA acuan, cabang pertama, OWNER pertama
      (database baru dari migrasi tidak punya akun, cabang, maupun user).
- [ ] Tiga timer systemd aktif: `systemctl list-timers 'idha-boga-*'`.
- [ ] Satu backup penuh berhasil: `flask --app run backup-full` → `PASS`.
- [ ] Pulihkan backup itu di server lain sekali (lihat `BACKUP_RESTORE_RECOVERY_SOP.md`).

**Data dasar (OWNER + ADMIN):**

- [ ] Pengaturan Perusahaan: identitas, **rekening pembayaran**, istilah
      (mis. PT / Mandor untuk cabang proyek), modul Warung & Hutang Pekerja.
- [ ] Pengaturan → Harga & Ongkir: harga standar per porsi, harga kontrak
      client yang berbeda, zona + tarif ongkir, gratis ongkir (kalau dipakai),
      minimal pesan pelanggan umum.
- [ ] Master: client (jalur Kontrak/Umum benar), sub client, lokasi (zona
      untuk pelanggan umum), pengantar, rekening bank.
- [ ] **PIC resmi** untuk setiap client kontrak (Master Client → PIC). Tanpa
      PIC, invoice kontrak tidak bisa disimpan.
- [ ] Kontrak aktif setiap PT (Pelanggan → Kontrak) dengan tanggal berakhir
      yang benar. Sistem mengingatkan mulai H-30 (mendesak H-7); setelah lewat
      tanggal, kontrak otomatis Kedaluwarsa, termin kembali 7 hari, dan pesanan
      baru PT itu perlu keputusan OWNER sampai diperpanjang.
- [ ] `PORTAL_ENABLED=1` di `.env.production` (bawaan template `0`: portal mati,
      pelanggan umum tidak bisa daftar/pesan).
- [ ] Akun pengguna: OWNER, ADMIN, DAPUR, PENGANTAR. Akun portal PT / Mandor
      dibuat OWNER di Pengaturan → User dan **dihubungkan** ke satu PT atau
      satu mandor (daftarnya di Portal → Pengaturan Akses). Pelanggan umum yang
      bersedia ikut mendaftar sendiri di portal.
- [ ] **Saldo awal** di satu tempat: Akuntansi → Saldo Awal. Isi tanggal mulai,
      kas dan tiap rekening bank, piutang lama per nota, hutang supplier lama,
      stok per barang dengan harga beli, aset dengan akumulasi penyusutan, dan
      hutang lain; modal pemilik dihitung otomatis. OWNER menekan **Kunci Saldo
      Awal** (dengan password): semua buku pembantu dan satu jurnal dibuat
      sekaligus dari angka yang sama. Salah isi sebelum ada transaksi → Buka
      Kembali; sesudahnya → koreksi dengan alasan. `ops-check` FAIL selama
      saldo awal belum dikunci.

**Gerbang mulai:** `flask --app run ops-check` harus **0 FAIL**, dan sebaiknya
0 WARN.

**Gladi dulu (disarankan):** `python tools/pilot_dry_run.py --db idha_boga_pilot`
menjalankan seluruh runbook ini dengan data demo di database gladi terpisah
dan mencocokkan setiap saldo dengan hitungan manual. Jalankan ulang setiap ada
perubahan besar sebelum dipakai.

## 2. Setiap hari

- [ ] Semua pesanan hari itu masuk sistem (portal atau input admin).
- [ ] Pesanan umum: bukti bayar diverifikasi Finance **dengan nominal yang
      benar-benar masuk rekening** sebelum dikonfirmasi.
- [ ] Order dikunci, produksi dan pengiriman dicatat; pengantar mengisi tanda
      terima di sistem (invoice pelanggan umum dibuat otomatis dari sini).
- [ ] Akuntansi → **Tutup Harian**: tidak ada status RISIKO.
- [ ] Kas fisik / mutasi bank hari itu = kas masuk di sistem (Finance → Buku Kas/Bank).
- [ ] Petugas IT: hasil `ops-check` 06:00 bersih (`systemctl --failed` kosong).

Catat setiap selisih atau kebingungan di satu lembar bersama:
tanggal, halaman, apa yang terjadi, siapa. Itu bahan perbaikan.

## 3. Setiap minggu

- [ ] `python tools/audit_financial_invariants.py --from-db` → baca
      `RINCIAN_AUDIT_REKONSILIASI_ERP_IDHA_BOGA.md`: tidak boleh ada pelanggaran.
- [ ] Akuntansi → **Cek Kesehatan Data**: tidak ada hutang pekerja/order yang
      belum masuk invoice tanpa alasan.
- [ ] Bandingkan dengan pembukuan lama: omzet, kas masuk, piutang per client.
      Dashboard OWNER → *Dua Jalur Transaksi* memberi angka per jalur.
- [ ] Neraca saldo seimbang (debit = kredit).
- [ ] Tinjau audit log: harga yang diubah OWNER, pesanan yang diloloskan
      sebelum lunas, pengembalian uang muka — semuanya punya alasan.

## 4. Lulus / berhenti

**Lulus** (boleh dipakai cabang lain) kalau selama 2 minggu:

- selisih kas, omzet, dan piutang dengan pembukuan lama **nol** (atau semua
  selisih terjelaskan sebagai kesalahan pembukuan lama);
- rekonsiliasi mingguan bersih dan neraca saldo seimbang;
- tidak ada hari dengan `ops-check` FAIL yang tidak ditindaklanjuti;
- tim tidak lagi butuh kertas untuk pesanan, produksi, dan pengiriman.

**Berhenti dan perbaiki dulu** kalau:

- ada selisih uang yang tidak bisa dijelaskan;
- jurnal tidak seimbang, atau invoice tanpa jurnal;
- pesanan terlewat tidak ditagih;
- backup gagal lebih dari sehari.

Pembukuan lama tetap menjadi acuan sampai pilot dinyatakan lulus.
