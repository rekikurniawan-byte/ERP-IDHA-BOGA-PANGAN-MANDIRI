"""PRODUCTION sensitive action guard service.

Guard ini sengaja tidak membuat tabel/permission baru. Tujuannya menjadi lapisan
proteksi reusable untuk aksi sensitif sebelum tahap permission detail/migration.
"""

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional, Tuple

from flask import has_request_context, request
from flask_login import current_user
from werkzeug.security import check_password_hash

from app.services.audit_log_service import record_critical_audit_log


APP_VERSION = "PRODUCTION"
GUARD_POLICY_VERSION = "PRODUCTION_SENSITIVE_ACTION_GUARD_V2"
MIN_REASON_LENGTH = 8


@dataclass(frozen=True)
class SensitiveActionPolicy:
    key: str
    label: str
    module: str
    event_type: str
    allowed_roles: Tuple[str, ...] = ("OWNER",)
    require_reason: bool = True
    require_password: bool = True
    min_reason_length: int = MIN_REASON_LENGTH
    severity: str = "HIGH"


SENSITIVE_ACTION_POLICIES: Dict[str, SensitiveActionPolicy] = {
    "COMPANY_SETTINGS_UPDATE": SensitiveActionPolicy(
        key="COMPANY_SETTINGS_UPDATE",
        label="Ubah identitas/pengaturan perusahaan",
        module="SETTINGS",
        event_type="SENSITIVE_COMPANY_SETTINGS_UPDATE",
    ),
    "USER_CREATE": SensitiveActionPolicy(
        key="USER_CREATE",
        label="Buat user baru",
        module="SECURITY",
        event_type="SENSITIVE_USER_CREATE",
    ),
    "USER_UPDATE": SensitiveActionPolicy(
        key="USER_UPDATE",
        label="Edit data user/role/cabang",
        module="SECURITY",
        event_type="SENSITIVE_USER_UPDATE",
    ),
    "USER_STATUS_TOGGLE": SensitiveActionPolicy(
        key="USER_STATUS_TOGGLE",
        label="Aktifkan/nonaktifkan user",
        module="SECURITY",
        event_type="SENSITIVE_USER_STATUS_TOGGLE",
    ),
    "USER_PASSWORD_RESET": SensitiveActionPolicy(
        key="USER_PASSWORD_RESET",
        label="Reset password user",
        module="SECURITY",
        event_type="SENSITIVE_USER_PASSWORD_RESET",
    ),
    "BACKUP_CREATE_DB_ONLY": SensitiveActionPolicy(
        key="BACKUP_CREATE_DB_ONLY",
        label="Buat backup DB-only",
        module="BACKUP",
        event_type="SENSITIVE_DB_BACKUP_CREATE",
    ),
    "BACKUP_CREATE_FULL": SensitiveActionPolicy(
        key="BACKUP_CREATE_FULL",
        label="Buat full backup DB + uploads",
        module="BACKUP",
        event_type="SENSITIVE_FULL_BACKUP_CREATE",
    ),
    "BACKUP_DOWNLOAD": SensitiveActionPolicy(
        key="BACKUP_DOWNLOAD",
        label="Download file backup/checksum",
        module="BACKUP",
        event_type="SENSITIVE_BACKUP_DOWNLOAD",
    ),
    "BACKUP_RESTORE_PREVIEW": SensitiveActionPolicy(
        key="BACKUP_RESTORE_PREVIEW",
        label="Validasi restore preview backup",
        module="BACKUP",
        event_type="SENSITIVE_RESTORE_PREVIEW",
    ),
    "DIGITAL_ATTACHMENT_SOFT_DELETE": SensitiveActionPolicy(
        key="DIGITAL_ATTACHMENT_SOFT_DELETE",
        label="Hapus lunak lampiran digital",
        module="ATTACHMENT",
        event_type="SENSITIVE_ATTACHMENT_SOFT_DELETE",
    ),
}


_REASON_FIELD_CANDIDATES = (
    "sensitive_reason",
    "guard_reason",
    "reason",
    "delete_note",
    "note",
)
_PASSWORD_FIELD_CANDIDATES = (
    "confirm_password",
    "sensitive_confirm_password",
    "current_password",
)


def get_sensitive_action_policy(action_key: str) -> SensitiveActionPolicy:
    policy = SENSITIVE_ACTION_POLICIES.get(action_key)
    if policy:
        return policy

    return SensitiveActionPolicy(
        key=action_key,
        label=action_key.replace("_", " ").title(),
        module="SYSTEM",
        event_type=f"SENSITIVE_{action_key}",
    )


def _get_first_form_value(form: Any, field_names: Iterable[str]) -> str:
    if not form:
        return ""
    for name in field_names:
        value = form.get(name)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _current_user_role() -> Optional[str]:
    try:
        if current_user and current_user.is_authenticated:
            return getattr(current_user, "role", None)
    except Exception:
        return None
    return None


