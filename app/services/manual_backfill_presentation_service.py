# Split from app.services.manual_backfill_billing_service.
from app.services.manual_backfill_billing_service import *  # noqa: F401,F403
from app.services.manual_backfill_billing_service import _to_float
from app.services.manual_backfill_bill_to_service import _clean_text
from app.services.manual_backfill_duplicate_service import get_manual_backfill_bill_to_context
from app.utils.clock import today_wib
from app.utils.terms import T

def get_manual_backfill_status_context(status):
    """Return human-readable status metadata for the manual-book backfill flow."""
    normalized = _clean_text(status).upper() or MANUAL_BACKFILL_STATUS_DRAFT
    mapping = {
        MANUAL_BACKFILL_STATUS_DRAFT: {
            "label": "Draft",
            "badge_class": "status-warning",
            "helper": "Masih bisa diperiksa. Belum dikunci, belum menjadi invoice/piutang.",
        },
        MANUAL_BACKFILL_STATUS_LOCKED: {
            "label": "Terkunci",
            "badge_class": "status-success",
            "helper": "Data sudah dikunci sebagai dasar tagihan. Tahap berikutnya bisa dipromosikan ke invoice.",
        },
        MANUAL_BACKFILL_STATUS_INVOICED: {
            "label": "Sudah Jadi Invoice",
            "badge_class": "status-info",
            "helper": "Rekap sudah dipromosikan menjadi invoice/piutang.",
        },
        MANUAL_BACKFILL_STATUS_PARTIALLY_PAID: {
            "label": "Dibayar Sebagian",
            "badge_class": "status-progress",
            "helper": "Invoice dari rekap ini sudah dibayar sebagian.",
        },
        MANUAL_BACKFILL_STATUS_PAID: {
            "label": "Lunas",
            "badge_class": "status-success",
            "helper": "Invoice dari rekap ini sudah lunas.",
        },
        MANUAL_BACKFILL_STATUS_VOID: {
            "label": "Batal",
            "badge_class": "status-danger",
            "helper": "Rekap ini dibatalkan dan tidak boleh dipakai untuk invoice.",
        },
    }
    return mapping.get(normalized, {
        "label": normalized,
        "badge_class": "status-progress",
        "helper": "Status rekap belum dikenali penuh oleh UI.",
    })



def get_manual_backfill_status_filter_choices():
    """Choices for the manual-book recap register filter.

    Kept in the service layer so route, template, and tests use one status
    vocabulary. This is read-only UI metadata and does not affect REALTIME flow.
    """
    return [
        {"value": "", "label": "Semua status"},
        {"value": MANUAL_BACKFILL_STATUS_DRAFT, "label": "Draft"},
        {"value": MANUAL_BACKFILL_STATUS_LOCKED, "label": "Terkunci"},
        {"value": MANUAL_BACKFILL_STATUS_INVOICED, "label": "Sudah Jadi Invoice"},
        {"value": MANUAL_BACKFILL_STATUS_PARTIALLY_PAID, "label": "Dibayar Sebagian"},
        {"value": MANUAL_BACKFILL_STATUS_PAID, "label": "Lunas"},
        {"value": MANUAL_BACKFILL_STATUS_VOID, "label": "Batal/Void"},
    ]


def get_manual_backfill_bill_to_filter_choices():
    """Choices for the manual-book billed-party type filter."""
    return [
        {"value": "", "label": "Semua pihak"},
        {"value": BILL_TO_MANDOR_EXISTING, "label": f"{T.sub_client} existing"},
        {"value": BILL_TO_CLIENT_EXISTING, "label": f"{T.client} existing"},
        {"value": BILL_TO_KELOMPOK, "label": "Kelompok"},
        {"value": BILL_TO_PERORANGAN, "label": "Perorangan"},
        {"value": BILL_TO_CLIENT_LAIN, "label": f"{T.client} lain"},
    ]


def normalize_manual_backfill_status_filter(value):
    normalized = _clean_text(value).upper()
    valid_statuses = {choice["value"] for choice in get_manual_backfill_status_filter_choices() if choice["value"]}
    return normalized if normalized in valid_statuses else ""


def normalize_manual_backfill_bill_to_filter(value):
    normalized = _clean_text(value).upper()
    if not normalized:
        return ""
    normalized = BILL_TO_ALIASES.get(normalized, normalized)
    return normalized if normalized in FLEXIBLE_BILL_TO_TYPES else ""


