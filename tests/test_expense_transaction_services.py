from datetime import date
from types import SimpleNamespace

from app.services import operational_expense_service, transport_expense_service


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


def test_create_transport_vehicle_expense_record_commits_once(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(transport_expense_service, "db", _FakeDb(session))
    expense = SimpleNamespace(id=10)
    calls = {}

    def fake_create_transport_vehicle_expense(**kwargs):
        calls.update(kwargs)
        return True, "ok", expense

    monkeypatch.setattr(
        transport_expense_service,
        "create_transport_vehicle_expense",
        fake_create_transport_vehicle_expense,
    )

    result = transport_expense_service.create_transport_vehicle_expense_record(
        branch_id=1,
        expense_date=date(2026, 7, 1),
        expense_type="TRANSPORT",
        payment_method="CASH",
        amount=100000,
        created_by=7,
    )

    assert result == (True, "ok", expense)
    assert calls["commit"] is False
    assert session.commit_count == 1
    assert session.rollback_count == 0


def test_create_operational_expense_record_rolls_back_when_commit_fails(monkeypatch):
    session = _FakeSession(fail_commit=True)
    monkeypatch.setattr(operational_expense_service, "db", _FakeDb(session))
    monkeypatch.setattr(
        operational_expense_service,
        "create_operational_expense",
        lambda **kwargs: (True, "ok", SimpleNamespace(id=11)),
    )

    try:
        operational_expense_service.create_operational_expense_record(
            branch_id=1,
            expense_date=date(2026, 7, 1),
            expense_category="ADMINISTRATION",
            payment_method="CASH",
            amount=100000,
            created_by=7,
        )
    except RuntimeError as error:
        assert str(error) == "commit failed"
    else:
        raise AssertionError("create_operational_expense_record should re-raise commit errors")

    assert session.commit_count == 1
    assert session.rollback_count == 1
