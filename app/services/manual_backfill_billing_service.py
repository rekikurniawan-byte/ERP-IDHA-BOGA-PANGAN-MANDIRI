"""Manual book/backfill billing helpers.

This flow is intentionally separate from the live/realtime operational flow.
It records old/manual book recap data as MANUAL_BACKFILL draft batches first;
invoice/piutang promotion is handled in a later stage so the live flow is not
changed accidentally.
"""

from datetime import date, datetime, timedelta, timezone

from app.extensions import db
from app.models.finance import Invoice, InvoiceItem, ManualBillingBatch, ManualBillingBatchItem
from app.models.master import Client, Mandor
from app.services.audit_log_service import record_audit_log
from app.services.billing_input_source_service import INPUT_SOURCE_MANUAL_BACKFILL, INPUT_SOURCE_REALTIME
from app.services.invoice_identity_service import build_company_bank_snapshot
from app.services.manual_billing_service import (
    MANUAL_BILLING_INVOICE_SOURCE,
    create_invoice_journal_for_invoice,
    generate_manual_billing_invoice_number,
    generate_manual_billing_number,
)

MANUAL_BACKFILL_SOURCE_CATERING = "MANUAL_BOOK_CATERING"
MANUAL_BACKFILL_SOURCE_WARUNG = "MANUAL_BOOK_WARUNG"
MANUAL_BACKFILL_ITEM_CATERING = "CATERING"
MANUAL_BACKFILL_ITEM_WARUNG = "WARUNG_DEBT"

MANUAL_BACKFILL_STATUS_DRAFT = "DRAFT"
MANUAL_BACKFILL_STATUS_LOCKED = "LOCKED"
MANUAL_BACKFILL_STATUS_INVOICED = "INVOICED"
MANUAL_BACKFILL_STATUS_PARTIALLY_PAID = "PARTIALLY_PAID"
MANUAL_BACKFILL_STATUS_PAID = "PAID"
MANUAL_BACKFILL_STATUS_VOID = "VOID"

MANUAL_BACKFILL_TERMINAL_STATUSES = {
    MANUAL_BACKFILL_STATUS_INVOICED,
    MANUAL_BACKFILL_STATUS_PARTIALLY_PAID,
    MANUAL_BACKFILL_STATUS_PAID,
    MANUAL_BACKFILL_STATUS_VOID,
}

# Status yang tidak boleh dipakai sebagai pembanding dobel-tagih.
# Selain status ini, invoice/batch dianggap masih aktif sebagai dokumen tagihan.
INACTIVE_BILLING_STATUSES = {"VOID", "VOIDED", "CANCELLED", "CANCELED", "REJECTED"}

BILLING_CATEGORY_CATERING = "CATERING"
BILLING_CATEGORY_WARUNG = "WARUNG_DEBT"
BILLING_CATEGORY_OTHER = "OTHER"

BILL_TO_MANDOR_EXISTING = "MANDOR_EXISTING"
BILL_TO_CLIENT_EXISTING = "CLIENT_EXISTING"
BILL_TO_KELOMPOK = "KELOMPOK"
BILL_TO_PERORANGAN = "PERORANGAN"
BILL_TO_CLIENT_LAIN = "CLIENT_LAIN"
FLEXIBLE_BILL_TO_TYPES = {
    BILL_TO_MANDOR_EXISTING,
    BILL_TO_CLIENT_EXISTING,
    BILL_TO_KELOMPOK,
    BILL_TO_PERORANGAN,
    BILL_TO_CLIENT_LAIN,
}
BILL_TO_ALIASES = {
    "MANDOR": BILL_TO_MANDOR_EXISTING,
    "CLIENT": BILL_TO_CLIENT_EXISTING,
}

CATERING_ITEM_TYPES = {"CATERING", "REVISION_INCREASE"}
WARUNG_ITEM_TYPES = {"WARUNG_DEBT"}
CATERING_SOURCE_TYPES = {
    MANUAL_BACKFILL_SOURCE_CATERING,
    "DAILY_ORDER",
    "DAILY_ORDER_DETAIL",
    "ORDER_DETAIL",
    "ORDER_REVISION",
    "PERIOD_INVOICE",
}
WARUNG_SOURCE_TYPES = {
    MANUAL_BACKFILL_SOURCE_WARUNG,
    "WORKER_DEBT",
}


class ManualBackfillBillingError(Exception):
    pass


def _to_float(value):
    if isinstance(value, str):
        value = value.replace(".", "").replace(",", ".").strip()
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def _clean_text(value):
    return str(value or "").strip()


def _normalize_bill_to_type(value):
    normalized = _clean_text(value).upper()
    normalized = BILL_TO_ALIASES.get(normalized, normalized)
    if normalized not in FLEXIBLE_BILL_TO_TYPES:
        raise ManualBackfillBillingError("Tipe pihak ditagih tidak valid.")
    return normalized


def _normalize_party_name(value):
    return " ".join(_clean_text(value).lower().split())


def _infer_bill_to_type(value=None, mandor_id=None, client_id=None, name=None):
    """Normalize bill-to type while keeping older test/data objects compatible.

    Tahap 10 stored manual/realtime invoices as MANDOR or CLIENT. Tahap 10.5
    stores manual backfill batches with the wider type set. For duplicate guard
    and lightweight unit fakes, infer the old mandor/client meaning when the type
    field is absent but ids are present.
    """
    raw = _clean_text(value)
    if raw:
        return _normalize_bill_to_type(raw)
    if mandor_id:
        return BILL_TO_MANDOR_EXISTING
    if client_id:
        return BILL_TO_CLIENT_EXISTING
    if _clean_text(name):
        return BILL_TO_CLIENT_LAIN
    return None


def _legacy_invoice_bill_to_type(value):
    normalized = _normalize_bill_to_type(value or BILL_TO_MANDOR_EXISTING)
    if normalized == BILL_TO_MANDOR_EXISTING:
        return "MANDOR"
    if normalized == BILL_TO_CLIENT_EXISTING:
        return "CLIENT"
    return normalized


def _bill_to_display_label(value):
    mapping = {
        BILL_TO_MANDOR_EXISTING: "Mandor existing",
        BILL_TO_CLIENT_EXISTING: "Client existing",
        BILL_TO_KELOMPOK: "Kelompok",
        BILL_TO_PERORANGAN: "Perorangan",
        BILL_TO_CLIENT_LAIN: "Client lain",
    }
    return mapping.get(_clean_text(value).upper(), _clean_text(value) or "-")


