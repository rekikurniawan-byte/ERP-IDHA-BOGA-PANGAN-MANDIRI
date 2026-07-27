from types import SimpleNamespace

from app.services import accounting_service


class _FakeColumn:
    def asc(self):
        return self

    def in_(self, values):
        return ("in", values)


class _FakeQuery:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *args):
        return self

    def order_by(self, *args):
        return self

    def all(self):
        return list(self.rows)


class _FakeInvoiceModel:
    source_type = _FakeColumn()
    invoice_date = _FakeColumn()
    id = _FakeColumn()

    def __init__(self, rows):
        self.query = _FakeQuery(rows)


class _FakePaymentModel:
    payment_date = _FakeColumn()
    id = _FakeColumn()

    def __init__(self, rows):
        self.query = _FakeQuery(rows)


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


def test_generate_period_invoice_journals_batch_counts_created_skipped_and_cancelled(monkeypatch):
    session = _FakeSession()
    invoices = [
        SimpleNamespace(id=1, status="OPEN"),
        SimpleNamespace(id=2, status="CANCELLED"),
        SimpleNamespace(id=3, status="OPEN"),
    ]
    monkeypatch.setattr(accounting_service, "db", _FakeDb(session))
    monkeypatch.setattr(accounting_service, "Invoice", _FakeInvoiceModel(invoices))

    def fake_create_invoice_journal_for_invoice(invoice, created_by, commit):
        return invoice.id == 1, "ok", None

    monkeypatch.setattr(accounting_service, "create_invoice_journal_for_invoice", fake_create_invoice_journal_for_invoice)

    result = accounting_service.generate_period_invoice_journals_batch(created_by=7)

    assert result == {
        "created_count": 1,
        "skipped_count": 2,
        "skipped_cancelled_count": 1,
    }
    assert session.commit_count == 1
    assert session.rollback_count == 0


def test_generate_period_invoice_journals_batch_rolls_back_errors(monkeypatch):
    session = _FakeSession()
    invoices = [SimpleNamespace(id=1, status="OPEN")]
    monkeypatch.setattr(accounting_service, "db", _FakeDb(session))
    monkeypatch.setattr(accounting_service, "Invoice", _FakeInvoiceModel(invoices))

    def raise_error(*args, **kwargs):
        raise RuntimeError("journal failed")

    monkeypatch.setattr(accounting_service, "create_invoice_journal_for_invoice", raise_error)

    try:
        accounting_service.generate_period_invoice_journals_batch(created_by=7)
    except RuntimeError as error:
        assert str(error) == "journal failed"
    else:
        raise AssertionError("generate_period_invoice_journals_batch should re-raise errors")

    assert session.commit_count == 0
    assert session.rollback_count == 1


def test_generate_payment_journals_batch_counts_created_and_skipped(monkeypatch):
    session = _FakeSession()
    payments = [SimpleNamespace(id=1), SimpleNamespace(id=2)]
    monkeypatch.setattr(accounting_service, "db", _FakeDb(session))
    monkeypatch.setattr(accounting_service, "Payment", _FakePaymentModel(payments))

    def fake_create_payment_journal_for_payment(payment, created_by, commit):
        return payment.id == 1, "ok", None

    monkeypatch.setattr(accounting_service, "create_payment_journal_for_payment", fake_create_payment_journal_for_payment)

    result = accounting_service.generate_payment_journals_batch(created_by=7)

    assert result == {"created_count": 1, "skipped_count": 1}
    assert session.commit_count == 1
    assert session.rollback_count == 0


def test_generate_payment_journals_batch_rolls_back_commit_failure(monkeypatch):
    session = _FakeSession(fail_commit=True)
    payments = [SimpleNamespace(id=1)]
    monkeypatch.setattr(accounting_service, "db", _FakeDb(session))
    monkeypatch.setattr(accounting_service, "Payment", _FakePaymentModel(payments))
    monkeypatch.setattr(accounting_service, "create_payment_journal_for_payment", lambda *args, **kwargs: (True, "ok", None))

    try:
        accounting_service.generate_payment_journals_batch(created_by=7)
    except RuntimeError as error:
        assert str(error) == "commit failed"
    else:
        raise AssertionError("generate_payment_journals_batch should re-raise commit errors")

    assert session.commit_count == 1
    assert session.rollback_count == 1


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


