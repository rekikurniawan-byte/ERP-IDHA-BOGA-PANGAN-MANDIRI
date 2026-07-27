# Split from app.services.manual_backfill_billing_service.
import sys

from app.services.manual_backfill_billing_service import *  # noqa: F401,F403
from app.services.manual_backfill_bill_to_service import (
    _bill_to_display_label,
    _clean_text,
    _infer_bill_to_type,
    _normalize_party_name,
)


def _root_attr(name, fallback):
    root = sys.modules.get("app.services.manual_backfill_billing_service")
    return getattr(root, name, fallback)


def _query_all_or_first(model, **filters):
    """Return query results while staying friendly to lightweight unit fakes."""
    query = getattr(model, "query", None)
    if query is None:
        return []
    query = query.filter_by(**filters)
    if hasattr(query, "all"):
        return [item for item in (query.all() or []) if item is not None]
    if hasattr(query, "first"):
        first = query.first()
        return [first] if first is not None else []
    return []


def _ranges_overlap(start_a, end_a, start_b, end_b):
    if not start_a or not end_a or not start_b or not end_b:
        return False
    return start_a <= end_b and start_b <= end_a


def _normalize_billing_category(item_type=None, source_type=None):
    item_type = _clean_text(item_type).upper()
    source_type = _clean_text(source_type).upper()
    if item_type in CATERING_ITEM_TYPES or source_type in CATERING_SOURCE_TYPES:
        return BILLING_CATEGORY_CATERING
    if item_type in WARUNG_ITEM_TYPES or source_type in WARUNG_SOURCE_TYPES:
        return BILLING_CATEGORY_WARUNG
    return BILLING_CATEGORY_OTHER


def _item_categories_from_items(items):
    categories = set()
    for item in list(items or []):
        categories.add(_normalize_billing_category(
            getattr(item, "item_type", None),
            getattr(item, "source_type", None),
        ))
    return categories or {BILLING_CATEGORY_OTHER}


def _party_key_from_values(bill_to_type=None, mandor_id=None, client_id=None, name=None):
    normalized_type = _infer_bill_to_type(bill_to_type, mandor_id, client_id, name)

    if normalized_type == BILL_TO_MANDOR_EXISTING and mandor_id:
        return ("MANDOR_ID", int(mandor_id))
    if normalized_type == BILL_TO_CLIENT_EXISTING and client_id:
        return ("CLIENT_ID", int(client_id))
    if normalized_type in {BILL_TO_KELOMPOK, BILL_TO_PERORANGAN, BILL_TO_CLIENT_LAIN}:
        normalized_name = _normalize_party_name(name)
        if normalized_name:
            return ("FREE_NAME", normalized_type, normalized_name)
    return None


def _batch_party_key(batch):
    return _party_key_from_values(
        getattr(batch, "bill_to_type", None),
        getattr(batch, "mandor_id", None),
        getattr(batch, "client_id", None),
        getattr(batch, "bill_to_name_snapshot", None),
    )


def _invoice_party_key(invoice):
    return _party_key_from_values(
        getattr(invoice, "bill_to_type", None),
        getattr(invoice, "mandor_id", None),
        getattr(invoice, "client_id", None),
        getattr(invoice, "client_name_snapshot", None),
    )


def _same_billed_party(left_key, right_key):
    return bool(left_key and right_key and left_key == right_key)


def _period_from_daily_order(invoice):
    source_order_id = getattr(invoice, "source_order_id", None)
    if not source_order_id:
        return None, None
    try:
        from app.models.operational import DailyOrder
        order = DailyOrder.query.get(source_order_id)
        order_date = getattr(order, "order_date", None)
        if order_date:
            return order_date, order_date
    except Exception:
        logger.exception("Suppressed unexpected exception in app/services/manual_backfill_billing_service.py:716")
        return None, None
    return None, None


def _invoice_period(invoice):
    period_start = getattr(invoice, "period_start", None)
    period_end = getattr(invoice, "period_end", None)
    if period_start and period_end:
        return period_start, period_end

    # Invoice order harian lama ada yang belum menyimpan periode. Fallback ini
    # penting agar backfill tidak bisa menabrak invoice order harian lama.
    if _clean_text(getattr(invoice, "source_type", "")).upper() == "DAILY_ORDER":
        return _period_from_daily_order(invoice)

    return None, None


