# Batch 3B - Payment Proof Upload Service

Status: COMPLETED

Tanggal: 2026-07-28

## Scope

Batch ini menambahkan service upload bukti pembayaran portal secara additive:

- upload file ke `DigitalAttachment` existing;
- attachment private di folder upload existing;
- attachment type `PAYMENT_PROOF_PENDING`;
- ownership invoice memakai instruksi pembayaran Stage 3A;
- tidak membuat `Payment`;
- tidak mengubah allocation;
- tidak mengubah invoice paid/remaining/status;
- tidak membuat journal;
- tidak membuat cash/bank transaction;
- tidak membuat route/template;
- tidak membuat migration.

## Perubahan

- `app/services/portal_payment_proof_service.py`
  - Menambahkan `upload_portal_payment_proof()`.
  - Menambahkan `list_pending_portal_payment_proofs()` untuk batch finance verification queue berikutnya.
  - Menggunakan `atomic_business_action()` saat commit nyata agar file attachment bisa dibersihkan saat rollback.

- `app/services/digital_attachment_service.py`
  - Menambahkan `stage_digital_attachment()` sebagai helper non-commit.
  - Mempertahankan `save_digital_attachment()` sebagai compatibility wrapper untuk caller existing.
  - Menambahkan cleanup dan rollback eksplisit bila commit wrapper lama gagal.

- `tests/test_portal_payment_proof_service.py`
  - Coverage upload bukti milik user.
  - Coverage invoice di luar ownership.
  - Coverage invoice cancelled.
  - Coverage role customer yang belum boleh upload.
  - Coverage file payload berbahaya.

- `tests/test_db_commit_audit_tool.py`
  - Baseline rollback audit naik dari 48 ke 49 karena wrapper attachment sekarang punya rollback eksplisit saat commit gagal.

## Guard

- Route commit/rollback tetap 0.
- Service Batch 3B tidak membuat `Payment`.
- Service Batch 3B tidak mengubah `invoice.paid_amount`.
- Service Batch 3B tidak mengubah `invoice.remaining_amount`.
- Service Batch 3B tidak mengubah `invoice.status`.

## Verifikasi

```text
python -m compileall app tests
PASS

python -m pytest tests/test_portal_payment_proof_service.py tests/test_db_commit_audit_tool.py -q
7 passed, 13 warnings

python -m pytest -q
338 passed, 57 warnings

rg "db\.session\.(commit|rollback)\(" app\routes -n
NO_ROUTE_COMMIT_OR_ROLLBACK

rg "Payment\(|invoice\.(paid_amount|remaining_amount|status)\s*=" app\services\portal_payment_proof_service.py -n
NO_PAYMENT_OR_INVOICE_MUTATION_IN_3B_SERVICE
```

## Risiko Tersisa

- Belum ada halaman/form portal untuk upload bukti. Itu masuk batch UI berikutnya.
- Belum ada queue verifikasi finance. Itu masuk Batch 3C.
- Belum ada creation `Payment` dari bukti terverifikasi. Itu masuk Batch 3D dan wajib memakai service existing.
- Payment gateway/webhook tetap deferred dan `APPROVAL REQUIRED`.

## Putusan

Batch 3B selesai sebagai service-level foundation. Status roadmap: lanjut ke Batch 3C - Finance verification queue.
