from types import SimpleNamespace

from app.services import invoice_identity_service


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


def test_refresh_invoice_identity_snapshot_record_applies_snapshot_and_commits(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(invoice_identity_service, "db", _FakeDb(session))
    invoice = SimpleNamespace(
        client_id=1,
        branch_id=2,
        client_name_snapshot="",
        client_code_snapshot="",
        client_pic_id=None,
        client_pic_name_snapshot="",
        client_pic_position_snapshot="",
        client_pic_phone_snapshot="",
        client_pic_email_snapshot="",
        company_bank_name_snapshot="",
        company_bank_account_number_snapshot="",
        company_bank_account_name_snapshot="",
    )
    client = SimpleNamespace(name="PT Client", client_code="CL-1")
    client_pic = SimpleNamespace(
        id=5,
        name="Ibu PIC",
        position="Finance",
        phone="0812",
        email="pic@example.test",
    )
    monkeypatch.setattr(
        invoice_identity_service,
        "build_company_bank_snapshot",
        lambda branch_id: {
            "company_bank_name_snapshot": "BCA",
            "company_bank_account_number_snapshot": "123",
            "company_bank_account_name_snapshot": "PT Idha",
        },
    )

    result = invoice_identity_service.refresh_invoice_identity_snapshot_record(
        invoice,
        client=client,
        client_pic=client_pic,
        branch_id=2,
    )

    assert result is invoice
    assert invoice.client_name_snapshot == "PT Client"
    assert invoice.client_pic_name_snapshot == "Ibu PIC"
    assert invoice.company_bank_name_snapshot == "BCA"
    assert session.commit_count == 1
    assert session.rollback_count == 0


def test_refresh_invoice_identity_snapshot_record_rolls_back_when_commit_fails(monkeypatch):
    session = _FakeSession(fail_commit=True)
    monkeypatch.setattr(invoice_identity_service, "db", _FakeDb(session))
    monkeypatch.setattr(
        invoice_identity_service,
        "apply_invoice_identity_snapshot",
        lambda invoice, client=None, client_pic=None, branch_id=None: invoice,
    )

    try:
        invoice_identity_service.refresh_invoice_identity_snapshot_record(
            SimpleNamespace(),
            branch_id=2,
        )
    except RuntimeError as error:
        assert str(error) == "commit failed"
    else:
        raise AssertionError("refresh_invoice_identity_snapshot_record should re-raise commit errors")

    assert session.commit_count == 1
    assert session.rollback_count == 1
