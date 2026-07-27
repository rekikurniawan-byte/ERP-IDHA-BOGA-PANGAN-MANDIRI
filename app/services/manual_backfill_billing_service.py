"""Manual book/backfill billing helpers.

This flow is intentionally separate from the live/realtime operational flow.
It records old/manual book recap data as MANUAL_BACKFILL draft batches first;
invoice/piutang promotion is handled in a later stage so the live flow is not
changed accidentally.
"""
import logging

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

logger = logging.getLogger(__name__)

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


def _run_in_transaction(action):
    try:
        result = action()
        db.session.commit()
        return result
    except Exception:
        db.session.rollback()
        raise


def _to_float(value):
    if isinstance(value, str):
        value = value.replace(".", "").replace(",", ".").strip()
    try:
        return float(value or 0)
    except Exception:
        logger.exception("Suppressed unexpected exception in app/services/manual_backfill_billing_service.py:103")
        return 0.0



from app.services.manual_backfill_bill_to_service import (  # noqa: E402
    _bill_to_display_label,
    _clean_text,
    _infer_bill_to_type,
    _legacy_invoice_bill_to_type,
    _normalize_bill_to_type,
    _normalize_party_name,
    _resolve_manual_backfill_bill_to,
)
from app.services.manual_backfill_rows_service import (  # noqa: E402
    _parse_date,
    build_catering_backfill_rows,
    build_warung_backfill_rows,
    summarize_backfill_rows,
)
from app.services.manual_backfill_duplicate_service import (  # noqa: E402
    _active_status,
    _batch_party_key,
    _category_labels,
    _format_period,
    _invoice_billing_categories,
    _invoice_party_key,
    _invoice_period,
    _item_categories_from_items,
    _normalize_billing_category,
    _party_key_from_values,
    _period_from_daily_order,
    _query_all_or_first,
    _ranges_overlap,
    _same_billed_party,
    assert_no_manual_backfill_duplicate_conflicts,
    build_manual_backfill_duplicate_guard_context,
    collect_manual_backfill_duplicate_conflicts,
    format_manual_backfill_duplicate_conflict_message,
    get_manual_backfill_bill_to_context,
)
from app.services.manual_backfill_presentation_service import (  # noqa: E402
    build_manual_backfill_print_context,
    build_manual_backfill_register_summary,
    get_manual_backfill_bill_to_filter_choices,
    get_manual_backfill_status_context,
    get_manual_backfill_status_filter_choices,
    normalize_manual_backfill_bill_to_filter,
    normalize_manual_backfill_status_filter,
)

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
    commit=False,
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

    if commit:
        db.session.commit()

    return batch


def create_manual_backfill_batch_record(**kwargs):
    kwargs["commit"] = False
    return _run_in_transaction(lambda: create_manual_backfill_batch(**kwargs))


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


def update_manual_backfill_batch_record(**kwargs):
    kwargs["commit"] = False
    return _run_in_transaction(lambda: update_manual_backfill_batch(**kwargs))


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


def lock_manual_backfill_batch_record(*, batch_id, branch_id, locked_by):
    return _run_in_transaction(lambda: lock_manual_backfill_batch(
        batch_id=batch_id,
        branch_id=branch_id,
        locked_by=locked_by,
        commit=False,
    ))


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


def void_manual_backfill_batch_record(*, batch_id, branch_id, voided_by, reason=None):
    return _run_in_transaction(lambda: void_manual_backfill_batch(
        batch_id=batch_id,
        branch_id=branch_id,
        voided_by=voided_by,
        reason=reason,
        commit=False,
    ))


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


def create_invoice_from_manual_backfill_batch_record(*, batch_id, branch_id, created_by, notes=None):
    return _run_in_transaction(lambda: create_invoice_from_manual_backfill_batch(
        batch_id=batch_id,
        branch_id=branch_id,
        created_by=created_by,
        notes=notes,
        commit=False,
    ))



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
