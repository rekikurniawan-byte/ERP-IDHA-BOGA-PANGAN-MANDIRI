# Batch 1I - Portal Authentication Mapping

Date: 2026-07-27

## Scope

Batch ini menjalankan foundation mapping portal eksternal secara additive di atas ERP existing.

Yang dikerjakan:

- menambahkan role portal pada user-management existing;
- menambahkan tabel `portal_user_mappings`;
- membuat resolver scope portal read-only berdasarkan mapping eksplisit;
- membuka route portal read-only untuk role portal eksternal;
- mengarahkan landing role portal ke `portal.dashboard` jika `PORTAL_ENABLED=True`;
- menambahkan regression test ownership agar data cabang lain tidak bocor.

Yang tidak dikerjakan:

- tidak membuat auth paralel;
- tidak membuat database baru;
- tidak membuat order portal;
- tidak menyentuh invoice, payment, journal, stock, HPP, closing;
- tidak membuka mutasi transaksi dari portal.

## Migration

Migration baru:

- `91a0a1b2c3d4_portal_user_mappings.py`

Sifat migration:

- additive;
- create table baru;
- tidak drop data;
- tidak mengubah migration lama;
- downgrade menghapus tabel mapping portal.

Database lokal aktif sudah dinaikkan dari `90a0a1b2c3d4` ke `91a0a1b2c3d4`.

## Role Mapping

Role baru:

- `PORTAL_CLIENT`
- `PORTAL_MANDOR`
- `PORTAL_DELEGATE`
- `PORTAL_CUSTOMER`

Role tersebut tetap memakai `users`, password hash, login, session, dan guard existing.

`PORTAL_CUSTOMER` masih role reservasi. Belum ada customer profile/table tersendiri, sehingga akses transaksi pelanggan umum tetap belum dibuka.

## Safety

Resolver scope hanya membaca:

- `users`;
- `portal_user_mappings`;
- `clients`;
- `client_pics`;
- `mandors`;
- `delivery_locations`.

Tidak ada `db.session.commit()` atau `db.session.rollback()` di route portal atau service mapping/access portal.

## Tests

Perintah yang dijalankan:

```text
python -m compileall app tests
.venv\Scripts\python.exe -m flask db upgrade  # test_db
.venv\Scripts\python.exe -m pytest tests\test_optimistic_locking_models.py tests\test_portal_foundation.py -q
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m flask db current
.venv\Scripts\python.exe -m flask db heads
.venv\Scripts\python.exe -m flask db upgrade
.venv\Scripts\python.exe -m flask db current
```

Hasil:

- compile: PASS;
- targeted portal/locking: `20 passed`;
- full regression: `299 passed`;
- active DB current: `91a0a1b2c3d4 (head)`.

## Rollback

Rollback code:

```text
git revert <batch-1i-commit>
```

Rollback database lokal:

```text
.venv\Scripts\python.exe -m flask db downgrade 90a0a1b2c3d4
```

Catatan: downgrade akan menghapus tabel `portal_user_mappings`.

## Status

READY_FOR_NEXT_BATCH