def _current_user_password_hash() -> Optional[str]:
    try:
        if current_user and current_user.is_authenticated:
            return getattr(current_user, "password_hash", None)
    except Exception:
        return None
    return None


def build_sensitive_guard_metadata(
    policy: SensitiveActionPolicy,
    *,
    reason: str = "",
    result: str = "PENDING",
    target: Optional[Dict[str, Any]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    metadata = {
        "app_version": APP_VERSION,
        "guard_policy_version": GUARD_POLICY_VERSION,
        "sensitive_action_key": policy.key,
        "sensitive_action_label": policy.label,
        "guard_result": result,
        "reason": reason,
        "reason_length": len(reason or ""),
        "require_reason": policy.require_reason,
        "require_password": policy.require_password,
        "allowed_roles": list(policy.allowed_roles),
        "request_method": request.method if has_request_context() else None,
    }
    if target:
        metadata["target"] = target
    if extra:
        metadata.update(extra)
    return metadata


def record_sensitive_action_guard(
    policy: SensitiveActionPolicy,
    *,
    result: str,
    reason: str = "",
    target: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
):
    metadata = build_sensitive_guard_metadata(
        policy,
        reason=reason,
        result=result,
        target=target,
        extra=extra,
    )
    if error:
        metadata["error"] = error

    severity = "CRITICAL" if result == "FAIL" else policy.severity
    return record_critical_audit_log(
        module=policy.module,
        event_type=f"{policy.event_type}_{result}",
        action="SECURITY_GUARD",
        description=(
            f"Sensitive action guard {result}: {policy.label}."
            + (f" Alasan: {reason}" if reason and result == "PASS" else "")
        ),
        metadata=metadata,
        severity=severity,
        reason=reason,
        reference_type="sensitive_action_policy",
        reference_id=None,
        policy_scope="SENSITIVE_ACTION_GUARD",
    )


def validate_sensitive_action_guard(
    action_key: str,
    *,
    form: Any = None,
    target: Optional[Dict[str, Any]] = None,
    extra: Optional[Dict[str, Any]] = None,
    record_pass: bool = True,
    record_fail: bool = True,
) -> Tuple[bool, str, Dict[str, Any]]:
    """Validate role + reason + password re-confirm for a sensitive action.

    Returns: (is_allowed, message, guard_metadata). Password is never returned or
    logged. The message is safe for flashing in UI.
    """
    policy = get_sensitive_action_policy(action_key)
    form = form if form is not None else (request.form if has_request_context() else None)
    reason = _get_first_form_value(form, _REASON_FIELD_CANDIDATES)
    password = _get_first_form_value(form, _PASSWORD_FIELD_CANDIDATES)

    role = _current_user_role()
    if role not in policy.allowed_roles:
        message = "Aksi sensitif ditolak. Role kamu tidak memiliki izin untuk aksi ini."
        if record_fail:
            record_sensitive_action_guard(policy, result="FAIL", reason=reason, target=target, error=message, extra=extra)
        return False, message, build_sensitive_guard_metadata(policy, reason=reason, result="FAIL", target=target, extra=extra)

    if policy.require_reason and len(reason) < policy.min_reason_length:
        message = f"Aksi sensitif ditolak. Alasan wajib diisi minimal {policy.min_reason_length} karakter."
        if record_fail:
            record_sensitive_action_guard(policy, result="FAIL", reason=reason, target=target, error=message, extra=extra)
        return False, message, build_sensitive_guard_metadata(policy, reason=reason, result="FAIL", target=target, extra=extra)

    if policy.require_password:
        password_hash = _current_user_password_hash()
        if not password_hash or not password:
            message = "Aksi sensitif ditolak. Password akun aktif wajib dikonfirmasi ulang."
            if record_fail:
                record_sensitive_action_guard(policy, result="FAIL", reason=reason, target=target, error=message, extra=extra)
            return False, message, build_sensitive_guard_metadata(policy, reason=reason, result="FAIL", target=target, extra=extra)

        try:
            password_ok = check_password_hash(password_hash, password)
        except Exception:
            password_ok = False

        if not password_ok:
            message = "Aksi sensitif ditolak. Password konfirmasi salah."
            if record_fail:
                record_sensitive_action_guard(policy, result="FAIL", reason=reason, target=target, error=message, extra=extra)
            return False, message, build_sensitive_guard_metadata(policy, reason=reason, result="FAIL", target=target, extra=extra)

    metadata = build_sensitive_guard_metadata(policy, reason=reason, result="PASS", target=target, extra=extra)
    if record_pass:
        record_sensitive_action_guard(policy, result="PASS", reason=reason, target=target, extra=extra)
    return True, "Aksi sensitif terverifikasi.", metadata