def _resolve_manual_backfill_bill_to(
    *,
    branch_id,
    bill_to_type=None,
    mandor_id=None,
    client_id=None,
    bill_to_name_snapshot=None,
    bill_to_phone_snapshot=None,
    bill_to_address_snapshot=None,
    bill_to_notes=None,
):
    bill_to_type = _normalize_bill_to_type(bill_to_type or BILL_TO_MANDOR_EXISTING)
    mandor = None
    client = None

    if bill_to_type == BILL_TO_MANDOR_EXISTING:
        try:
            mandor_id = int(mandor_id)
        except (TypeError, ValueError):
            raise ManualBackfillBillingError("Mandor existing wajib dipilih.")
        mandor = Mandor.query.filter_by(id=mandor_id, branch_id=branch_id, is_active=True).first()
        if not mandor:
            raise ManualBackfillBillingError("Mandor/PIC lapangan tidak ditemukan atau nonaktif.")
        client = getattr(mandor, "client", None)
        return {
            "bill_to_type": bill_to_type,
            "mandor": mandor,
            "client": client,
            "mandor_id": getattr(mandor, "id", None),
            "client_id": getattr(client, "id", None) or getattr(mandor, "client_id", None),
            "bill_to_name_snapshot": _clean_text(bill_to_name_snapshot) or _clean_text(getattr(mandor, "name", "")),
            "bill_to_phone_snapshot": _clean_text(bill_to_phone_snapshot) or _clean_text(getattr(mandor, "phone", "")),
            "bill_to_address_snapshot": _clean_text(bill_to_address_snapshot),
            "bill_to_notes": _clean_text(bill_to_notes),
        }

    if bill_to_type == BILL_TO_CLIENT_EXISTING:
        try:
            client_id = int(client_id)
        except (TypeError, ValueError):
            raise ManualBackfillBillingError("Client existing wajib dipilih.")
        client = Client.query.filter_by(id=client_id, is_active=True).first()
        if not client:
            raise ManualBackfillBillingError("Client tidak ditemukan atau nonaktif.")
        return {
            "bill_to_type": bill_to_type,
            "mandor": None,
            "client": client,
            "mandor_id": None,
            "client_id": getattr(client, "id", None),
            "bill_to_name_snapshot": _clean_text(bill_to_name_snapshot) or _clean_text(getattr(client, "name", "")),
            "bill_to_phone_snapshot": _clean_text(bill_to_phone_snapshot) or _clean_text(getattr(client, "phone", "")),
            "bill_to_address_snapshot": _clean_text(bill_to_address_snapshot) or _clean_text(getattr(client, "address", "")),
            "bill_to_notes": _clean_text(bill_to_notes),
        }

    bill_to_name_snapshot = _clean_text(bill_to_name_snapshot)
    if not bill_to_name_snapshot:
        raise ManualBackfillBillingError("Nama pihak ditagih wajib diisi untuk pihak bebas.")
    return {
        "bill_to_type": bill_to_type,
        "mandor": None,
        "client": None,
        "mandor_id": None,
        "client_id": None,
        "bill_to_name_snapshot": bill_to_name_snapshot,
        "bill_to_phone_snapshot": _clean_text(bill_to_phone_snapshot),
        "bill_to_address_snapshot": _clean_text(bill_to_address_snapshot),
        "bill_to_notes": _clean_text(bill_to_notes),
    }


def _parse_date(value):
    if isinstance(value, date):
        return value
    value = _clean_text(value)
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def build_catering_backfill_rows(dates, lunch_qtys, dinner_qtys, unit_prices, notes=None, breakfast_qtys=None):
    """Normalize repeated catering form rows into ready-to-persist line dicts.

    Tahap 10.13 keeps breakfast/sarapan inside MANUAL_BACKFILL only by storing
    it in the line description and total qty. No realtime order schema is touched.
    Duplicate dates inside one manual recap are rejected so users do not silently
    double-charge the same catering day. Put sarapan/siang/sore in one row for
    the date, or adjust the same row before lock.
    """
    notes = notes or []
    breakfast_qtys = breakfast_qtys or []
    rows = []
    seen_dates = {}
    max_len = max(
        len(dates or []),
        len(breakfast_qtys or []),
        len(lunch_qtys or []),
        len(dinner_qtys or []),
        len(unit_prices or []),
        len(notes or []),
        0,
    )

    for index in range(max_len):
        row_date = _parse_date(dates[index] if index < len(dates or []) else None)
        breakfast_qty = _to_float(breakfast_qtys[index] if index < len(breakfast_qtys or []) else 0)
        lunch_qty = _to_float(lunch_qtys[index] if index < len(lunch_qtys or []) else 0)
        dinner_qty = _to_float(dinner_qtys[index] if index < len(dinner_qtys or []) else 0)
        unit_price = _to_float(unit_prices[index] if index < len(unit_prices or []) else 0)
        note = _clean_text(notes[index] if index < len(notes or []) else "")

        # Blank row: ignore it. Partially filled row: fail loudly so totals do not lie.
        if not row_date and breakfast_qty <= 0 and lunch_qty <= 0 and dinner_qty <= 0 and unit_price <= 0 and not note:
            continue
        if not row_date:
            raise ManualBackfillBillingError(f"Tanggal catering baris {index + 1} wajib diisi.")
        if row_date in seen_dates:
            first_row = seen_dates[row_date]
            raise ManualBackfillBillingError(
                "Tanggal catering tidak boleh dobel dalam satu rekap. "
                f"Tanggal {row_date.strftime('%d-%m-%Y')} sudah ada di baris {first_row}. "
                "Gabungkan sarapan/siang/sore atau penyesuaian pada satu baris tanggal yang sama."
            )
        seen_dates[row_date] = index + 1

        total_qty = breakfast_qty + lunch_qty + dinner_qty
        if total_qty <= 0:
            raise ManualBackfillBillingError(f"Porsi catering baris {index + 1} wajib lebih dari 0.")
        if unit_price <= 0:
            raise ManualBackfillBillingError(f"Harga per porsi catering baris {index + 1} wajib lebih dari 0.")

        subtotal = total_qty * unit_price
        description = (
            f"Catering manual buku {row_date.strftime('%d-%m-%Y')} | "
            f"Sarapan {breakfast_qty:g} | Siang {lunch_qty:g} | Sore {dinner_qty:g} | Total {total_qty:g} porsi"
        )
        if note:
            description = f"{description} | {note}"

        rows.append({
            "item_type": MANUAL_BACKFILL_ITEM_CATERING,
            "source_type": MANUAL_BACKFILL_SOURCE_CATERING,
            "source_date": row_date,
            "description": description,
            "qty": total_qty,
            "unit_price": unit_price,
            "subtotal": subtotal,
            "source_label": row_date.strftime("%d-%m-%Y"),
        })

    return rows


