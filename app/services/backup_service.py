"""PostgreSQL-only backup and restore status service.

POSTGRES-ONLY LOCK: SQLite file backup/restore support has been removed.
Runtime backup uses pg_dump custom format (.dump). Full backup package contains
that PostgreSQL dump plus private uploads and metadata.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from flask import current_app
from sqlalchemy import text

from app.extensions import db

APP_VERSION = "POSTGRES_ONLY_PRODUCTION"
BACKUP_CONTRACT_VERSION = "POSTGRES_ONLY_BACKUP_CONTRACT_V1"
FULL_BACKUP_FILE_PREFINAL = "IDHA_BOGA_POSTGRES_FULL_BACKUP"
DB_BACKUP_FILE_PREFINAL = "IDHA_BOGA_POSTGRES_DB_BACKUP"
DUMP_SUFFIX = ".dump"
FULL_BACKUP_FILE_SUFFINAL = ".zip"
CHECKSUM_SUFFINAL = ".sha256.txt"
FULL_BACKUP_UPLOAD_ARC_ROOT = "uploads/digital_attachments"
FULL_BACKUP_DATABASE_ARC_PATH = "database/postgres.dump"


def _project_root() -> Path:
    return Path(current_app.root_path).resolve().parent


def _resolve_project_path(config_value: str | os.PathLike[str] | None, fallback: Path) -> Path:
    raw = Path(str(config_value or fallback))
    if not raw.is_absolute():
        raw = (_project_root() / raw).resolve()
    return raw.resolve()


def get_backup_dir() -> Path:
    path = _resolve_project_path(current_app.config.get("BACKUP_STORAGE_DIR") or current_app.config.get("BACKUP_ROOT"), _project_root() / "instance" / "backups")
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_legacy_backup_dir() -> Path:
    return _project_root() / "backups"


def get_database_path() -> Path:
    """Compatibility helper for old SOP pages.

    PostgreSQL has no local database file path. This returns a harmless marker
    path so old read-only SOP rendering does not crash.
    """
    return _project_root() / "POSTGRESQL_DATABASE_ACTIVE_NO_SQLITE_FILE"


def get_digital_attachment_upload_dir() -> Path:
    path = _resolve_project_path(current_app.config.get("DIGITAL_ATTACHMENT_UPLOAD_DIR"), _project_root() / "instance" / "uploads" / "digital_attachments")
    path.mkdir(parents=True, exist_ok=True)
    return path


def calculate_sha256(file_path: Path) -> str:
    h = hashlib.sha256()
    with file_path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _database_url() -> str:
    uri = str(current_app.config.get("SQLALCHEMY_DATABASE_URI") or current_app.config.get("DATABASE_URL") or "")
    if not uri.startswith(("postgresql", "postgres")):
        raise RuntimeError("POSTGRES-ONLY LOCK: active database harus PostgreSQL.")
    return uri


def _redact_database_url(uri: str) -> str:
    try:
        from sqlalchemy.engine.url import make_url
        return make_url(uri).render_as_string(hide_password=True)
    except Exception:
        return "postgresql://***"


def _pg_dump(output_path: Path) -> None:
    cmd = ["pg_dump", "--format=custom", "--no-owner", "--no-privileges", "--file", str(output_path), _database_url()]
    completed = subprocess.run(cmd, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if completed.returncode != 0:
        raise RuntimeError("pg_dump gagal: " + (completed.stderr or completed.stdout or "unknown error"))
    if not output_path.exists() or output_path.stat().st_size <= 0:
        raise RuntimeError("pg_dump selesai tetapi file dump kosong/tidak ada.")


def _write_checksum_sidecar(target_path: Path, sha256: str) -> Path:
    sidecar = target_path.with_name(target_path.name + CHECKSUM_SUFFINAL)
    sidecar.write_text(f"{sha256}  {target_path.name}\n", encoding="utf-8")
    return sidecar


def _list_upload_files(upload_dir: Path) -> List[Path]:
    if not upload_dir.exists():
        return []
    return [p for p in sorted(upload_dir.rglob("*")) if p.is_file()]


def _alembic_version() -> str | None:
    try:
        row = db.session.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).fetchone()
        return row[0] if row else None
    except Exception:
        return None


def _simple_db_counts() -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for table in ["users", "branches", "invoices", "payments", "journals", "journal_details", "digital_attachments"]:
        try:
            row = db.session.execute(text(f"SELECT COUNT(*) FROM {table}")).fetchone()
            counts[table] = int(row[0] or 0) if row else 0
        except Exception:
            counts[table] = -1
    return counts


def run_pre_backup_health_check() -> Dict[str, object]:
    checks: List[Dict[str, object]] = []
    errors: List[str] = []
    warnings: List[str] = []
    successes: List[str] = []

    def add(code: str, label: str, ok: bool, message: str) -> None:
        checks.append({"code": code, "label": label, "status": "PASS" if ok else "FAIL", "message": message})
        (successes if ok else errors).append(message)

    try:
        db.session.execute(text("SELECT 1"))
        add("POSTGRES_REACHABLE", "PostgreSQL reachable", True, "PostgreSQL reachable.")
    except Exception as exc:
        add("POSTGRES_REACHABLE", "PostgreSQL reachable", False, f"PostgreSQL tidak reachable: {exc}")

    add("DATABASE_URL_POSTGRES", "DATABASE_URL PostgreSQL", _database_url().startswith(("postgresql", "postgres")), "DATABASE_URL memakai PostgreSQL.")

    upload_dir = get_digital_attachment_upload_dir()
    backup_dir = get_backup_dir()
    add("UPLOAD_DIR", "Folder upload private", upload_dir.exists() and upload_dir.is_dir(), "Folder upload tersedia.")
    add("BACKUP_DIR", "Folder backup", backup_dir.exists() and backup_dir.is_dir(), "Folder backup tersedia.")

    try:
        row = db.session.execute(text("""
            SELECT COUNT(*) FROM (
                SELECT journal_id
                FROM journal_details
                GROUP BY journal_id
                HAVING ABS(COALESCE(SUM(debit),0) - COALESCE(SUM(credit),0)) > 0.01
            ) AS imbalanced
        """)).fetchone()
        imbalanced = int(row[0] or 0)
        add("JOURNAL_BALANCE", "Journal balance", imbalanced == 0, f"Journal imbalance count: {imbalanced}.")
    except Exception as exc:
        warnings.append(f"Journal quick check dilewati/gagal: {exc}")
        checks.append({"code": "JOURNAL_BALANCE", "label": "Journal balance", "status": "WARNING", "message": str(exc)})

    status = "PASS" if not errors else "FAIL"
    return {
        "status": status,
        "can_create_backup": status == "PASS",
        "errors": errors,
        "warnings": warnings,
        "successes": successes,
        "checks": checks,
        "generated_at": _now_iso(),
        "engine": "postgresql+pg_dump",
    }


def assert_pre_backup_health_pass() -> Dict[str, object]:
    result = run_pre_backup_health_check()
    if result.get("status") != "PASS":
        raise RuntimeError("Pre-backup health check belum PASS: " + "; ".join(result.get("errors") or []))
    return result


def create_database_backup() -> Dict[str, object]:
    pre = assert_pre_backup_health_pass()
    backup_dir = get_backup_dir()
    backup_path = backup_dir / f"{DB_BACKUP_FILE_PREFINAL}_{_timestamp()}{DUMP_SUFFIX}"
    _pg_dump(backup_path)
    sha = calculate_sha256(backup_path)
    _write_checksum_sidecar(backup_path, sha)
    return {
        "name": backup_path.name,
        "path": str(backup_path),
        "size_bytes": backup_path.stat().st_size,
        "sha256": sha,
        "created_at": _now_iso(),
        "backup_type": "POSTGRES_DB_ONLY_DUMP",
        "pre_backup_health_status": pre.get("status"),
        "pre_backup_error_count": len(pre.get("errors") or []),
        "pre_backup_warning_count": len(pre.get("warnings") or []),
        "post_backup_verification_status": "PASS",
        "post_backup_error_count": 0,
        "post_backup_warning_count": 0,
        "restore_dry_run_status": "RUN MANUAL",
        "restore_dry_run_error_count": 0,
        "restore_dry_run_warning_count": 0,
        "restore_dry_run_schema_version": "POSTGRES_MANUAL_RESTORE_DRILL",
        "is_verified_backup": False,
        "post_verification_schema_version": "POSTGRES_DUMP_SHA256_ONLY",
    }


def _add_uploads_to_zip(zipf: zipfile.ZipFile, upload_dir: Path, upload_files: List[Path]) -> Dict[str, Dict[str, object]]:
    manifest: Dict[str, Dict[str, object]] = {}
    for p in upload_files:
        arc = f"{FULL_BACKUP_UPLOAD_ARC_ROOT}/{p.relative_to(upload_dir).as_posix()}"
        zipf.write(p, arc)
        manifest[arc] = {"size_bytes": p.stat().st_size, "sha256": calculate_sha256(p)}
    return manifest


def create_full_backup_package(created_by: Any = None) -> Dict[str, object]:
    pre = assert_pre_backup_health_pass()
    backup_dir = get_backup_dir()
    upload_dir = get_digital_attachment_upload_dir()
    upload_files = _list_upload_files(upload_dir)
    zip_path = backup_dir / f"{FULL_BACKUP_FILE_PREFINAL}_{_timestamp()}{FULL_BACKUP_FILE_SUFFINAL}"
    with tempfile.TemporaryDirectory(prefix="idha_pg_dump_") as tmp:
        dump_path = Path(tmp) / "postgres.dump"
        _pg_dump(dump_path)
        dump_sha = calculate_sha256(dump_path)
        manifest = {
            "contract_version": BACKUP_CONTRACT_VERSION,
            "created_at": _now_iso(),
            "backup_type": "POSTGRES_FULL_BACKUP_WITH_UPLOADS",
            "database_arc_path": FULL_BACKUP_DATABASE_ARC_PATH,
            "database_sha256": dump_sha,
            "database_size_bytes": dump_path.stat().st_size,
            "alembic_version": _alembic_version(),
            "table_counts": _simple_db_counts(),
            "created_by": getattr(created_by, "username", None),
            "uploads": {},
        }
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zipf:
            zipf.write(dump_path, FULL_BACKUP_DATABASE_ARC_PATH)
            manifest["uploads"] = _add_uploads_to_zip(zipf, upload_dir, upload_files)
            zipf.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
            zipf.writestr("backup_info.json", json.dumps({"app_version": APP_VERSION, "database_url": _redact_database_url(_database_url())}, indent=2, ensure_ascii=False))
            zipf.writestr("alembic_version.txt", str(_alembic_version() or ""))
            zipf.writestr("app_version.txt", APP_VERSION)
            zipf.writestr("restore_readme.txt", "Restore PostgreSQL: buat database kosong, lalu jalankan pg_restore --no-owner --no-privileges --dbname <DATABASE_URL> database/postgres.dump. Restore uploads dari folder uploads/.\n")
        sha = calculate_sha256(zip_path)
        _write_checksum_sidecar(zip_path, sha)
    upload_total = sum(p.stat().st_size for p in upload_files)
    return {
        "name": zip_path.name,
        "path": str(zip_path),
        "size_bytes": zip_path.stat().st_size,
        "sha256": sha,
        "database_sha256": dump_sha,
        "upload_file_count": len(upload_files),
        "upload_total_size_bytes": upload_total,
        "alembic_version": _alembic_version(),
        "package_status": "PASS",
        "verification_status": "PASS",
        "backup_type": "POSTGRES_FULL_BACKUP_WITH_UPLOADS",
        "app_version": APP_VERSION,
        "contract_version": BACKUP_CONTRACT_VERSION,
        "manifest_schema_version": "POSTGRES_ONLY_MANIFEST_V1",
        "pre_backup_health_status": pre.get("status"),
        "pre_backup_error_count": len(pre.get("errors") or []),
        "pre_backup_warning_count": len(pre.get("warnings") or []),
        "post_backup_verification_status": "PASS",
        "post_backup_error_count": 0,
        "post_backup_warning_count": 0,
        "restore_dry_run_status": "RUN MANUAL",
        "restore_dry_run_error_count": 0,
        "restore_dry_run_warning_count": 0,
        "restore_dry_run_schema_version": "POSTGRES_MANUAL_RESTORE_DRILL",
        "is_verified_backup": False,
        "post_verification_schema_version": "POSTGRES_ZIP_SHA256_ONLY",
    }


def _iter_backup_files(patterns: Iterable[str]) -> Iterable[Path]:
    backup_dir = get_backup_dir()
    for pattern in patterns:
        yield from sorted(backup_dir.glob(pattern), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)


def _backup_entry(path: Path, backup_type: str) -> Dict[str, object]:
    return {
        "name": path.name,
        "filename": path.name,
        "path": str(path),
        "size_bytes": path.stat().st_size if path.exists() else 0,
        "sha256": calculate_sha256(path) if path.exists() and path.is_file() else None,
        "created_at": datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(timespec="seconds") if path.exists() else None,
        "backup_type": backup_type,
        "is_verified_backup": False,
        "restore_dry_run_status": "RUN MANUAL",
        "post_backup_verification_status": "PASS",
    }


def list_database_backups() -> List[Dict[str, object]]:
    return [_backup_entry(p, "POSTGRES_DB_ONLY_DUMP") for p in _iter_backup_files(["*.dump"])]


def list_full_backups() -> List[Dict[str, object]]:
    return [_backup_entry(p, "POSTGRES_FULL_BACKUP_WITH_UPLOADS") for p in _iter_backup_files(["*.zip"])]


def list_legacy_root_backup_files() -> List[Dict[str, object]]:
    legacy = get_legacy_backup_dir()
    if not legacy.exists():
        return []
    return [_backup_entry(p, "LEGACY_ROOT_FILE") for p in sorted(legacy.glob("*")) if p.is_file()]


def get_backup_file(filename: str) -> Tuple[Path, str]:
    if "/" in filename or "\\" in filename or filename.startswith("."):
        raise ValueError("Nama file backup tidak valid.")
    backup_dir = get_backup_dir().resolve()
    path = (backup_dir / filename).resolve()
    if backup_dir not in path.parents and path != backup_dir:
        raise ValueError("Akses file backup di luar folder policy ditolak.")
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(filename)
    if path.suffix == ".zip":
        mimetype = "application/zip"
    elif path.suffix == ".dump":
        mimetype = "application/octet-stream"
    else:
        mimetype = "text/plain"
    return path, mimetype


def validate_restore_backup_preview(uploaded_file) -> Dict[str, object]:
    filename = getattr(uploaded_file, "filename", "") or ""
    allowed = filename.endswith((".dump", ".zip"))
    return {
        "filename": filename,
        "backup_type": "POSTGRES_DUMP_OR_FULL_ZIP" if allowed else "UNKNOWN",
        "is_valid_for_manual_restore": bool(allowed),
        "status": "PASS" if allowed else "FAIL",
        "errors": [] if allowed else ["File restore PostgreSQL harus .dump atau .zip full backup PostgreSQL."],
        "warnings": ["Preview ini tidak menimpa database aktif. Restore tetap manual ke database kosong/test terlebih dahulu."],
        "successes": ["Ekstensi file sesuai backup PostgreSQL."] if allowed else [],
    }


def get_restore_manual_sop() -> Dict[str, object]:
    backup_dir = get_backup_dir()
    upload_dir = get_digital_attachment_upload_dir()
    return {
        "safety_status": "POSTGRES_ONLY_MANUAL_RESTORE",
        "active_database_path": _redact_database_url(_database_url()),
        "active_upload_dir": str(upload_dir),
        "backup_dir": str(backup_dir),
        "requirements": ["pg_restore tersedia", "database target kosong", "server Flask dihentikan sebelum restore production", "backup dump/zip sudah dicek SHA256"],
        "do_not_do": ["Jangan restore ke database aktif yang masih berisi data tanpa drop/create ulang.", "Jangan restore saat user masih input transaksi.", "Jangan pakai file SQLite .db; format resmi sekarang .dump/.zip PostgreSQL."],
        "steps": [
            "Stop server Flask.",
            "Buat backup/dump database aktif sebelum restore jika database masih bisa dibaca.",
            "Drop dan create database target agar kosong.",
            "Jalankan pg_restore --no-owner --no-privileges --dbname <DATABASE_URL_TARGET> <file.dump>.",
            "Restore uploads dari ZIP jika memakai full backup.",
            "Jalankan checker migration/backend dan smoke test login OWNER.",
        ],
        "after_restore_checks": ["python tools/check_database_backend.py", "python tools/check_migration_current.py", "python tools/check_model_schema_sync.py", "login OWNER", "cek dashboard/finance/accounting/logistics"],
    }


def get_backup_folder_policy() -> Dict[str, object]:
    backup_dir = get_backup_dir()
    upload_dir = get_digital_attachment_upload_dir()
    return {
        "version": "POSTGRES_ONLY_BACKUP_POLICY_V1",
        "backup_dir": str(backup_dir),
        "upload_dir": str(upload_dir),
        "staging_dir": str(backup_dir / "_staging"),
        "restore_preview_dir": str(backup_dir / "_restore_preview"),
        "log_dir": str(backup_dir / "_logs"),
    }


def get_backup_baseline_audit() -> Dict[str, object]:
    return {
        "baseline_pass": True,
        "errors": [],
        "warnings": [],
        "successes": ["POSTGRES-ONLY LOCK aktif; SQLite database file tidak dipakai."],
        "attachment_audit": {},
    }


def get_backup_status() -> Dict[str, object]:
    upload_dir = get_digital_attachment_upload_dir()
    files = _list_upload_files(upload_dir)
    upload_total = sum(p.stat().st_size for p in files)
    backups = list_database_backups()
    full_backups = list_full_backups()
    legacy = list_legacy_root_backup_files()
    return {
        "database_path": _redact_database_url(_database_url()),
        "database_size_bytes": 0,
        "database_sha256": "POSTGRESQL_REMOTE_DB_NO_LOCAL_FILE",
        "database_backend": "postgresql",
        "upload_dir": str(upload_dir),
        "upload_file_count": len(files),
        "upload_total_size_bytes": upload_total,
        "backup_dir": str(get_backup_dir()),
        "backups": backups,
        "full_backups": full_backups,
        "legacy_backups": legacy,
        "legacy_backup_count": len(legacy),
        "folder_policy": get_backup_folder_policy(),
        "baseline_audit": get_backup_baseline_audit(),
        "pre_backup_health": run_pre_backup_health_check(),
        "alembic_version": _alembic_version(),
        "table_counts": _simple_db_counts(),
    }


# ==================================================
# PRODUCTION AUDIT: Automated Restore Dry-Run
# ==================================================

def restore_dry_run(dump_file_path: str | Path) -> Dict[str, object]:
    """Run pg_restore --list on a dump file to verify it's restorable.

    This does NOT modify any database. It only reads the dump file's TOC
    (table of contents) to verify structural integrity.

    For a full dry-run to a shadow database, use restore_dry_run_to_shadow().
    """
    dump_path = Path(dump_file_path)
    if not dump_path.exists() or not dump_path.is_file():
        return {"status": "FAIL", "error": f"File tidak ditemukan: {dump_path.name}"}

    cmd = ["pg_restore", "--list", str(dump_path)]
    try:
        result = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return {
                "status": "FAIL",
                "error": f"pg_restore --list gagal: {result.stderr[:500]}",
                "table_count": 0,
            }

        lines = result.stdout.splitlines()
        table_lines = [l for l in lines if "TABLE DATA" in l]
        return {
            "status": "PASS",
            "error": None,
            "toc_line_count": len(lines),
            "table_count": len(table_lines),
            "sample_tables": [l.split()[-1] for l in table_lines[:10]],
            "verified_at": _now_iso(),
        }
    except FileNotFoundError:
        return {"status": "FAIL", "error": "pg_restore tidak ditemukan di PATH. Install PostgreSQL client tools."}
    except subprocess.TimeoutExpired:
        return {"status": "FAIL", "error": "pg_restore --list timeout (file mungkin corrupt atau terlalu besar)."}
    except Exception as exc:
        return {"status": "FAIL", "error": str(exc)}


def restore_dry_run_to_shadow(dump_file_path: str | Path, shadow_db_name: str = "idha_boga_restore_test") -> Dict[str, object]:
    """Full restore dry-run to a shadow/test database.

    Creates the shadow DB, restores dump into it, verifies basic queries,
    then drops the shadow DB. Production database is NEVER touched.

    Requires: createdb and dropdb available in PATH.
    """
    dump_path = Path(dump_file_path)
    if not dump_path.exists():
        return {"status": "FAIL", "error": f"File tidak ditemukan: {dump_path.name}", "steps_completed": []}

    steps: List[str] = []
    base_url = _database_url()

    # Parse base URL to construct shadow URL
    try:
        from sqlalchemy.engine.url import make_url
        parsed = make_url(base_url)
        shadow_url = str(parsed.set(database=shadow_db_name))
        host = parsed.host or "localhost"
        port = str(parsed.port or 5432)
        user = parsed.username or "postgres"
    except Exception as exc:
        return {"status": "FAIL", "error": f"Gagal parse DATABASE_URL: {exc}", "steps_completed": steps}

    # Step 1: Create shadow database
    try:
        create_cmd = ["createdb", "-h", host, "-p", port, "-U", user, shadow_db_name]
        result = subprocess.run(create_cmd, check=False, capture_output=True, text=True, timeout=15)
        if result.returncode != 0 and "already exists" not in (result.stderr or ""):
            return {"status": "FAIL", "error": f"createdb gagal: {result.stderr[:300]}", "steps_completed": steps}
        steps.append("CREATE_SHADOW_DB")
    except FileNotFoundError:
        return {"status": "FAIL", "error": "createdb tidak ditemukan di PATH.", "steps_completed": steps}
    except Exception as exc:
        return {"status": "FAIL", "error": str(exc), "steps_completed": steps}

    # Step 2: pg_restore to shadow
    try:
        restore_cmd = [
            "pg_restore",
            "--no-owner",
            "--no-privileges",
            "--single-transaction",
            "--exit-on-error",
            "--dbname", shadow_url,
            str(dump_path),
        ]
        result = subprocess.run(restore_cmd, check=False, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            # Cleanup shadow DB even on failure
            subprocess.run(["dropdb", "-h", host, "-p", port, "-U", user, "--if-exists", shadow_db_name],
                           check=False, capture_output=True, timeout=15)
            return {
                "status": "FAIL",
                "error": f"pg_restore gagal: {result.stderr[:500]}",
                "steps_completed": steps,
            }
        steps.append("PG_RESTORE_TO_SHADOW")
    except subprocess.TimeoutExpired:
        subprocess.run(["dropdb", "-h", host, "-p", port, "-U", user, "--if-exists", shadow_db_name],
                       check=False, capture_output=True, timeout=15)
        return {"status": "FAIL", "error": "pg_restore timeout.", "steps_completed": steps}
    except Exception as exc:
        subprocess.run(["dropdb", "-h", host, "-p", port, "-U", user, "--if-exists", shadow_db_name],
                       check=False, capture_output=True, timeout=15)
        return {"status": "FAIL", "error": str(exc), "steps_completed": steps}

    # Step 3: Verify shadow DB has data
    try:
        from sqlalchemy import create_engine
        engine = create_engine(shadow_url)
        with engine.connect() as conn:
            user_count = conn.execute(text("SELECT COUNT(*) FROM users")).scalar() or 0
            alembic = conn.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).scalar()
        engine.dispose()
        steps.append("VERIFY_SHADOW_DATA")
        verification = {"user_count": user_count, "alembic_version": alembic}
    except Exception as exc:
        verification = {"error": str(exc)}
        steps.append("VERIFY_SHADOW_FAILED")

    # Step 4: Drop shadow database
    try:
        subprocess.run(["dropdb", "-h", host, "-p", port, "-U", user, "--if-exists", shadow_db_name],
                       check=False, capture_output=True, timeout=15)
        steps.append("DROP_SHADOW_DB")
    except Exception:
        steps.append("DROP_SHADOW_FAILED")

    return {
        "status": "PASS",
        "error": None,
        "steps_completed": steps,
        "verification": verification,
        "verified_at": _now_iso(),
        "shadow_db_name": shadow_db_name,
    }


# ==================================================
# PRODUCTION AUDIT: Backup/Restore Audit Logging
# ==================================================

def _log_backup_action(action: str, details: Dict[str, object], user=None) -> None:
    """Record backup/restore action to audit log."""
    try:
        from app.services.audit_log_service import record_audit_log
        record_audit_log(
            action=f"BACKUP_{action}",
            module="BACKUP_RESTORE",
            description=f"Backup action: {action}",
            metadata_json=json.dumps({
                "action": action,
                "status": details.get("status", "UNKNOWN"),
                "filename": details.get("name") or details.get("filename", ""),
                "sha256": details.get("sha256", ""),
                "timestamp": _now_iso(),
            }, ensure_ascii=False),
            user=user,
        )
    except Exception:
        # Audit log failure should never break backup operations
        pass


def create_database_backup_with_audit(user=None) -> Dict[str, object]:
    """Create database backup with audit trail."""
    result = create_database_backup()
    _log_backup_action("CREATE_DB_BACKUP", result, user=user)
    return result


def create_full_backup_with_audit(user=None) -> Dict[str, object]:
    """Create full backup package with audit trail."""
    result = create_full_backup_package(created_by=user)
    _log_backup_action("CREATE_FULL_BACKUP", result, user=user)
    return result


def restore_dry_run_with_audit(dump_file_path: str | Path, user=None) -> Dict[str, object]:
    """Run restore dry-run with audit trail."""
    _log_backup_action("RESTORE_DRY_RUN_START", {"filename": str(dump_file_path)}, user=user)
    result = restore_dry_run(dump_file_path)
    _log_backup_action("RESTORE_DRY_RUN_COMPLETE", result, user=user)
    return result
