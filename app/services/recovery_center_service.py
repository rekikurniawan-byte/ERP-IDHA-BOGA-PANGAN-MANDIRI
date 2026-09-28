"""PRODUCTION Recovery Center final polish service.

Service ini menyatukan status Kesehatan Sistem, verified backup, restore dry-run,
critical audit, atomic map, atomic smoke access, dan SOP recovery dalam satu
ringkasan read-only untuk owner/admin. Tidak ada restore aktif, overwrite DB,
migration, atau mutation data bisnis di service ini.
"""
from __future__ import annotations
import logging

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import or_

from app.models.system import AuditLog
from app.services.audit_log_service import (
    CRITICAL_AUDIT_POLICY_VERSION,
    get_audit_logs,
    get_audit_log_summary,
)
from app.services.atomic_failure_simulation_service import (
    ATOMIC_SMOKE_SCHEMA_VERSION,
    FAILURE_INJECTION_POLICY_VERSION,
)
from app.services.atomic_transaction_audit_map_service import build_atomic_transaction_audit_map
from app.services.backup_service import APP_VERSION as BACKUP_ENGINE_VERSION
from app.services.disaster_recovery_sop_service import (
    BACKUP_RESTORE_SOP_VERSION,
    DISASTER_RECOVERY_SOP_VERSION,
    RESTORE_DRILL_SOP_VERSION,
)
from app.services.system_health_service import (
    build_empty_system_health_report,
    build_system_health_report,
)

logger = logging.getLogger(__name__)


APP_VERSION = "PRODUCTION"
RECOVERY_CENTER_SCHEMA_VERSION = "PRODUCTION_RECOVERY_CENTER_FINAL_POLISH_V1"
RECOVERY_CENTER_POLICY_VERSION = "PRODUCTION_RECOVERY_CENTER_READONLY_POLICY_V1"


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _status_class(status: str) -> str:
    status = str(status or "").upper()
    if status in {"PASS", "AMAN", "OK", "READY", "VERIFIED"}:
        return "success"
    if status in {"WARNING", "PERLU CEK", "CHECK", "PENDING", "BELUM ADA", "RUN MANUAL"}:
        return "warning"
    return "danger"


def _decision_label(has_errors: bool, has_warnings: bool, has_verified_backup: bool, atomic_status: str) -> str:
    if has_errors:
        return "STOP PATCH"
    if not has_verified_backup:
        return "BACKUP DULU"
    if atomic_status in {"PERLU C2", "HIGH RISK", "PERLU REVIEW", "C2 BERJALAN"}:
        return "PATCH BERTAHAP"
    if has_warnings:
        return "BOLEH LANJUT DENGAN CATATAN"
    return "READY"


def _parse_iso_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        logger.exception("Suppressed unexpected exception in app/services/recovery_center_service.py:79")
        return None


def _backup_age_label(created_at: Any) -> Dict[str, Any]:
    dt = _parse_iso_datetime(created_at)
    if not dt:
        return {
            "label": "BELUM ADA",
            "status": "WARNING",
            "message": "Belum ada timestamp backup verified yang bisa dibaca.",
            "age_days": None,
        }

    now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
    age = now - dt
    days = max(age.days, 0)
    if age <= timedelta(days=1):
        status = "PASS"
        label = "SEGAR"
        message = "Backup verified masih sangat baru."
    elif age <= timedelta(days=7):
        status = "PASS"
        label = "MINGGU INI"
        message = "Backup verified masih dalam batas wajar mingguan."
    else:
        status = "WARNING"
        label = "PERLU BACKUP BARU"
        message = "Backup verified terakhir sudah lebih dari 7 hari. Buat backup baru sebelum patch besar."

    return {
        "label": label,
        "status": status,
        "message": message,
        "age_days": days,
    }


def _critical_audit_activity(branch_id: Optional[int] = None) -> Dict[str, Any]:
    logs = get_audit_logs(branch_id=branch_id, critical_only=True, limit=12)
    summary = get_audit_log_summary(logs)

    since = datetime.utcnow() - timedelta(days=7)
    query = AuditLog.query.filter(AuditLog.created_at >= since)
    if branch_id:
        query = query.filter(or_(AuditLog.branch_id == branch_id, AuditLog.branch_id.is_(None)))
    recent_count = query.count()

    return {
        "status": "PASS" if summary.get("critical", 0) >= 0 else "WARNING",
        "status_class": "success",
        "policy_version": CRITICAL_AUDIT_POLICY_VERSION,
        "recent_critical_logs": logs,
        "summary": summary,
        "last_7_days_total": recent_count,
        "message": "Critical audit aktif. Log terbaru bisa dibuka dari Audit Log Sistem.",
    }


