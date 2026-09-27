"""Invoice order harian: satu invoice per order per sub client.

Dipindah dari app/routes/finance/realtime_invoice_routes.py supaya satu aturan
dipakai dua jalan: tombol invoice Finance, dan invoice otomatis pesanan
pelanggan umum yang sudah dibayar di muka (app/services/prepaid_order_service.py).

Fungsi di sini tidak commit; pemanggil membungkusnya dalam atomic_business_action.
"""
from datetime import date

from app.extensions import db
from app.models.finance import Invoice, InvoiceItem
from app.services.billing_input_source_service import INPUT_SOURCE_REALTIME
from app.services.mandor_invoice_helper_service import (
    calculate_realtime_locked_base_quantities,
    delivery_fee_invoice_lines,
    finance_safe_label,
    get_client_for_mandor_invoice,
    is_after_lock_increase_revision,
)
from app.utils.terms import T
from app.utils.money import money


class OrderInvoiceError(ValueError):
    pass


def build_order_invoice_lines(order, mandor_id):
    lines = []

    for detail in order.details:
        if int(detail.mandor_id) != int(mandor_id):
            continue

        mandor_name = finance_safe_label(getattr(detail, "mandor", None))
        location_name = finance_safe_label(getattr(detail, "delivery_location", None))

        lunch_qty, dinner_qty = calculate_realtime_locked_base_quantities(
            detail,
            is_after_lock_increase_revision,
        )
        total_qty = lunch_qty + dinner_qty
        price = money(getattr(detail, "price_per_portion", 0) or 0)

        if total_qty > 0 and price >= 0:
            lines.append({
                "item_type": "CATERING",
                "description": (
                    f"{order.order_number} | PIC {mandor_name} | {location_name} | "
                    f"Porsi locked: Lunch {lunch_qty}, Dinner {dinner_qty}"
                ),
                "qty": total_qty,
                "unit_price": price,
                "subtotal": total_qty * price,
                "source_type": "DAILY_ORDER_DETAIL",
                "source_id": detail.id
            })

        for revision in getattr(detail, "revisions", []) or []:
            if not is_after_lock_increase_revision(revision):
                continue

            lunch_change = int(getattr(revision, "lunch_qty_change", 0) or 0)
            dinner_change = int(getattr(revision, "dinner_qty_change", 0) or 0)
            qty_change = lunch_change + dinner_change

            if qty_change <= 0:
                continue

            revision_price = getattr(revision, "price_per_portion", None)

            if revision_price is None:
                revision_price = price

            revision_price = money(revision_price or 0)

            lines.append({
                "item_type": "REVISION_INCREASE",
                "description": (
                    f"{order.order_number} | PIC {mandor_name} | {location_name} | "
                    f"Revisi tambah setelah lock: Lunch +{lunch_change}, Dinner +{dinner_change}"
                ),
                "qty": qty_change,
                "unit_price": revision_price,
                "subtotal": qty_change * revision_price,
                "source_type": "ORDER_REVISION",
                "source_id": revision.id
            })

    # Ongkir per pengiriman, sesuai tarif yang dikunci di baris order.
    for detail in order.details:
        if int(detail.mandor_id) == int(mandor_id):
            lines.extend(delivery_fee_invoice_lines(order, detail))

    return lines


def generate_invoice_number(invoice_date):
    prefix = f"INV-{invoice_date.strftime('%Y%m%d')}"
    counter = Invoice.query.filter(Invoice.invoice_number.like(f"{prefix}-%")).count() + 1

    while True:
        invoice_number = f"{prefix}-{counter:03d}"
        existing = Invoice.query.filter_by(invoice_number=invoice_number).first()

        if not existing:
            return invoice_number

        counter += 1


def find_order_invoice(branch_id, order_id, mandor_id):
    return Invoice.query.filter_by(
        branch_id=branch_id,
        source_type="DAILY_ORDER",
        source_order_id=order_id,
        mandor_id=mandor_id,
    ).first()


