"""Ganti seluruh data ERP di database staging dengan data demo yang rapi.

Urutan (berhenti di langkah pertama yang gagal):
1. Database sumber (bawaan idha_boga_demotest) dibuat ulang: migrate, bootstrap
   owner, lalu tools/seed_demo_data.py dengan "hari ini" = hari dijalankan.
   Seeder harus lolos semua langkah dan semua pemeriksaan pembukuan.
2. Backup penuh database tujuan (pg_dump -Fc + sha256) ke instance/backups/.
3. Hash password akun yang dipertahankan + pengaturan perusahaan (nama, alamat,
   logo, ...) disimpan dari database tujuan.
4. Dalam SATU transaksi: semua tabel model ERP (db.metadata) dikosongkan lalu
   diisi data sumber. Tabel lain -- data ML/SPK (ml_*, research_dataset_*,
   migrations), view, alembic_version -- tidak disentuh; tabel ERP lama yang
   modelnya sudah dihapus hanya ikut dikosongkan kalau memang kosong.
5. Sequence disetel, password lama & pengaturan perusahaan dikembalikan,
   jumlah baris tabel ML dicek sama persis, pembukuan diperiksa ulang.

Akun yang tersisa (satu per peran/portal): owner, admin, dapur, pengantar,
portal.pt.local, portal.mandor.local, portal.customer.local -- dengan password
yang sama seperti sebelum reset.

Pakai (server dev sebaiknya dimatikan dulu, lalu dinyalakan ulang sesudahnya):
    python tools/reset_staging_demo.py --confirm
Butuh PG_BIN (folder pg_dump/psql) bila tidak ada di PATH, mis.
    PG_BIN=C:\\laragon\\bin\\postgresql\\postgresql-11.0-1\\bin
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import os
import shutil
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEPT_USERS = ["owner", "admin", "dapur", "pengantar", "portal.pt.local", "portal.mandor.local", "portal.customer.local"]
ML_TABLES = ["ml_catering_historical", "ml_mandor", "ml_predictions", "ml_recipe_bom", "ml_training_runs",
             "research_dataset_clean", "research_dataset_features", "migrations"]
DEMO_OWNER_PASSWORD = "DemoOwner#2026"  # hanya di database sumber; staging memakai password lama


def pg_tool(name):
    folder = os.environ.get("PG_BIN")
    if folder:
        return str(Path(folder) / name)
    found = shutil.which(name)
    if not found:
        raise SystemExit(f"{name} tidak ditemukan. Set PG_BIN ke folder bin PostgreSQL.")
    return found


def run(args, env=None):
    result = subprocess.run([str(a) for a in args], capture_output=True, text=True, encoding="utf-8", env=env, cwd=ROOT)
    if result.returncode != 0:
        raise SystemExit(f"GAGAL: {' '.join(map(str, args[:4]))} ...\n{(result.stdout + result.stderr)[-4000:]}")
    return result.stdout


def psql(db, sql):
    return run([pg_tool("psql"), "-U", "postgres", "-d", db, "-v", "ON_ERROR_STOP=1", "-At", "-c", sql])


def counts(db, tables):
    return {t: int(psql(db, f'SELECT count(*) FROM "{t}"').strip()) for t in tables}


def database_url(db):
    from dotenv import dotenv_values

    base = os.environ.get("DATABASE_URL") or dotenv_values(ROOT / ".env").get("DATABASE_URL")
    return base.rsplit("/", 1)[0] + "/" + db


def app_env(db, **extra):
    env = dict(os.environ, DATABASE_URL=database_url(db), PYTHONIOENCODING="utf-8", **extra)
    return env


def build_source(source, today):
    print(f"[1] Membuat data demo di {source} (hari ini {today}) ...", flush=True)
    run([pg_tool("dropdb"), "-U", "postgres", "--if-exists", source])
    run([pg_tool("createdb"), "-U", "postgres", "-O", "idha_boga_user", source])
    python = sys.executable
    run([python, "-m", "flask", "--app", "run", "db", "upgrade"], env=app_env(source))
    run([python, "-m", "flask", "--app", "run", "bootstrap", "--branch-code", "OKI", "--branch-name", "Air Sugihan",
         "--owner-username", "owner", "--owner-name", "Owner Idha Boga"],
        env=app_env(source, BOOTSTRAP_OWNER_PASSWORD=DEMO_OWNER_PASSWORD))
    output = run([python, "-W", "ignore", "tools/seed_demo_data.py", "--db", source, "--confirm", "--today", today.isoformat()],
                 env=app_env(source, DEMO_OWNER_PASSWORD=DEMO_OWNER_PASSWORD))
    print("    " + "\n    ".join(line for line in output.splitlines() if line.startswith(("Periode", "Selesai"))))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--confirm", action="store_true", help="Wajib: data ERP di database tujuan diganti.")
    parser.add_argument("--target", default="idha_boga_staging")
    parser.add_argument("--source", default="idha_boga_demotest")
    parser.add_argument("--today", type=date.fromisoformat, default=date.today())
    parser.add_argument("--skip-seed", action="store_true", help="Pakai database sumber yang sudah ada.")
    args = parser.parse_args()
    if not args.confirm:
        raise SystemExit("Tambahkan --confirm.")
    if args.source == args.target or "staging" in args.source:
        raise SystemExit("Database sumber tidak boleh staging/tujuan.")

    if not args.skip_seed:
        build_source(args.source, args.today)

    sys.path.insert(0, str(ROOT))
    os.environ["DATABASE_URL"] = database_url(args.target)
    from app import create_app
    from app.extensions import db

    create_app()
    erp_tables = sorted(db.metadata.tables)
    assert not set(erp_tables) & set(ML_TABLES), "tabel ML terdaftar sebagai tabel ERP"

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = ROOT / "instance" / "backups" / f"{args.target}_sebelum_reset_demo_{stamp}.dump"
    backup.parent.mkdir(parents=True, exist_ok=True)
    print(f"[2] Backup penuh {args.target} ...", flush=True)
    run([pg_tool("pg_dump"), "-U", "postgres", "-Fc", "-f", backup, args.target])
    digest = hashlib.sha256(backup.read_bytes()).hexdigest()
    backup.with_name(backup.name + ".sha256").write_text(f"{digest}  {backup.name}\n", encoding="utf-8")
    entries = len(run([pg_tool("pg_restore"), "-l", backup]).splitlines())
    print(f"    {backup.relative_to(ROOT)} ({backup.stat().st_size:,} byte, {entries} entri)")

    # Skema target disamakan dulu (migrasi hanya menambah kolom/tabel; tabel ML tidak disentuh).
    print(f"    Migrasi skema {args.target} ...", flush=True)
    run([sys.executable, "-m", "flask", "--app", "run", "db", "upgrade"], env=app_env(args.target))
    existing = set(psql(args.target, "SELECT tablename FROM pg_tables WHERE schemaname='public'").split())
    source_tables = set(psql(args.source, "SELECT tablename FROM pg_tables WHERE schemaname='public'").split())
    missing = [t for t in erp_tables if t not in existing or t not in source_tables]
    if missing:
        raise SystemExit(f"Skema berbeda (jalankan flask db upgrade): {missing}")
    leftovers = sorted(existing - set(erp_tables) - set(ML_TABLES) - {"alembic_version"})
    leftover_rows = counts(args.target, leftovers)
    if any(leftover_rows.values()):
        raise SystemExit(f"Tabel di luar model ERP berisi data, tidak berani dikosongkan: {leftover_rows}")
    ml_present = [t for t in ML_TABLES if t in existing]

    print("[3] Menyimpan password akun & pengaturan perusahaan ...", flush=True)
    ml_before = counts(args.target, ml_present)
    names = ",".join(f"'{u}'" for u in KEPT_USERS)
    kept = list(csv.reader(io.StringIO(psql(args.target, f"COPY (SELECT username, password_hash FROM users WHERE username IN ({names})) TO STDOUT WITH CSV"))))
    settings = list(csv.reader(io.StringIO(psql(args.target, "COPY (SELECT setting_key, setting_value FROM branch_settings WHERE branch_id = (SELECT min(id) FROM branches) AND setting_key LIKE 'company%' AND setting_key <> 'company_email') TO STDOUT WITH CSV"))))
    print(f"    {len(kept)} akun, {len(settings)} pengaturan")

    print(f"[4] Mengganti data ERP {args.target} (satu transaksi) ...", flush=True)
    work = ROOT / "instance" / "backups" / f"reset_demo_{stamp}"
    work.mkdir(parents=True, exist_ok=True)
    data = work / "demo_data.dump"
    run([pg_tool("pg_dump"), "-U", "postgres", "-Fc", "--data-only", *sum((["-t", f'public."{t}"'] for t in erp_tables), []), "-f", data, args.source])
    restore_sql = work / "restore.sql"
    # pg_restore 11 menulis "-f -" ke file bernama "-": selalu ke file eksplisit.
    run([pg_tool("pg_restore"), "--data-only", "--disable-triggers", "-f", restore_sql, data])
    expected = {t: int(psql(args.source, f"SELECT count(*) FROM {t}").strip()) for t in ("users", "journals", "daily_orders")}
    table_list = ", ".join(f'public."{t}"' for t in erp_tables + leftovers)
    head = f"BEGIN;\nSET lock_timeout = '15s';\nTRUNCATE {table_list} RESTART IDENTITY;\n".encode()
    checks = " OR ".join(f"(SELECT count(*) FROM public.{t}) <> {n}" for t, n in expected.items())
    tail = (f"\nDO $$ BEGIN IF {checks} THEN RAISE EXCEPTION 'data demo tidak termuat lengkap'; END IF; END $$;\nCOMMIT;\n").encode()
    script = work / "reset.sql"
    script.write_bytes(head + restore_sql.read_bytes() + tail)
    run([pg_tool("psql"), "-U", "postgres", "-d", args.target, "-v", "ON_ERROR_STOP=1", "-q", "-f", script])
    shutil.rmtree(work)

    print("[5] Sequence, password lama, pengaturan perusahaan, pemeriksaan ...", flush=True)
    for table in erp_tables:
        seq = psql(args.target, f"SELECT pg_get_serial_sequence('public.\"{table}\"', 'id')").strip()
        if seq:
            psql(args.target, f'SELECT setval(\'{seq}\', COALESCE((SELECT MAX(id) FROM public."{table}"), 0) + 1, false)')
    for username, password_hash in kept:
        psql(args.target, f"UPDATE users SET password_hash = '{password_hash}' WHERE username = '{username}'")
    branch_id = psql(args.target, "SELECT min(id) FROM branches").strip()
    for key, value in settings:
        escaped = value.replace("'", "''")
        if not psql(args.target, f"UPDATE branch_settings SET setting_value = '{escaped}' WHERE branch_id = {branch_id} AND setting_key = '{key}' RETURNING id").strip():
            psql(args.target, f"INSERT INTO branch_settings (branch_id, setting_key, setting_value, created_at, version_id) VALUES ({branch_id}, '{key}', '{escaped}', now(), 1)")
    ml_after = counts(args.target, ml_present)
    if ml_after != ml_before:
        raise SystemExit(f"PERINGATAN: jumlah baris tabel ML berubah {ml_before} -> {ml_after}. Pulihkan dari {backup.name}.")
    users = psql(args.target, "SELECT string_agg(username, ', ' ORDER BY id) FROM users").strip()
    verify = subprocess.run([sys.executable, "-W", "ignore", "tools/seed_demo_data.py", "--db", args.target, "--verify-only"],
                            capture_output=True, text=True, encoding="utf-8", cwd=ROOT, env=app_env(args.target))
    print("    Tabel ML utuh: " + ", ".join(f"{t} {n}" for t, n in ml_after.items()))
    print(f"    Akun: {users}")
    print("    " + "\n    ".join(line for line in verify.stdout.splitlines() if line.strip().startswith(("[", "Pembukuan"))))
    if verify.returncode != 0:
        raise SystemExit("Pemeriksaan pembukuan gagal; lihat di atas.")
    print(f"\nSelesai. Backup sebelum reset: {backup.relative_to(ROOT)}. Nyalakan ulang server dev.")


if __name__ == "__main__":
    main()