def _build_readiness_cards(system_health: Dict[str, Any], atomic_map: Dict[str, Any], audit_activity: Dict[str, Any]) -> List[Dict[str, Any]]:
    overall = system_health.get("overall", {})
    rc = system_health.get("recovery_center", {})
    backup = system_health.get("backup", {})
    atomic_summary = atomic_map.get("summary", {})

    latest_backup_at = rc.get("latest_verified_backup_at") or rc.get("latest_verified_backup_at_display")
    age = _backup_age_label(latest_backup_at)
    atomic_status = atomic_summary.get("status") or atomic_map.get("overall_status") or "PERLU CEK"

    return [
        {
            "title": "Kesehatan Sistem",
            "value": overall.get("label", "PERLU CEK"),
            "detail": overall.get("summary", "Kesehatan Sistem belum terbaca."),
            "status": overall.get("label", "PERLU CEK"),
            "status_class": overall.get("status_class", "warning"),
            "endpoint": "settings.system_health",
            "action_label": "Buka Health",
            "icon": "bi-heart-pulse",
        },
        {
            "title": "Backup VERIFIED",
            "value": backup.get("verified_full_backup_count", 0),
            "detail": age.get("message"),
            "status": age.get("status"),
            "status_class": _status_class(age.get("status")),
            "endpoint": "settings.backups",
            "action_label": "Buka Backup",
            "owner_only": True,
            "icon": "bi-database-check",
        },
        {
            "title": "Restore Dry-run",
            "value": rc.get("latest_restore_dry_run_status", "BELUM ADA"),
            "detail": "Restore dry-run PASS adalah syarat backup dianggap aman dipakai.",
            "status": "PASS" if rc.get("latest_restore_dry_run_status") == "PASS" else "WARNING",
            "status_class": "success" if rc.get("latest_restore_dry_run_status") == "PASS" else "warning",
            "endpoint": "settings.backups",
            "action_label": "Cek Backup",
            "owner_only": True,
            "icon": "bi-arrow-counterclockwise",
        },
        {
            "title": "Atomic Guard",
            "value": atomic_status,
            "detail": atomic_summary.get("summary") or "Atomic map memantau flow transaksi yang sudah/belum guarded.",
            "status": "WARNING" if atomic_status in {"PERLU C2", "HIGH RISK", "PERLU REVIEW", "C2 BERJALAN"} else "PASS",
            "status_class": "warning" if atomic_status in {"PERLU C2", "HIGH RISK", "PERLU REVIEW", "C2 BERJALAN"} else "success",
            "endpoint": "settings.atomic_transaction_map",
            "action_label": "Buka Atomic Map",
            "owner_only": True,
            "icon": "bi-diagram-3",
        },
        {
            "title": "Critical Audit",
            "value": audit_activity.get("summary", {}).get("critical", 0),
            "detail": "Critical audit menyimpan severity, reason, reference, dan policy version tanpa migration.",
            "status": "PASS",
            "status_class": "success",
            "endpoint": "settings.audit_logs",
            "action_label": "Buka Audit",
            "owner_only": True,
            "icon": "bi-activity",
        },
        {
            "title": "SOP Recovery",
            "value": "TERSEDIA",
            "detail": "SOP disaster recovery, backup-restore, dan restore drill sudah masuk aplikasi.",
            "status": "PASS",
            "status_class": "success",
            "endpoint": "sop.disaster_recovery",
            "action_label": "Buka SOP",
            "icon": "bi-life-preserver",
        },
    ]


def _build_action_plan(system_health: Dict[str, Any], atomic_map: Dict[str, Any]) -> List[Dict[str, Any]]:
    overall = system_health.get("overall", {})
    rc = system_health.get("recovery_center", {})
    atomic_summary = atomic_map.get("summary", {})
    plan: List[Dict[str, Any]] = []

    if overall.get("error_count", 0) > 0:
        plan.append({
            "level": "danger",
            "title": "Stop patch besar dulu",
            "description": "Kesehatan Sistem masih punya error kritis. Selesaikan integrity/FK/upload/journal issue sebelum lanjut.",
            "endpoint": "settings.system_health",
            "action_label": "Lihat error",
        })

    if not rc.get("has_verified_backup"):
        plan.append({
            "level": "warning",
            "title": "Buat full backup VERIFIED",
            "description": "Belum ada full backup verified. Buat backup full DB + uploads sampai restore dry-run PASS.",
            "endpoint": "settings.backups",
            "action_label": "Buat backup",
            "owner_only": True,
        })

    if atomic_summary.get("status") in {"PERLU C2", "HIGH RISK", "PERLU REVIEW", "C2 BERJALAN"}:
        plan.append({
            "level": "warning",
            "title": "Patch atomic bertahap",
            "description": "Masih ada transaksi high risk. Lanjutkan atomic guard per modul prioritas, jangan refactor massal sekaligus.",
            "endpoint": "settings.atomic_transaction_map",
            "action_label": "Cek prioritas",
            "owner_only": True,
        })

    if overall.get("warning_count", 0) > 0:
        plan.append({
            "level": "info",
            "title": "Catat warning sebelum deploy",
            "description": "Warning tidak selalu blokir, tapi wajib dicatat sebelum patch atau restore planning.",
            "endpoint": "settings.system_health",
            "action_label": "Lihat warning",
        })

    plan.append({
        "level": "info",
        "title": "Jalankan restore drill berkala",
        "description": "Minimal sebelum patch besar atau mingguan: cek backup verified, restore preview, buka invoice/payment/delivery proof, dan validasi jurnal.",
        "endpoint": "sop.backup_restore",
        "action_label": "Buka SOP Drill",
    })

    return plan


