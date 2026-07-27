"""Preflight checklist for PostgreSQL UAT, migration, and restore drill.

Default mode is read-only and does not connect to a database. Use ``--from-db``
only when DATABASE_URL points to the intended PostgreSQL staging/snapshot target.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from sqlalchemy.engine.url import make_url
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_OUTPUT = ROOT / "RINCIAN_PREFLIGHT_POSTGRES_UAT_ERP_IDHA_BOGA.md"
POSTGRES_TOOLS = ("psql", "pg_dump", "pg_restore", "createdb", "dropdb")


def load_environment_file(env_file: Path = ROOT / ".env") -> None:
    if env_file.exists():
        load_dotenv(env_file, override=False)


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str
    message: str
    critical: bool = True

    @property
    def ok(self) -> bool:
        return self.status in {"PASS", "SKIP"}


def _pass(name: str, message: str, critical: bool = True) -> CheckResult:
    return CheckResult(name, "PASS", message, critical)


def _fail(name: str, message: str, critical: bool = True) -> CheckResult:
    return CheckResult(name, "FAIL", message, critical)


def _skip(name: str, message: str, critical: bool = False) -> CheckResult:
    return CheckResult(name, "SKIP", message, critical)


def check_database_url(env: dict[str, str] | None = None) -> CheckResult:
    env = os.environ if env is None else env
    url = env.get("DATABASE_URL", "")
    if not url:
        return _fail("DATABASE_URL", "DATABASE_URL belum diset.")
    try:
        parsed = make_url(url)
    except Exception as exc:
        return _fail("DATABASE_URL", f"DATABASE_URL tidak bisa diparse: {exc}")
    if not parsed.drivername.lower().startswith(("postgresql", "postgres")):
        return _fail("DATABASE_URL", f"Backend bukan PostgreSQL: {parsed.drivername}")
    return _pass("DATABASE_URL", parsed.render_as_string(hide_password=True))


def _candidate_postgres_bins() -> list[Path]:
    candidates: list[Path] = []
    env_bin = os.environ.get("POSTGRES_BIN") or os.environ.get("POSTGRESQL_BIN")
    if env_bin:
        candidates.append(Path(env_bin))

    candidates.extend(sorted(Path("C:/laragon/bin/postgresql").glob("*/bin"), reverse=True))
    candidates.extend(sorted(Path("C:/Program Files/PostgreSQL").glob("*/bin"), reverse=True))
    candidates.extend(sorted(Path("C:/Program Files (x86)/PostgreSQL").glob("*/bin"), reverse=True))
    return candidates


def _resolve_postgres_tool(tool: str, which: Callable[[str], str | None] = shutil.which) -> str | None:
    path = which(tool)
    if path:
        return path
    executable = f"{tool}.exe" if os.name == "nt" else tool
    for directory in _candidate_postgres_bins():
        candidate = directory / executable
        if candidate.exists() and candidate.is_file():
            return str(candidate)
    return None


def check_postgres_tools(which: Callable[[str], str | None] = shutil.which) -> list[CheckResult]:
    results: list[CheckResult] = []
    for tool in POSTGRES_TOOLS:
        path = _resolve_postgres_tool(tool, which=which) if which is shutil.which else which(tool)
        if path:
            results.append(_pass(f"tool:{tool}", path))
        else:
            results.append(_fail(f"tool:{tool}", f"{tool} tidak ditemukan di PATH/POSTGRES_BIN/Laragon/Program Files."))
    return results


def check_migration_integrity() -> list[CheckResult]:
    from tools.audit_migration_integrity import audit_migrations, collect_migrations

    audit = audit_migrations(collect_migrations())
    results = [
        _pass("migration:total", f"{audit['total']} migration file."),
        _pass("migration:head", ", ".join(audit["heads"]) or "-") if len(audit["heads"]) == 1 else _fail("migration:head", f"Head tidak tunggal: {audit['heads']}"),
    ]
    if audit["duplicate_revisions"]:
        results.append(_fail("migration:duplicate_revision", ", ".join(audit["duplicate_revisions"])))
    else:
        results.append(_pass("migration:duplicate_revision", "Tidak ada duplicate revision."))
    if audit["missing_parents"]:
        results.append(_fail("migration:missing_parent", ", ".join(audit["missing_parents"])))
    else:
        results.append(_pass("migration:missing_parent", "Tidak ada missing parent."))
    return results


def check_model_float_inventory() -> CheckResult:
    from tools.audit_float_fields import collect_float_fields

    fields = collect_float_fields(ROOT / "app" / "models")
    if fields:
        return _fail("model:float_inventory", f"Masih ada {len(fields)} db.Float di model.")
    return _pass("model:float_inventory", "Tidak ada db.Float di app/models.")


def check_raw_sql_inventory() -> CheckResult:
    from tools.audit_raw_sql import collect_raw_sql_findings

    findings = collect_raw_sql_findings(ROOT / "app")
    if findings:
        return _fail("model:raw_sql_dynamic", f"Masih ada {len(findings)} raw SQL dinamis.")
    return _pass("model:raw_sql_dynamic", "Tidak ada raw SQL dinamis terdeteksi.")


def check_from_db() -> list[CheckResult]:
    try:
        from app import create_app
        from app.extensions import db
        from sqlalchemy import text
    except Exception as exc:
        return [_fail("db:import_app", f"Import app gagal: {exc}")]

    app = create_app()
    with app.app_context():
        results: list[CheckResult] = []
        try:
            db.session.execute(text("SELECT 1"))
            results.append(_pass("db:reachable", "PostgreSQL reachable."))
        except Exception as exc:
            results.append(_fail("db:reachable", f"Database tidak reachable: {exc}"))
            return results

        try:
            head = check_migration_integrity()[1].message
            row = db.session.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).fetchone()
            current = row[0] if row else None
            if current == head:
                results.append(_pass("db:migration_current", f"current={current}; head={head}"))
            else:
                results.append(_fail("db:migration_current", f"current={current}; head={head}"))
        except Exception as exc:
            results.append(_fail("db:migration_current", f"Gagal cek alembic_version: {exc}"))
        return results


def check_restore_dump(dump_path: Path | None) -> CheckResult:
    if dump_path is None:
        return _skip("restore:pg_restore_list", "Tidak ada dump path. Lewati restore dry-run.")
    if not dump_path.exists() or not dump_path.is_file():
        return _fail("restore:pg_restore_list", f"File dump tidak ditemukan: {dump_path}")
    pg_restore = _resolve_postgres_tool("pg_restore")
    if not pg_restore:
        return _fail("restore:pg_restore_list", "pg_restore tidak ditemukan di PATH/POSTGRES_BIN/Laragon/Program Files.")
    try:
        result = subprocess.run(
            [pg_restore, "--list", str(dump_path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError:
        return _fail("restore:pg_restore_list", "pg_restore tidak ditemukan di PATH.")
    except subprocess.TimeoutExpired:
        return _fail("restore:pg_restore_list", "pg_restore --list timeout.")
    if result.returncode != 0:
        return _fail("restore:pg_restore_list", (result.stderr or result.stdout or "pg_restore gagal")[:500])
    return _pass("restore:pg_restore_list", f"TOC lines: {len(result.stdout.splitlines())}")


def build_checks(*, from_db: bool = False, restore_dump: Path | None = None) -> list[CheckResult]:
    load_environment_file()
    checks: list[CheckResult] = [
        check_database_url(),
        *check_postgres_tools(),
        *check_migration_integrity(),
        check_model_float_inventory(),
        check_raw_sql_inventory(),
        check_restore_dump(restore_dump),
    ]
    if from_db:
        checks.extend(check_from_db())
    else:
        checks.append(_skip("db:readiness", "Gunakan --from-db saat DATABASE_URL staging/snapshot sudah siap."))
    return checks


def render_report(checks: list[CheckResult]) -> str:
    failed_critical = [check for check in checks if check.status == "FAIL" and check.critical]
    status = "PASS" if not failed_critical else "FAIL"
    rows = [
        ["Status", status],
        ["Total check", str(len(checks))],
        ["Critical failed", str(len(failed_critical))],
    ]
    detail_rows = [
        [check.status, check.name, "ya" if check.critical else "tidak", check.message.replace("|", "\\|")]
        for check in checks
    ]
    return "\n\n".join([
        "# Preflight PostgreSQL UAT ERP Idha Boga",
        "Tool ini read-only secara default. Gunakan `--from-db` hanya untuk database staging/snapshot yang memang akan diuji.",
        "## Ringkasan",
        _table(["Metrik", "Nilai"], rows),
        "## Detail",
        _table(["Status", "Check", "Critical", "Pesan"], detail_rows),
        "## Perintah Lanjutan Saat Environment Siap",
        "```text\npython tools/postgres_uat_preflight.py --from-db\npython -m flask db current\npython -m flask db upgrade\npython tools/audit_financial_invariants.py --from-db\n```",
        "",
    ])


def _table(headers: list[str], rows: list[list[str]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-db", action="store_true", help="Connect to DATABASE_URL and check DB readiness.")
    parser.add_argument("--restore-dump", type=Path, default=None, help="Optional pg_dump custom-format file for pg_restore --list.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    checks = build_checks(from_db=args.from_db, restore_dump=args.restore_dump)
    args.output.write_text(render_report(checks), encoding="utf-8")
    failed = [check for check in checks if check.status == "FAIL" and check.critical]
    print(f"PostgreSQL UAT preflight written: {args.output}")
    print(f"Critical failed: {len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
