"""PRODUCTION Global Filter Bar V2 helpers.

Centralized date preset parsing for dashboard/report pages. This module is
read-only: it never writes to the database and is safe to call from GET routes.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any


PRESET_TODAY = "today"
PRESET_WEEK = "this_week"
PRESET_MONTH = "this_month"
PRESET_YEAR = "this_year"
PRESET_ALL = "all"
PRESET_CUSTOM = "custom"

PRESET_OPTIONS = [
    {"value": PRESET_TODAY, "label": "Hari ini"},
    {"value": PRESET_WEEK, "label": "Minggu ini"},
    {"value": PRESET_MONTH, "label": "Bulan ini"},
    {"value": PRESET_YEAR, "label": "Tahun ini"},
    {"value": PRESET_ALL, "label": "Semua"},
    {"value": PRESET_CUSTOM, "label": "Custom"},
]


@dataclass(frozen=True)
class DateFilterState:
    preset: str
    start_date: date | None
    end_date: date | None
    start_value: str
    end_value: str
    label: str
    is_custom: bool
    has_active_date: bool
    warning: str = ""

    def to_template(self) -> dict[str, Any]:
        return {
            "preset": self.preset,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "start_value": self.start_value,
            "end_value": self.end_value,
            "label": self.label,
            "is_custom": self.is_custom,
            "has_active_date": self.has_active_date,
            "warning": self.warning,
            "preset_options": PRESET_OPTIONS,
        }


def parse_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except Exception:
        return None


def _week_start(today: date) -> date:
    return today - timedelta(days=today.weekday())


def _range_for_preset(preset: str, today: date | None = None) -> tuple[date | None, date | None, str]:
    today = today or date.today()
    if preset == PRESET_TODAY:
        return today, today, "Hari ini"
    if preset == PRESET_WEEK:
        start = _week_start(today)
        return start, start + timedelta(days=6), "Minggu ini"
    if preset == PRESET_YEAR:
        return date(today.year, 1, 1), date(today.year, 12, 31), "Tahun ini"
    if preset == PRESET_ALL:
        return None, None, "Semua data"
    # Default month
    start = date(today.year, today.month, 1)
    next_month = date(today.year + (today.month // 12), (today.month % 12) + 1, 1)
    return start, next_month - timedelta(days=1), "Bulan ini"


def resolve_date_filter(
    args: Any,
    *,
    start_key: str = "start_date",
    end_key: str = "end_date",
    preset_key: str = "period_preset",
    default_preset: str = PRESET_MONTH,
    today: date | None = None,
) -> DateFilterState:
    today = today or date.today()
    allowed = {item["value"] for item in PRESET_OPTIONS}
    raw_preset = str(args.get(preset_key) or "").strip()
    raw_start = str(args.get(start_key) or "").strip()
    raw_end = str(args.get(end_key) or "").strip()

    preset = raw_preset if raw_preset in allowed else default_preset
    explicit_custom = preset == PRESET_CUSTOM or bool(raw_start or raw_end)

    warning = ""
    if explicit_custom:
        start = parse_date(raw_start)
        end = parse_date(raw_end)
        preset = PRESET_CUSTOM if preset != PRESET_ALL else PRESET_ALL
        if raw_start and not start:
            warning = "Tanggal mulai tidak valid."
        if raw_end and not end:
            warning = "Tanggal akhir tidak valid." if not warning else warning + " Tanggal akhir tidak valid."
        if start and end and start > end:
            warning = "Tanggal mulai lebih besar dari tanggal akhir. Filter dikembalikan ke bulan ini."
            start, end, label = _range_for_preset(PRESET_MONTH, today)
            preset = PRESET_MONTH
        elif not start and not end and preset == PRESET_CUSTOM:
            start, end, label = _range_for_preset(PRESET_MONTH, today)
            preset = PRESET_MONTH
        else:
            if start and end:
                label = f"{start.strftime('%d-%m-%Y')} s/d {end.strftime('%d-%m-%Y')}"
            elif start:
                label = f"Mulai {start.strftime('%d-%m-%Y')}"
            elif end:
                label = f"Sampai {end.strftime('%d-%m-%Y')}"
            else:
                label = "Semua data"
    else:
        start, end, label = _range_for_preset(preset, today)

    return DateFilterState(
        preset=preset,
        start_date=start,
        end_date=end,
        start_value=start.isoformat() if start else "",
        end_value=end.isoformat() if end else "",
        label=label,
        is_custom=preset == PRESET_CUSTOM,
        has_active_date=bool(start or end),
        warning=warning,
    )


def apply_date_range_to_query(query: Any, column: Any, state: DateFilterState) -> Any:
    if state.start_date:
        query = query.filter(column >= state.start_date)
    if state.end_date:
        query = query.filter(column <= state.end_date)
    return query


def date_in_range(value: Any, state: DateFilterState) -> bool:
    if not value:
        return not state.has_active_date
    try:
        current = value.date() if hasattr(value, "date") and not isinstance(value, date) else value
    except Exception:
        current = value
    if state.start_date and current < state.start_date:
        return False
    if state.end_date and current > state.end_date:
        return False
    return True


def build_filter_bar_context(
    *,
    state: DateFilterState,
    action_url: str,
    reset_url: str,
    title: str = "Filter Periode",
    description: str = "Gunakan preset atau tanggal custom untuk mempersempit data.",
    start_name: str = "start_date",
    end_name: str = "end_date",
    preset_name: str = "period_preset",
    status_name: str = "",
    status_value: str = "",
    status_options: list[dict[str, str]] | None = None,
    source_name: str = "",
    source_value: str = "",
    source_options: list[dict[str, str]] | None = None,
    hidden_fields: dict[str, Any] | None = None,
    extra_selects: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "title": title,
        "description": description,
        "action_url": action_url,
        "reset_url": reset_url,
        "preset_name": preset_name,
        "preset_value": state.preset,
        "preset_options": PRESET_OPTIONS,
        "start_name": start_name,
        "end_name": end_name,
        "start_value": state.start_value,
        "end_value": state.end_value,
        "status_name": status_name,
        "status_value": status_value,
        "status_options": status_options or [],
        "source_name": source_name,
        "source_value": source_value,
        "source_options": source_options or [],
        "hidden_fields": hidden_fields or {},
        "extra_selects": extra_selects or [],
        "active_label": state.label,
        "warning": state.warning,
    }
