from types import SimpleNamespace

from app.services.billing_input_source_service import (
    INPUT_SOURCE_MANUAL_BACKFILL,
    INPUT_SOURCE_REALTIME,
    build_input_source_context,
)
from app.routes.finance_routes import (
    _build_catering_invoice_lines,
    _calculate_realtime_locked_base_quantities,
    _is_after_lock_increase_revision,
)


def _revision(revision_id, lunch, dinner, price=15000, revision_type="AFTER_LOCK"):
    return SimpleNamespace(
        id=revision_id,
        revision_type=revision_type,
        revision_direction="INCREASE",
        lunch_qty_change=lunch,
        dinner_qty_change=dinner,
        price_per_portion=price,
    )


def _detail(detail_id, lunch, dinner, price, revisions):
    return SimpleNamespace(
        id=detail_id,
        mandor_id=7,
        lunch_qty=lunch,
        dinner_qty=dinner,
        total_qty=lunch + dinner,
        price_per_portion=price,
        revisions=revisions,
        mandor=SimpleNamespace(name="Pak Yatno"),
        delivery_location=SimpleNamespace(location_name="Lokasi Proyek"),
    )


def test_realtime_invoice_splits_locked_base_and_after_lock_increase_without_double_count():
    revision = _revision(revision_id=55, lunch=2, dinner=1, price=16000)
    detail = _detail(
        detail_id=10,
        # Current qty sudah termasuk revisi after-lock.
        lunch=12,
        dinner=10,
        price=15000,
        revisions=[revision],
    )
    order = SimpleNamespace(order_number="ORD-20260706-001", details=[detail])

    lines = _build_catering_invoice_lines(order, mandor_id=7)

    assert [line["item_type"] for line in lines] == ["CATERING", "REVISION_INCREASE"]
    assert lines[0]["qty"] == 19  # locked base: (12-2) + (10-1)
    assert lines[0]["subtotal"] == 285000
    assert lines[1]["qty"] == 3
    assert lines[1]["subtotal"] == 48000
    assert sum(line["subtotal"] for line in lines) == 333000


def test_realtime_invoice_new_detail_after_lock_only_bills_revision_line_once():
    revision = _revision(revision_id=56, lunch=4, dinner=4, price=15000, revision_type="AFTER_LOCK_NEW_DETAIL")
    detail = _detail(
        detail_id=11,
        # Detail baru setelah lock tidak punya base locked; qty saat ini sama dengan revisi.
        lunch=4,
        dinner=4,
        price=15000,
        revisions=[revision],
    )
    order = SimpleNamespace(order_number="ORD-20260706-002", details=[detail])

    lines = _build_catering_invoice_lines(order, mandor_id=7)

    assert [line["item_type"] for line in lines] == ["REVISION_INCREASE"]
    assert lines[0]["qty"] == 8
    assert lines[0]["subtotal"] == 120000


def test_locked_base_quantity_never_negative_when_revision_matches_current_qty():
    detail = _detail(
        detail_id=12,
        lunch=2,
        dinner=0,
        price=15000,
        revisions=[_revision(revision_id=57, lunch=5, dinner=1)],
    )

    assert _calculate_realtime_locked_base_quantities(detail, _is_after_lock_increase_revision) == (0, 0)


def test_billing_input_source_context_locks_two_input_lanes():
    realtime = build_input_source_context(INPUT_SOURCE_REALTIME)
    backfill = build_input_source_context(INPUT_SOURCE_MANUAL_BACKFILL)

    assert realtime["label"] == "Langsung"
    assert backfill["label"] == "Input Belakangan"
    assert realtime["value"] != backfill["value"]
