"""Helpers for tagging invoice/tagihan input sources.

Business rule:
- REALTIME means the source document was created inside the live operational flow.
- MANUAL_BACKFILL means the source was entered later from a manual book/old recap.

This is intentionally separate from `source_type`, because `source_type` points to the
technical source document (DAILY_ORDER, PERIOD_INVOICE, WORKER_DEBT, etc.), while
`input_source` answers how the data entered the system.
"""

INPUT_SOURCE_REALTIME = "REALTIME"
INPUT_SOURCE_MANUAL_BACKFILL = "MANUAL_BACKFILL"

VALID_INPUT_SOURCES = {
    INPUT_SOURCE_REALTIME,
    INPUT_SOURCE_MANUAL_BACKFILL,
}

INPUT_SOURCE_LABELS = {
    INPUT_SOURCE_REALTIME: "Realtime",
    INPUT_SOURCE_MANUAL_BACKFILL: "Input Belakangan",
}

INPUT_SOURCE_HELPERS = {
    INPUT_SOURCE_REALTIME: "Data berasal dari alur operasional yang dicatat langsung di sistem.",
    INPUT_SOURCE_MANUAL_BACKFILL: "Data berasal dari buku/rekap manual yang dimasukkan belakangan.",
}


def normalize_input_source(value):
    """Normalize persisted input source values to a safe enum value."""
    source = str(value or "").strip().upper()
    if source in VALID_INPUT_SOURCES:
        return source
    return INPUT_SOURCE_REALTIME


def input_source_label(value):
    source = normalize_input_source(value)
    return INPUT_SOURCE_LABELS[source]


def input_source_helper(value):
    source = normalize_input_source(value)
    return INPUT_SOURCE_HELPERS[source]


def input_source_badge_class(value):
    source = normalize_input_source(value)
    if source == INPUT_SOURCE_MANUAL_BACKFILL:
        return "status-warning"
    return "status-locked"


def build_input_source_context(value):
    source = normalize_input_source(value)
    return {
        "value": source,
        "label": input_source_label(source),
        "helper": input_source_helper(source),
        "badge_class": input_source_badge_class(source),
    }


def assert_valid_input_source(value):
    source = str(value or "").strip().upper()
    if source not in VALID_INPUT_SOURCES:
        raise ValueError("Sumber input tagihan tidak valid.")
    return source


def is_manual_backfill(value):
    return normalize_input_source(value) == INPUT_SOURCE_MANUAL_BACKFILL


def is_realtime(value):
    return normalize_input_source(value) == INPUT_SOURCE_REALTIME