def build_warung_backfill_rows(worker_names, debt_amounts, notes=None):
    """Normalize repeated warung/kasbon form rows into ready-to-persist line dicts."""
    notes = notes or []
    rows = []
    max_len = max(len(worker_names or []), len(debt_amounts or []), len(notes or []), 0)

    for index in range(max_len):
        worker_name = _clean_text(worker_names[index] if index < len(worker_names or []) else "")
        amount = _to_float(debt_amounts[index] if index < len(debt_amounts or []) else 0)
        note = _clean_text(notes[index] if index < len(notes or []) else "")

        if not worker_name and amount <= 0 and not note:
            continue
        if not worker_name:
            raise ManualBackfillBillingError(f"Nama pekerja warung/kasbon baris {index + 1} wajib diisi.")
        if amount <= 0:
            raise ManualBackfillBillingError(f"Nominal warung/kasbon baris {index + 1} wajib lebih dari 0.")

        description = f"Kasbon/hutang warung pekerja {worker_name}"
        if note:
            description = f"{description} | {note}"

        rows.append({
            "item_type": MANUAL_BACKFILL_ITEM_WARUNG,
            "source_type": MANUAL_BACKFILL_SOURCE_WARUNG,
            "source_date": None,
            "description": description,
            "qty": 1,
            "unit_price": amount,
            "subtotal": amount,
            "source_label": worker_name,
        })

    return rows


def summarize_backfill_rows(rows):
    catering_total = sum(_to_float(row.get("subtotal")) for row in rows if row.get("item_type") == MANUAL_BACKFILL_ITEM_CATERING)
    warung_total = sum(_to_float(row.get("subtotal")) for row in rows if row.get("item_type") == MANUAL_BACKFILL_ITEM_WARUNG)
    return {
        "catering_total": catering_total,
        "warung_total": warung_total,
        "total_amount": catering_total + warung_total,
        "item_count": len(rows),
    }


def _normalize_manual_backfill_batch_payload(
    *,
    branch_id,
    mandor_id=None,
    client_id=None,
    bill_to_type=BILL_TO_MANDOR_EXISTING,
    bill_to_name_snapshot=None,
    bill_to_phone_snapshot=None,
    bill_to_address_snapshot=None,
    bill_to_notes=None,
    period_start,
    period_end,
    catering_rows=None,
    warung_rows=None,
):
    period_start = _parse_date(period_start)
    period_end = _parse_date(period_end)
    if not period_start or not period_end:
        raise ManualBackfillBillingError("Periode rekap wajib valid.")
    if period_start > period_end:
        raise ManualBackfillBillingError("Tanggal mulai tidak boleh lebih besar dari tanggal selesai.")

    bill_to = _resolve_manual_backfill_bill_to(
        branch_id=branch_id,
        bill_to_type=bill_to_type,
        mandor_id=mandor_id,
        client_id=client_id,
        bill_to_name_snapshot=bill_to_name_snapshot,
        bill_to_phone_snapshot=bill_to_phone_snapshot,
        bill_to_address_snapshot=bill_to_address_snapshot,
        bill_to_notes=bill_to_notes,
    )

    rows = list(catering_rows or []) + list(warung_rows or [])
    summary = summarize_backfill_rows(rows)
    if summary["total_amount"] <= 0 or not rows:
        raise ManualBackfillBillingError("Minimal isi satu baris catering atau warung/kasbon.")

    return period_start, period_end, bill_to, rows, summary


def _add_manual_backfill_batch_items(batch, rows):
    for index, row in enumerate(rows, start=1):
        source_type = row["source_type"]
        # Existing schema requires (source_type, source_id) to be globally unique.
        # Manual book lines do not have an external id, so derive one from batch id.
        source_id = int(getattr(batch, "id", 0) or 0) * 100000 + index
        db.session.add(ManualBillingBatchItem(
            batch=batch,
            item_type=row["item_type"],
            description=row["description"],
            qty=_to_float(row.get("qty")),
            unit_price=_to_float(row.get("unit_price")),
            subtotal=_to_float(row.get("subtotal")),
            source_type=source_type,
            source_id=source_id,
            source_date=row.get("source_date"),
            input_source=INPUT_SOURCE_MANUAL_BACKFILL,
            source_label=row.get("source_label"),
        ))


def _apply_manual_backfill_batch_values(batch, *, period_start, period_end, bill_to, summary, notes):
    batch.period_start = period_start
    batch.period_end = period_end
    batch.bill_to_type = bill_to["bill_to_type"]
    batch.client_id = bill_to["client_id"]
    batch.mandor_id = bill_to["mandor_id"]
    batch.client_pic_id = None
    batch.bill_to_name_snapshot = bill_to["bill_to_name_snapshot"]
    batch.bill_to_phone_snapshot = bill_to["bill_to_phone_snapshot"]
    batch.bill_to_address_snapshot = bill_to["bill_to_address_snapshot"]
    batch.bill_to_notes = bill_to["bill_to_notes"]
    batch.total_amount = summary["total_amount"]
    batch.notes = notes


def create_manual_backfill_batch(
    *,
    branch_id,
    mandor_id=None,
    client_id=None,
    bill_to_type=BILL_TO_MANDOR_EXISTING,
    bill_to_name_snapshot=None,
    bill_to_phone_snapshot=None,
    bill_to_address_snapshot=None,
    bill_to_notes=None,
    period_start,
    period_end,
    catering_rows=None,
    warung_rows=None,
    notes=None,
    created_by,
):
    """Create a MANUAL_BACKFILL draft recap from manual book rows.

    This function only stores the book recap as a draft batch. It does not create
    invoice/piutang yet; promotion is intentionally done after lock.
    """
    period_start, period_end, bill_to, rows, summary = _normalize_manual_backfill_batch_payload(
        branch_id=branch_id,
        bill_to_type=bill_to_type,
        mandor_id=mandor_id,
        client_id=client_id,
        bill_to_name_snapshot=bill_to_name_snapshot,
        bill_to_phone_snapshot=bill_to_phone_snapshot,
        bill_to_address_snapshot=bill_to_address_snapshot,
        bill_to_notes=bill_to_notes,
        period_start=period_start,
        period_end=period_end,
        catering_rows=catering_rows,
        warung_rows=warung_rows,
    )

    batch = ManualBillingBatch(
        branch_id=branch_id,
        batch_number=generate_manual_billing_number(period_end),
        status=MANUAL_BACKFILL_STATUS_DRAFT,
        input_source=INPUT_SOURCE_MANUAL_BACKFILL,
        created_by=created_by,
    )
    _apply_manual_backfill_batch_values(
        batch,
        period_start=period_start,
        period_end=period_end,
        bill_to=bill_to,
        summary=summary,
        notes=notes,
    )
    db.session.add(batch)
    db.session.flush()
    _add_manual_backfill_batch_items(batch, rows)

    record_audit_log(
        module="FINANCE",
        event_type="MANUAL_BACKFILL_BATCH_CREATED",
        action="CREATE",
        table_name="manual_billing_batches",
        record_id=getattr(batch, "id", None),
        description=f"Input rekap manual dari buku {batch.batch_number} dibuat sebagai draft.",
        metadata={
            "batch_number": batch.batch_number,
            "input_source": INPUT_SOURCE_MANUAL_BACKFILL,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "bill_to_type": bill_to["bill_to_type"],
            "bill_to_name_snapshot": bill_to["bill_to_name_snapshot"],
            **summary,
        },
        user_id=created_by,
        branch_id=branch_id,
        commit=False,
    )

    return batch


