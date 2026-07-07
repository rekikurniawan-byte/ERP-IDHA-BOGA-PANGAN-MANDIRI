from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from flask import current_app

from app.services.backup_service import (
    APP_VERSION as BACKUP_ENGINE_VERSION,
    get_backup_status,
)
from app.services.sensitive_action_guard_service import GUARD_POLICY_VERSION


SYSTEM_HEALTH_VERSION = "PRODUCTION"
SYSTEM_HEALTH_SCHEMA_VERSION = "PRODUCTION_SYSTEM_HEALTH_RECOVERY_CENTER_SCHEMA_V2"


STATUS_SAFE = "AMAN"
STATUS_CHECK = "PERLU CEK"
STATUS_DANGER = "BAHAYA"


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value or default)
    except Exception:
        return default


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value or default)
    except Exception:
        return default


def _project_root() -> Path:
    return Path(current_app.root_path).resolve().parent


def _status_class(status: str) -> str:
    if status in {"PASS", "AMAN", "OK", "VERIFIED"}:
        return "success"
    if status in {"WARNING", "PERLU CEK", "PENDING", "BELUM ADA"}:
        return "warning"
    return "danger"


def _severity_from_status(status: str) -> str:
    if status in {"PASS", "AMAN", "OK", "VERIFIED"}:
        return "success"
    if status in {"WARNING", "PERLU CEK", "PENDING", "BELUM ADA"}:
        return "warning"
    return "danger"


def _find_check(checks: Iterable[Dict[str, object]], code: str) -> Dict[str, object]:
    for item in checks or []:
        if item.get("code") == code:
            return item
    return {}


def _make_check(label: str, status: str, value: object = "-", message: str = "", details: Dict[str, object] | None = None) -> Dict[str, object]:
    return {
        "label": label,
        "status": status,
        "status_class": _status_class(status),
        "severity": _severity_from_status(status),
        "value": value,
        "message": message,
        "details": details or {},
    }


def _parse_migration_metadata(migrations_dir: Path) -> Dict[str, object]:
    revisions: Dict[str, Dict[str, object]] = {}
    down_revisions: set[str] = set()

    if not migrations_dir.exists() or not migrations_dir.is_dir():
        return {
            "migration_files_found": False,
            "revision_count": 0,
            "head_revisions": [],
            "revisions": {},
        }

    for file_path in sorted(migrations_dir.glob("*.py")):
        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception:
            continue

        revision_match = re.search(r"revision\s*=\s*['\"]([^'\"]+)['\"]", content)
        if not revision_match:
            continue
        revision = revision_match.group(1)

        down_match = re.search(r"down_revision\s*=\s*([^\n]+)", content)
        file_down_revisions: List[str] = []
        if down_match:
            raw_down = down_match.group(1).strip()
            if raw_down not in {"None", ""}:
                file_down_revisions = re.findall(r"['\"]([^'\"]+)['\"]", raw_down)
                down_revisions.update(file_down_revisions)

        revisions[revision] = {
            "revision": revision,
            "down_revisions": file_down_revisions,
            "filename": file_path.name,
        }

    heads = sorted(revision for revision in revisions if revision not in down_revisions)
    return {
        "migration_files_found": True,
        "revision_count": len(revisions),
        "head_revisions": heads,
        "revisions": revisions,
    }


def _build_migration_health(alembic_version: str | None) -> Dict[str, object]:
    migrations_dir = _project_root() / "migrations" / "versions"
    parsed = _parse_migration_metadata(migrations_dir)
    heads = list(parsed.get("head_revisions") or [])
    current = alembic_version or None

    if not parsed.get("migration_files_found"):
        status = "WARNING"
        message = "Folder migrations/versions tidak ditemukan; pending migration tidak bisa dipastikan."
    elif not current:
        status = "WARNING"
        message = "Tabel alembic_version kosong/tidak tersedia; versi migration DB tidak bisa dipastikan."
    elif current in heads:
        status = "PASS"
        message = f"DB berada pada migration head aktif: {current}."
    elif current in (parsed.get("revisions") or {}):
        status = "WARNING"
        message = f"DB berada di revision {current}, tetapi head migration saat ini {', '.join(heads) or '-'}. Cek apakah ada migration pending."
    else:
        status = "WARNING"
        message = f"Revision DB {current} tidak ditemukan di file migrations/versions. Cek sinkronisasi migration."

    return {
        "status": status,
        "status_class": _status_class(status),
        "current_version": current,
        "head_revisions": heads,
        "head_revision": heads[0] if len(heads) == 1 else None,
        "revision_count": parsed.get("revision_count", 0),
        "message": message,
        "migrations_dir": str(migrations_dir),
    }


