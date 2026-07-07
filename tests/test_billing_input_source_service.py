import pytest

from app.services.billing_input_source_service import (
    INPUT_SOURCE_MANUAL_BACKFILL,
    INPUT_SOURCE_REALTIME,
    assert_valid_input_source,
    build_input_source_context,
    input_source_label,
    is_manual_backfill,
    is_realtime,
    normalize_input_source,
)


def test_normalize_input_source_defaults_to_realtime_for_empty_or_unknown_values():
    assert normalize_input_source(None) == INPUT_SOURCE_REALTIME
    assert normalize_input_source("") == INPUT_SOURCE_REALTIME
    assert normalize_input_source("unknown") == INPUT_SOURCE_REALTIME


def test_manual_backfill_input_source_context_is_business_readable():
    context = build_input_source_context("manual_backfill")

    assert context["value"] == INPUT_SOURCE_MANUAL_BACKFILL
    assert context["label"] == "Input Belakangan"
    assert "buku/rekap manual" in context["helper"]
    assert context["badge_class"] == "status-warning"


def test_realtime_input_source_helpers():
    assert input_source_label(INPUT_SOURCE_REALTIME) == "Realtime"
    assert is_realtime(INPUT_SOURCE_REALTIME)
    assert not is_manual_backfill(INPUT_SOURCE_REALTIME)


def test_assert_valid_input_source_rejects_invalid_value():
    with pytest.raises(ValueError):
        assert_valid_input_source("LEGACY_RANDOM")