def _delete_manual_backfill_batch_items(batch):
    for item in list(getattr(batch, "items", []) or []):
        db.session.delete(item)
    db.session.flush()


def update_manual_backfill_batch(
    *,
    batch_id,
    branch_id,
    mandor_id=None,
    client_id=None,
    bill_to_type=BILL_TO_MANDOR_EXISTING,
    bill_to_name_snapshot=None,
    bill_to_phone_snapshot=None,
    bill_to_address_snapshot=None,
    bill_to_notes=None,
    period_start,
    period_end,
    catering_rows=None,
    warung_rows=None,
    notes=None,
    updated_by,
    commit=False,
):
    """Edit a manual backfill recap while it is still a draft.

    Locked/invoiced/paid recaps are immutable here because they can already be
    part of invoice, receivable, payment, and audit trace flows.
    """
    batch = _get_manual_backfill_batch(batch_id, branch_id)
    if getattr(batch, "status", None) != MANUAL_BACKFILL_STATUS_DRAFT:
        raise ManualBackfillBillingError("Hanya rekap manual berstatus Draft yang bisa diedit.")
    if getattr(batch, "invoice_id", None):
        raise ManualBackfillBillingError("Rekap yang sudah memiliki invoice tidak bisa diedit.")

    period_start, period_end, bill_to, rows, summary = _normalize_manual_backfill_batch_payload(
        branch_id=branch_id,
        bill_to_type=bill_to_type,
        mandor_id=mandor_id,
        client_id=client_id,
        bill_to_name_snapshot=bill_to_name_snapshot,
        bill_to_phone_snapshot=bill_to_phone_snapshot,
        bill_to_address_snapshot=bill_to_address_snapshot,
        bill_to_notes=bill_to_notes,
        period_start=period_start,
        period_end=period_end,
        catering_rows=catering_rows,
        warung_rows=warung_rows,
    )

    before_total = _to_float(getattr(batch, "total_amount", 0))
    before_item_count = len(getattr(batch, "items", []) or [])
    _apply_manual_backfill_batch_values(
        batch,
        period_start=period_start,
        period_end=period_end,
        bill_to=bill_to,
        summary=summary,
        notes=notes,
    )
    _delete_manual_backfill_batch_items(batch)
    _add_manual_backfill_batch_items(batch, rows)

    record_audit_log(
        module="FINANCE",
        event_type="MANUAL_BACKFILL_BATCH_UPDATED",
        action="UPDATE",
        table_name="manual_billing_batches",
        record_id=getattr(batch, "id", None),
        description=f"Draft rekap manual dari buku {batch.batch_number} diperbarui.",
        metadata={
            "batch_number": getattr(batch, "batch_number", None),
            "input_source": INPUT_SOURCE_MANUAL_BACKFILL,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "bill_to_type": bill_to["bill_to_type"],
            "bill_to_name_snapshot": bill_to["bill_to_name_snapshot"],
            "before_total_amount": before_total,
            "before_item_count": before_item_count,
            **summary,
        },
        user_id=updated_by,
        branch_id=branch_id,
        commit=False,
    )

    if commit:
        db.session.commit()
    return batch


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

    invoices = _query_all_or_first(Invoice, branch_id=branch_id)
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

    batches = _query_all_or_first(ManualBillingBatch, branch_id=branch_id)
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
    conflicts = collect_manual_backfill_duplicate_conflicts(batch)
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
        {"value": BILL_TO_MANDOR_EXISTING, "label": "Mandor existing"},
        {"value": BILL_TO_CLIENT_EXISTING, "label": "Client existing"},
        {"value": BILL_TO_KELOMPOK, "label": "Kelompok"},
        {"value": BILL_TO_PERORANGAN, "label": "Perorangan"},
        {"value": BILL_TO_CLIENT_LAIN, "label": "Client lain"},
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
        "generated_date": date.today(),
        "batch": batch,
        "bill_to_context": get_manual_backfill_bill_to_context(batch),
        "status_context": get_manual_backfill_status_context(getattr(batch, "status", None)),
        "summary": summary,
        "payment_summary": payment_summary,
        "catering_rows": catering_rows,
        "warung_rows": warung_rows,
        "other_rows": other_rows,
    }

def _get_manual_backfill_batch(batch_id, branch_id):
    try:
        batch_id = int(batch_id)
    except (TypeError, ValueError):
        raise ManualBackfillBillingError("Rekap tagihan tidak valid.")

    batch = ManualBillingBatch.query.filter_by(
        id=batch_id,
        branch_id=branch_id,
        input_source=INPUT_SOURCE_MANUAL_BACKFILL,
    ).first()
    if not batch:
        raise ManualBackfillBillingError("Rekap input belakangan dari buku tidak ditemukan.")
    return batch


