"""Safe dry-run first reset planner for local ERP development data.

This tool is intentionally conservative. It defaults to dry-run and refuses
execute mode unless the environment, database name, Alembic revision, admin
user, backup checksum, and confirmation token all pass safety checks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

CONFIRMATION_PHRASE = "RESET_ERP_DEVELOPMENT_DATA_CONFIRMED"
DEFAULT_ALLOWED_DATABASES = {
    "idha_boga_staging",
    "idha_boga_development",
    "idha_boga_dev",
    "idha_boga_testing",
    "idha_boga_test",
}
SAFE_APP_ENVS = {"development", "testing", "test", "local"}
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def load_dotenv(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def sanitize_database_url(url: str) -> dict[str, Any]:
    parsed = urlparse(url)
    return {
        "driver": parsed.scheme,
        "host": parsed.hostname,
        "port": parsed.port,
        "database": (parsed.path or "").lstrip("/"),
        "username_present": bool(parsed.username),
        "password_redacted": bool(parsed.password),
    }


def quote_identifier(identifier: str) -> str:
    if not IDENTIFIER_RE.match(identifier):
        raise ValueError(f"Unsafe SQL identifier: {identifier!r}")
    return f'"{identifier}"'


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_expected_sha256(path: Path) -> str:
    text = path.read_text(encoding="utf-8").strip()
    return text.split()[0].strip().lower()


def verify_pg_restore_list(backup_file: Path) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["pg_restore", "--list", str(backup_file)],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except FileNotFoundError:
        return False, "pg_restore command not found"
    except subprocess.TimeoutExpired:
        return False, "pg_restore --list timed out"
    if result.returncode != 0:
        return False, (result.stderr or result.stdout or "pg_restore --list failed").strip()
    return True, "pg_restore --list succeeded"


def latest_migration_revision(versions_dir: Path = Path("migrations/versions")) -> str | None:
    revisions: dict[str, str | None] = {}
    if not versions_dir.exists():
        return None
    revision_re = re.compile(r"^revision\s*=\s*['\"]([^'\"]+)['\"]", re.MULTILINE)
    down_re = re.compile(r"^down_revision\s*=\s*['\"]([^'\"]+)['\"]", re.MULTILINE)
    none_down_re = re.compile(r"^down_revision\s*=\s*None", re.MULTILINE)
    for path in versions_dir.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        revision_match = revision_re.search(text)
        if not revision_match:
            continue
        down_match = down_re.search(text)
        down_revision = down_match.group(1) if down_match else None
        if none_down_re.search(text):
            down_revision = None
        revisions[revision_match.group(1)] = down_revision
    if not revisions:
        return None
    referenced = {down for down in revisions.values() if down}
    heads = sorted(set(revisions) - referenced)
    if len(heads) != 1:
        return None
    return heads[0]


def load_classification(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def model_mapping(db: Any) -> dict[str, dict[str, str]]:
    mapping: dict[str, dict[str, str]] = {}
    for mapper in db.Model.registry.mappers:
        cls = mapper.class_
        table = getattr(cls, "__tablename__", None)
        if table:
            mapping[table] = {"model": cls.__name__, "module": cls.__module__}
    return mapping


def collect_inventory(app: Any, db: Any) -> dict[str, Any]:
    from sqlalchemy import inspect, text

    with app.app_context():
        inspector = inspect(db.engine)
        tables = sorted(inspector.get_table_names(schema="public"))
        counts: dict[str, int | str] = {}
        fk_out: dict[str, list[dict[str, Any]]] = {}
        fk_in: dict[str, list[dict[str, Any]]] = {table: [] for table in tables}
        sequences: dict[str, str | None] = {}

        for table in tables:
            quoted = quote_identifier(table)
            counts[table] = int(db.session.execute(text(f"SELECT COUNT(*) FROM {quoted}")).scalar() or 0)
            try:
                sequences[table] = db.session.execute(
                    text("SELECT pg_get_serial_sequence(:table_name, 'id')"),
                    {"table_name": f"public.{table}"},
                ).scalar()
            except Exception as exc:  # pragma: no cover - defensive reporting only
                db.session.rollback()
                sequences[table] = f"ERROR:{type(exc).__name__}"

        for table in tables:
            entries: list[dict[str, Any]] = []
            for fk in inspector.get_foreign_keys(table, schema="public"):
                referred = fk.get("referred_table")
                entry = {
                    "columns": fk.get("constrained_columns") or [],
                    "referred_table": referred,
                    "referred_columns": fk.get("referred_columns") or [],
                }
                entries.append(entry)
                if referred in fk_in:
                    fk_in[referred].append({"table": table, "columns": entry["columns"]})
            fk_out[table] = entries

        try:
            current_revisions = [
                row[0] for row in db.session.execute(text("SELECT version_num FROM alembic_version")).fetchall()
            ]
        except Exception as exc:  # pragma: no cover - defensive reporting only
            current_revisions = [f"ERROR:{type(exc).__name__}"]

        return {
            "tables": tables,
            "counts": counts,
            "fk_out": fk_out,
            "fk_in": fk_in,
            "sequences": sequences,
            "model_mapping": model_mapping(db),
            "alembic_current": current_revisions,
        }


def action_for(table_entry: dict[str, Any], option: str) -> str:
    key = "option_a_action" if option == "A" else "option_b_action"
    return str(table_entry.get(key) or "approval_required")


def deletion_order(tables: set[str], fk_out: dict[str, list[dict[str, Any]]]) -> tuple[list[str], list[str]]:
    graph: dict[str, set[str]] = {table: set() for table in tables}
    indegree: dict[str, int] = {table: 0 for table in tables}
    for child in tables:
        for fk in fk_out.get(child, []):
            parent = fk.get("referred_table")
            if parent in tables and parent != child and parent not in graph[child]:
                graph[child].add(parent)
                indegree[parent] += 1

    queue = deque(sorted(table for table, degree in indegree.items() if degree == 0))
    ordered: list[str] = []
    while queue:
        table = queue.popleft()
        ordered.append(table)
        for parent in sorted(graph[table]):
            indegree[parent] -= 1
            if indegree[parent] == 0:
                queue.append(parent)

    remaining = sorted(table for table, degree in indegree.items() if degree > 0)
    return ordered, remaining


def build_plan(classification: dict[str, Any], inventory: dict[str, Any], option: str) -> dict[str, Any]:
    entries = {entry["table"]: entry for entry in classification.get("tables", [])}
    db_tables = set(inventory["tables"])
    classified_tables = set(entries)
    unknown_tables = sorted(db_tables - classified_tables)
    stale_classification = sorted(classified_tables - db_tables)

    preserve: list[str] = []
    empty: list[str] = []
    approval_required: list[str] = []

    for table in sorted(db_tables & classified_tables):
        action = action_for(entries[table], option)
        if action == "preserve":
            preserve.append(table)
        elif action == "empty":
            empty.append(table)
        else:
            approval_required.append(table)

    ordered_empty, cycle_tables = deletion_order(set(empty), inventory["fk_out"])
    empty_set = set(ordered_empty)
    external_fk_blockers: list[dict[str, Any]] = []
    for target in sorted(empty_set):
        for inbound in inventory["fk_in"].get(target, []):
            source = inbound.get("table")
            if source not in empty_set and inventory["counts"].get(source, 0):
                external_fk_blockers.append(
                    {
                        "target_empty_table": target,
                        "referencing_preserved_or_pending_table": source,
                        "columns": inbound.get("columns") or [],
                    }
                )

    return {
        "option": option,
        "unknown_tables": unknown_tables,
        "stale_classification": stale_classification,
        "preserve_tables": preserve,
        "empty_tables": ordered_empty,
        "approval_required_tables": approval_required,
        "dependency_cycle_tables": cycle_tables,
        "external_fk_blockers": external_fk_blockers,
        "sequences_to_reset": {
            table: inventory["sequences"].get(table)
            for table in ordered_empty
            if inventory["sequences"].get(table)
        },
        "row_counts_before": {table: inventory["counts"].get(table) for table in sorted(db_tables)},
    }


def safety_checks(
    app: Any,
    db: Any,
    inventory: dict[str, Any],
    plan: dict[str, Any],
    args: argparse.Namespace,
) -> list[str]:
    from sqlalchemy import text

    errors: list[str] = []
    uri = app.config.get("SQLALCHEMY_DATABASE_URI") or app.config.get("DATABASE_URL") or ""
    sanitized = sanitize_database_url(uri)
    app_env = str(app.config.get("APP_ENV") or os.getenv("APP_ENV") or "").lower()
    allowed_databases = set(DEFAULT_ALLOWED_DATABASES)
    allowed_databases.update(args.allow_database or [])

    if app_env not in SAFE_APP_ENVS:
        errors.append(f"APP_ENV {app_env!r} is not development/testing/local")
    if sanitized["host"] not in LOCAL_HOSTS:
        errors.append(f"database host {sanitized['host']!r} is not local")
    if sanitized["database"] not in allowed_databases:
        errors.append(f"database {sanitized['database']!r} is not in allowlist")
    if not str(sanitized["driver"]).startswith(("postgresql", "postgres")):
        errors.append("DATABASE_URL is not PostgreSQL")
    if plan["unknown_tables"]:
        errors.append("database has unclassified tables")
    if plan["stale_classification"]:
        errors.append("classification contains tables not present in database")
    if plan["dependency_cycle_tables"]:
        errors.append("target table dependency cycle requires manual ordering")
    if plan["external_fk_blockers"]:
        errors.append("preserved or approval-required rows still reference tables selected for emptying")

    latest_revision = latest_migration_revision()
    current_revisions = inventory.get("alembic_current") or []
    if not latest_revision or current_revisions != [latest_revision]:
        errors.append(f"Alembic current {current_revisions!r} is not exactly head {latest_revision!r}")

    with app.app_context():
        admin_count = int(
            db.session.execute(
                text("SELECT COUNT(*) FROM users WHERE is_active = true AND role IN ('OWNER', 'ADMIN')")
            ).scalar()
            or 0
        )
        orphan_users = int(
            db.session.execute(
                text("SELECT COUNT(*) FROM users u LEFT JOIN branches b ON b.id = u.branch_id WHERE b.id IS NULL")
            ).scalar()
            or 0
        )
    if admin_count < 1:
        errors.append("no active OWNER/ADMIN user found")
    if orphan_users:
        errors.append("users with invalid branch dependency exist")

    if args.execute:
        if args.confirm_token != CONFIRMATION_PHRASE:
            errors.append("confirmation token mismatch")
        if plan["approval_required_tables"]:
            errors.append("approval-required tables remain in selected option")
        if not args.backup_file or not args.backup_sha256:
            errors.append("execute mode requires --backup-file and --backup-sha256")
        else:
            backup_file = Path(args.backup_file)
            backup_sha256 = Path(args.backup_sha256)
            if not backup_file.exists():
                errors.append("backup file does not exist")
            if not backup_sha256.exists():
                errors.append("backup sha256 file does not exist")
            if backup_file.exists() and backup_sha256.exists():
                actual = sha256_file(backup_file)
                expected = read_expected_sha256(backup_sha256)
                if actual.lower() != expected.lower():
                    errors.append("backup SHA-256 mismatch")
                restore_ok, restore_message = verify_pg_restore_list(backup_file)
                if not restore_ok:
                    errors.append(f"backup restore-list verification failed: {restore_message}")

    return errors


def execute_reset(db: Any, plan: dict[str, Any], restart_identity: bool, method: str) -> None:
    from sqlalchemy import text

    with db.session.begin():
        if method == "truncate":
            if plan["empty_tables"]:
                tables_sql = ", ".join(quote_identifier(table) for table in plan["empty_tables"])
                identity_sql = "RESTART IDENTITY" if restart_identity else "CONTINUE IDENTITY"
                db.session.execute(text(f"TRUNCATE TABLE {tables_sql} {identity_sql} RESTRICT"))
        else:
            for table in plan["empty_tables"]:
                db.session.execute(text(f"DELETE FROM {quote_identifier(table)}"))
        if restart_identity:
            for sequence in plan["sequences_to_reset"].values():
                if sequence and isinstance(sequence, str) and "." in sequence:
                    db.session.execute(text(f"ALTER SEQUENCE {sequence} RESTART WITH 1"))


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dry-run first ERP development data reset planner.")
    parser.add_argument("--classification", default="storage/final_reports/DATABASE_RESET_TABLE_CLASSIFICATION.json")
    parser.add_argument("--option", choices=["A", "B"], default="A")
    parser.add_argument("--output-json", default=None)
    parser.add_argument("--execute", action="store_true", help="Run destructive reset after all safety checks pass.")
    parser.add_argument("--confirm-token", default="")
    parser.add_argument("--backup-file", default="")
    parser.add_argument("--backup-sha256", default="")
    parser.add_argument("--allow-database", action="append", default=[])
    parser.add_argument("--restart-identity", action="store_true")
    parser.add_argument("--method", choices=["delete", "truncate"], default="delete")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    load_dotenv()

    from app import create_app, db

    app = create_app()
    inventory = collect_inventory(app, db)
    classification = load_classification(Path(args.classification))
    plan = build_plan(classification, inventory, args.option)
    checks = safety_checks(app, db, inventory, plan, args)

    uri = app.config.get("SQLALCHEMY_DATABASE_URI") or app.config.get("DATABASE_URL") or ""
    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "execute" if args.execute else "dry_run",
        "method": args.method,
        "database": sanitize_database_url(uri),
        "app_env": app.config.get("APP_ENV"),
        "alembic_current": inventory.get("alembic_current"),
        "alembic_head_detected": latest_migration_revision(),
        "safety_errors": checks,
        "plan": plan,
    }

    output = json.dumps(result, indent=2, ensure_ascii=False)
    print(output)
    if args.output_json:
        Path(args.output_json).write_text(output + "\n", encoding="utf-8")

    if checks:
        return 2
    if args.execute:
        with app.app_context():
            db.session.rollback()
            execute_reset(db, plan, args.restart_identity, args.method)
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
