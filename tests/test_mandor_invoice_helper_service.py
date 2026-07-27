from types import SimpleNamespace

from app.services.mandor_invoice_helper_service import (
    calculate_realtime_locked_base_quantities,
    finance_safe_label,
    is_after_lock_increase_revision,
)


def test_finance_safe_label_prefers_human_name_fields():
    assert finance_safe_label(SimpleNamespace(name="Mandor QA", id=9)) == "Mandor QA"
    assert finance_safe_label(SimpleNamespace(location_name="Dapur QA", id=10)) == "Dapur QA"
    assert finance_safe_label(SimpleNamespace(id=11)) == "ID 11"
    assert finance_safe_label(None) == "-"


def test_after_lock_increase_revision_detection():
    assert is_after_lock_increase_revision(SimpleNamespace(revision_type="AFTER_LOCK_EXTRA", revision_direction="INCREASE"))
    assert not is_after_lock_increase_revision(SimpleNamespace(revision_type="AFTER_LOCK_EXTRA", revision_direction="DECREASE"))
    assert not is_after_lock_increase_revision(SimpleNamespace(revision_type="BEFORE_LOCK", revision_direction="INCREASE"))


def test_calculate_locked_base_quantities_subtracts_after_lock_increases():
    detail = SimpleNamespace(
        lunch_qty=12,
        dinner_qty=8,
        revisions=[
            SimpleNamespace(lunch_qty_change=2, dinner_qty_change=1, billable=True),
            SimpleNamespace(lunch_qty_change=4, dinner_qty_change=4, billable=False),
        ],
    )

    def only_billable(revision):
        return revision.billable

    assert calculate_realtime_locked_base_quantities(detail, only_billable) == (10, 7)
