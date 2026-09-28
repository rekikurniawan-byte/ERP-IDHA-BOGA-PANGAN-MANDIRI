# Gladi Pilot Satu Cabang — 28-09-2026

Runbook `PILOT_SATU_CABANG.md` dijalankan penuh dengan **data demo** di
database terpisah (`idha_boga_pilot`), dari database kosong sampai invoice
lunas dan pemeriksaan mingguan. Belum ada server dan belum ada data nyata, jadi
bagian yang butuh server dilewati (lihat bagian terakhir).

Semua langkah dijalankan lewat halaman aslinya dengan login sesuai peran
(OWNER, ADMIN, DAPUR, PENGANTAR, pelanggan portal) — bukan jalan pintas ke
database. Alatnya: `tools/pilot_dry_run.py`, bisa diulang kapan saja.

## Hasil akhir

| | |
|---|---|
| Langkah dijalankan | **114 / 114 OK** (termasuk 10 percobaan salah yang memang harus ditolak sistem) |
| Pemeriksaan | **14 / 15 lulus** — yang gagal: akun portal client kontrak (lihat Keputusan 1) |
| Saldo buku besar | **11 akun cocok sampai rupiah** dengan hitungan manual |
| Neraca saldo | BALANCE |
| Audit rekonsiliasi mingguan | 0 pelanggaran |
| Cek Kesehatan Data / Tutup Harian (3 hari) | 0 RISIKO |
| `ops-check` | 9 cek, 0 FAIL, 0 WARN |
| Backup penuh | PASS (dibuat dan diverifikasi) |

## Skenario yang dijalankan

- **OWNER**: identitas perusahaan, rekening, istilah PT/Mandor, modul Warung &
  Hutang Pekerja, harga standar Rp18.000, harga kontrak PT Maju Rp16.000,
  minimal 10 porsi, zona Dekat Rp10.000 / Jauh Rp25.000, ongkir kontrak PT
  Sinar Rp15.000/trip, gratis ongkir ≥100 porsi, saldo awal.
- **Master**: 2 client kontrak + PIC, 3 mandor, 3 lokasi, 2 pengantar,
  2 rekening; 3 pelanggan umum mendaftar sendiri di portal.
- **2 hari operasional**: 5 order kontrak, 6 pesanan portal pelanggan umum.
  Bayar di muka lewat bukti transfer → Finance verifikasi dan catat nominal →
  admin konfirmasi. Termasuk: bayar kurang (ditolak), bayar dicicil sampai
  lunas, pesanan yang sudah dibayar lalu ditolak (uang dikembalikan OWNER),
  pesanan yang diloloskan OWNER sebelum lunas (dengan alasan, lalu dibayar
  tunai saat antar), dan satu pengiriman kurang 2 porsi.
- Kunci order → produksi dapur → pengiriman → tanda terima → invoice pelanggan
  umum terbit otomatis dan lunas dari uang muka.
- Invoice periode 3 mandor kontrak, bayar lunas / sebagian, percobaan bayar
  lebih (ditolak), percobaan menagih pelanggan umum dua kali (ditolak).

## Bug yang ditemukan dan sudah diperbaiki

Semua di bawah ini membuat pilot **tidak bisa jalan** atau **laporannya salah**,
dan sekarang dikunci dengan tes otomatis.

1. **Database baru kosong total** — tidak ada COA, cabang, maupun user; tidak
   ada yang bisa login. Baru: `flask --app run bootstrap`.
2. **Tambah Mandor dan tambah Pengantar crash.** Sisa pemecahan file rute:
   fungsi pembantu tidak ikut terbawa. Scan seluruh modul menemukan masalah yang
   sama di **9 file lain**; halaman ini gagal begitu disimpan:
   - Finance: input uang muka/DP, **pengembalian uang muka pelanggan** (nominal
     selalu "tidak valid"), **input biaya transport**, **input biaya
     operasional**, saldo awal / transfer / penyesuaian kas-bank, bayar hutang
     supplier, input transaksi tagihan manual, detail invoice tagihan manual;
   - Akuntansi: **Tutup Periode**, jurnal akrual hutang warung, tombol
     "generate jurnal" (invoice periode, pembayaran, HPP produksi, pembelian,
     koreksi pembayaran warung).

   Sekarang ada tes yang memeriksa seluruh modul supaya tidak terulang.
3. **Kunci order crash** di database baru (nominal harga tidak bisa disimpan ke
   snapshot). Tanpa kunci order, produksi dan pengiriman tidak bisa jalan.
4. **Pesanan pelanggan umum yang sudah ditagih tampil "Belum masuk invoice"**
   di Cek Kesehatan Data, dan invoice yang lunas dari uang muka tampil
   **RISIKO**. Penyebab: dua nama berbeda untuk sumber item invoice, dan
   pelunasan dari uang muka tidak dihitung. Laporan mingguan akan selalu merah.
5. **Audit rekonsiliasi mingguan** melaporkan 5 pelanggaran palsu untuk hal
   yang sama.