def build_manual_backfill_register_summary(batches):
    """Build compact totals for the manual-book recap register.

    The register is an operational control screen, not accounting posting. VOID
    rows remain visible for trace, but they are excluded from active amount so
    users do not read cancelled book input as collectable receivable.
    """
    rows = list(batches or [])
    status_counts = {
        MANUAL_BACKFILL_STATUS_DRAFT: 0,
        MANUAL_BACKFILL_STATUS_LOCKED: 0,
        MANUAL_BACKFILL_STATUS_INVOICED: 0,
        MANUAL_BACKFILL_STATUS_PARTIALLY_PAID: 0,
        MANUAL_BACKFILL_STATUS_PAID: 0,
        MANUAL_BACKFILL_STATUS_VOID: 0,
    }
    total_amount = 0.0
    active_total_amount = 0.0
    invoice_ready_count = 0
    receivable_count = 0

    for batch in rows:
        status = _clean_text(getattr(batch, "status", "")).upper() or MANUAL_BACKFILL_STATUS_DRAFT
        amount = _to_float(getattr(batch, "total_amount", 0))
        total_amount += amount
        status_counts[status] = status_counts.get(status, 0) + 1

        if status != MANUAL_BACKFILL_STATUS_VOID:
            active_total_amount += amount
        if status == MANUAL_BACKFILL_STATUS_LOCKED and not getattr(batch, "invoice_id", None):
            invoice_ready_count += 1
        if status in {
            MANUAL_BACKFILL_STATUS_INVOICED,
            MANUAL_BACKFILL_STATUS_PARTIALLY_PAID,
        }:
            receivable_count += 1

    return {
        "total_count": len(rows),
        "total_amount": total_amount,
        "active_total_amount": active_total_amount,
        "draft_count": status_counts.get(MANUAL_BACKFILL_STATUS_DRAFT, 0),
        "locked_count": status_counts.get(MANUAL_BACKFILL_STATUS_LOCKED, 0),
        "invoice_ready_count": invoice_ready_count,
        "receivable_count": receivable_count,
        "paid_count": status_counts.get(MANUAL_BACKFILL_STATUS_PAID, 0),
        "void_count": status_counts.get(MANUAL_BACKFILL_STATUS_VOID, 0),
        "status_counts": status_counts,
    }



def build_manual_backfill_print_context(batch):
    """Build read-only print context for one MANUAL_BACKFILL recap.

    This helper only summarizes an existing batch for browser print/save-PDF.
    It does not create files, write database rows, or touch the REALTIME flow.
    """
    items = sorted(
        list(getattr(batch, "items", []) or []),
        key=lambda item: (
            getattr(item, "source_date", None) is None,
            getattr(item, "source_date", None) or date.min,
            getattr(item, "id", 0) or 0,
        ),
    )
    catering_rows = []
    warung_rows = []
    other_rows = []
    summary = {
        "item_count": len(items),
        "catering_count": 0,
        "warung_count": 0,
        "other_count": 0,
        "catering_qty": 0.0,
        "warung_qty": 0.0,
        "other_qty": 0.0,
        "catering_total": 0.0,
        "warung_total": 0.0,
        "other_total": 0.0,
        "grand_total": _to_float(getattr(batch, "total_amount", 0)),
    }

    for index, item in enumerate(items, start=1):
        item_type = _clean_text(getattr(item, "item_type", "")).upper()
        qty = _to_float(getattr(item, "qty", 0))
        subtotal = _to_float(getattr(item, "subtotal", 0))
        row = {
            "index": index,
            "item": item,
            "source_date": getattr(item, "source_date", None),
            "item_type": item_type,
            "description": getattr(item, "description", "") or "-",
            "source_label": getattr(item, "source_label", "") or "-",
            "qty": qty,
            "unit_price": _to_float(getattr(item, "unit_price", 0)),
            "subtotal": subtotal,
        }
        if item_type == MANUAL_BACKFILL_ITEM_CATERING:
            summary["catering_count"] += 1
            summary["catering_qty"] += qty
            summary["catering_total"] += subtotal
            catering_rows.append(row)
        elif item_type == MANUAL_BACKFILL_ITEM_WARUNG:
            summary["warung_count"] += 1
            summary["warung_qty"] += qty
            summary["warung_total"] += subtotal
            warung_rows.append(row)
        else:
            summary["other_count"] += 1
            summary["other_qty"] += qty
            summary["other_total"] += subtotal
            other_rows.append(row)

    invoice = getattr(batch, "invoice", None)
    payment_summary = {
        "invoice_number": getattr(invoice, "invoice_number", None) if invoice else None,
        "invoice_status": getattr(invoice, "status", None) if invoice else None,
        "paid_amount": _to_float(getattr(invoice, "paid_amount", 0)) if invoice else 0.0,
        "remaining_amount": _to_float(getattr(invoice, "remaining_amount", 0)) if invoice else summary["grand_total"],
    }

    return {
        "generated_date": today_wib(),
        "batch": batch,
        "bill_to_context": get_manual_backfill_bill_to_context(batch),
        "status_context": get_manual_backfill_status_context(getattr(batch, "status", None)),
        "summary": summary,
        "payment_summary": payment_summary,
        "catering_rows": catering_rows,
        "warung_rows": warung_rows,
        "other_rows": other_rows,
    }
