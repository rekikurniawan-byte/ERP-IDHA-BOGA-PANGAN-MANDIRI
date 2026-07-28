# Batch 3F - Cash Confirmation Impact Plan

STATUS: APPROVED_BY_ROADMAP

SCOPE:
- Tambah service read-only cash confirmation untuk customer payment.
- Verifikasi payment memiliki cash-bank ledger.
- Verifikasi ledger amount/type/account sesuai payment.
- Deteksi duplicate ledger untuk payment reference.
- Tidak membuat ledger baru.
- Tidak mengubah payment/invoice/journal/cash-bank.
- Tidak membuat route/template.
- Tidak membuat migration.

BLUEPRINT REFERENCE:
- `erp_development_blueprint_codex/roadmap.md` Stage 3F.
- `erp_development_blueprint_codex/04_PAYMENT_CREDIT_INVOICE_CLOSING.md`.

TARGETED TEST:
- Payment transfer dengan ledger valid PASS.
- Payment cash dengan ledger valid PASS.
- Missing ledger FAIL.
- Duplicate ledger FAIL.
- Amount mismatch FAIL.

FULL TEST:
- `python -m compileall app tests`
- targeted pytest 3F
- `python -m pytest -q`

ROLLBACK:
- `git revert <batch-3f-commit>`

NEXT SAFE STEP:
- Stage 3 summary and gate report.
