"""Shared helpers for client-billed mandor invoice flows."""

from app.models.master import Client
from app.utils.terms import T
from app.utils.money import money


def finance_safe_label(obj):
    if not obj:
        return "-"

    for attr in ["name", "location_name", "full_name", "location_code", "code"]:
        value = getattr(obj, attr, None)
        if value:
            return str(value)

    return f"ID {getattr(obj, 'id', '-')}"


def get_client_for_mandor_invoice(mandor):
    """Return (client, error_message) for official client invoice flow.

    Mandor is kept as field PIC, but the invoice bill-to must be the client/company.
    """
    if not mandor:
        return None, f"Data {T.sub_client_lower}/PIC lapangan tidak ditemukan."

    client_id = getattr(mandor, "client_id", None)

    if not client_id:
        return None, f"{T.sub_client}/PIC lapangan belum terhubung ke {T.client_lower}."

    client = getattr(mandor, "client", None)

    if not client:
        client = Client.query.get(client_id)

    if not client:
        return None, f"{T.client} untuk {T.sub_client_lower}/PIC lapangan ini tidak ditemukan."

    if hasattr(client, "is_active") and not client.is_active:
        return None, f"{T.client} untuk {T.sub_client_lower}/PIC lapangan ini sedang nonaktif."

    return client, None


def is_after_lock_increase_revision(revision):
    revision_type = str(getattr(revision, "revision_type", "") or "").upper()
    direction = str(getattr(revision, "revision_direction", "") or "").upper()

    return direction == "INCREASE" and revision_type.startswith("AFTER_LOCK")


def calculate_realtime_locked_base_quantities(detail, revision_predicate):
    """Return locked-base quantities for realtime catering invoice lines.

    After-lock increases are stored both by mutating DailyOrderDetail totals and
    by creating OrderRevision rows. Invoice generation must bill the locked base
    and after-lock revisions as separate lines, so the base line subtracts all
    after-lock increase revisions from the current detail quantity.
    """
    lunch_qty = int(getattr(detail, "lunch_qty", 0) or 0)
    dinner_qty = int(getattr(detail, "dinner_qty", 0) or 0)

    for revision in getattr(detail, "revisions", []) or []:
        if not revision_predicate(revision):
            continue

        lunch_qty -= int(getattr(revision, "lunch_qty_change", 0) or 0)
        dinner_qty -= int(getattr(revision, "dinner_qty_change", 0) or 0)

    return max(lunch_qty, 0), max(dinner_qty, 0)


DELIVERY_FEE_ITEM_TYPE = "ONGKIR"
DELIVERY_FEE_SOURCES = (
    ("DELIVERY_FEE_LUNCH", "lunch_delivery_fee", "siang"),
    ("DELIVERY_FEE_DINNER", "dinner_delivery_fee", "malam"),
)


def delivery_fee_invoice_lines(order, detail):
    """Baris invoice ongkir untuk satu baris order: satu per pengiriman berbayar.

    Tarifnya sudah dikunci di baris order saat pesanan dibuat. Pengiriman gratis
    atau yang ongkirnya termasuk harga kontrak (0) tidak menghasilkan baris.
    """
    location_name = finance_safe_label(getattr(detail, "delivery_location", None))
    lines = []
    for source_type, field, label in DELIVERY_FEE_SOURCES:
        fee = money(getattr(detail, field, 0) or 0)
        if fee <= 0:
            continue
        lines.append({
            "item_type": DELIVERY_FEE_ITEM_TYPE,
            "description": f"{order.order_number} | Ongkos kirim {label} | {location_name}",
            "qty": 1,
            "unit_price": fee,
            "subtotal": fee,
            "source_type": source_type,
            "source_id": detail.id,
        })
    return lines
