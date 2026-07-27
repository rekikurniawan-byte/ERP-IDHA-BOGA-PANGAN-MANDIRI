from __future__ import annotations
import logging

import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable
from urllib.parse import urlparse

from flask import current_app
from sqlalchemy import text

from app.extensions import db

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _project_root() -> Path:
    return Path(current_app.root_path).resolve().parent


def _safe_path(value: str | os.PathLike[str] | None, fallback: Path) -> Path:
    raw = Path(str(value or fallback))
    if not raw.is_absolute():
        raw = (_project_root() / raw).resolve()
    return raw.resolve()


def _database_backend(uri: str | None) -> str:
    if not uri:
        return "unknown"
    scheme = urlparse(uri).scheme.lower()
    if scheme.startswith("postgresql") or scheme.startswith("postgres"):
        return "postgresql"
    return scheme or "unknown"


def _check(name: str, ok: bool, message: str, *, details: Dict[str, Any] | None = None, critical: bool = True) -> Dict[str, Any]:
    return {
        "name": name,
        "status": "PASS" if ok else "FAIL",
        "ok": bool(ok),
        "critical": bool(critical),
        "message": message,
        "details": details or {},
    }


def _migration_heads() -> list[str]:
    versions_dir = _project_root() / "migrations" / "versions"
    revisions: set[str] = set()
    down_revisions: set[str] = set()
    if not versions_dir.exists():
        return []
    for file_path in versions_dir.glob("*.py"):
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        revision = re.search(r"revision\s*=\s*['\"]([^'\"]+)['\"]", content)
        if revision:
            revisions.add(revision.group(1))
        down = re.search(r"down_revision\s*=\s*([^\n]+)", content)
        if down:
            for item in re.findall(r"['\"]([^'\"]+)['\"]", down.group(1)):
                down_revisions.add(item)
    return sorted(revisions - down_revisions)


def _check_database() -> Dict[str, Any]:
    uri = current_app.config.get("SQLALCHEMY_DATABASE_URI")
    backend = _database_backend(uri)
    try:
        db.session.execute(text("SELECT 1"))
        ok = True
        message = f"Database reachable via backend {backend}."
    except Exception as exc:
        logger.exception("Suppressed unexpected exception in app/services/production_runtime_health_service.py:80")
        ok = False
        message = f"Database tidak reachable: {exc}"
    return _check("database_reachable", ok, message, details={"backend": backend})


def _check_migration() -> Dict[str, Any]:
    heads = _migration_heads()
    current = None
    try:
        row = db.session.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).fetchone()
        current = row[0] if row else None
    except Exception as exc:
        logger.exception("Suppressed unexpected exception in app/services/production_runtime_health_service.py:92")
        return _check("migration_current", False, f"alembic_version tidak bisa dibaca: {exc}", details={"head_revisions": heads})
    ok = bool(current and current in heads)
    return _check(
        "migration_current",
        ok,
        f"Migration current {current}; head {', '.join(heads) or '-'}.",
        details={"current_version": current, "head_revisions": heads},
    )


def _check_path(name: str, path: Path, *, must_be_private: bool = False) -> Dict[str, Any]:
    exists = path.exists() and path.is_dir()
    writable = exists and os.access(path, os.W_OK)
    public_static = False
    if must_be_private:
        try:
            public_static = (_project_root() / "app" / "static").resolve() in path.parents or path == (_project_root() / "app" / "static").resolve()
        except Exception:
            logger.exception("Suppressed unexpected exception in app/services/production_runtime_health_service.py:110")
            public_static = False
    ok = exists and writable and not public_static
    message = "Path tersedia dan writable."
    if not exists:
        message = "Path belum ada atau bukan folder."
    elif not writable:
        message = "Path tidak writable oleh app user."
    elif public_static:
        message = "Path berada di app/static; bukti digital production wajib private."
    return _check(name, ok, message, details={"path": str(path), "exists": exists, "writable": writable, "inside_static": public_static})


