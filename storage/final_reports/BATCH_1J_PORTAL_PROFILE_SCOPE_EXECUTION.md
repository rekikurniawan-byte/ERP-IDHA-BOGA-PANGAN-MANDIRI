# Batch 1J - Portal Profile dan Scope Resolver Final

Date: 2026-07-27

## Scope

Batch ini memperkuat resolver ownership portal dan menambahkan halaman profil scope portal read-only.

Yang dikerjakan:

- mempersempit resolver `PORTAL_MANDOR` agar hanya melihat mandor yang dimapping;
- mempersempit resolver `PORTAL_DELEGATE` agar hanya melihat objek yang dimapping;
- mempertahankan `PORTAL_CLIENT` sebagai client/PT scope yang dapat melihat mandor dan lokasi di bawah client tersebut;
- menambahkan route `GET /portal/profile`;
- menambahkan template `portal/profile.html`;
- menambahkan test anti data-leak untuk sibling mandor/lokasi dan client lain.

Yang tidak dikerjakan:

- tidak membuka draft order;
- tidak membuat pembayaran;
- tidak menyentuh invoice/journal/stock;
- tidak membuat mutasi dari portal;
- tidak menambahkan schema baru.

## Business Rule Scope

- `PORTAL_CLIENT`: melihat client miliknya dan mandor/lokasi di bawah client tersebut.
- `PORTAL_MANDOR`: melihat client identity, mandor miliknya, dan lokasi mandor tersebut.
- `PORTAL_DELEGATE`: melihat hanya client/mandor/lokasi yang eksplisit dimapping.
- `PORTAL_CUSTOMER`: tetap pending sampai customer profile/ownership final disetujui di batch berikutnya.

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
git revert <batch-1j-commit>
```

Tidak ada migration pada batch ini.

## Status

READY_FOR_NEXT_BATCH
