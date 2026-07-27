from types import SimpleNamespace

from app.services import fixed_asset_depreciation_service, fixed_asset_purchase_service


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


def test_configure_asset_depreciation_record_commits_once(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(fixed_asset_depreciation_service, "db", _FakeDb(session))
    config = SimpleNamespace(id=20)
    calls = {}

    def fake_configure_asset_depreciation(**kwargs):
        calls.update(kwargs)
        return config

    monkeypatch.setattr(
        fixed_asset_depreciation_service,
        "configure_asset_depreciation",
        fake_configure_asset_depreciation,
    )

    result = fixed_asset_depreciation_service.configure_asset_depreciation_record(
        branch_id=1,
        asset_id=5,
        depreciation_start_date="2026-01-01",
        useful_life_months=36,
        residual_value=0,
        accumulated_account_code="2101",
        status="CONFIGURED",
        notes="",
        created_by=7,
    )

    assert result is config
    assert calls["commit"] is False
    assert session.commit_count == 1
    assert session.rollback_count == 0


def test_post_asset_depreciation_record_rolls_back_when_commit_fails(monkeypatch):
    session = _FakeSession(fail_commit=True)
    monkeypatch.setattr(fixed_asset_depreciation_service, "db", _FakeDb(session))
    monkeypatch.setattr(
        fixed_asset_depreciation_service,
        "post_asset_depreciation",
        lambda **kwargs: SimpleNamespace(id=21),
    )

    try:
        fixed_asset_depreciation_service.post_asset_depreciation_record(
            branch_id=1,
            asset_id=5,
            period_year=2026,
            period_month=7,
            created_by=7,
        )
    except RuntimeError as error:
        assert str(error) == "commit failed"
    else:
        raise AssertionError("post_asset_depreciation_record should re-raise commit errors")

    assert session.commit_count == 1
    assert session.rollback_count == 1


def test_create_fixed_asset_purchase_record_commits_once(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(fixed_asset_purchase_service, "db", _FakeDb(session))
    purchase = SimpleNamespace(id=30)
    ledger = SimpleNamespace(id=31)
    journal = SimpleNamespace(id=32)
    calls = {}

    def fake_create_fixed_asset_purchase(**kwargs):
        calls.update(kwargs)
        return purchase, ledger, journal

    monkeypatch.setattr(
        fixed_asset_purchase_service,
        "create_fixed_asset_purchase",
        fake_create_fixed_asset_purchase,
    )

    result = fixed_asset_purchase_service.create_fixed_asset_purchase_record(
        branch_id=1,
        purchase_date="2026-07-01",
        asset_mode="NEW",
        amount=100000,
        payment_method="CASH",
        created_by=7,
    )

    assert result == (purchase, ledger, journal)
    assert calls["commit"] is False
    assert session.commit_count == 1
    assert session.rollback_count == 0


def test_create_fixed_asset_purchase_record_rolls_back_mid_process_failure(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(fixed_asset_purchase_service, "db", _FakeDb(session))
    monkeypatch.setattr(
        fixed_asset_purchase_service,
        "create_fixed_asset_purchase",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("journal failed")),
    )

    try:
        fixed_asset_purchase_service.create_fixed_asset_purchase_record(
            branch_id=1,
            purchase_date="2026-07-01",
            asset_mode="NEW",
            amount=100000,
            payment_method="CASH",
            created_by=7,
        )
    except RuntimeError as error:
        assert str(error) == "journal failed"
    else:
        raise AssertionError("create_fixed_asset_purchase_record should re-raise service errors")

    assert session.commit_count == 0
    assert session.rollback_count == 1
