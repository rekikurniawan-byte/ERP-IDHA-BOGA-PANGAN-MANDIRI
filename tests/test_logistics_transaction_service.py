from datetime import date
from types import SimpleNamespace

from app.services import logistics_transaction_service


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


def test_create_stock_audit_movement_commits(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(logistics_transaction_service, "db", _FakeDb(session))

    movement = logistics_transaction_service.create_stock_audit_movement(
        branch_id=2,
        item_id=10,
        movement_date=date(2026, 1, 2),
        movement_type="ADJUSTMENT_IN",
        qty=3,
        notes="Audit stok",
        created_by=7,
    )

    assert movement in session.added
    assert movement.branch_id == 2
    assert movement.item_id == 10
    assert movement.reference_type == "AUDIT_STOK"
    assert movement.qty == 3
    assert session.commit_count == 1
    assert session.rollback_count == 0


def test_create_stock_audit_movement_rolls_back_when_commit_fails(monkeypatch):
    session = _FakeSession(fail_commit=True)
    monkeypatch.setattr(logistics_transaction_service, "db", _FakeDb(session))

    try:
        logistics_transaction_service.create_stock_audit_movement(
            branch_id=2,
            item_id=10,
            movement_date=date(2026, 1, 2),
            movement_type="ADJUSTMENT_IN",
            qty=3,
            notes="Audit stok",
            created_by=7,
        )
    except RuntimeError as error:
        assert str(error) == "commit failed"
    else:
        raise AssertionError("create_stock_audit_movement should re-raise commit errors")

    assert session.commit_count == 1
    assert session.rollback_count == 1


def test_create_item_request_record_adds_header_details_and_commits(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(logistics_transaction_service, "db", _FakeDb(session))
    item = SimpleNamespace(id=10, unit="KG")

    item_request = logistics_transaction_service.create_item_request_record(
        request_number="REQ-20260102-001",
        branch_id=2,
        request_date=date(2026, 1, 2),
        requested_by=7,
        purpose="Produksi",
        notes="Catatan",
        rows=[{"item": item, "requested_qty": 5, "notes": "Segera"}],
    )

    assert item_request in session.added
    assert item_request.id == 501
    assert item_request.request_number == "REQ-20260102-001"
    assert item_request.status == "PENDING"
    assert session.flush_count == 1
    assert len(session.added) == 2
    detail = session.added[1]
    assert detail.item_request_id == 501
    assert detail.item_id == 10
    assert detail.qty == 5
    assert detail.requested_qty == 5
    assert detail.approved_qty == 0
    assert session.commit_count == 1
    assert session.rollback_count == 0


def test_approve_item_request_record_sets_approved_qty_and_notes(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(logistics_transaction_service, "db", _FakeDb(session))
    item_request = SimpleNamespace(
        status="PENDING",
        notes="Awal",
        details=[
            SimpleNamespace(requested_qty=3, qty=0, approved_qty=0),
            SimpleNamespace(requested_qty=0, qty=4, approved_qty=0),
        ],
    )

    updated = logistics_transaction_service.approve_item_request_record(
        item_request,
        owner_note="OK",
    )

    assert updated is item_request
    assert item_request.status == "APPROVED"
    assert item_request.notes == "Awal | Catatan owner: OK"
    assert [detail.approved_qty for detail in item_request.details] == [3, 4]
    assert session.commit_count == 1
    assert session.rollback_count == 0


def test_reject_item_request_record_resets_qty_and_commits(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(logistics_transaction_service, "db", _FakeDb(session))
    item_request = SimpleNamespace(
        status="PENDING",
        notes="Awal",
        details=[
            SimpleNamespace(approved_qty=3, fulfilled_qty=1),
        ],
    )

    updated = logistics_transaction_service.reject_item_request_record(
        item_request,
        reject_reason="Tidak perlu",
    )

    assert updated is item_request
    assert item_request.status == "REJECTED"
    assert item_request.notes == "Awal | Alasan ditolak: Tidak perlu"
    assert item_request.details[0].approved_qty == 0
    assert item_request.details[0].fulfilled_qty == 0
    assert session.commit_count == 1
    assert session.rollback_count == 0


def test_fulfill_item_request_record_adds_movements_and_commits(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(logistics_transaction_service, "db", _FakeDb(session))
    monkeypatch.setattr(logistics_transaction_service, "get_item_stock_for_update", lambda branch_id, item_id: 10)
    item = SimpleNamespace(id=10, unit="KG")
    detail = SimpleNamespace(item=item, approved_qty=4, requested_qty=4, qty=4, fulfilled_qty=0)
    item_request = SimpleNamespace(
        id=99,
        request_number="REQ-20260102-001",
        request_date=date(2026, 1, 2),
        purpose="Produksi",
        notes="Awal",
        details=[detail],
    )

    updated = logistics_transaction_service.fulfill_item_request_record(
        item_request,
        branch_id=2,
        fulfilled_by=7,
        fulfill_note="Ambil pagi",
    )

    assert updated is item_request
    assert item_request.status == "FULFILLED"
    assert item_request.notes == "Awal | Catatan pemenuhan: Ambil pagi"
    assert detail.fulfilled_qty == 4
    assert len(session.added) == 1
    movement = session.added[0]
    assert movement.branch_id == 2
    assert movement.item_id == 10
    assert movement.movement_type == "OUT"
    assert movement.reference_type == "PERMINTAAN_BARANG_DAPUR"
    assert movement.reference_id == 99
    assert movement.qty == 4
    assert session.commit_count == 1
    assert session.rollback_count == 0
