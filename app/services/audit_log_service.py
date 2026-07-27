import logging
import json
from datetime import datetime

from flask import has_request_context, request
from flask_login import current_user
from sqlalchemy import or_

from app.extensions import db
from app.models.system import AuditLog

logger = logging.getLogger(__name__)


APP_VERSION = "PRODUCTION"
AUDIT_SCHEMA_VERSION = "PRODUCTION_AUDIT_LOG_SCHEMA_V1"
CRITICAL_AUDIT_POLICY_VERSION = "PRODUCTION_CRITICAL_AUDIT_EXPANSION_V1"
SEVERITY_LEVELS = ("INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL")
CRITICAL_SEVERITIES = ("HIGH", "CRITICAL")

# Tanpa migration: severity, reason, reference_type, dan critical flag disimpan
# di metadata_json agar tabel audit existing tetap aman dipakai.
_CRITICAL_KEYWORDS = (
    "SENSITIVE",
    "RESTORE",
    "BACKUP",
    "USER_",
    "ROLE",
    "PASSWORD",
    "COMPANY_SETTING",
    "BANK_ACCOUNT",
    "JOURNAL",
    "POSTING",
    "PERIOD_CLOSING",
    "PAYMENT",
    "INVOICE_CANCEL",
    "CANCEL",
    "DELETE",
    "SOFT_DELETED",
    "STOCK_ADJUSTMENT",
    "PROCUREMENT",
    "SUPPLIER_BILL",
    "SUPPLIER_PAYMENT",
    "PAYROLL",
    "FIXED_ASSET",
    "LOGIN_FAILED",
)

def _safe_json(value):
    if value is None:
        return None
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        logger.exception("Suppressed unexpected exception in app/services/audit_log_service.py:53")
        return str(value)


def _metadata_to_dict(value):
    if value in (None, ""):
        return {}
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
            return decoded if isinstance(decoded, dict) else {"raw_metadata": decoded}
        except Exception:
            logger.exception("Suppressed unexpected exception in app/services/audit_log_service.py:66")
            return {"raw_metadata": value}
    return {"raw_metadata": str(value)}


def _normalize_severity(value):
    value = str(value or "INFO").strip().upper()
    return value if value in SEVERITY_LEVELS else "INFO"


def _extract_reason(metadata):
    if not isinstance(metadata, dict):
        return ""
    for key in ("reason", "delete_note", "guard_reason", "sensitive_reason"):
        value = metadata.get(key)
        if value:
            return str(value)
    guard = metadata.get("sensitive_guard")
    if isinstance(guard, dict):
        value = guard.get("reason") or guard.get("delete_note")
        if value:
            return str(value)
    target = metadata.get("target")
    if isinstance(target, dict):
        value = target.get("reason")
        if value:
            return str(value)
    return ""


def _critical_keyword_hit(module, event_type, action):
    combined = f"{module or ''} {event_type or ''} {action or ''}".upper()
    return any(keyword in combined for keyword in _CRITICAL_KEYWORDS)


def _infer_severity(module, event_type, action, metadata):
    if isinstance(metadata, dict) and metadata.get("severity"):
        return _normalize_severity(metadata.get("severity"))

    text = f"{module or ''} {event_type or ''} {action or ''}".upper()
    if any(token in text for token in ("RESTORE", "ROLE", "PASSWORD", "USER_STATUS", "DELETE", "CANCEL", "PERIOD_CLOSING", "BANK_ACCOUNT")):
        return "CRITICAL"
    if any(token in text for token in ("BACKUP", "JOURNAL", "POSTING", "PAYMENT", "PAYROLL", "COMPANY_SETTING", "STOCK_ADJUSTMENT", "PROCUREMENT", "SUPPLIER", "FIXED_ASSET")):
        return "HIGH"
    if any(token in text for token in ("LOGIN_FAILED", "FAILED", "FAIL", "DENIED")):
        return "MEDIUM"
    if _critical_keyword_hit(module, event_type, action):
        return "HIGH"
    return "INFO"


