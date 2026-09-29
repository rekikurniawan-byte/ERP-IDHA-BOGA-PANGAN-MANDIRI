from datetime import date
from types import SimpleNamespace

from app.services import cash_bank_service


class _FakeSession:
    def __init__(self, *, fail_commit=False):
        self.commit_count = 0
        self.rollback_count = 0
        self.fail_commit = fail_commit

    def commit(self):
        self.commit_count += 1
        if self.fail_commit:
            raise RuntimeError("commit failed")

    def rollback(self):
        self.rollback_count += 1


class _FakeDb:
    def __init__(self, session):
        self.session = session


def test_create_cash_bank_transfer_record_rolls_back_when_commit_fails(monkeypatch):
    session = _FakeSession(fail_commit=True)
    monkeypatch.setattr(cash_bank_service, "db", _FakeDb(session))

    def fake_create_cash_bank_transfer(**kwargs):
        return SimpleNamespace(id=1), SimpleNamespace(id=2), SimpleNamespace(id=3)

    monkeypatch.setattr(cash_bank_service, "create_cash_bank_transfer", fake_create_cash_bank_transfer)

    try:
        cash_bank_service.create_cash_bank_transfer_record(
            transfer_date=date(2026, 1, 2),
            from_account_type="CASH",
            from_bank_account_id=None,
            to_account_type="BANK",
            to_bank_account_id=5,
            amount=500,
            created_by=7,
            branch_id=2,
        )
    except RuntimeError as error:
        assert str(error) == "commit failed"
    else:
        raise AssertionError("create_cash_bank_transfer_record should re-raise commit errors")

    assert session.commit_count == 1
    assert session.rollback_count == 1


def test_reconcile_cash_bank_transaction_record_sets_state_and_commits(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(cash_bank_service, "db", _FakeDb(session))
    transaction = SimpleNamespace(
        is_reconciled=False,
        reconciled_at=None,
        reconciled_by=None,
        reconciliation_note=None,
    )

    result = cash_bank_service.reconcile_cash_bank_transaction_record(
        transaction,
        reconciled_by=9,
        note="Cocok mutasi bank",
    )

    assert result is transaction
    assert transaction.is_reconciled is True
    assert transaction.reconciled_by == 9
    assert transaction.reconciliation_note == "Cocok mutasi bank"
    assert transaction.reconciled_at is not None
    assert session.commit_count == 1
    assert session.rollback_count == 0


def test_unreconcile_cash_bank_transaction_record_sets_state_and_commits(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(cash_bank_service, "db", _FakeDb(session))
    transaction = SimpleNamespace(
        is_reconciled=True,
        reconciled_at="2026-01-01",
        reconciled_by=9,
        reconciliation_note="Sudah cocok",
    )

    result = cash_bank_service.unreconcile_cash_bank_transaction_record(transaction)

    assert result is transaction
    assert transaction.is_reconciled is False
    assert transaction.reconciled_at is None
    assert transaction.reconciled_by is None
    assert transaction.reconciliation_note is None
    assert session.commit_count == 1
    assert session.rollback_count == 0
