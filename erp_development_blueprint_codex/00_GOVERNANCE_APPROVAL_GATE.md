# 00 — Governance and Approval Gate

## Prinsip tertinggi
1. ERP tidak dibangun ulang.
2. Fitur baru harus memanfaatkan model, service, route, permission, dan database existing sejauh memungkinkan.
3. Jangan membuat fungsi tumpang tindih.
4. Jangan menghapus kompatibilitas data lama.
5. Jangan mengubah histori transaksi yang telah disahkan.
6. Setiap batch harus kecil, dapat diuji, dan dapat di-rollback.
7. Ketidakjelasan dianggap `APPROVAL REQUIRED`.

## Boleh tanpa persetujuan tambahan
- bug fix;
- regression test;
- perbaikan import/helper/template/JavaScript;
- refactor behavior-preserving;
- memindahkan business rule dari route ke service;
- logging dan observability;
- validasi tambahan yang tidak mengubah aturan bisnis;
- dokumentasi;
- feature flag default-off;
- optimasi yang terbukti tanpa mengubah hasil.

## Wajib persetujuan pengguna
Codex wajib berhenti sebelum:
- mengubah tabel/kolom/tipe data existing;
- menghapus atau rename field;
- mengubah relasi model;
- mengubah lifecycle order, invoice, payment, journal, stock, closing, atau contract;
- mengubah aturan kredit, limit, pihak ditagih, atau cicilan;
- mengubah role/permission;
- mengubah numbering dokumen;
- mengubah rumus saldo, hutang, piutang, HPP, cash, journal, atau laporan;
- menambah payment gateway/webhook;
- menambah auto-approval, auto-posting, atau auto-settlement;
- melakukan data migration massal;
- mengganti PostgreSQL, Flask, autentikasi, atau deployment topology;
- menghapus route/model/service/migration/template existing;
- melakukan perubahan yang berpotensi mengubah laporan keuangan.

## Dilarang
- rebuild total;
- database portal terpisah;
- edit migration lama yang sudah pernah dijalankan;
- hard delete invoice terbit, payment, contract, atau transaksi historis;
- menggabungkan invoice antar-periode;
- memberi kredit default kepada pelanggan umum;
- memproses order pelanggan umum sebelum prepayment terverifikasi;
- membuat chat internal;
- membuat navigasi sendiri;
- `except Exception: pass`;
- menurunkan test agar build lulus.

## Format permintaan persetujuan
```text
APPROVAL REQUIRED
Perubahan:
Alasan:
Modul/tabel terdampak:
Risiko:
Alternatif paling aman:
Dampak jika tidak dilakukan:
Rencana rollback:
Test yang akan ditambahkan:
```

## Bukti setiap batch
- file dan fungsi diubah;
- perilaku sebelum/sesudah;
- schema impact;
- targeted test;
- full test;
- route/template impact;
- risiko tersisa;
- status: VERIFIED / PARTIAL / BLOCKED / APPROVAL REQUIRED.
