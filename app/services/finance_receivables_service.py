from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping, Optional

from app.utils.terms import L, T

BILL_TO_TYPE_CHOICES = [
    {"value": "MANDOR_EXISTING", "label": L("{sub_client}")},
    {"value": "CLIENT_EXISTING", "label": L("{client}")},
    {"value": "KELOMPOK", "label": "Kelompok"},
    {"value": "PERORANGAN", "label": "Perorangan"},
    {"value": "CLIENT_LAIN", "label": L("{client} Lain")},
]

BILL_TO_TYPE_LABELS = {choice["value"]: choice["label"] for choice in BILL_TO_TYPE_CHOICES}
BILL_TO_TYPE_ALIASES = {
    "MANDOR": "MANDOR_EXISTING",
    "MANDOR_EXISTING": "MANDOR_EXISTING",
    "CLIENT": "CLIENT_EXISTING",
    "CLIENT_EXISTING": "CLIENT_EXISTING",
    "KELOMPOK": "KELOMPOK",
    "PERORANGAN": "PERORANGAN",
    "CLIENT_LAIN": "CLIENT_LAIN",
    "CLIENT LAIN": "CLIENT_LAIN",
    "LAIN": "CLIENT_LAIN",
}

INPUT_SOURCE_LABELS = {
    "REALTIME": "Realtime",
    "MANUAL_BACKFILL": "Manual Backfill",
}

INACTIVE_INVOICE_STATUSES = {"CANCELLED", "CANCELED"}


def clean_text(value: Any) -> str:
    return str(value or "").strip()


def normalize_upper(value: Any) -> str:
    return clean_text(value).upper()


def parse_date_filter(value: Any) -> Optional[date]:
    raw = clean_text(value)
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def normalize_bill_to_type_filter(value: Any) -> str:
    raw = normalize_upper(value)
    if not raw or raw == "ALL":
        return ""
    return BILL_TO_TYPE_ALIASES.get(raw, "")


def normalize_status_filter(value: Any) -> str:
    raw = normalize_upper(value)
    if not raw or raw == "ALL":
        return ""
    return raw


def normalize_input_source(value: Any) -> str:
    raw = normalize_upper(value)
    if raw in INPUT_SOURCE_LABELS:
        return raw
    # Tahap 10.5+ invoice manual backfill always stores input_source, but this
    # fallback keeps older rows and test fakes readable.
    if raw in {"MANUAL", "MANUAL_BOOK", "MANUAL_BILLING"}:
        return "MANUAL_BACKFILL"
    return "REALTIME"


def input_source_label(value: Any) -> str:
    source = normalize_input_source(value)
    return INPUT_SOURCE_LABELS.get(source, source or "-")


def bill_to_type_label(value: Any) -> str:
    normalized = normalize_bill_to_type_filter(value) or normalize_upper(value)
    return BILL_TO_TYPE_LABELS.get(normalized, clean_text(value) or "-")


def _safe_name(obj: Any) -> str:
    if not obj:
        return ""
    for attr in ("name", "full_name", "client_name"):
        value = clean_text(getattr(obj, attr, ""))
        if value:
            return value
    obj_id = getattr(obj, "id", None)
    return f"ID {obj_id}" if obj_id else ""