def _validate_manual_backfill_batch_items(batch):
    """Validate manual-book recap content regardless of current workflow status."""
    period_start = getattr(batch, "period_start", None)
    period_end = getattr(batch, "period_end", None)
    if not period_start or not period_end or period_start > period_end:
        raise ManualBackfillBillingError("Periode rekap tidak valid.")

    raw_bill_to_type = getattr(batch, "bill_to_type", None)
    bill_to_type = _infer_bill_to_type(
        raw_bill_to_type,
        getattr(batch, "mandor_id", None),
        getattr(batch, "client_id", None),
        getattr(batch, "bill_to_name_snapshot", None),
    )
    if raw_bill_to_type and bill_to_type == BILL_TO_MANDOR_EXISTING and not getattr(batch, "mandor_id", None):
        raise ManualBackfillBillingError("Mandor existing wajib ada pada rekap manual.")
    if raw_bill_to_type and bill_to_type == BILL_TO_CLIENT_EXISTING and not getattr(batch, "client_id", None):
        raise ManualBackfillBillingError("Client existing wajib ada pada rekap manual.")
    if bill_to_type in {BILL_TO_KELOMPOK, BILL_TO_PERORANGAN, BILL_TO_CLIENT_LAIN} and not _clean_text(getattr(batch, "bill_to_name_snapshot", "")):
        raise ManualBackfillBillingError("Nama pihak ditagih wajib ada pada rekap manual.")

    items = list(getattr(batch, "items", []) or [])
    if not items:
        raise ManualBackfillBillingError("Rekap belum punya rincian item, tidak bisa diproses.")

    allowed_item_types = {MANUAL_BACKFILL_ITEM_CATERING, MANUAL_BACKFILL_ITEM_WARUNG}
    total_from_items = 0.0
    seen_catering_dates = {}
    seen_source_keys = {}
    for index, item in enumerate(items, start=1):
        item_type = _clean_text(getattr(item, "item_type", "")).upper()
        if item_type not in allowed_item_types:
            raise ManualBackfillBillingError(f"Jenis item baris {index} tidak didukung untuk input belakangan.")

        qty = _to_float(getattr(item, "qty", 0))
        unit_price = _to_float(getattr(item, "unit_price", 0))
        subtotal = _to_float(getattr(item, "subtotal", 0))
        if qty <= 0 or unit_price <= 0 or subtotal <= 0:
            raise ManualBackfillBillingError(f"Qty, harga, dan subtotal baris {index} wajib lebih dari 0.")

        if getattr(item, "input_source", None) != INPUT_SOURCE_MANUAL_BACKFILL:
            raise ManualBackfillBillingError(f"Sumber input item baris {index} bukan Input Belakangan.")

        source_date = getattr(item, "source_date", None)
        source_type = getattr(item, "source_type", None)
        source_id = getattr(item, "source_id", None)
        source_key = (source_type, source_id)
        if source_type and source_id is not None:
            if source_key in seen_source_keys:
                raise ManualBackfillBillingError(
                    f"Source item baris {index} dobel dengan baris {seen_source_keys[source_key]}."
                )
            seen_source_keys[source_key] = index

        if item_type == MANUAL_BACKFILL_ITEM_CATERING:
            if not source_date:
                raise ManualBackfillBillingError(f"Tanggal catering baris {index} wajib ada sebelum diproses.")
            if source_date < period_start or source_date > period_end:
                raise ManualBackfillBillingError(f"Tanggal catering baris {index} di luar periode rekap.")
            if source_date in seen_catering_dates:
                raise ManualBackfillBillingError(
                    f"Tanggal catering baris {index} dobel dengan baris {seen_catering_dates[source_date]}. "
                    "Gabungkan sarapan/siang/sore atau penyesuaian pada satu baris tanggal yang sama."
                )
            seen_catering_dates[source_date] = index

        total_from_items += subtotal

    total_amount = _to_float(getattr(batch, "total_amount", 0))
    if total_amount <= 0:
        raise ManualBackfillBillingError("Total rekap wajib lebih dari 0.")
    if abs(total_amount - total_from_items) > 0.01:
        raise ManualBackfillBillingError("Total rekap tidak sama dengan total rincian item.")

    return {
        "item_count": len(items),
        "total_amount": total_amount,
        "catering_total": sum(_to_float(getattr(item, "subtotal", 0)) for item in items if getattr(item, "item_type", None) == MANUAL_BACKFILL_ITEM_CATERING),
        "warung_total": sum(_to_float(getattr(item, "subtotal", 0)) for item in items if getattr(item, "item_type", None) == MANUAL_BACKFILL_ITEM_WARUNG),
    }


def validate_manual_backfill_batch_before_lock(batch):
    """Validate draft manual-book recap before it becomes locked source data."""
    if not batch:
        raise ManualBackfillBillingError("Rekap input belakangan dari buku tidak ditemukan.")

    status = _clean_text(getattr(batch, "status", "")).upper()
    if status != MANUAL_BACKFILL_STATUS_DRAFT:
        raise ManualBackfillBillingError("Hanya rekap berstatus Draft yang bisa dikunci.")

    if getattr(batch, "invoice_id", None):
        raise ManualBackfillBillingError("Rekap ini sudah terkait invoice dan tidak bisa dikunci ulang.")

    if getattr(batch, "input_source", None) != INPUT_SOURCE_MANUAL_BACKFILL:
        raise ManualBackfillBillingError("Lock tahap ini hanya untuk rekap input belakangan dari buku.")

    return _validate_manual_backfill_batch_items(batch)


def lock_manual_backfill_batch(*, batch_id, branch_id, locked_by, commit=False):
    """Lock a MANUAL_BACKFILL draft so it becomes a controlled invoice source."""
    batch = _get_manual_backfill_batch(batch_id, branch_id)
    summary = validate_manual_backfill_batch_before_lock(batch)
    assert_no_manual_backfill_duplicate_conflicts(batch)

    batch.status = MANUAL_BACKFILL_STATUS_LOCKED
    batch.locked_at = datetime.now(timezone.utc).replace(tzinfo=None)
    batch.locked_by = locked_by

    record_audit_log(
        module="FINANCE",
        event_type="MANUAL_BACKFILL_BATCH_LOCKED",
        action="LOCK",
        table_name="manual_billing_batches",
        record_id=getattr(batch, "id", None),
        description=f"Input rekap manual dari buku {batch.batch_number} dikunci sebagai sumber tagihan.",
        metadata={
            "batch_number": getattr(batch, "batch_number", None),
            "input_source": INPUT_SOURCE_MANUAL_BACKFILL,
            "status": MANUAL_BACKFILL_STATUS_LOCKED,
            **summary,
        },
        user_id=locked_by,
        branch_id=branch_id,
        commit=False,
    )

    if commit:
        db.session.commit()

    return batch


def validate_manual_backfill_batch_before_void(batch):
    """Validate a manual-book recap can be voided before invoice creation.

    Void is only allowed on the MANUAL_BACKFILL lane before invoice/piutang
    exists. This keeps historical wrong book entries auditable without deleting
    rows and without touching the realtime billing flow.
    """
    if not batch:
        raise ManualBackfillBillingError("Rekap input belakangan dari buku tidak ditemukan.")

    if getattr(batch, "input_source", None) != INPUT_SOURCE_MANUAL_BACKFILL:
        raise ManualBackfillBillingError("Void tahap ini hanya untuk rekap input belakangan dari buku.")

    status = _clean_text(getattr(batch, "status", "")).upper()
    if status not in {MANUAL_BACKFILL_STATUS_DRAFT, MANUAL_BACKFILL_STATUS_LOCKED}:
        raise ManualBackfillBillingError("Hanya rekap manual berstatus Draft atau Terkunci yang belum jadi invoice yang bisa dibatalkan.")

    if getattr(batch, "invoice_id", None):
        raise ManualBackfillBillingError("Rekap yang sudah memiliki invoice tidak bisa dibatalkan dari halaman rekap manual.")

    existing_invoice = Invoice.query.filter_by(
        source_type=MANUAL_BILLING_INVOICE_SOURCE,
        source_order_id=getattr(batch, "id", None),
    ).first()
    if existing_invoice:
        raise ManualBackfillBillingError(
            f"Rekap ini sudah punya invoice {getattr(existing_invoice, 'invoice_number', '-')}, tidak bisa dibatalkan."
        )

    return True


