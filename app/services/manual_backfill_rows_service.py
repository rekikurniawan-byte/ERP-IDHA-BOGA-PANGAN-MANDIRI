# Split from app.services.manual_backfill_billing_service.
from app.services.manual_backfill_billing_service import *  # noqa: F401,F403
from app.services.manual_backfill_billing_service import _to_float
from app.services.manual_backfill_bill_to_service import _clean_text
from app.utils.terms import T

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
            raise ManualBackfillBillingError(f"Nama {T.worker_lower} warung/kasbon baris {index + 1} wajib diisi.")
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
