# Batch 1K - Portal Location Read-only

Date: 2026-07-27

## Scope

Batch ini membuka lokasi portal secara read-only memakai `DeliveryLocation` existing.

Yang dikerjakan:

- menambahkan service `build_portal_location_directory`;
- menambahkan route `GET /portal/locations`;
- menambahkan template `portal/locations.html`;
- menambahkan link Lokasi di dashboard portal dan sidebar internal;
- menambahkan regression test untuk branch scope admin, mandor scope, dan delegate location scope.

Yang tidak dikerjakan:

- tidak menambah kolom alamat/lat-long/patokan/kontak;
- tidak membuat create/edit/delete lokasi dari portal;
- tidak menyentuh order, delivery, invoice, payment, journal, stock, atau closing;
- tidak ada migration.

## Compatibility Decision

`DeliveryLocation` existing masih dipakai apa adanya. Tambahan field alamat/koordinat/patokan/kontak ditunda sampai batch khusus karena menyentuh schema/master data.

## Tests

Perintah yang dijalankan:

```text
python -m compileall app tests
.venv\Scripts\python.exe -m pytest tests\test_portal_foundation.py -q
.venv\Scripts\python.exe -m pytest -q
```

Hasil:

- compile: PASS;
- targeted portal: `19 passed`;
- full regression: `301 passed`.

## Rollback

Rollback code:

```text
git revert <batch-1k-commit>
```

Tidak ada rollback database karena tidak ada migration.

## Status

READY_FOR_NEXT_BATCH
