from datetime import date

from app.services import finance_collection_service


class _FakeSession:
    def __init__(self, *, fail_commit=False):
        self.added = []
        self.commit_count = 0
        self.rollback_count = 0
        self.fail_commit = fail_commit

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.commit_count += 1
        if self.fail_commit:
            raise RuntimeError("commit failed")

    def rollback(self):
        self.rollback_count += 1


class _FakeDb:
    def __init__(self, session):
        self.session = session


class _FakeCollectionLog:
    query = None

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _FakeCollectionQuery:
    def __init__(self, existing_invoice_ids):
        self.existing_invoice_ids = set(existing_invoice_ids)
        self.filters = {}

    def filter_by(self, **kwargs):
        self.filters = kwargs
        return self

    def first(self):
        invoice_id = self.filters.get("invoice_id")
        if invoice_id in self.existing_invoice_ids:
            return object()
        return None


def test_create_invoice_collection_log_record_adds_log_and_commits(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(finance_collection_service, "db", _FakeDb(session))

    log = finance_collection_service.create_invoice_collection_log_record(
        branch_id=2,
        invoice_id=10,
        follow_up_date=date(2026, 1, 2),
        channel="WHATSAPP",
        contact_person="PIC",
        response_note="Sudah dikirim",
        promise_date=None,
        next_action="Follow up",
        collection_status="SENT",
        created_by=7,
    )

    assert log in session.added
    assert log.branch_id == 2
    assert log.invoice_id == 10
    assert log.channel == "WHATSAPP"
    assert log.contact_person == "PIC"
    assert log.response_note == "Sudah dikirim"
    assert log.collection_status == "SENT"
    assert session.commit_count == 1
    assert session.rollback_count == 0


def test_create_invoice_collection_log_record_rolls_back_when_commit_fails(monkeypatch):
    session = _FakeSession(fail_commit=True)
    monkeypatch.setattr(finance_collection_service, "db", _FakeDb(session))

    try:
        finance_collection_service.create_invoice_collection_log_record(
            branch_id=2,
            invoice_id=10,
            follow_up_date=date(2026, 1, 2),
            channel="WHATSAPP",
            contact_person="PIC",
            response_note="Sudah dikirim",
            promise_date=None,
            next_action="Follow up",
            collection_status="SENT",
            created_by=7,
        )
    except RuntimeError as error:
        assert str(error) == "commit failed"
    else:
        raise AssertionError("create_invoice_collection_log_record should re-raise commit errors")

    assert session.commit_count == 1
    assert session.rollback_count == 1


def test_create_receivables_statement_logs_skips_existing_and_commits(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(finance_collection_service, "db", _FakeDb(session))
    _FakeCollectionLog.query = _FakeCollectionQuery(existing_invoice_ids={2})
    monkeypatch.setattr(finance_collection_service, "InvoiceCollectionLog", _FakeCollectionLog)
    invoices = [
        type("Invoice", (), {"id": 1})(),
        type("Invoice", (), {"id": 2})(),
        type("Invoice", (), {"id": 3})(),
    ]

    created_count, skipped_count = finance_collection_service.create_receivables_statement_logs(
        invoices=invoices,
        branch_id=4,
        follow_up_date=date(2026, 1, 2),
        contact_person="PIC",
        response_note_factory=lambda invoice: f"Statement invoice {invoice.id}",
        created_by=7,
    )

    assert created_count == 2
    assert skipped_count == 1
    assert [log.invoice_id for log in session.added] == [1, 3]
    assert all(log.collection_status == "STATEMENT_SENT" for log in session.added)
    assert session.commit_count == 1
    assert session.rollback_count == 0