6. **Alasan tidak masuk audit log** untuk perubahan harga, ongkir, dan
   pengembalian uang muka — padahal runbook meminta OWNER meninjaunya.
7. **Simpan ulang harga yang sama menumpuk baris harga** dan jejak audit palsu.
   Sekarang ditolak dengan pesan "tidak ada yang diubah".
8. Pesan penolakan saat **kurang bayar** keliru ("menunggu Finance"); sekarang
   "Pembayaran kurang Rp …".

Tambahan `ops-check` dari temuan gladi:

- **PIC client kontrak** — tanpa PIC, invoice kontrak tidak bisa disimpan
  (admin baru tahu saat menagih).
- **Buku Kas/Bank vs jurnal** — saldo awal lewat Akuntansi hanya membuat
  jurnal, lewat Finance hanya mengisi buku kas/bank. Kalau hanya satu diisi,
  cek kas harian membandingkan angka yang salah (di gladi selisihnya Rp30 juta).

## Keputusan yang perlu OWNER

1. **Akun portal untuk client kontrak.** *Keputusan owner: dibuat sesuai
   rekomendasi — sudah dikerjakan.* OWNER menghubungkan akun di form User
   (satu akun = satu PT atau satu mandor); Portal PT memantau, memesan hanya
   lewat Order langsung; Portal Mandor memesan, admin tetap mengonfirmasi. Pelanggan umum otomatis terhubung saat
   mendaftar, tapi akun portal PT/mandor tidak bisa dihubungkan ke client-nya —
   belum ada halamannya. Perlu dibuat halaman "hubungkan akun portal ke PT /
   mandor / lokasi" (alurnya akan dijelaskan dulu sebelum dibangun). Sementara
   itu pesanan kontrak diinput admin.
2. **Pengiriman kurang yang tidak diganti.** *Keputusan owner: tagih yang
   diterima, kelebihan uang muka dikembalikan — sudah dikerjakan.* Mandor Joko pesan 25, diterima 23.
   Invoice periode tetap menagih **25**. Yang benar: tagih yang dipesan, atau
   yang diterima?
3. **Pilih pengantar per pengiriman.** Sekarang semua pengiriman otomatis
   diberikan ke pengantar aktif pertama. *Keputusan owner 28-09-2026: tetap
   otomatis.*
4. Kecil: di portal pelanggan umum masih tampil istilah cabang ("PT Ibu Rina",
   "Mandor Ibu Rina"). *Keputusan owner: disembunyikan — sudah dikerjakan.*

## Yang belum bisa digladikan (butuh server / data nyata)

- Timer systemd (`credit-sweep`, `backup`, `ops-check` 06:00), `systemctl --failed`.
- Memulihkan backup di **server lain** (backup sudah dibuat dan diverifikasi di laptop).
- Dua minggu data nyata dan perbandingan dengan pembukuan lama.
- Kas fisik / mutasi bank sungguhan.

## Mengulang gladi

```bash
createdb -O idha_boga_user idha_boga_pilot
DATABASE_URL=<url .../idha_boga_pilot> flask --app run db upgrade
DATABASE_URL=<...> BOOTSTRAP_OWNER_PASSWORD='PilotOwner#2026' flask --app run bootstrap \
    --branch-code PILOT --branch-name "Cabang Pilot" --owner-username owner.pilot --owner-name "Owner Pilot"
python tools/pilot_dry_run.py --db idha_boga_pilot --backup   # PG_DUMP_PATH kalau pg_dump tidak di PATH
```

Alat hanya mau jalan di database yang namanya mengandung "pilot" atau "gladi",
dan menolak database yang sudah pernah dipakai gladi. Hasil per langkah ditulis
ke `instance/gladi_pilot_hasil.md`.

## Gladi ulang setelah keputusan owner (28-09-2026 sore)

Skenario ditambah: akun Portal PT dan Portal Mandor dihubungkan lewat form
User, Mandor Budi memesan siang dan malam lewat portal, kurang kirim di
kontrak (Gudang Cikarang 23/25) dan di pelanggan umum (Kantor Notaris 19/20)
dengan sisa uang muka Rp18.000 dikembalikan OWNER.

Hasil: **120 / 120 langkah OK, 17 / 17 pemeriksaan lulus**, saldo semua akun
cocok dengan hitungan manual, `ops-check` 10 cek 0 FAIL 0 WARN.

Temuan baru dan sudah diperbaiki:

- **Pesanan portal siang + malam untuk lokasi yang sama tidak bisa
  dikonfirmasi** — sesi kedua ditolak "detail sudah ada". Sekarang digabung ke
  baris order yang sama; yang ditolak hanya pesanan ganda sesi yang sama atau
  harga berbeda.
- `PORTAL_ENABLED` bawaan template produksi `0` — portal mati. Masuk runbook
  dan `ops-check` (juga memeriksa akun portal yang belum terhubung).
- Halaman "Pengaturan Akses Portal" hanya berisi hitungan dan nama tabel;
  sekarang daftar akun portal dan ke mana masing-masing terhubung.