def build_empty_recovery_center_report(error_message: str) -> Dict[str, Any]:
    health = build_empty_system_health_report(error_message)
    return {
        "schema_version": RECOVERY_CENTER_SCHEMA_VERSION,
        "policy_version": RECOVERY_CENTER_POLICY_VERSION,
        "app_version": APP_VERSION,
        "checked_at": _now_iso(),
        "overall": {
            "decision": "STOP PATCH",
            "status_class": "danger",
            "summary": "Recovery Center gagal dibaca penuh.",
            "errors": [error_message],
            "warnings": [],
        },
        "readiness_cards": [],
        "action_plan": [],
        "system_health": health,
        "atomic_map": {},
        "audit_activity": {},
        "sop_versions": {},
    }


def build_recovery_center_report(branch_id: Optional[int] = None) -> Dict[str, Any]:
    """Build final Recovery Center read-only report for PRODUCTION."""
    system_health = build_system_health_report()
    atomic_map = build_atomic_transaction_audit_map()
    audit_activity = _critical_audit_activity(branch_id=branch_id)

    overall = system_health.get("overall", {})
    rc = system_health.get("recovery_center", {})
    atomic_summary = atomic_map.get("summary", {})
    atomic_status = atomic_summary.get("status") or atomic_map.get("overall_status") or "PERLU CEK"
    decision = _decision_label(
        has_errors=overall.get("error_count", 0) > 0,
        has_warnings=overall.get("warning_count", 0) > 0,
        has_verified_backup=bool(rc.get("has_verified_backup")),
        atomic_status=atomic_status,
    )

    status_class = (
        "danger" if decision == "STOP PATCH" else
        "warning" if decision in {"BACKUP DULU", "PATCH BERTAHAP", "BOLEH LANJUT DENGAN CATATAN"} else
        "success"
    )

    readiness_cards = _build_readiness_cards(system_health, atomic_map, audit_activity)
    action_plan = _build_action_plan(system_health, atomic_map)

    return {
        "schema_version": RECOVERY_CENTER_SCHEMA_VERSION,
        "policy_version": RECOVERY_CENTER_POLICY_VERSION,
        "app_version": APP_VERSION,
        "checked_at": _now_iso(),
        "overall": {
            "decision": decision,
            "status_class": status_class,
            "summary": (
                "Recovery Center aman untuk monitoring. Tetap lakukan full backup verified sebelum patch besar."
                if decision == "READY"
                else "Recovery Center menemukan hal yang harus dicek sebelum patch/restore planning."
            ),
            "errors": overall.get("errors", []),
            "warnings": overall.get("warnings", []),
            "system_label": overall.get("label"),
            "system_status_class": overall.get("status_class"),
        },
        "readiness_cards": readiness_cards,
        "action_plan": action_plan,
        "system_health": system_health,
        "atomic_map": atomic_map,
        "audit_activity": audit_activity,
        "sop_versions": {
            "disaster_recovery": DISASTER_RECOVERY_SOP_VERSION,
            "backup_restore": BACKUP_RESTORE_SOP_VERSION,
            "restore_drill": RESTORE_DRILL_SOP_VERSION,
        },
        "policy_stack": {
            "backup_engine": BACKUP_ENGINE_VERSION,
            "atomic_smoke_schema": ATOMIC_SMOKE_SCHEMA_VERSION,
            "failure_injection_policy": FAILURE_INJECTION_POLICY_VERSION,
            "critical_audit_policy": CRITICAL_AUDIT_POLICY_VERSION,
        },
        "safety_rules": [
            "Halaman ini read-only: tidak restore aktif, tidak overwrite DB, tidak migration, dan tidak mengubah data bisnis.",
            "Active restore tetap manual-assisted dan harus mengikuti SOP setelah backup VERIFIED + dry-run PASS.",
            "Atomic smoke simulation tetap dijalankan dari halaman owner-only agar tidak berat di dashboard recovery.",
        ],
    }
