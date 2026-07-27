# 08 — Codex Execution Protocol

## Instruksi utama
Audit implementation existing sebelum coding. Jangan berasumsi fitur belum ada. Kembangkan secara incremental dan konservatif.

## Workflow wajib
### 1. Discover
Cari route, service, model, template, JS, test, migration, permission, business rule, dan data compatibility.

### 2. Classify
Klasifikasikan: bug fix, additive feature, behavior-preserving refactor, schema change, business-rule change, atau sensitive change.

### 3. Impact plan
Sebelum edit, tulis:
- current behavior;
- desired behavior;
- file terdampak;
- schema impact;
- compatibility;
- tests;
- rollback;
- approval status.

### 4. Implement
- gunakan service existing;
- jangan duplikasi;
- satu transaction boundary;
- no commit/rollback di route;
- no silent exception;
- no hard delete transaksi;
- no direct history mutation;
- feature flag untuk rollout berisiko;
- pertahankan route/API lama bila masih dipakai.

### 5. Verify
Minimal:
```bash
python -m compileall app tests
python -m pytest -q -k "<target>"
python -m pytest -q
```
Tambahkan route smoke, template render, role matrix, PostgreSQL integration, rollback, idempotency, failure injection, migration, dan UAT sesuai scope.

### 6. Regression rule
Setiap bug wajib menghasilkan test. Termasuk NameError helper, invalid url_for, template `true`, missing role guard, duplicate submit, partial commit, dan stale field name.

### 7. Stop condition
Berhenti dan minta persetujuan jika:
- business rule ambigu;
- dokumen bertentangan;
- schema/data migration diperlukan;
- role mapping tidak jelas;
- invoice/payment/journal/stock/report berubah;
- rollback tidak jelas;
- test DB tidak tersedia;
- perubahan sensitif.

## Format laporan
```text
STATUS:
SCOPE:
FILES CHANGED:
BEHAVIOR BEFORE:
BEHAVIOR AFTER:
DATABASE CHANGE:
SENSITIVE CHANGE:
TARGETED TEST:
FULL TEST:
ROUTE/TEMPLATE COVERAGE:
KNOWN LIMITATIONS:
ROLLBACK:
NEXT SAFE STEP:
```

## Larangan klaim
Jangan menyatakan “tidak ada error”, “semua aman”, atau “production ready” hanya karena pytest lulus. Gunakan VERIFIED, PARTIAL, NOT VERIFIED, BLOCKED, atau APPROVAL REQUIRED.
