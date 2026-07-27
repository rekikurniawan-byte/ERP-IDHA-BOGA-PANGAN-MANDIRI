"""Idempotency helpers for critical ERP POST operations."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Mapping

from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.system import IdempotencyKey


class IdempotencyConflictError(ValueError):
    """Raised when a reused key carries a different request payload."""


def build_request_hash(payload: Mapping[str, Any] | None) -> str:
    normalized = json.dumps(payload or {}, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def assert_replay_matches(existing_request_hash: str | None, request_hash: str) -> None:
    if existing_request_hash and existing_request_hash != request_hash:
        raise IdempotencyConflictError("Idempotency key sudah pernah dipakai dengan payload berbeda.")


def reserve_idempotency_key(
    *,
    scope: str,
    key: str,
    branch_id: int | None,
    user_id: int | None,
    request_payload: Mapping[str, Any] | None = None,
) -> tuple[IdempotencyKey, bool]:
    request_hash = build_request_hash(request_payload)
    existing = IdempotencyKey.query.filter_by(scope=scope, key=key).with_for_update().first()
    if existing:
        assert_replay_matches(existing.request_hash, request_hash)
        return existing, False

    record = IdempotencyKey(
        scope=scope,
        key=key,
        branch_id=branch_id,
        user_id=user_id,
        request_hash=request_hash,
        status="STARTED",
    )
    db.session.add(record)
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        existing = IdempotencyKey.query.filter_by(scope=scope, key=key).with_for_update().first()
        if not existing:
            raise
        assert_replay_matches(existing.request_hash, request_hash)
        return existing, False
    return record, True


def mark_idempotency_completed(
    record: IdempotencyKey,
    *,
    reference_type: str | None = None,
    reference_id: int | None = None,
    response_payload: Mapping[str, Any] | None = None,
    commit: bool = False,
) -> IdempotencyKey:
    record.status = "COMPLETED"
    record.reference_type = reference_type
    record.reference_id = reference_id
    record.response_payload_json = json.dumps(response_payload or {}, sort_keys=True, default=str)
    record.error_message = None
    record.completed_at = datetime.utcnow()
    if commit:
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
    return record


def mark_idempotency_failed(record: IdempotencyKey, error: Exception | str, *, commit: bool = False) -> IdempotencyKey:
    record.status = "FAILED"
    record.error_message = str(error)
    record.completed_at = datetime.utcnow()
    if commit:
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
    return record