def _invoice_billing_categories(invoice):
    categories = _item_categories_from_items(getattr(invoice, "items", []) or [])
    if categories and categories != {BILLING_CATEGORY_OTHER}:
        return categories
    source_type = _clean_text(getattr(invoice, "source_type", "")).upper()
    if source_type == "DAILY_ORDER":
        return {BILLING_CATEGORY_CATERING}
    if source_type == "PERIOD_INVOICE":
        return {BILLING_CATEGORY_CATERING, BILLING_CATEGORY_WARUNG}
    if source_type == MANUAL_BILLING_INVOICE_SOURCE:
        return categories
    return categories


def _active_status(value):
    return _clean_text(value).upper() not in INACTIVE_BILLING_STATUSES


def _format_period(start, end):
    if not start or not end:
        return "periode tidak diketahui"
    try:
        return f"{start.strftime('%d-%m-%Y')} s/d {end.strftime('%d-%m-%Y')}"
    except Exception:
        logger.exception("Suppressed unexpected exception in app/services/manual_backfill_billing_service.py:758")
        return f"{start} s/d {end}"


def _category_labels(categories):
    labels = []
    if BILLING_CATEGORY_CATERING in categories:
        labels.append("catering")
    if BILLING_CATEGORY_WARUNG in categories:
        labels.append("warung/kasbon")
    if BILLING_CATEGORY_OTHER in categories:
        labels.append("tagihan lain")
    return ", ".join(labels) or "tagihan"


def collect_manual_backfill_duplicate_conflicts(batch):
    """Find active documents that could double-charge this manual-book recap.

    Guard boundary:
    - Same branch
    - Same mandor/kelompok
    - Overlapping period
    - Overlapping billing category, e.g. catering vs catering or warung vs warung

    This intentionally blocks across input lanes: REALTIME and MANUAL_BACKFILL.
    """
    if not batch:
        return []
    if not _active_status(getattr(batch, "status", None)):
        return []

    branch_id = getattr(batch, "branch_id", None)
    period_start = getattr(batch, "period_start", None)
    period_end = getattr(batch, "period_end", None)
    current_batch_id = getattr(batch, "id", None)
    current_invoice_id = getattr(batch, "invoice_id", None)
    target_categories = _item_categories_from_items(getattr(batch, "items", []) or [])
    target_party_key = _batch_party_key(batch)

    if not branch_id or not target_party_key or not period_start or not period_end or not target_categories:
        return []

    conflicts = []

    invoices = _query_all_or_first(_root_attr("Invoice", Invoice), branch_id=branch_id)
    for invoice in invoices:
        if not _same_billed_party(target_party_key, _invoice_party_key(invoice)):
            continue
        if current_invoice_id and int(getattr(invoice, "id", 0) or 0) == int(current_invoice_id):
            continue
        if not _active_status(getattr(invoice, "status", None)):
            continue

        invoice_start, invoice_end = _invoice_period(invoice)
        if not _ranges_overlap(period_start, period_end, invoice_start, invoice_end):
            continue

        invoice_categories = _invoice_billing_categories(invoice)
        overlap_categories = target_categories & invoice_categories
        if not overlap_categories:
            continue

        conflicts.append({
            "kind": "INVOICE",
            "invoice_id": getattr(invoice, "id", None),
            "number": getattr(invoice, "invoice_number", None) or f"Invoice #{getattr(invoice, 'id', '-')}",
            "status": getattr(invoice, "status", None),
            "status_label": _clean_text(getattr(invoice, "status", None)).upper() or "-",
            "input_source": getattr(invoice, "input_source", None) or INPUT_SOURCE_REALTIME,
            "period": _format_period(invoice_start, invoice_end),
            "categories": sorted(overlap_categories),
            "category_label": _category_labels(overlap_categories),
        })

    batches = _query_all_or_first(_root_attr("ManualBillingBatch", ManualBillingBatch), branch_id=branch_id)
    for other_batch in batches:
        if not _same_billed_party(target_party_key, _batch_party_key(other_batch)):
            continue
        if current_batch_id and int(getattr(other_batch, "id", 0) or 0) == int(current_batch_id):
            continue
        status = _clean_text(getattr(other_batch, "status", "")).upper()
        if status == MANUAL_BACKFILL_STATUS_DRAFT or not _active_status(status):
            continue
        if not _ranges_overlap(period_start, period_end, getattr(other_batch, "period_start", None), getattr(other_batch, "period_end", None)):
            continue

        other_categories = _item_categories_from_items(getattr(other_batch, "items", []) or [])
        overlap_categories = target_categories & other_categories
        if not overlap_categories:
            continue

        conflicts.append({
            "kind": "REKAP",
            "batch_id": getattr(other_batch, "id", None),
            "invoice_id": getattr(other_batch, "invoice_id", None),
            "number": getattr(other_batch, "batch_number", None) or f"Rekap #{getattr(other_batch, 'id', '-')}",
            "linked_invoice_number": getattr(getattr(other_batch, "invoice", None), "invoice_number", None),
            "status": getattr(other_batch, "status", None),
            "status_label": _clean_text(getattr(other_batch, "status", None)).upper() or "-",
            "input_source": getattr(other_batch, "input_source", None) or INPUT_SOURCE_REALTIME,
            "period": _format_period(getattr(other_batch, "period_start", None), getattr(other_batch, "period_end", None)),
            "categories": sorted(overlap_categories),
            "category_label": _category_labels(overlap_categories),
        })

    return conflicts


