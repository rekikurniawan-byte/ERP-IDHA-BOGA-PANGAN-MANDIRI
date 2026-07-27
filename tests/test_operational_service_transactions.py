from types import SimpleNamespace

from app.services import operational_service


class _FakeSession:
    def __init__(self, *, fail_commit=False):
        self.added = []
        self.commit_count = 0
        self.rollback_count = 0
        self.fail_commit = fail_commit

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        return None

    def commit(self):
        self.commit_count += 1
        if self.fail_commit:
            raise RuntimeError("commit failed")

    def rollback(self):
        self.rollback_count += 1


class _FakeDb:
    def __init__(self, session):
        self.session = session


class _FakeDetailQuery:
    def __init__(self, result):
        self.result = result

    def filter_by(self, **kwargs):
        return self

    def first(self):
        return self.result


class _FakeDailyOrderDetail:
    query = None

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
        self.id = kwargs.get("id", 99)


def test_lock_daily_order_creates_snapshot_without_inner_commit(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(operational_service, "db", _FakeDb(session))
    captured = {}

    def fake_create_order_snapshot(daily_order, created_by, commit=True):
        captured["created_by"] = created_by
        captured["commit"] = commit
        return SimpleNamespace(id=12)

    monkeypatch.setattr(operational_service, "create_order_snapshot", fake_create_order_snapshot)
    daily_order = SimpleNamespace(is_locked=False, details=[object()], status="DRAFT", locked_at=None)

    success, message = operational_service.lock_daily_order(daily_order, locked_by=7)

    assert success is True
    assert "berhasil" in message
    assert daily_order.is_locked is True
    assert daily_order.status == "LOCKED"
    assert captured == {"created_by": 7, "commit": False}
    assert session.commit_count == 1
    assert session.rollback_count == 0


def test_add_increase_after_lock_existing_detail_uses_single_outer_commit(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(operational_service, "db", _FakeDb(session))
    daily_order = SimpleNamespace(id=1, is_locked=True)
    existing_detail = SimpleNamespace(price_per_portion=15000)
    calls = {}
    _FakeDailyOrderDetail.query = _FakeDetailQuery(existing_detail)
    monkeypatch.setattr(operational_service, "DailyOrderDetail", _FakeDailyOrderDetail)

    def fake_revise_order_detail(**kwargs):
        calls.update(kwargs)
        return True, "ok"

    monkeypatch.setattr(operational_service, "revise_order_detail", fake_revise_order_detail)

    success, message, detail = operational_service.add_increase_after_lock(
        daily_order=daily_order,
        mandor_id=2,
        delivery_location_id=3,
        price_per_portion=15000,
        lunch_qty=1,
        dinner_qty=0,
        reason="tambahan",
        created_by=7,
    )

    assert success is True
    assert message == "ok"
    assert detail is existing_detail
    assert calls["commit"] is False
    assert session.commit_count == 1
    assert session.rollback_count == 0


def test_add_increase_after_lock_rolls_back_when_outer_commit_fails(monkeypatch):
    session = _FakeSession(fail_commit=True)
    monkeypatch.setattr(operational_service, "db", _FakeDb(session))
    _FakeDailyOrderDetail.query = _FakeDetailQuery(None)
    monkeypatch.setattr(operational_service, "DailyOrderDetail", _FakeDailyOrderDetail)
    monkeypatch.setattr(operational_service, "OrderRevision", lambda **kwargs: SimpleNamespace(**kwargs))
    daily_order = SimpleNamespace(id=1, is_locked=True)

    try:
        operational_service.add_increase_after_lock(
            daily_order=daily_order,
            mandor_id=2,
            delivery_location_id=3,
            price_per_portion=15000,
            lunch_qty=1,
            dinner_qty=0,
            reason="tambahan",
            created_by=7,
        )
    except RuntimeError as error:
        assert str(error) == "commit failed"
    else:
        raise AssertionError("add_increase_after_lock should re-raise commit errors")

    assert session.commit_count == 1
    assert session.rollback_count == 1
