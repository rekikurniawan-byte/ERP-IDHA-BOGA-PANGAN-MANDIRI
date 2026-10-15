# Tugas Gemini: Fase 9 — Surat kontrak otomatis

Jalankan SETELAH gladi pilot selesai. Baca dulu `RENCANA_PENGEMBANGAN_ERP.md` **bagian 1, Fase 3, Fase 7 (9.1–9.3), dan Fase 9 (bagian 11)** — itu spesifikasi lengkapnya (alur, pengaman, penandatangan, 17 pasal). Kerjakan, jangan tanya balik.

## Inti yang wajib benar
1. **Isi surat diambil dari data sistem**, bukan diketik: kontrak (`CustomerContract` + `ContractHoliday`), client/PIC, sub client & lokasi antar, harga per porsi + ongkir (`pricing_service`), jam lock, libur, siklus & tanggal potong, tempo (`due_days` — teks tempo DIBUAT dari angka ini, lihat Daftar tunggu "Dua tempat tempo"), pihak yang ditagih per sub client (`contract_rules_service.billing_mode_for`), ambang kredit (`credit_control_service.get_thresholds`), ta'zir nominal tetap → Dana Sosial, kelonggaran, ta'widh biaya riil, pengadilan. Angka di surat = angka yang dijalankan sistem.
2. **Pihak PT**: nama PT, NPWP & alamat dari pengaturan perusahaan (`company_settings_service`); penandatangan **Ida Royani — Direktur**, **Reki Kurniawan — Komisaris**.
3. **Pasal pajak**: buat partial `app/templates/contracts/_pasal_pajak.html` berisi teks sementara "Ketentuan pajak mengikuti peraturan yang berlaku dan pengaturan pajak perusahaan." — **jangan isi detail pajak**; Claude mengisinya di Fase 8.
4. **Snapshot terkunci**: saat "Buat Surat Kontrak", HTML hasil render disimpan (tabel baru, mis. `contract_documents`: contract_id, versi, jenis KONTRAK/ADENDUM, html_snapshot, dibuat_oleh/pada, status DRAFT/MENUNGGU_TTD/DITANDATANGANI, metode TTD, lampiran scan, waktu setuju portal). Template yang berubah kemudian **tidak** mengubah surat lama.
5. **Cetak A4**: kop PT, nomor kontrak, nomor halaman, kolom paraf tiap halaman (CSS print).
6. **Tanda tangan, pilih salah satu**: (a) basah di atas meterai → admin unggah scan (lewat `digital_attachment_service`, disajikan lewat route dengan cek akses), atau (b) **klik setuju + OTP email** di portal (pakai mekanisme email yang sudah ada untuk lupa password; WhatsApp OTP belum ada).
7. **Kontrak baru aktif setelah ditandatangani**: tombol aktifkan kontrak ditolak bila surat belum DITANDATANGANI; pesanan otomatis (`auto_order_service`) dan invoice otomatis hanya untuk kontrak aktif (sudah begitu — pastikan tidak bocor).
8. **Adendum**: perubahan harga/jam lock/pihak ditagih/ta'zir di tengah kontrak membuat dokumen ADENDUM (snapshot + TTD yang sama).
9. **Portal**: client (dan sub client terkait) bisa melihat & mengunduh surat/adendum miliknya.

## Teknis
- Migrasi baru: `down_revision` = head saat itu (cek `flask db heads` **tanpa** menjalankan upgrade); daftarkan di `tests/test_numeric_migration_coverage.py` & `tests/test_optimistic_locking_models.py` bila tabel baru punya `version_id`/Numeric.
- Aturan wajib: tidak commit/rollback di route (`atomic_business_action` di service), tidak `except` luas yang diam, `Decimal` untuk uang, semua query dibatasi `branch_id`, waktu pakai `today_wib()/now_wib()`.
- UI ikuti halaman kontrak yang sudah ada (`customer_success/contract_detail.html`): kelas `app-card`, `app-btn-primary/secondary`, `status-badge`, card tidak siku, tombol berjajar horizontal, rapi di HP 390px, tanpa dark mode.
- Test: `tests/test_contract_documents.py` — surat memuat angka dari kontrak (jam lock, tempo, ta'zir, pihak ditagih), snapshot tidak berubah setelah kontrak diubah, aktivasi ditolak sebelum TTD, adendum terbentuk, portal hanya melihat miliknya.

## Aturan keras
- **Dilarang** `git clean`, `git checkout -- .`, `git reset --hard`, menghapus file belum di-commit, `Stop-Process`.
- **Dilarang** `flask db upgrade/downgrade`, `flask jobs`, atau skrip apa pun ke DB dev `idha_boga_staging`. Jangan jalankan pytest.
- Jangan sentuh `.env`, `storage/`, `instance/`, `app.zip`, `tools/reset_staging_demo.py`, tabel `ml_*`/`research_dataset_*`.
- Jangan ubah logika uang/jurnal/kredit/pajak (`accounting_service`, `credit_*`, `sharia_credit_service`, `auto_invoice_service`, pembayaran) — hanya membaca datanya.
- Tidak `git add -A`, tidak commit, tidak push.

## Laporan akhir (singkat)
File diubah/baru, migrasi baru (revision id), lalu command untuk pemilik:
```
venv\Scripts\python.exe -m pytest -q -p no:warnings tests/test_contract_documents.py
venv\Scripts\python.exe -m pytest -q -p no:warnings
venv\Scripts\python.exe -m flask db upgrade
```