def build_manual_backfill_duplicate_guard_context(batch):
    conflicts = collect_manual_backfill_duplicate_conflicts(batch)
    return {
        "has_conflicts": bool(conflicts),
        "conflicts": conflicts,
        "message": format_manual_backfill_duplicate_conflict_message(conflicts) if conflicts else "",
    }


def format_manual_backfill_duplicate_conflict_message(conflicts):
    if not conflicts:
        return ""
    first = conflicts[0]
    return (
        "Rekap ini berpotensi menagih data dobel. "
        f"Bentrok dengan {first['kind'].lower()} {first['number']} "
        f"periode {first['period']} untuk kategori {first['category_label']}."
    )


def assert_no_manual_backfill_duplicate_conflicts(batch):
    conflict_collector = _root_attr(
        "collect_manual_backfill_duplicate_conflicts",
        collect_manual_backfill_duplicate_conflicts,
    )
    conflicts = conflict_collector(batch)
    if conflicts:
        raise ManualBackfillBillingError(format_manual_backfill_duplicate_conflict_message(conflicts))
    return True


def get_manual_backfill_bill_to_context(batch):
    """Return display-safe billed party data for manual backfill screens."""
    if not batch:
        return {
            "type": "",
            "type_label": "-",
            "name": "-",
            "phone": "",
            "address": "",
            "notes": "",
            "master_context": "-",
        }

    bill_to_type = _infer_bill_to_type(
        getattr(batch, "bill_to_type", None),
        getattr(batch, "mandor_id", None),
        getattr(batch, "client_id", None),
        getattr(batch, "bill_to_name_snapshot", None),
    ) or _clean_text(getattr(batch, "bill_to_type", ""))
    mandor = getattr(batch, "mandor", None)
    client = getattr(batch, "client", None)

    snapshot_name = _clean_text(getattr(batch, "bill_to_name_snapshot", ""))
    if not snapshot_name and bill_to_type == BILL_TO_MANDOR_EXISTING:
        snapshot_name = _clean_text(getattr(mandor, "name", ""))
    if not snapshot_name and bill_to_type == BILL_TO_CLIENT_EXISTING:
        snapshot_name = _clean_text(getattr(client, "name", ""))

    master_context = "-"
    if bill_to_type == BILL_TO_MANDOR_EXISTING:
        master_context = _clean_text(getattr(mandor, "name", "")) or f"Mandor ID {getattr(batch, 'mandor_id', '-')}"
        if client:
            master_context = f"{master_context} / {getattr(client, 'name', '-')}"
    elif bill_to_type == BILL_TO_CLIENT_EXISTING:
        master_context = _clean_text(getattr(client, "name", "")) or f"Client ID {getattr(batch, 'client_id', '-')}"
    else:
        master_context = "Pihak bebas tanpa master mandor/client"

    return {
        "type": bill_to_type,
        "type_label": _bill_to_display_label(bill_to_type),
        "name": snapshot_name or "-",
        "phone": _clean_text(getattr(batch, "bill_to_phone_snapshot", "")),
        "address": _clean_text(getattr(batch, "bill_to_address_snapshot", "")),
        "notes": _clean_text(getattr(batch, "bill_to_notes", "")),
        "master_context": master_context,
    }
