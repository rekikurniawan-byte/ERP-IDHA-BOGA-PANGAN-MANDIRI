# Preflight PostgreSQL UAT ERP Idha Boga

Tool ini read-only secara default. Gunakan `--from-db` hanya untuk database staging/snapshot yang memang akan diuji.

## Ringkasan

| Metrik | Nilai |
| --- | --- |
| Status | PASS |
| Total check | 15 |
| Critical failed | 0 |

## Detail

| Status | Check | Critical | Pesan |
| --- | --- | --- | --- |
| PASS | DATABASE_URL | ya | postgresql+psycopg://idha_boga_user:***@localhost:5432/idha_boga_staging |
| PASS | tool:psql | ya | C:\laragon\bin\postgresql\postgresql-11.0-1\bin\psql.exe |
| PASS | tool:pg_dump | ya | C:\laragon\bin\postgresql\postgresql-11.0-1\bin\pg_dump.exe |
| PASS | tool:pg_restore | ya | C:\laragon\bin\postgresql\postgresql-11.0-1\bin\pg_restore.exe |
| PASS | tool:createdb | ya | C:\laragon\bin\postgresql\postgresql-11.0-1\bin\createdb.exe |
| PASS | tool:dropdb | ya | C:\laragon\bin\postgresql\postgresql-11.0-1\bin\dropdb.exe |
| PASS | migration:total | ya | 45 migration file. |
| PASS | migration:head | ya | 88a0a1b2c3d4 |
| PASS | migration:duplicate_revision | ya | Tidak ada duplicate revision. |
| PASS | migration:missing_parent | ya | Tidak ada missing parent. |
| PASS | model:float_inventory | ya | Tidak ada db.Float di app/models. |
| PASS | model:raw_sql_dynamic | ya | Tidak ada raw SQL dinamis terdeteksi. |
| SKIP | restore:pg_restore_list | tidak | Tidak ada dump path. Lewati restore dry-run. |
| PASS | db:reachable | ya | PostgreSQL reachable. |
| PASS | db:migration_current | ya | current=88a0a1b2c3d4; head=88a0a1b2c3d4 |

## Perintah Lanjutan Saat Environment Siap

```text
python tools/postgres_uat_preflight.py --from-db
python -m flask db current
python -m flask db upgrade
python tools/audit_financial_invariants.py --from-db
```

