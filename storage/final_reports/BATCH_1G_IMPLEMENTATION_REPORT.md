# BATCH 1G IMPLEMENTATION REPORT

ERP PT Idha Boga Pangan Mandiri

Status: VERIFIED - APPROVAL PACKAGE ONLY

Tanggal: 2026-07-27

## Scope

Batch 1G membuat paket approval untuk desain mapping akun eksternal portal.

Yang dibuat:
- `storage/final_reports/BATCH_1G_EXTERNAL_PORTAL_MAPPING_APPROVAL_PACKAGE.md`
- Analisis role existing.
- Analisis ownership source existing.
- Opsi desain mapping eksternal.
- Rekomendasi Option A mapping table additive.
- Acceptance criteria untuk batch implementasi setelah approval.
- Format keputusan owner.

Yang tidak dilakukan:
- Tidak ada kode aplikasi.
- Tidak ada migration.
- Tidak ada role baru.
- Tidak ada permission baru.
- Tidak ada mapping user eksternal.
- Tidak ada route/template/service baru.
- Tidak ada perubahan order, invoice, payment, journal, stock, HPP, receivable/payable, atau closing.

## Evidence Existing

Role existing di `app/services/user_management_service.py`:
- `OWNER`
- `ADMIN`
- `FINANCE`
- `ACCOUNTING`
- `LOGISTICS`
- `HR`
- `DAPUR`
- `PENGANTAR`

Model `User` existing:
- `branch_id`
- `full_name`
- `username`
- `password_hash`
- `role`
- `is_active`

Belum ada:
- `client_id` pada user;
- `mandor_id` pada user;
- `client_pic_id` pada user;
- portal principal type;
- mapping table user-to-client/mandor/PIC.

## Database Change

Tidak ada.

## Sensitive Change

Tidak ada perubahan sensitif yang dijalankan.

Isi dokumen menyatakan batch berikutnya akan menjadi `APPROVAL_REQUIRED` jika menyentuh:
- role;
- permission;
- schema;
- migration;
- mapping eksternal;
- order/invoice/payment.

## Verification

Karena Batch 1G hanya dokumen, tidak ada route/template Python baru.

Baseline sebelum dokumen:
- Full pytest terakhir dari Batch 1F: `295 passed, 11 warnings`.
- Baseline audit terakhir: `READY_FOR_STAGE_1`.

## Rollback

Rollback Batch 1G:

```bash
git revert <batch-1g-commit>
```

Tidak ada rollback database.

## Next Step

Menunggu keputusan owner:

```text
APPROVE_BATCH_1H_OPTION_A_MAPPING_READ_ONLY
```

atau

```text
DEFER_EXTERNAL_MAPPING_KEEP_INTERNAL_PREVIEW_ONLY
```