def _extract_latest_backup(backups: List[Dict[str, object]], verified_only: bool = False) -> Dict[str, object] | None:
    for backup in backups or []:
        if verified_only and not backup.get("is_verified_backup"):
            continue
        return backup
    return None


def _build_backup_health(backup_status: Dict[str, object]) -> Dict[str, object]:
    full_backups = list(backup_status.get("full_backups") or [])
    db_backups = list(backup_status.get("backups") or [])
    latest_full = _extract_latest_backup(full_backups)
    latest_verified = _extract_latest_backup(full_backups, verified_only=True)

    verified_count = sum(1 for item in full_backups if item.get("is_verified_backup"))
    unverified_count = max(len(full_backups) - verified_count, 0)
    latest_restore_status = None
    latest_restore_checked_at = None
    if latest_verified:
        latest_restore_status = latest_verified.get("restore_dry_run_status")
        latest_restore_checked_at = latest_verified.get("restore_dry_run_checked_at")
    elif latest_full:
        latest_restore_status = latest_full.get("restore_dry_run_status")
        latest_restore_checked_at = latest_full.get("restore_dry_run_checked_at")

    if latest_verified:
        status = "PASS"
        message = "Minimal satu full backup VERIFIED tersedia."
    elif full_backups:
        status = "WARNING"
        message = "Full backup tersedia, tetapi belum ada yang VERIFIED."
    else:
        status = "WARNING"
        message = "Belum ada full backup di folder policy aktif."

    return {
        "status": status,
        "status_class": _status_class(status),
        "message": message,
        "full_backup_count": len(full_backups),
        "database_backup_count": len(db_backups),
        "verified_full_backup_count": verified_count,
        "unverified_full_backup_count": unverified_count,
        "latest_full_backup": latest_full,
        "latest_verified_backup": latest_verified,
        "latest_restore_dry_run_status": latest_restore_status or "BELUM ADA",
        "latest_restore_dry_run_checked_at": latest_restore_checked_at,
        "legacy_backup_count": _safe_int(backup_status.get("legacy_backup_count")),
    }


def _build_disk_health(precheck: Dict[str, object], backup_status: Dict[str, object]) -> Dict[str, object]:
    disk = dict(precheck.get("disk_space") or {})
    if not disk:
        try:
            usage = shutil.disk_usage(str(backup_status.get("backup_dir") or _project_root()))
            disk = {
                "ok": usage.free > 0,
                "free_bytes": usage.free,
                "total_bytes": usage.total,
                "used_bytes": usage.used,
                "message": "Disk usage dibaca dari folder backup aktif.",
            }
        except Exception as exc:
            return {
                "status": "WARNING",
                "status_class": "warning",
                "message": f"Disk free space tidak bisa dibaca: {exc}",
                "free_bytes": 0,
                "total_bytes": 0,
            }

    status = "PASS" if disk.get("ok") else "FAIL"
    return {
        "status": status,
        "status_class": _status_class(status),
        "message": disk.get("message") or ("Disk free space PASS." if disk.get("ok") else "Disk free space tidak cukup."),
        "free_bytes": _safe_int(disk.get("free_bytes")),
        "total_bytes": _safe_int(disk.get("total_bytes")),
        "required_bytes": _safe_int(disk.get("required_bytes")),
        "details": disk,
    }