def void_manual_backfill_batch(*, batch_id, branch_id, voided_by, reason=None, commit=False):
    """Void a MANUAL_BACKFILL recap before invoice/piutang is created."""
    batch = _get_manual_backfill_batch(batch_id, branch_id)
    validate_manual_backfill_batch_before_void(batch)

    old_status = _clean_text(getattr(batch, "status", "")).upper() or None
    reason = _clean_text(reason) or "Dibatalkan sebelum invoice/piutang dibuat."
    existing_notes = _clean_text(getattr(batch, "notes", ""))
    void_note = f"[VOID sebelum invoice] {reason}"
    batch.notes = f"{existing_notes}\n{void_note}".strip() if existing_notes else void_note
    batch.status = MANUAL_BACKFILL_STATUS_VOID

    record_audit_log(
        module="FINANCE",
        event_type="MANUAL_BACKFILL_BATCH_VOIDED",
        action="VOID",
        table_name="manual_billing_batches",
        record_id=getattr(batch, "id", None),
        description=f"Input rekap manual dari buku {batch.batch_number} dibatalkan sebelum menjadi invoice/piutang.",
        metadata={
            "batch_number": getattr(batch, "batch_number", None),
            "input_source": INPUT_SOURCE_MANUAL_BACKFILL,
            "old_status": old_status,
            "new_status": MANUAL_BACKFILL_STATUS_VOID,
            "reason": reason,
        },
        user_id=voided_by,
        branch_id=branch_id,
        commit=False,
    )

    if commit:
        db.session.commit()

    return batch


def validate_manual_backfill_batch_before_invoice(batch, *, invoice_date=None):
    """Validate locked manual-book recap before creating invoice/piutang."""
    if not batch:
        raise ManualBackfillBillingError("Rekap input belakangan dari buku tidak ditemukan.")

    status = _clean_text(getattr(batch, "status", "")).upper()
    if status != MANUAL_BACKFILL_STATUS_LOCKED:
        raise ManualBackfillBillingError("Hanya rekap manual berstatus Terkunci yang bisa dibuat menjadi invoice.")

    invoice_date = invoice_date or date.today()
    period_end = getattr(batch, "period_end", None)
    if period_end and period_end > invoice_date:
        raise ManualBackfillBillingError("Periode rekap manual belum selesai, belum boleh dibuat invoice.")

    if getattr(batch, "input_source", None) != INPUT_SOURCE_MANUAL_BACKFILL:
        raise ManualBackfillBillingError("Pembuatan invoice tahap ini hanya untuk rekap Input Belakangan dari Buku.")

    if getattr(batch, "invoice_id", None):
        raise ManualBackfillBillingError("Rekap ini sudah pernah dibuat menjadi invoice.")

    existing_invoice = Invoice.query.filter_by(
        source_type=MANUAL_BILLING_INVOICE_SOURCE,
        source_order_id=getattr(batch, "id", None),
    ).first()
    if existing_invoice:
        raise ManualBackfillBillingError(
            f"Rekap ini sudah punya invoice {getattr(existing_invoice, 'invoice_number', '-')}."
        )

    summary = _validate_manual_backfill_batch_items(batch)

    for index, item in enumerate(list(getattr(batch, "items", []) or []), start=1):
        source_type = getattr(item, "source_type", None)
        source_id = getattr(item, "source_id", None)
        existing_item = InvoiceItem.query.filter_by(
            source_type=source_type,
            source_id=source_id,
        ).first()
        if existing_item:
            raise ManualBackfillBillingError(
                f"Item baris {index} sudah pernah masuk invoice. Cek ulang agar tagihan tidak dobel."
            )

    assert_no_manual_backfill_duplicate_conflicts(batch)

    return summary


def _resolve_backfill_bill_to_snapshot(batch):
    """Build invoice party snapshot for manual-book backfill.

    Manual-book recap may be billed to existing masters or a free typed party.
    PIC is deliberately optional for MANUAL_BACKFILL.
    """
    bill_to_type = _infer_bill_to_type(
        getattr(batch, "bill_to_type", None),
        getattr(batch, "mandor_id", None),
        getattr(batch, "client_id", None),
        getattr(batch, "bill_to_name_snapshot", None),
    ) or BILL_TO_MANDOR_EXISTING
    mandor = getattr(batch, "mandor", None)
    client = getattr(batch, "client", None)

    if bill_to_type == BILL_TO_MANDOR_EXISTING and not mandor and getattr(batch, "mandor_id", None):
        mandor = Mandor.query.filter_by(id=batch.mandor_id, branch_id=batch.branch_id).first()
    if bill_to_type == BILL_TO_CLIENT_EXISTING and not client and getattr(batch, "client_id", None):
        client = Client.query.filter_by(id=batch.client_id).first()

    if bill_to_type == BILL_TO_MANDOR_EXISTING:
        if not mandor:
            raise ManualBackfillBillingError("Mandor existing pada rekap tidak ditemukan.")
        client = client or getattr(mandor, "client", None)
        label = _clean_text(getattr(batch, "bill_to_name_snapshot", "")) or _clean_text(getattr(mandor, "name", "")) or f"Mandor ID {getattr(batch, 'mandor_id', '-')}"
        phone = _clean_text(getattr(batch, "bill_to_phone_snapshot", "")) or _clean_text(getattr(mandor, "phone", ""))
        client_context = _clean_text(getattr(client, "name", "")) if client else "Mandor/Kelompok tanpa PT penaung"
    elif bill_to_type == BILL_TO_CLIENT_EXISTING:
        if not client:
            raise ManualBackfillBillingError("Client existing pada rekap tidak ditemukan.")
        label = _clean_text(getattr(batch, "bill_to_name_snapshot", "")) or _clean_text(getattr(client, "name", ""))
        phone = _clean_text(getattr(batch, "bill_to_phone_snapshot", "")) or _clean_text(getattr(client, "phone", ""))
        client_context = label
    else:
        label = _clean_text(getattr(batch, "bill_to_name_snapshot", ""))
        if not label:
            raise ManualBackfillBillingError("Nama pihak ditagih pada rekap tidak ditemukan.")
        phone = _clean_text(getattr(batch, "bill_to_phone_snapshot", ""))
        client_context = _bill_to_display_label(bill_to_type)

    address = _clean_text(getattr(batch, "bill_to_address_snapshot", ""))
    notes = _clean_text(getattr(batch, "bill_to_notes", ""))
    return {
        "mandor": mandor,
        "client": client,
        "batch_bill_to_type": bill_to_type,
        "bill_to_type": _legacy_invoice_bill_to_type(bill_to_type),
        "client_id": getattr(client, "id", None),
        "client_pic_id": None,
        "client_name_snapshot": label,
        "client_code_snapshot": _clean_text(getattr(client, "client_code", "")) if client else "",
        "client_pic_name_snapshot": "",
        "client_pic_position_snapshot": "",
        "client_pic_phone_snapshot": phone,
        "client_pic_email_snapshot": "",
        "bill_to_label": label,
        "client_context_label": client_context,
        "bill_to_address_snapshot": address,
        "bill_to_notes": notes,
    }