def _is_critical_event(module, event_type, action, metadata):
    if isinstance(metadata, dict) and metadata.get("critical_audit") is not None:
        return bool(metadata.get("critical_audit"))
    return _infer_severity(module, event_type, action, metadata) in CRITICAL_SEVERITIES or _critical_keyword_hit(module, event_type, action)


def _enrich_audit_metadata(module, event_type, action, metadata, *, severity=None, reason=None, reference_type=None, reference_id=None, critical_audit=None, policy_scope=None):
    data = _metadata_to_dict(metadata)
    inferred_severity = _normalize_severity(severity or data.get("severity") or _infer_severity(module, event_type, action, data))
    inferred_critical = _is_critical_event(module, event_type, action, data) if critical_audit is None else bool(critical_audit)
    extracted_reason = reason if reason is not None else _extract_reason(data)

    data.setdefault("audit_schema_version", AUDIT_SCHEMA_VERSION)
    data.setdefault("app_version", APP_VERSION)
    data.setdefault("critical_audit_policy_version", CRITICAL_AUDIT_POLICY_VERSION)
    data.setdefault("critical_audit", inferred_critical)
    data.setdefault("severity", inferred_severity)
    data.setdefault("reason", extracted_reason or "")
    data.setdefault("reference_type", reference_type or data.get("reference_type"))
    data.setdefault("reference_id", reference_id if reference_id is not None else data.get("reference_id"))
    data.setdefault("policy_scope", policy_scope or ("CRITICAL_DATA_CHANGE" if inferred_critical else "GENERAL_AUDIT"))
    data.setdefault("audit_note", "PRODUCTION menyimpan severity/reason/reference di metadata_json tanpa migration.")
    return data


def _truncate(value, limit):
    if value is None:
        return None
    value = str(value)
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def _current_user_snapshot():
    if not has_request_context():
        return None, None, None, None

    try:
        if current_user and current_user.is_authenticated:
            return (
                getattr(current_user, "id", None),
                getattr(current_user, "branch_id", None),
                getattr(current_user, "username", None),
                getattr(current_user, "role", None),
            )
    except Exception:
        logger.exception("Suppressed unexpected exception in app/services/audit_log_service.py:163")
        pass

    return None, None, None, None


def record_audit_log(
    *,
    module,
    event_type,
    action="INFO",
    description=None,
    table_name=None,
    record_id=None,
    old_value=None,
    new_value=None,
    metadata=None,
    user_id=None,
    branch_id=None,
    username_snapshot=None,
    user_role_snapshot=None,
    commit=True,
):
    """Write audit log without breaking the main business flow.

    Service ini sengaja defensive: kalau audit log gagal, transaksi utama tidak ikut
    dianggap gagal. Panggil setelah transaksi utama berhasil commit untuk event yang
    memang sudah tersimpan.
    """
    fallback_user_id, fallback_branch_id, fallback_username, fallback_role = _current_user_snapshot()

    if user_id is None:
        user_id = fallback_user_id
    if branch_id is None:
        branch_id = fallback_branch_id
    if username_snapshot is None:
        username_snapshot = fallback_username
    if user_role_snapshot is None:
        user_role_snapshot = fallback_role

    ip_address = None
    user_agent = None
    if has_request_context():
        ip_address = request.headers.get("X-Forwarded-For", request.remote_addr)
        if ip_address and "," in ip_address:
            ip_address = ip_address.split(",", 1)[0].strip()
        user_agent = request.headers.get("User-Agent")

    metadata = _enrich_audit_metadata(module, event_type, action, metadata)

    log = AuditLog(
        branch_id=branch_id,
        user_id=user_id,
        username_snapshot=_truncate(username_snapshot, 100),
        user_role_snapshot=_truncate(user_role_snapshot, 50),
        module=_truncate(module or "SYSTEM", 80),
        event_type=_truncate(event_type or "GENERAL", 100),
        table_name=_truncate(table_name, 100),
        record_id=record_id,
        action=_truncate(action or "INFO", 50),
        description=description,
        old_value=_safe_json(old_value),
        new_value=_safe_json(new_value),
        metadata_json=_safe_json(metadata),
        ip_address=_truncate(ip_address, 80),
        user_agent=_truncate(user_agent, 255),
        created_at=datetime.utcnow(),
    )

    try:
        db.session.add(log)
        if commit:
            db.session.commit()
        return log
    except Exception:
        logger.exception("Suppressed unexpected exception in app/services/audit_log_service.py:237")
        db.session.rollback()
        return None