def _build_overall_status(
    *,
    precheck: Dict[str, object],
    baseline: Dict[str, object],
    backup_health: Dict[str, object],
    migration_health: Dict[str, object],
) -> Dict[str, object]:
    errors: List[str] = []
    warnings: List[str] = []

    if precheck.get("status") != "PASS" or not precheck.get("can_create_backup"):
        errors.extend(str(item) for item in (precheck.get("errors") or ["Pre-backup health check belum PASS."]))

    if baseline.get("baseline_pass") is False:
        errors.extend(str(item) for item in (baseline.get("errors") or []))
        warnings.extend(str(item) for item in (baseline.get("warnings") or []))

    if backup_health.get("verified_full_backup_count", 0) <= 0:
        warnings.append("Belum ada full backup VERIFIED di folder backup aktif.")

    if backup_health.get("legacy_backup_count", 0) > 0:
        warnings.append(f"Ada {backup_health.get('legacy_backup_count')} file legacy di root backups/. Backup baru tetap memakai instance/backups.")

    if migration_health.get("status") != "PASS":
        warnings.append(str(migration_health.get("message") or "Migration state perlu dicek."))

    # Remove duplicates while preserving order.
    errors = list(dict.fromkeys(errors))
    warnings = list(dict.fromkeys(warnings))

    if errors:
        label = STATUS_DANGER
    elif warnings:
        label = STATUS_CHECK
    else:
        label = STATUS_SAFE

    return {
        "label": label,
        "status_class": _status_class(label),
        "errors": errors,
        "warnings": warnings,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "summary": (
            "Sistem perlu tindakan segera sebelum backup/patch besar." if errors else
            "Sistem berjalan, tetapi ada warning yang perlu diawasi." if warnings else
            "Sistem read-only health check aman. Backup verified tersedia."
        ),
    }


def build_empty_system_health_report(error: str) -> Dict[str, object]:
    return {
        "schema_version": SYSTEM_HEALTH_SCHEMA_VERSION,
        "app_version": SYSTEM_HEALTH_VERSION,
        "backup_engine_version": BACKUP_ENGINE_VERSION,
        "checked_at": _now_iso(),
        "overall": {
            "label": STATUS_DANGER,
            "status_class": "danger",
            "summary": "System Health gagal dibaca.",
            "errors": [error],
            "warnings": [],
            "error_count": 1,
            "warning_count": 0,
        },
        "metrics": [],
        "check_groups": [],
        "backup_status": {},
    }


