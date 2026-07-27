# 06 — Security, Audit, Approval, and Data Integrity

## Approval engine
Satu mekanisme approval bersama untuk order, kredit, perubahan/pembatalan order, closing, adjustment invoice, return, dan contract. Jangan membuat approval terpisah di tiap modul.

Mapping Supervisor/Manager/Direktur ke role existing wajib dianalisis; perubahan role perlu persetujuan.

## Audit trail
Minimal menyimpan:
- user dan role;
- aktivitas/modul/record;
- before/after;
- waktu;
- IP/user agent bila tersedia;
- request/correlation ID.

Audit trail tidak boleh dihapus oleh user biasa.

## Security baseline
- password hashing;
- session timeout;
- logout POST;
- CSRF;
- secure cookie dan HTTPS production;
- generic login error;
- least privilege;
- ownership guard;
- upload validation;
- file size limit;
- dokumen private;
- shared rate-limit storage production;
- no traceback production.

## Error handling
- logger.exception untuk error tak terduga;
- tidak ada `except Exception: pass`;
- tidak boleh mengubah kegagalan menjadi status sukses/aman palsu;
- transaksi gagal wajib rollback.

## Data integrity
- order tidak dihapus setelah produksi;
- invoice terbit tidak dihapus/diubah;
- payment hanya reversal;
- contract dinonaktifkan/versi baru, bukan delete;
- worker dengan transaksi tidak dapat dihapus;
- foreign key valid;
- nomor dokumen immutable;
- historical price tetap;
- transaksi kritis atomik dan idempotent.

## Backup
Backup harian/mingguan/bulanan harus dilengkapi restore drill. Backup belum dianggap valid sebelum restore berhasil di mesin/database lain.