def record_critical_audit_log(
    *,
    module,
    event_type,
    action="CRITICAL",
    description=None,
    table_name=None,
    record_id=None,
    old_value=None,
    new_value=None,
    metadata=None,
    severity="HIGH",
    reason=None,
    reference_type=None,
    reference_id=None,
    policy_scope="CRITICAL_DATA_CHANGE",
    user_id=None,
    branch_id=None,
    username_snapshot=None,
    user_role_snapshot=None,
    commit=True,
):
    """Record critical audit event using existing audit_logs table.

    PRODUCTION sengaja tidak membuat migration. Semua field tambahan disimpan di
    metadata_json agar kompatibel dengan database aktif.
    """
    enriched_metadata = _enrich_audit_metadata(
        module,
        event_type,
        action,
        metadata,
        severity=severity,
        reason=reason,
        reference_type=reference_type or table_name,
        reference_id=reference_id if reference_id is not None else record_id,
        critical_audit=True,
        policy_scope=policy_scope,
    )
    return record_audit_log(
        module=module,
        event_type=event_type,
        action=action,
        description=description,
        table_name=table_name,
        record_id=record_id,
        old_value=old_value,
        new_value=new_value,
        metadata=enriched_metadata,
        user_id=user_id,
        branch_id=branch_id,
        username_snapshot=username_snapshot,
        user_role_snapshot=user_role_snapshot,
        commit=commit,
    )


def _decode_json_text(value):
    """Return parsed JSON if possible, otherwise raw text."""
    if value in (None, ""):
        return None
    try:
        return json.loads(value)
    except Exception:
        logger.exception("Suppressed unexpected exception in app/services/audit_log_service.py:305")
        return value


def _pretty_json_text(value):
    """Pretty string for UI display without changing stored value."""
    decoded = _decode_json_text(value)
    if decoded is None:
        return None
    if isinstance(decoded, (dict, list)):
        return json.dumps(decoded, ensure_ascii=False, indent=2, default=str)
    return str(decoded)


def _decorate_log_for_ui(log):
    if not log:
        return log
    metadata = _metadata_to_dict(getattr(log, "metadata_json", None))
    severity = _normalize_severity(metadata.get("severity") or _infer_severity(log.module, log.event_type, log.action, metadata))
    reason = _extract_reason(metadata)
    is_critical = _is_critical_event(log.module, log.event_type, log.action, metadata)
    reference_type = metadata.get("reference_type") or log.table_name
    reference_id = metadata.get("reference_id") if metadata.get("reference_id") is not None else log.record_id

    # Transient attributes for Jinja only. They are not database columns.
    log.audit_metadata = metadata
    log.audit_severity = severity
    log.audit_reason = reason
    log.audit_is_critical = is_critical
    log.audit_reference_type = reference_type
    log.audit_reference_id = reference_id
    log.audit_policy_version = metadata.get("critical_audit_policy_version") or CRITICAL_AUDIT_POLICY_VERSION
    return log


def _apply_audit_ui_filters(logs, *, severity=None, critical_only=False):
    severity = _normalize_severity(severity) if severity else None
    filtered = []
    for log in logs:
        _decorate_log_for_ui(log)
        if severity and log.audit_severity != severity:
            continue
        if critical_only and not log.audit_is_critical:
            continue
        filtered.append(log)
    return filtered


def get_audit_log_summary(logs):
    summary = {
        "total": 0,
        "critical": 0,
        "high": 0,
        "medium": 0,
        "info_low": 0,
        "policy_version": CRITICAL_AUDIT_POLICY_VERSION,
    }
    for log in logs:
        _decorate_log_for_ui(log)
        summary["total"] += 1
        if log.audit_is_critical:
            summary["critical"] += 1
        if log.audit_severity == "CRITICAL":
            summary["critical"] += 0  # already counted as critical flag above
            summary.setdefault("critical_severity", 0)
            summary["critical_severity"] += 1
        elif log.audit_severity == "HIGH":
            summary["high"] += 1
        elif log.audit_severity == "MEDIUM":
            summary["medium"] += 1
        else:
            summary["info_low"] += 1
    return summary