def build_system_health_report() -> Dict[str, object]:
    """Build read-only system health summary for PRODUCTION.

    This function must not mutate database, uploads, backup ZIPs, or migration files.
    It only reads the active PostgreSQL DB, backup metadata, upload references, disk info,
    and Alembic migration files.
    """
    backup_status = get_backup_status()
    precheck = dict(backup_status.get("pre_backup_health") or {})
    baseline = dict(backup_status.get("baseline_audit") or {})
    checks = list(precheck.get("checks") or [])
    attachment_audit = dict((precheck.get("attachment_audit") or baseline.get("attachment_audit") or {}))
    folder_policy = dict(precheck.get("folder_policy") or backup_status.get("folder_policy") or {})
    journal_balance = dict(precheck.get("journal_balance") or {})
    db_info = dict(precheck.get("database") or {})
    summary = dict(precheck.get("summary") or {})

    alembic_version = summary.get("alembic_version") or backup_status.get("alembic_version")
    migration_health = _build_migration_health(alembic_version)
    backup_health = _build_backup_health(backup_status)
    disk_health = _build_disk_health(precheck, backup_status)
    overall = _build_overall_status(
        precheck=precheck,
        baseline=baseline,
        backup_health=backup_health,
        migration_health=migration_health,
    )

    db_integrity_check = _find_check(checks, "POSTGRES_REACHABLE")
    db_fk_check = _find_check(checks, "DATABASE_URL_POSTGRES")
    db_lock_check = _find_check(checks, "DB_LOCK")
    db_readable_check = _find_check(checks, "DB_READABLE")
    folder_check = _find_check(checks, "FOLDER_POLICY")
    upload_folder_check = _find_check(checks, "UPLOADS_FOLDER")
    missing_upload_check = _find_check(checks, "MISSING_UPLOAD_REFERENCE")
    upload_checksum_check = _find_check(checks, "UPLOAD_CHECKSUM")
    orphan_upload_check = _find_check(checks, "ORPHAN_UPLOAD_FILE")

    latest_verified = backup_health.get("latest_verified_backup") or {}
    latest_full = backup_health.get("latest_full_backup") or {}

    metrics = [
        {
            "label": "Overall",
            "value": overall.get("label"),
            "detail": overall.get("summary"),
            "status_class": overall.get("status_class"),
        },
        {
            "label": "Backup VERIFIED",
            "value": backup_health.get("verified_full_backup_count", 0),
            "detail": f"Total full backup: {backup_health.get('full_backup_count', 0)}",
            "status_class": backup_health.get("status_class"),
        },
        {
            "label": "Upload fisik",
            "value": backup_status.get("upload_file_count", 0),
            "detail": f"Missing: {attachment_audit.get('missing_reference_count', 0)} · Orphan: {attachment_audit.get('orphan_file_count', 0)}",
            "status_class": "danger" if attachment_audit.get("missing_reference_count") else ("warning" if attachment_audit.get("orphan_file_count") else "success"),
        },
        {
            "label": "Journal imbalance",
            "value": journal_balance.get("imbalance_count", 0),
            "detail": journal_balance.get("message") or "Journal balance check.",
            "status_class": "success" if journal_balance.get("ok", True) else "danger",
        },
    ]

    check_groups = [
        {
            "title": "Database",
            "description": "Kesehatan PostgreSQL aktif tanpa mengubah data.",
            "items": [
                _make_check("PostgreSQL reachable", str(db_integrity_check.get("status") or "WARNING"), message=str(db_integrity_check.get("message") or "Integrity check belum tersedia.")),
                _make_check("Foreign key", str(db_fk_check.get("status") or "WARNING"), message=str(db_fk_check.get("message") or "FK check belum tersedia.")),
                _make_check("DB readable", str(db_readable_check.get("status") or "WARNING"), message=str(db_readable_check.get("message") or "DB readable belum tersedia.")),
                _make_check("DB locked/busy", str(db_lock_check.get("status") or "WARNING"), message=str(db_lock_check.get("message") or "DB lock check belum tersedia.")),
                _make_check("Journal balance", "PASS" if journal_balance.get("ok", True) else "FAIL", value=journal_balance.get("imbalance_count", 0), message=str(journal_balance.get("message") or "Journal balance check."), details=journal_balance),
                _make_check("Alembic migration", str(migration_health.get("status")), value=migration_health.get("current_version") or "-", message=str(migration_health.get("message")), details=migration_health),
            ],
        },
        {
            "title": "Backup & Restore",
            "description": "Status backup aktif di instance/backups dan restore preview dry-run.",
            "items": [
                _make_check("Full backup VERIFIED", "PASS" if backup_health.get("verified_full_backup_count", 0) > 0 else "WARNING", value=backup_health.get("verified_full_backup_count", 0), message=str(backup_health.get("message")), details=backup_health),
                _make_check("Latest full backup", "PASS" if latest_full else "WARNING", value=(latest_full or {}).get("name", "BELUM ADA"), message=f"Status: {(latest_full or {}).get('verification_status') or '-'}"),
                _make_check("Latest restore dry-run", "PASS" if backup_health.get("latest_restore_dry_run_status") == "PASS" else "WARNING", value=backup_health.get("latest_restore_dry_run_status"), message=f"Checked at: {backup_health.get('latest_restore_dry_run_checked_at') or '-'}"),
                _make_check("Backup folder policy", str(folder_check.get("status") or ("PASS" if folder_policy.get("policy_pass") else "FAIL")), value=folder_policy.get("backup_dir") or backup_status.get("backup_dir") or "-", message=str(folder_check.get("message") or "Folder policy check."), details=folder_policy),
                _make_check("Legacy root backups", "WARNING" if backup_health.get("legacy_backup_count", 0) else "PASS", value=backup_health.get("legacy_backup_count", 0), message="Legacy backup hanya untuk audit/import; backup baru tetap instance/backups."),
            ],
        },
        {
            "title": "Uploads & Lampiran Digital",
            "description": "Konsistensi metadata digital_attachments dengan file fisik private.",
            "items": [
                _make_check("Uploads folder", str(upload_folder_check.get("status") or "WARNING"), value=backup_status.get("upload_dir") or "-", message=str(upload_folder_check.get("message") or "Uploads folder check.")),
                _make_check("Missing upload reference", str(missing_upload_check.get("status") or ("PASS" if not attachment_audit.get("missing_reference_count") else "FAIL")), value=attachment_audit.get("missing_reference_count", 0), message=str(missing_upload_check.get("message") or "Missing upload reference check."), details=attachment_audit),
                _make_check("Upload checksum", str(upload_checksum_check.get("status") or ("PASS" if not attachment_audit.get("checksum_mismatch_count") else "FAIL")), value=attachment_audit.get("checksum_mismatch_count", 0), message=str(upload_checksum_check.get("message") or "Upload checksum check."), details=attachment_audit),
                _make_check("Orphan upload file", str(orphan_upload_check.get("status") or ("PASS" if not attachment_audit.get("orphan_file_count") else "WARNING")), value=attachment_audit.get("orphan_file_count", 0), message=str(orphan_upload_check.get("message") or "Orphan upload check."), details=attachment_audit),
            ],
        },
        {
            "title": "Storage & Runtime",
            "description": "Ruang disk, versi release, dan arah patch berikutnya.",
            "items": [
                _make_check("Disk free space", str(disk_health.get("status")), value=disk_health.get("free_bytes", 0), message=str(disk_health.get("message")), details=disk_health),
                _make_check("System Health schema", "PASS", value=SYSTEM_HEALTH_SCHEMA_VERSION, message="PRODUCTION read-only health report aktif."),
                _make_check("Backup engine", "PASS", value=BACKUP_ENGINE_VERSION, message="Backup engine B3 tetap menjadi sumber verifikasi backup."),
                _make_check("Sensitive action guard", "PASS", value=GUARD_POLICY_VERSION, message="Aksi backup, user, company setting, dan hapus lampiran digital wajib reason + password re-confirm."),
                _make_check("Active DB hash", "PASS", value=backup_status.get("database_sha256") or "-", message="Hash database aktif dibaca read-only."),
            ],
        },
    ]

    latest_verified_at = (latest_verified or {}).get("created_at")
    if hasattr(latest_verified_at, "strftime"):
        latest_verified_at_display = latest_verified_at.strftime("%d/%m/%Y %H:%M:%S")
    else:
        latest_verified_at_display = str(latest_verified_at) if latest_verified_at else None

    recovery_center = {
        "is_system_safe": overall.get("label") == STATUS_SAFE,
        "can_create_backup": bool(precheck.get("can_create_backup")),
        "has_verified_backup": backup_health.get("verified_full_backup_count", 0) > 0,
        "latest_verified_backup_name": (latest_verified or {}).get("name"),
        "latest_verified_backup_at": latest_verified_at,
        "latest_verified_backup_at_display": latest_verified_at_display,
        "latest_restore_dry_run_status": backup_health.get("latest_restore_dry_run_status"),
        "missing_upload_references": attachment_audit.get("missing_reference_count", 0),
        "orphan_upload_files": attachment_audit.get("orphan_file_count", 0),
        "journal_imbalance_count": journal_balance.get("imbalance_count", 0),
        "migration_status": migration_health.get("status"),
    }

    return {
        "schema_version": SYSTEM_HEALTH_SCHEMA_VERSION,
        "app_version": SYSTEM_HEALTH_VERSION,
        "backup_engine_version": BACKUP_ENGINE_VERSION,
        "checked_at": _now_iso(),
        "overall": overall,
        "metrics": metrics,
        "check_groups": check_groups,
        "database": {
            "path": backup_status.get("database_path"),
            "size_bytes": backup_status.get("database_size_bytes", 0),
            "sha256": backup_status.get("database_sha256"),
            "info": db_info,
        },
        "uploads": {
            "path": backup_status.get("upload_dir"),
            "file_count": backup_status.get("upload_file_count", 0),
            "total_size_bytes": backup_status.get("upload_total_size_bytes", 0),
            "audit": attachment_audit,
        },
        "backup": backup_health,
        "disk": disk_health,
        "migration": migration_health,
        "recovery_center": recovery_center,
        "backup_status": backup_status,
        "pre_backup_health": precheck,
        "baseline_audit": baseline,
    }