def create_order_invoice(order, mandor, *, created_by, client_pic_id=None, prepaid=False):
    """Buat invoice + itemnya + jurnalnya untuk satu order dan satu sub client.

    prepaid=True untuk pesanan pelanggan umum yang dibayar di muka: jatuh tempo
    hari itu juga. Tidak commit. Kesalahan dilempar sebagai OrderInvoiceError.
    """
    from app.services.accounting_service import create_invoice_journal_for_invoice
    from app.services.credit_control_service import invoice_billing_terms
    from app.services.invoice_identity_service import build_company_bank_snapshot, invoice_contact_snapshot

    branch_id = order.branch_id
    if order.status != "LOCKED":
        raise OrderInvoiceError("Invoice hanya bisa dibuat dari order yang sudah LOCKED.")
    if not mandor or int(getattr(mandor, "branch_id", 0) or 0) != int(branch_id):
        raise OrderInvoiceError(f"{T.sub_client}/PIC lapangan tidak valid untuk cabang order.")

    client, client_error = get_client_for_mandor_invoice(mandor)
    if client_error:
        raise OrderInvoiceError(client_error)

    existing = find_order_invoice(branch_id, order.id, mandor.id)
    if existing:
        raise OrderInvoiceError(
            f"Invoice untuk order dan {T.sub_client_lower} ini sudah pernah dibuat ({existing.invoice_number})."
        )

    invoice_date = date.today()
    # Aturan yang sama dengan invoice periode: termin dari akun kredit atau
    # kontrak; mandor yang ditagih langsung ditagih atas namanya sendiri dan
    # menjadi kontak invoice, tanpa mewajibkan PIC client.
    billing = invoice_billing_terms(invoice_date, branch_id, client, mandor)
    contact, client_pic_error = invoice_contact_snapshot(client, mandor, client_pic_id, billing["bill_to_type"])
    if client_pic_error:
        raise OrderInvoiceError(client_pic_error)

    lines = build_order_invoice_lines(order, mandor.id)
    total_amount = sum(line["subtotal"] for line in lines)
    if not lines or total_amount <= 0:
        raise OrderInvoiceError(f"Tidak ada item invoice yang valid untuk order dan {T.sub_client_lower} ini.")

    source_note = (
        "Pesanan pelanggan umum yang dibayar di muka; dibuat otomatis setelah semua pengiriman diterima."
        if prepaid
        else f"Sumber order locked {order.order_number} + revisi AFTER_LOCK INCREASE. Belum termasuk warung."
    )
    invoice = Invoice(
        branch_id=branch_id,
        invoice_number=generate_invoice_number(invoice_date),
        invoice_date=invoice_date,
        due_date=invoice_date if prepaid else billing["due_date"],
        period_start=order.order_date,
        period_end=order.order_date,
        bill_to_type=billing["bill_to_type"],
        client_id=client.id,
        mandor_id=mandor.id,
        **contact,
        **build_company_bank_snapshot(branch_id),
        client_name_snapshot=billing["bill_to_name"],
        client_code_snapshot=getattr(client, "client_code", None),
        expected_payment_percent=100,
        total_amount=total_amount,
        paid_amount=0,
        remaining_amount=total_amount,
        status="DRAFT",
        notes=(
            f"Invoice catering resmi ke {billing['bill_to_name']}. "
            f"PIC lapangan: {mandor.name}. {source_note}"
        ),
        source_type="DAILY_ORDER",
        source_order_id=order.id,
        input_source=INPUT_SOURCE_REALTIME,
        created_by=created_by,
    )
    db.session.add(invoice)
    db.session.flush()

    for line in lines:
        db.session.add(InvoiceItem(
            invoice_id=invoice.id,
            item_type=line["item_type"],
            description=line["description"],
            qty=line["qty"],
            unit_price=line["unit_price"],
            subtotal=line["subtotal"],
            source_type=line.get("source_type"),
            source_id=line.get("source_id"),
            input_source=INPUT_SOURCE_REALTIME,
        ))

    db.session.flush()
    # Invoice tanpa jurnal membuat piutang 1004 tidak cocok dengan buku besar;
    # lebih baik seluruh invoice dibatalkan.
    journal_ok, journal_message, _ = create_invoice_journal_for_invoice(
        invoice=invoice, created_by=created_by, commit=False
    )
    if not journal_ok:
        raise OrderInvoiceError(f"Jurnal invoice gagal dibuat: {journal_message}")
    return invoice
