from types import SimpleNamespace

import pytest

from app.services.field_transaction_service import (
    FieldTransactionValidationError,
    create_field_counterparty,
)


class _FakeQuery:
    def __init__(self, rows):
        self.rows = rows

    def filter_by(self, **kwargs):
        filtered = self.rows
        for key, value in kwargs.items():
            filtered = [row for row in filtered if getattr(row, key, None) == value]
        return _FakeQuery(filtered)

    def all(self):
        return list(self.rows)


def test_create_field_counterparty_blocks_duplicate_active_counterparty(monkeypatch):
    existing = SimpleNamespace(
        id=41,
        branch_id=1,
        is_active=True,
        counterparty_type="MANDOR_NON_PT",
        name="Mandor Andi",
        phone="08123",
        company_name=None,
        site_location="Site A",
        linked_mandor_id=7,
    )

    monkeypatch.setattr(
        "app.services.field_transaction_service.FieldCounterparty",
        SimpleNamespace(query=_FakeQuery([existing])),
    )
    monkeypatch.setattr(
        "app.services.field_transaction_service.Mandor",
        SimpleNamespace(query=_FakeQuery([])),
    )

    with pytest.raises(FieldTransactionValidationError) as exc:
        create_field_counterparty(
            branch_id=1,
            counterparty_type="MANDOR_NON_PT",
            name=" mandor  andi ",
            phone="08123",
            site_location="Site A",
            created_by=9,
            commit=False,
        )

    assert "sudah ada" in str(exc.value)