def validate_manual_backfill_invoice_consistency(batch, invoice, *, invoice_items=None, summary=None):
    """Final hardening check for MANUAL_BACKFILL invoice/piutang consistency.

    This is intentionally read-only: it verifies that the promoted invoice is a
    faithful snapshot of the locked manual recap before journals/payment flow can
    continue. It protects the lane Buku -> Rekap -> Invoice -> Piutang -> Bayar
    without changing the realtime lane.
    """
    if not batch or not invoice:
        raise ManualBackfillBillingError("Invoice manual backfill tidak valid.")

    if getattr(invoice, "input_source", None) != INPUT_SOURCE_MANUAL_BACKFILL:
        raise ManualBackfillBillingError("Invoice manual backfill wajib bertanda input MANUAL_BACKFILL.")
    if getattr(invoice, "source_type", None) != MANUAL_BILLING_INVOICE_SOURCE:
        raise ManualBackfillBillingError("Source invoice manual backfill tidak valid.")
    if getattr(invoice, "source_order_id", None) != getattr(batch, "id", None):
        raise ManualBackfillBillingError("Invoice tidak tersambung ke rekap manual yang benar.")
    if getattr(invoice, "branch_id", None) != getattr(batch, "branch_id", None):
        raise ManualBackfillBillingError("Cabang invoice tidak sama dengan cabang rekap manual.")
    if getattr(invoice, "period_start", None) != getattr(batch, "period_start", None) or getattr(invoice, "period_end", None) != getattr(batch, "period_end", None):
        raise ManualBackfillBillingError("Periode invoice tidak sama dengan periode rekap manual.")
    if not _clean_text(getattr(invoice, "client_name_snapshot", "")):
        raise ManualBackfillBillingError("Snapshot nama pihak ditagih pada invoice wajib ada.")

    invoice_total = _to_float(getattr(invoice, "total_amount", 0))
    invoice_paid = _to_float(getattr(invoice, "paid_amount", 0))
    invoice_remaining = _to_float(getattr(invoice, "remaining_amount", 0))
    batch_total = _to_float(getattr(batch, "total_amount", 0))
    expected_total = _to_float((summary or {}).get("total_amount", batch_total))

    if invoice_total <= 0:
        raise ManualBackfillBillingError("Total invoice manual backfill wajib lebih dari 0.")
    if abs(invoice_total - batch_total) > 0.01 or abs(invoice_total - expected_total) > 0.01:
        raise ManualBackfillBillingError("Total invoice tidak sama dengan total rekap manual.")
    if invoice_paid < 0 or invoice_remaining < 0:
        raise ManualBackfillBillingError("Nilai paid/remaining invoice tidak boleh negatif.")
    if abs((invoice_total - invoice_paid) - invoice_remaining) > 0.01:
        raise ManualBackfillBillingError("Sisa piutang invoice tidak sinkron dengan total dan pembayaran.")

    batch_items = list(getattr(batch, "items", []) or [])
    rows = list(invoice_items) if invoice_items is not None else list(getattr(invoice, "items", []) or [])
    if len(rows) != len(batch_items):
        raise ManualBackfillBillingError("Jumlah item invoice tidak sama dengan jumlah rincian rekap manual.")
    if not rows:
        raise ManualBackfillBillingError("Invoice manual backfill wajib punya rincian item.")

    batch_sources = {
        (getattr(item, "source_type", None), getattr(item, "source_id", None))
        for item in batch_items
    }
    invoice_sources = set()
    invoice_item_total = 0.0
    for index, item in enumerate(rows, start=1):
        qty = _to_float(getattr(item, "qty", 0))
        unit_price = _to_float(getattr(item, "unit_price", 0))
        subtotal = _to_float(getattr(item, "subtotal", 0))
        if qty <= 0 or unit_price <= 0 or subtotal <= 0:
            raise ManualBackfillBillingError(f"Item invoice manual baris {index} wajib bernilai lebih dari 0.")
        if getattr(item, "input_source", None) != INPUT_SOURCE_MANUAL_BACKFILL:
            raise ManualBackfillBillingError(f"Item invoice manual baris {index} wajib bertanda input MANUAL_BACKFILL.")
        source_key = (getattr(item, "source_type", None), getattr(item, "source_id", None))
        if source_key in invoice_sources:
            raise ManualBackfillBillingError(f"Source item invoice manual baris {index} dobel.")
        invoice_sources.add(source_key)
        if source_key not in batch_sources:
            raise ManualBackfillBillingError(f"Item invoice manual baris {index} tidak cocok dengan sumber rekap manual.")
        invoice_item_total += subtotal

    if abs(invoice_item_total - invoice_total) > 0.01:
        raise ManualBackfillBillingError("Total rincian invoice tidak sama dengan total invoice.")

    return {
        "invoice_item_count": len(rows),
        "invoice_item_total": invoice_item_total,
        "invoice_total": invoice_total,
        "remaining_amount": invoice_remaining,
    }