def get_critical_audit_policy_matrix():
    return [
        {"module": "SECURITY", "scope": "user/role/password/login failure", "severity": "CRITICAL/HIGH"},
        {"module": "BACKUP", "scope": "create/download/restore preview", "severity": "CRITICAL/HIGH"},
        {"module": "ACCOUNTING", "scope": "journal/posting/period closing", "severity": "HIGH"},
        {"module": "FINANCE", "scope": "invoice/payment/bank/supplier payment", "severity": "HIGH"},
        {"module": "LOGISTICS", "scope": "procurement/stock adjustment/damaged stock", "severity": "HIGH"},
        {"module": "HR", "scope": "payroll finalize/payment/posting", "severity": "HIGH"},
        {"module": "ATTACHMENT", "scope": "upload/delete sensitive proof documents", "severity": "HIGH/CRITICAL"},
    ]


def get_audit_log_detail(log_id, branch_id=None):
    """Fetch one audit log and prepare decoded metadata for owner detail view."""
    query = AuditLog.query.filter(AuditLog.id == log_id)

    if branch_id:
        query = query.filter(or_(AuditLog.branch_id == branch_id, AuditLog.branch_id.is_(None)))

    log = query.first()
    if not log:
        return None

    _decorate_log_for_ui(log)

    return {
        "log": log,
        "old_value_raw": log.old_value,
        "new_value_raw": log.new_value,
        "metadata_raw": log.metadata_json,
        "old_value_pretty": _pretty_json_text(log.old_value),
        "new_value_pretty": _pretty_json_text(log.new_value),
        "metadata_pretty": _pretty_json_text(log.metadata_json),
        "has_detail_payload": bool(log.old_value or log.new_value or log.metadata_json),
    }


def get_audit_logs(
    *,
    branch_id=None,
    module=None,
    event_type=None,
    action=None,
    q=None,
    date_from=None,
    date_to=None,
    severity=None,
    critical_only=False,
    limit=200,
):
    query = AuditLog.query

    if branch_id:
        query = query.filter(or_(AuditLog.branch_id == branch_id, AuditLog.branch_id.is_(None)))
    if module:
        query = query.filter(AuditLog.module == module)
    if event_type:
        query = query.filter(AuditLog.event_type == event_type)
    if action:
        query = query.filter(AuditLog.action == action)
    if date_from:
        query = query.filter(AuditLog.created_at >= date_from)
    if date_to:
        query = query.filter(AuditLog.created_at <= date_to)
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                AuditLog.description.ilike(like),
                AuditLog.username_snapshot.ilike(like),
                AuditLog.module.ilike(like),
                AuditLog.event_type.ilike(like),
                AuditLog.table_name.ilike(like),
            )
        )

    fetch_limit = limit
    if severity or critical_only:
        fetch_limit = max(limit * 5, 1000)

    logs = query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(fetch_limit).all()
    logs = _apply_audit_ui_filters(logs, severity=severity, critical_only=critical_only)
    return logs[:limit]


def get_audit_filter_options(branch_id=None):
    query = AuditLog.query
    if branch_id:
        query = query.filter(or_(AuditLog.branch_id == branch_id, AuditLog.branch_id.is_(None)))

    modules = [row[0] for row in query.with_entities(AuditLog.module).distinct().order_by(AuditLog.module.asc()).all() if row[0]]
    event_types = [row[0] for row in query.with_entities(AuditLog.event_type).distinct().order_by(AuditLog.event_type.asc()).all() if row[0]]
    actions = [row[0] for row in query.with_entities(AuditLog.action).distinct().order_by(AuditLog.action.asc()).all() if row[0]]

    return {
        "modules": modules,
        "event_types": event_types,
        "actions": actions,
        "severity_levels": SEVERITY_LEVELS,
        "critical_audit_policy_version": CRITICAL_AUDIT_POLICY_VERSION,
        "critical_policy_matrix": get_critical_audit_policy_matrix(),
    }
