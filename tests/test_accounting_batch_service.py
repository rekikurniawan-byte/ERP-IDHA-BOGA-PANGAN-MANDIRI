from app.services import accounting_service


class _FakeSession:
    def __init__(self, *, fail_commit=False):
        self.added = []
        self.flush_count = 0
        self.commit_count = 0
        self.rollback_count = 0
        self.fail_commit = fail_commit

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        self.flush_count += 1
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = 501

    def commit(self):
        self.commit_count += 1
        if self.fail_commit:
            raise RuntimeError("commit failed")

    def rollback(self):
        self.rollback_count += 1


class _FakeDb:
    def __init__(self, session):
        self.session = session


def test_commit_accounting_transaction_commits(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(accounting_service, "db", _FakeDb(session))

    accounting_service.commit_accounting_transaction()

    assert session.commit_count == 1
    assert session.rollback_count == 0


def test_commit_accounting_transaction_rolls_back_commit_failure(monkeypatch):
    session = _FakeSession(fail_commit=True)
    monkeypatch.setattr(accounting_service, "db", _FakeDb(session))

    try:
        accounting_service.commit_accounting_transaction()
    except RuntimeError as error:
        assert str(error) == "commit failed"
    else:
        raise AssertionError("commit_accounting_transaction should re-raise commit errors")

    assert session.commit_count == 1
    assert session.rollback_count == 1


def test_rollback_accounting_transaction_rolls_back(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(accounting_service, "db", _FakeDb(session))

    accounting_service.rollback_accounting_transaction()

    assert session.commit_count == 0
    assert session.rollback_count == 1