def invoice_party_context(invoice: Any, client_map: Optional[Mapping[int, Any]] = None, mandor_map: Optional[Mapping[int, Any]] = None) -> dict[str, Any]:
    """Return the unified bill-to identity used by the enhanced receivables page.

    Existing invoices use legacy bill_to_type CLIENT/MANDOR. Manual backfill can
    also use KELOMPOK/PERORANGAN/CLIENT_LAIN with the free party name stored in
    the stable invoice snapshot fields.
    """
    client_map = client_map or {}
    mandor_map = mandor_map or {}

    raw_bill_to_type = normalize_upper(getattr(invoice, "bill_to_type", ""))
    bill_to_type = normalize_bill_to_type_filter(raw_bill_to_type)

    client_id = getattr(invoice, "client_id", None)
    mandor_id = getattr(invoice, "mandor_id", None)
    client = client_map.get(client_id) if client_id else None
    mandor = mandor_map.get(mandor_id) if mandor_id else None
    snapshot_name = clean_text(getattr(invoice, "client_name_snapshot", ""))

    if not bill_to_type:
        if mandor_id:
            bill_to_type = "MANDOR_EXISTING"
        elif client_id:
            bill_to_type = "CLIENT_EXISTING"
        elif snapshot_name:
            bill_to_type = "CLIENT_LAIN"
        else:
            bill_to_type = "CLIENT_EXISTING"

    if bill_to_type == "MANDOR_EXISTING":
        party_name = _safe_name(mandor) or snapshot_name or (f"{T.sub_client} ID {mandor_id}" if mandor_id else f"Tanpa {T.sub_client}")
        party_key = f"MANDOR:{mandor_id}" if mandor_id else f"MANDOR_SNAPSHOT:{party_name.upper()}"
        client_name = _safe_name(client) or "-"
        mandor_name = party_name
    elif bill_to_type == "CLIENT_EXISTING":
        party_name = snapshot_name or _safe_name(client) or (f"{T.client} ID {client_id}" if client_id else f"Tanpa {T.client}")
        party_key = f"CLIENT:{client_id}" if client_id else f"CLIENT_SNAPSHOT:{party_name.upper()}"
        client_name = party_name
        mandor_name = _safe_name(mandor) or "-"
    else:
        party_name = snapshot_name or "Pihak bebas tanpa nama"
        party_key = f"{bill_to_type}:" + " ".join(party_name.upper().split())
        client_name = party_name
        mandor_name = "-"

    input_source = normalize_input_source(getattr(invoice, "input_source", ""))

    return {
        "type": bill_to_type,
        "type_label": bill_to_type_label(bill_to_type),
        "key": party_key,
        "name": party_name,
        "client_name": client_name,
        "mandor_name": mandor_name,
        "input_source": input_source,
        "input_source_label": input_source_label(input_source),
    }


def invoice_period_basis(invoice: Any) -> tuple[Optional[date], Optional[date]]:
    start = getattr(invoice, "period_start", None) or getattr(invoice, "invoice_date", None)
    end = getattr(invoice, "period_end", None) or getattr(invoice, "invoice_date", None)
    return start, end


def invoice_matches_period(invoice: Any, period_from: Optional[date] = None, period_to: Optional[date] = None) -> bool:
    start, end = invoice_period_basis(invoice)
    if not start and not end:
        return True
    start = start or end
    end = end or start
    if period_from and end and end < period_from:
        return False
    if period_to and start and start > period_to:
        return False
    return True


def invoice_matches_receivable_filters(
    invoice: Any,
    party: Mapping[str, Any],
    *,
    bill_to_type: str = "",
    status: str = "",
    period_from: Optional[date] = None,
    period_to: Optional[date] = None,
) -> bool:
    selected_type = normalize_bill_to_type_filter(bill_to_type)
    if selected_type and party.get("type") != selected_type:
        return False

    selected_status = normalize_status_filter(status)
    if selected_status and normalize_upper(getattr(invoice, "status", "")) != selected_status:
        return False

    if not invoice_matches_period(invoice, period_from, period_to):
        return False

    return True


def receivable_status_choices_from_invoices(invoices: list[Any]) -> list[dict[str, Any]]:
    counter: dict[str, int] = {}
    for invoice in invoices:
        status = normalize_upper(getattr(invoice, "status", "")) or "UNKNOWN"
        if status in INACTIVE_INVOICE_STATUSES:
            continue
        counter[status] = counter.get(status, 0) + 1
    return [
        {"value": status, "label": status.replace("_", " ").title(), "count": count}
        for status, count in sorted(counter.items(), key=lambda item: item[0])
    ]
