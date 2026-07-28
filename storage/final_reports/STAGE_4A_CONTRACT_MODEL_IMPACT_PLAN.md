# Stage 4A - Contract Model Impact Plan

STATUS: COMPLETED

Tanggal: 2026-07-28

## Scope

Stage 4A menganalisis kebutuhan contract, complaint, dan document archive berdasarkan blueprint.

## Existing Findings

- Belum ada model kontrak pelanggan/PT umum.
- Model `AssetFinancingContract` sudah ada, tetapi hanya untuk cicilan aset tetap dan tidak boleh dipakai sebagai contract customer.
- `DigitalAttachment` sudah ada dan dapat dipakai sebagai fondasi arsip dokumen private tanpa membuat file system paralel.
- Belum ada complaint lifecycle model.
- Belum ada return/correction workflow model.

## Blueprint Requirements

Contract:

- PT/client/PIC;
- nomor kontrak;
- mulai/selesai;
- termin;
- limit;
- dokumen;
- status;
- versi;
- tidak dihapus;
- renewal membuat versi/contract baru;
- contract lama expired;
- perubahan limit/termin diaudit.

Complaint:

- kategori;
- status `OPEN -> IN_PROGRESS -> RESOLVED -> CLOSED`;
- relasi order/delivery/invoice bila ada;
- tidak menimpa histori transaksi.

Document archive:

- contract;
- invoice;
- payment proof;
- delivery proof;
- handover proof;
- complaint/return;
- version history;
- private access;
- uploader/timestamp.

## Safe Implementation Order

1. 4B - Customer contract lifecycle foundation.
2. 4C - Contract document archive using `DigitalAttachment`.
3. 4D - Contract expiry notification read model.
4. 4E - Complaint workflow foundation.
5. 4F - Return/correction impact plan and foundation.
6. 4G - Document archive access control recap.

## Sensitive Changes

4B requires a new table and migration. It is additive only and must not alter invoice/payment/journal/stock.

## Approval

User has approved roadmap execution. The implementation must remain incremental and reversible per batch.

## Rollback

Each batch must be committed and tagged separately. Migration rollback must drop only tables introduced by that batch.

## Next Step

Batch 4B - Customer contract lifecycle foundation.