def _check_disk(paths: Iterable[Path]) -> Dict[str, Any]:
    min_free = int(current_app.config.get("HEALTH_DISK_MIN_FREE_BYTES") or (1024 * 1024 * 1024))
    checked = []
    ok = True
    for path in paths:
        target = path if path.exists() else path.parent
        try:
            usage = shutil.disk_usage(str(target))
            item_ok = usage.free >= min_free
            checked.append({"path": str(path), "free_bytes": usage.free, "total_bytes": usage.total, "required_bytes": min_free, "ok": item_ok})
            ok = ok and item_ok
        except Exception as exc:
            logger.exception("Suppressed unexpected exception in app/services/production_runtime_health_service.py:134")
            checked.append({"path": str(path), "error": str(exc), "ok": False})
            ok = False
    return _check("disk_space", ok, "Disk free space cukup." if ok else "Disk free space perlu dicek.", details={"checked_paths": checked})


def _check_journal_balance() -> Dict[str, Any]:
    try:
        exists = db.session.execute(text("SELECT 1 FROM information_schema.tables WHERE table_name='journal_details' LIMIT 1")).fetchone()
    except Exception as exc:
        logger.exception("Suppressed unexpected exception in app/services/production_runtime_health_service.py:143")
        return _check("journal_balance_quick", False, f"Tabel journal_details tidak bisa dicek: {exc}", critical=False)
    if not exists:
        return _check("journal_balance_quick", True, "Tabel journal_details belum ada/masih kosong untuk dicek.", critical=False)
    try:
        row = db.session.execute(text(
            """
            SELECT COUNT(*) FROM (
                SELECT journal_id
                FROM journal_details
                GROUP BY journal_id
                HAVING ABS(COALESCE(SUM(debit),0) - COALESCE(SUM(credit),0)) > 0.01
            ) AS imbalanced
            """
        )).fetchone()
        count = int(row[0] or 0)
        return _check("journal_balance_quick", count == 0, f"Journal imbalance count: {count}.", details={"imbalance_count": count}, critical=False)
    except Exception as exc:
        logger.exception("Suppressed unexpected exception in app/services/production_runtime_health_service.py:160")
        return _check("journal_balance_quick", False, f"Journal balance quick check gagal: {exc}", critical=False)


def build_healthz_payload() -> Dict[str, Any]:
    return {
        "status": "ok",
        "service": "idha-boga",
        "app_version": current_app.config.get("APP_VERSION"),
        "app_env": current_app.config.get("APP_ENV"),
        "checked_at_utc": _now(),
    }


def build_readiness_payload() -> Dict[str, Any]:
    upload_dir = _safe_path(current_app.config.get("DIGITAL_ATTACHMENT_UPLOAD_DIR"), _project_root() / "instance" / "uploads" / "digital_attachments")
    backup_root = _safe_path(current_app.config.get("BACKUP_ROOT"), _project_root() / "instance" / "backups")
    log_root = _safe_path(current_app.config.get("LOG_ROOT"), _project_root() / "instance" / "logs")
    db_check = _check_database()
    checks = [
        db_check,
        _check_migration(),
        _check_path("upload_storage_private_writable", upload_dir, must_be_private=True),
        _check_path("backup_storage_writable", backup_root),
        _check_path("log_storage_writable", log_root),
        _check_disk([upload_dir, backup_root, log_root]),
        _check_journal_balance(),
    ]

    backend = (db_check.get("details") or {}).get("backend")
    if current_app.config.get("HEALTH_REQUIRE_POSTGRES_IN_PRODUCTION") and current_app.config.get("IS_PRODUCTION"):
        checks.append(_check("postgres_required_in_production", backend == "postgresql", "Production final harus memakai PostgreSQL."))

    critical_failed = [item for item in checks if item.get("critical") and not item.get("ok")]
    status = "ready" if not critical_failed else "not_ready"
    return {
        "status": status,
        "service": "idha-boga",
        "app_version": current_app.config.get("APP_VERSION"),
        "app_env": current_app.config.get("APP_ENV"),
        "checked_at_utc": _now(),
        "critical_failed_count": len(critical_failed),
        "checks": checks,
    }
