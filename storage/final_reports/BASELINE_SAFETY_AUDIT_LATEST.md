# Baseline Safety Audit ERP PT Idha Boga Pangan Mandiri

Timestamp: 20260727_170723
Status: READY_FOR_STAGE_1

## Scope
- Read-only Flask startup audit.
- Route map snapshot.
- Template parse and literal url_for endpoint validation.
- Safe GET smoke for non-parameterized, non-download/export/API routes.
- Database identity and user safety check.
- Route transaction boundary scan.

## Database
- URL: `postgresql+psycopg://idha_boga_user:***@localhost:5432/idha_boga_staging`
- Tabel: 113
- Alembic revision: `90a0a1b2c3d4`
- Alembic heads: `90a0a1b2c3d4`
- Current is head: True
- Users: 8
- Active OWNER/ADMIN: 2
- Orphan users: 0
- QA marker hits: 0

## Route Map
- Total route: 344
- Duplicate rule/method: 0
- Safe GET candidates: 149
- Safe GET executed: 149
- Smoke failures: 0

## Template And url_for
- Total template: 215
- Parsed: 215
- Template parse errors: 0
- Literal endpoint references: 331
- Missing endpoint references: 0
- Missing template file references: 0

## Transaction Boundary Static Scan
- Route commit: 0
- Route rollback: 0
- Service commit: 102
- Service rollback: 45

## Smoke Failures
- Tidak ada status 500/exception/error marker pada safe GET smoke.

## Missing Endpoint References
- Tidak ada literal endpoint hilang yang terdeteksi.

## Files
- Route map JSON: `C:\Users\Acer\Downloads\ERP_PT_IDHA_BOGA_PANGAN_MANDIRI\storage\final_reports\baseline_route_map_20260727_170723.json`
- Template audit JSON: `C:\Users\Acer\Downloads\ERP_PT_IDHA_BOGA_PANGAN_MANDIRI\storage\final_reports\baseline_template_audit_20260727_170723.json`
- Runtime smoke JSON: `C:\Users\Acer\Downloads\ERP_PT_IDHA_BOGA_PANGAN_MANDIRI\storage\final_reports\baseline_runtime_smoke_20260727_170723.json`
