from app.services import canteen_service


class _Comparable:
    def __eq__(self, other):
        return ("eq", other)


class _FakeFunc:
    def lower(self, value):
        return _Comparable()


class _FakeSession:
    def __init__(self, *, fail_commit=False):
        self.added = []
        self.commit_count = 0
        self.rollback_count = 0
        self.flush_count = 0
        self.fail_commit = fail_commit

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        self.flush_count += 1
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = 42

    def commit(self):
        self.commit_count += 1
        if self.fail_commit:
            raise RuntimeError("commit failed")

    def rollback(self):
        self.rollback_count += 1


class _FakeDb:
    func = _FakeFunc()

    def __init__(self, session):
        self.session = session


class _FakeItemQuery:
    def __init__(self, existing=None):
        self.existing = existing

    def filter(self, *conditions):
        return self

    def first(self):
        return self.existing


class _FakeItem:
    category = _Comparable()
    item_name = _Comparable()
    query = _FakeItemQuery()

    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


def test_get_or_create_custom_item_updates_existing_empty_price_and_commits(monkeypatch):
    session = _FakeSession()
    existing = _FakeItem(item_name="Kopi", selling_price=0)
    fake_item = _FakeItem
    fake_item.query = _FakeItemQuery(existing=existing)
    monkeypatch.setattr(canteen_service, "db", _FakeDb(session))
    monkeypatch.setattr(canteen_service, "Item", fake_item)

    item = canteen_service.get_or_create_custom_item(" Kopi ", selling_price=5000)

    assert item is existing
    assert existing.selling_price == 5000
    assert session.added == []
    assert session.flush_count == 0
    assert session.commit_count == 1
    assert session.rollback_count == 0


def test_get_or_create_custom_item_rolls_back_existing_price_commit_failure(monkeypatch):
    session = _FakeSession(fail_commit=True)
    existing = _FakeItem(item_name="Kopi", selling_price=0)
    fake_item = _FakeItem
    fake_item.query = _FakeItemQuery(existing=existing)
    monkeypatch.setattr(canteen_service, "db", _FakeDb(session))
    monkeypatch.setattr(canteen_service, "Item", fake_item)

    try:
        canteen_service.get_or_create_custom_item("Kopi", selling_price=5000)
    except RuntimeError as error:
        assert str(error) == "commit failed"
    else:
        raise AssertionError("get_or_create_custom_item should re-raise commit errors")

    assert session.commit_count == 1
    assert session.rollback_count == 1


def test_get_or_create_custom_item_creates_new_item_with_flush_without_commit(monkeypatch):
    session = _FakeSession()
    fake_item = _FakeItem
    fake_item.query = _FakeItemQuery(existing=None)
    monkeypatch.setattr(canteen_service, "db", _FakeDb(session))
    monkeypatch.setattr(canteen_service, "Item", fake_item)
    monkeypatch.setattr(canteen_service, "generate_item_code", lambda category: "WRG-0001")

    item = canteen_service.get_or_create_custom_item("Teh Manis", selling_price=7000)

    assert item in session.added
    assert item.id == 42
    assert item.item_code == "WRG-0001"
    assert item.item_name == "Teh Manis"
    assert item.category == "MERCHANDISE"
    assert item.unit == "PCS"
    assert item.selling_price == 7000
    assert item.is_stock_tracked is False
    assert session.flush_count == 1
    assert session.commit_count == 0
    assert session.rollback_count == 0


def test_get_or_create_custom_item_returns_none_for_blank_name(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(canteen_service, "db", _FakeDb(session))

    assert canteen_service.get_or_create_custom_item("   ", selling_price=7000) is None
    assert session.commit_count == 0
    assert session.flush_count == 0
