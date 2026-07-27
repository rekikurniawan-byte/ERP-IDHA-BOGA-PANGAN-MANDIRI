"""PRODUCTION atomic transaction guard service.

Satu aksi bisnis kritis harus punya satu boundary commit/rollback. Service ini
sengaja reusable dan ringan agar bisa dipasang bertahap per modul tanpa migration.
"""
from __future__ import annotations
import logging

from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any, Iterable, Optional

from sqlalchemy.exc import InvalidRequestError

from app.extensions import db
from app.services.audit_log_service import record_critical_audit_log

logger = logging.getLogger(__name__)


APP_VERSION = "PRODUCTION"
ATOMIC_GUARD_POLICY_VERSION = "PRODUCTION_ATOMIC_TRANSACTION_GUARD_V2"


class AtomicTransactionError(RuntimeError):
    """Raised when an atomic transaction boundary cannot be completed."""


class AtomicBusinessAction(AbstractContextManager):
    """Atomic boundary for one business action.

    Prinsip:
    - semua perubahan DB di dalam block harus commit satu kali di akhir;
    - exception apa pun melakukan rollback penuh;
    - file fisik yang sudah ditulis selama transaksi bisa didaftarkan agar
      dihapus lagi bila rollback;
    - audit PASS/FAIL dicatat sesudah commit/rollback, bukan di tengah mutasi.
    """

    def __init__(
        self,
        *,
        module: str,
        action: str,
        description: str = "",
        reference_type: Optional[str] = None,
        reference_id: Optional[int] = None,
        reason: Optional[str] = None,
        user_id: Optional[int] = None,
        branch_id: Optional[int] = None,
        severity: str = "HIGH",
        audit_success: bool = True,
        audit_failure: bool = True,
        metadata: Optional[dict[str, Any]] = None,
    ):
        self.module = module
        self.action = action
        self.description = description or action
        self.reference_type = reference_type
        self.reference_id = reference_id
        self.reason = reason or "PRODUCTION atomic business transaction boundary."
        self.user_id = user_id
        self.branch_id = branch_id
        self.severity = severity
        self.audit_success = audit_success
        self.audit_failure = audit_failure
        self.metadata = dict(metadata or {})
        self._rollback_files: list[Path] = []
        self._transaction = None
        self._nested = False
        self._session = None

    def _current_session(self):
        """Return the actual SQLAlchemy Session behind Flask-SQLAlchemy.

        In Flask-SQLAlchemy 3.x ``db.session`` is a scoped_session proxy. Calling
        ``db.session.in_transaction()`` can be unreliable across versions, while
        calling ``db.session()`` returns the concrete Session for the current app
        context. Atomic routes often query records before entering this guard, so
        SQLAlchemy 2.x may already have an implicit transaction open.
        """
        try:
            return db.session()
        except Exception:
            logger.exception("Suppressed unexpected exception in app/services/atomic_transaction_service.py:81")
            return db.session

    def _session_in_transaction(self) -> bool:
        session = self._session or self._current_session()
        try:
            return bool(session.in_transaction())
        except Exception:
            logger.exception("Suppressed unexpected exception in app/services/atomic_transaction_service.py:88")
            try:
                return session.get_transaction() is not None
            except Exception:
                logger.exception("Suppressed unexpected exception in app/services/atomic_transaction_service.py:91")
                return False

    def __enter__(self):
        # SQLAlchemy 2.x otomatis membuka transaksi saat route melakukan SELECT
        # sebelum block atomic. Jika sudah ada transaksi, pakai SAVEPOINT. Jika
        # deteksi transaction gagal dan begin() menolak karena transaksi sudah
        # aktif, fallback ke SAVEPOINT juga. Ini menjaga nested transaction tetap aman
        # dan PostgreSQL tanpa error "transaction is already begun".
        self._session = self._current_session()

        if self._session_in_transaction():
            self._nested = True
            self._transaction = self._session.begin_nested()
        else:
            try:
                self._nested = False
                self._transaction = self._session.begin()
            except InvalidRequestError as error:
                if "already begun" not in str(error).lower():
                    raise
                self._nested = True
                self._transaction = self._session.begin_nested()

        self._transaction.__enter__()
        return self

    def register_rollback_file(self, file_path: Optional[Path | str]) -> None:
        if not file_path:
            return
        try:
            path = Path(file_path).resolve()
        except Exception:
            logger.exception("Suppressed unexpected exception in app/services/atomic_transaction_service.py:123")
            return
        if path not in self._rollback_files:
            self._rollback_files.append(path)

    def track_attachment(self, attachment: Any) -> None:
        """Register a DigitalAttachment physical file for rollback cleanup."""
        if not attachment:
            return
        try:
            from app.services.digital_attachment_service import get_upload_root

            upload_root = get_upload_root().resolve()
            relative = getattr(attachment, "file_path", None) or getattr(attachment, "stored_filename", None)
            if relative:
                candidate = (upload_root / relative).resolve()
                if upload_root in candidate.parents or candidate == upload_root:
                    self.register_rollback_file(candidate)
        except Exception:
            logger.exception("Suppressed unexpected exception in app/services/atomic_transaction_service.py:141")
            return

    def _cleanup_rollback_files(self) -> list[str]:
        cleaned: list[str] = []
        for path in self._rollback_files:
            try:
                if path.exists() and path.is_file():
                    path.unlink()
                    cleaned.append(str(path))
            except Exception:
                # Cleanup failure is reported in audit metadata but should not
                # hide the original business exception.
                logger.exception("Suppressed unexpected exception in app/services/atomic_transaction_service.py:151")
                continue
        return cleaned

    def _audit(self, *, status: str, error: Optional[BaseException] = None, cleaned_files: Optional[Iterable[str]] = None) -> None:
        if status == "PASS" and not self.audit_success:
            return
        if status == "FAIL" and not self.audit_failure:
            return

        metadata = dict(self.metadata)
        metadata.update({
            "app_version": APP_VERSION,
            "atomic_guard_policy_version": ATOMIC_GUARD_POLICY_VERSION,
            "atomic_status": status,
            "atomic_action": self.action,
            "reference_type": self.reference_type,
            "reference_id": self.reference_id,
            "cleaned_rollback_files": list(cleaned_files or []),
        })
        if error is not None:
            metadata["error_type"] = type(error).__name__
            metadata["error_message"] = str(error)

        record_critical_audit_log(
            module=self.module,
            event_type=f"{self.action}_{status}",
            action="ATOMIC_TRANSACTION",
            table_name=self.reference_type,
            record_id=self.reference_id,
            description=f"{self.description} | Atomic {status}.",
            metadata=metadata,
            severity=self.severity if status == "PASS" else "CRITICAL",
            reason=self.reason,
            reference_type=self.reference_type,
            reference_id=self.reference_id,
            policy_scope="ATOMIC_TRANSACTION_GUARD",
            user_id=self.user_id,
            branch_id=self.branch_id,
            commit=True,
        )

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type is not None:
            try:
                if self._transaction is not None:
                    self._transaction.__exit__(exc_type, exc_value, traceback)
            finally:
                (self._session or db.session).rollback()
                cleaned = self._cleanup_rollback_files()
                self._audit(status="FAIL", error=exc_value, cleaned_files=cleaned)
            return False

        try:
            if self._transaction is not None:
                self._transaction.__exit__(None, None, None)
            # Jika menggunakan nested transaction karena query sebelumnya sudah
            # membuka transaction, commit outer session di sini.
            if self._nested:
                (self._session or db.session).commit()
            self._audit(status="PASS")
            return False
        except Exception as error:
            (self._session or db.session).rollback()
            cleaned = self._cleanup_rollback_files()
            self._audit(status="FAIL", error=error, cleaned_files=cleaned)
            raise


def atomic_business_action(**kwargs) -> AtomicBusinessAction:
    """Factory supaya route bisa memakai `with atomic_business_action(...):`."""
    return AtomicBusinessAction(**kwargs)
