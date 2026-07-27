from types import SimpleNamespace

import pytest

from app.services import approval_service
from app.services.approval_service import (
    APPROVAL_STATUS_APPROVED,
    APPROVAL_STATUS_REJECTED,
    APPROVAL_STATUS_SUBMITTED,
    ApprovalError,
)


class FakeSession:
    def __init__(self, *, fail_commit=False):
        self.added = []
        self.commits = 0
        self.rollbacks = 0
        self.fail_commit = fail_commit

    def add(self, row):
        self.added.append(row)

    def commit(self):
        self.commits += 1
        if self.fail_commit:
            raise RuntimeError("commit failed")

    def rollback(self):
        self.rollbacks += 1


class FakeDb:
    def __init__(self, session):
        self.session = session


def _patch_session(monkeypatch, session):
    monkeypatch.setattr(approval_service, "db", FakeDb(session))


def test_create_approval_request_requires_reason():
    with pytest.raises(ApprovalError):
        approval_service.create_approval_request(
            branch_id=1,
            action_key="payment_void",
            reference_type="payment",
            reference_id=7,
            requested_by=2,
            requested_reason=" ",
        )


def test_create_approval_request_normalizes_payload_and_commits(monkeypatch):
    session = FakeSession()
    _patch_session(monkeypatch, session)

    row = approval_service.create_approval_request(
        branch_id=1,
        action_key=" payment_void ",
        reference_type=" payment ",
        reference_id=7,
        requested_by=2,
        requested_reason="Perlu koreksi",
        payload={"amount": 12500},
    )

    assert row.action_key == "PAYMENT_VOID"
    assert row.reference_type == "PAYMENT"
    assert row.status == APPROVAL_STATUS_SUBMITTED
    assert '"amount": 12500' in row.payload_json
    assert session.added == [row]
    assert session.commits == 1
    assert session.rollbacks == 0


def test_create_approval_request_rolls_back_failed_commit(monkeypatch):
    session = FakeSession(fail_commit=True)
    _patch_session(monkeypatch, session)

    with pytest.raises(RuntimeError):
        approval_service.create_approval_request(
            branch_id=1,
            action_key="payment_void",
            reference_type="payment",
            reference_id=7,
            requested_by=2,
            requested_reason="Perlu koreksi",
        )

    assert session.commits == 1
    assert session.rollbacks == 1


def test_approve_request_blocks_same_user_checker(monkeypatch):
    session = FakeSession()
    _patch_session(monkeypatch, session)
    row = SimpleNamespace(status=APPROVAL_STATUS_SUBMITTED, requested_by=2)

    with pytest.raises(ApprovalError):
        approval_service.approve_request(row, reviewed_by=2)


def test_approve_request_sets_final_status_and_commits(monkeypatch):
    session = FakeSession()
    _patch_session(monkeypatch, session)
    row = SimpleNamespace(status=APPROVAL_STATUS_SUBMITTED, requested_by=2)

    approval_service.approve_request(row, reviewed_by=3, review_note="OK")

    assert row.status == APPROVAL_STATUS_APPROVED
    assert row.reviewed_by == 3
    assert row.review_note == "OK"
    assert row.reviewed_at is not None
    assert session.commits == 1


def test_reject_request_requires_note(monkeypatch):
    session = FakeSession()
    _patch_session(monkeypatch, session)
    row = SimpleNamespace(status=APPROVAL_STATUS_SUBMITTED, requested_by=2)

    with pytest.raises(ApprovalError):
        approval_service.reject_request(row, reviewed_by=3, review_note=" ")


def test_reject_request_sets_final_status_and_commits(monkeypatch):
    session = FakeSession()
    _patch_session(monkeypatch, session)
    row = SimpleNamespace(status=APPROVAL_STATUS_SUBMITTED, requested_by=2)

    approval_service.reject_request(row, reviewed_by=3, review_note="Dokumen belum lengkap")

    assert row.status == APPROVAL_STATUS_REJECTED
    assert row.reviewed_by == 3
    assert row.review_note == "Dokumen belum lengkap"
    assert row.reviewed_at is not None
    assert session.commits == 1


def test_terminal_approval_cannot_be_reviewed_again(monkeypatch):
    session = FakeSession()
    _patch_session(monkeypatch, session)
    row = SimpleNamespace(status=APPROVAL_STATUS_APPROVED, requested_by=2)

    with pytest.raises(ApprovalError):
        approval_service.reject_request(row, reviewed_by=3, review_note="Batal")


def test_ensure_action_has_approval_reuses_approved_request(monkeypatch):
    row = SimpleNamespace(status=APPROVAL_STATUS_APPROVED, id=11)
    monkeypatch.setattr(approval_service, "get_latest_action_request", lambda **kwargs: row)

    approved, request_row, message = approval_service.ensure_action_has_approval(
        branch_id=1,
        action_key="manual_backfill_void",
        reference_type="manual_billing_batch",
        reference_id=7,
        requested_by=2,
        requested_reason="Void salah input",
    )

    assert approved is True
    assert request_row is row
    assert "disetujui" in message


def test_ensure_action_has_approval_creates_missing_request(monkeypatch):
    session = FakeSession()
    _patch_session(monkeypatch, session)
    created = SimpleNamespace(status=APPROVAL_STATUS_SUBMITTED, id=12)
    monkeypatch.setattr(approval_service, "get_latest_action_request", lambda **kwargs: None)
    monkeypatch.setattr(approval_service, "create_approval_request", lambda **kwargs: created)

    approved, request_row, message = approval_service.ensure_action_has_approval(
        branch_id=1,
        action_key="manual_backfill_void",
        reference_type="manual_billing_batch",
        reference_id=7,
        requested_by=2,
        requested_reason="Void salah input",
    )

    assert approved is False
    assert request_row is created
    assert "Checker" in message
    assert session.commits == 1