def create_invoice_from_manual_backfill_batch(*, batch_id, branch_id, created_by, notes=None, commit=False):
    """Promote a locked MANUAL_BACKFILL recap into invoice/piutang.

    This is the controlled merge point for the second input path:
    Buku/manual -> draft -> lock -> invoice -> piutang.
    It does not alter the realtime order/invoice flow.
    """
    batch = _get_manual_backfill_batch(batch_id, branch_id)
    invoice_date = date.today()
    summary = validate_manual_backfill_batch_before_invoice(batch, invoice_date=invoice_date)
    identity = _resolve_backfill_bill_to_snapshot(batch)

    due_date = invoice_date + timedelta(days=7)

    invoice = Invoice(
        branch_id=branch_id,
        invoice_number=generate_manual_billing_invoice_number(invoice_date),
        invoice_date=invoice_date,
        due_date=due_date,
        period_start=getattr(batch, "period_start", None),
        period_end=getattr(batch, "period_end", None),
        bill_to_type=identity["bill_to_type"],
        client_id=identity["client_id"],
        mandor_id=getattr(identity["mandor"], "id", getattr(batch, "mandor_id", None)),
        client_pic_id=identity["client_pic_id"],
        **build_company_bank_snapshot(branch_id),
        client_name_snapshot=identity["client_name_snapshot"],
        client_code_snapshot=identity["client_code_snapshot"],
        client_pic_name_snapshot=identity["client_pic_name_snapshot"],
        client_pic_position_snapshot=identity["client_pic_position_snapshot"],
        client_pic_phone_snapshot=identity["client_pic_phone_snapshot"],
        client_pic_email_snapshot=identity["client_pic_email_snapshot"],
        expected_payment_percent=100,
        total_amount=summary["total_amount"],
        paid_amount=0,
        remaining_amount=summary["total_amount"],
        status="DRAFT",
        notes=(
            notes
            or (
                f"Invoice dari Input Rekap Manual dari Buku {batch.batch_number}. "
                f"Periode {batch.period_start.strftime('%d-%m-%Y')} s/d {batch.period_end.strftime('%d-%m-%Y')}. "
                f"Pihak ditagih: {identity['bill_to_label']}. "
                f"Tipe pihak: {_bill_to_display_label(identity.get('batch_bill_to_type') or identity['bill_to_type'])}. "
                f"Konteks perusahaan/PT: {identity['client_context_label']}. "
                f"Alamat: {identity['bill_to_address_snapshot'] or '-'}. "
                f"Catatan pihak: {identity['bill_to_notes'] or '-'}. "
                "Sumber: input belakangan, bukan pembayaran tunai."
            )
        ),
        source_type=MANUAL_BILLING_INVOICE_SOURCE,
        source_order_id=getattr(batch, "id", None),
        input_source=INPUT_SOURCE_MANUAL_BACKFILL,
        created_by=created_by,
    )
    db.session.add(invoice)
    db.session.flush()

    invoice_items = []
    for item in list(getattr(batch, "items", []) or []):
        invoice_item = InvoiceItem(
            invoice=invoice,
            item_type=getattr(item, "item_type", None),
            description=f"{batch.batch_number} | {getattr(item, 'description', '')}",
            qty=_to_float(getattr(item, "qty", 0)),
            unit_price=_to_float(getattr(item, "unit_price", 0)),
            subtotal=_to_float(getattr(item, "subtotal", 0)),
            source_type=getattr(item, "source_type", None),
            source_id=getattr(item, "source_id", None),
            input_source=INPUT_SOURCE_MANUAL_BACKFILL,
        )
        invoice_items.append(invoice_item)
        db.session.add(invoice_item)

    consistency = validate_manual_backfill_invoice_consistency(
        batch,
        invoice,
        invoice_items=invoice_items,
        summary=summary,
    )

    batch.invoice_id = getattr(invoice, "id", None)
    batch.status = MANUAL_BACKFILL_STATUS_INVOICED

    create_invoice_journal_for_invoice(invoice=invoice, created_by=created_by, commit=False)

    record_audit_log(
        module="FINANCE",
        event_type="MANUAL_BACKFILL_INVOICE_CREATED",
        action="CREATE",
        table_name="manual_billing_batches",
        record_id=getattr(batch, "id", None),
        description=f"Input rekap manual dari buku {batch.batch_number} dibuat menjadi invoice {invoice.invoice_number}.",
        metadata={
            "batch_number": getattr(batch, "batch_number", None),
            "invoice_number": getattr(invoice, "invoice_number", None),
            "source_type": MANUAL_BILLING_INVOICE_SOURCE,
            "input_source": INPUT_SOURCE_MANUAL_BACKFILL,
            "validation": "MANUAL_BACKFILL_INVOICE_CONSISTENCY_OK",
            **summary,
            **consistency,
        },
        user_id=created_by,
        branch_id=branch_id,
        commit=False,
    )

    if commit:
        db.session.commit()

    return batch, invoice



def sync_manual_backfill_batch_status_from_invoice(invoice, *, updated_by=None, commit=False):
    """Sync MANUAL_BACKFILL recap status after invoice payment changes.

    The second input path must not stop at invoice creation. Once the invoice is
    paid partially or fully, the source recap has to show the same business
    state so users can audit: Buku -> Rekap -> Invoice -> Bayar.
    """
    if not invoice:
        return None

    if getattr(invoice, "input_source", None) != INPUT_SOURCE_MANUAL_BACKFILL:
        return None
    if getattr(invoice, "source_type", None) != MANUAL_BILLING_INVOICE_SOURCE:
        return None
    if not getattr(invoice, "source_order_id", None):
        return None

    batch = ManualBillingBatch.query.filter_by(
        id=getattr(invoice, "source_order_id", None),
        branch_id=getattr(invoice, "branch_id", None),
        invoice_id=getattr(invoice, "id", None),
        input_source=INPUT_SOURCE_MANUAL_BACKFILL,
    ).first()
    if not batch:
        return None

    current_status = _clean_text(getattr(batch, "status", "")).upper()
    if current_status == MANUAL_BACKFILL_STATUS_VOID:
        raise ManualBackfillBillingError("Rekap manual yang sudah dibatalkan tidak boleh menerima sinkronisasi pembayaran.")

    invoice_status = _clean_text(getattr(invoice, "status", "")).upper()
    paid_amount = _to_float(getattr(invoice, "paid_amount", 0))
    remaining_amount = _to_float(getattr(invoice, "remaining_amount", 0))

    if invoice_status == "PAID" or remaining_amount <= 0:
        next_status = MANUAL_BACKFILL_STATUS_PAID
    elif invoice_status == "PARTIAL" or paid_amount > 0:
        next_status = MANUAL_BACKFILL_STATUS_PARTIALLY_PAID
    else:
        next_status = MANUAL_BACKFILL_STATUS_INVOICED

    if current_status != next_status:
        old_status = current_status or None
        batch.status = next_status
        record_audit_log(
            module="FINANCE",
            event_type="MANUAL_BACKFILL_PAYMENT_STATUS_SYNCED",
            action="UPDATE",
            table_name="manual_billing_batches",
            record_id=getattr(batch, "id", None),
            description=(
                f"Status rekap manual dari buku {getattr(batch, 'batch_number', '-')} "
                f"disinkronkan dari invoice {getattr(invoice, 'invoice_number', '-')} menjadi {next_status}."
            ),
            metadata={
                "batch_number": getattr(batch, "batch_number", None),
                "invoice_number": getattr(invoice, "invoice_number", None),
                "old_status": old_status,
                "new_status": next_status,
                "invoice_status": invoice_status,
                "paid_amount": paid_amount,
                "remaining_amount": remaining_amount,
                "input_source": INPUT_SOURCE_MANUAL_BACKFILL,
            },
            user_id=updated_by,
            branch_id=getattr(invoice, "branch_id", None),
            commit=False,
        )

    if commit:
        db.session.commit()

    return batch