def test_generate_procurement_journals_batch_creates_journal_and_skips_existing(monkeypatch):
    session = _FakeSession()
    inventory = SimpleNamespace(id=1006)
    credit = SimpleNamespace(id=1001)
    procurement = SimpleNamespace(
        id=10,
        procurement_date=SimpleNamespace(strftime=lambda fmt: "20260102"),
        procurement_number="PO-001",
        purchase_type="CASH",
    )
    existing_procurement = SimpleNamespace(id=11, purchase_type="CASH")
    candidates = [
        {
            "procurement": procurement,
            "amount": 250000,
            "purchase_type": "CASH",
            "credit_account": credit,
            "existing_journal": None,
        },
        {
            "procurement": existing_procurement,
            "amount": 100000,
            "purchase_type": "CASH",
            "credit_account": credit,
            "existing_journal": SimpleNamespace(id=99),
        },
    ]
    monkeypatch.setattr(accounting_service, "db", _FakeDb(session))
    monkeypatch.setattr(accounting_service, "get_active_account_by_code", lambda code: inventory if code == "1006" else credit)
    monkeypatch.setattr(accounting_service, "build_procurement_journal_candidates", lambda: candidates)
    monkeypatch.setattr(accounting_service, "generate_journal_number", lambda journal_date: "JRN-20260102-001")

    result = accounting_service.generate_procurement_journals_batch(created_by_id=7)

    assert len(result["created"]) == 1
    assert len(result["skipped"]) == 1
    assert result["errors"] == []
    assert result["created"][0]["procurement"] is procurement
    assert result["created"][0]["amount"] == 250000
    assert session.flush_count == 1
    assert len(session.added) == 3
    assert session.commit_count == 1
    assert session.rollback_count == 0


def test_generate_procurement_journals_batch_returns_missing_account_without_commit(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(accounting_service, "db", _FakeDb(session))
    monkeypatch.setattr(accounting_service, "get_active_account_by_code", lambda code: None)
    monkeypatch.setattr(accounting_service, "build_procurement_journal_candidates", lambda: [])

    result = accounting_service.generate_procurement_journals_batch(created_by_id=7)

    assert result["created"] == []
    assert result["skipped"] == []
    assert result["errors"] == ["Akun wajib belum ada: 1006 - Persediaan Bahan Baku"]
    assert session.commit_count == 0
    assert session.rollback_count == 0


def test_generate_procurement_journals_batch_rolls_back_commit_failure(monkeypatch):
    session = _FakeSession(fail_commit=True)
    inventory = SimpleNamespace(id=1006)
    credit = SimpleNamespace(id=1001)
    procurement = SimpleNamespace(
        id=10,
        procurement_date=SimpleNamespace(strftime=lambda fmt: "20260102"),
        procurement_number="PO-001",
        purchase_type="CASH",
    )
    monkeypatch.setattr(accounting_service, "db", _FakeDb(session))
    monkeypatch.setattr(accounting_service, "get_active_account_by_code", lambda code: inventory if code == "1006" else credit)
    monkeypatch.setattr(accounting_service, "build_procurement_journal_candidates", lambda: [{
        "procurement": procurement,
        "amount": 250000,
        "purchase_type": "CASH",
        "credit_account": credit,
        "existing_journal": None,
    }])
    monkeypatch.setattr(accounting_service, "generate_journal_number", lambda journal_date: "JRN-20260102-001")

    try:
        accounting_service.generate_procurement_journals_batch(created_by_id=7)
    except RuntimeError as error:
        assert str(error) == "commit failed"
    else:
        raise AssertionError("generate_procurement_journals_batch should re-raise commit errors")

    assert session.commit_count == 1
    assert session.rollback_count == 1
