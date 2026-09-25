# Split from app.routes.finance_routes. Keep root imports/helpers as shared context.
from app.routes.finance_routes import *  # noqa: F401,F403
from app.services.mandor_invoice_helper_service import (
    calculate_realtime_locked_base_quantities,
    finance_safe_label,
    get_client_for_mandor_invoice,
    is_after_lock_increase_revision,
)

def _build_catering_invoice_lines(order, mandor_id):
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
        price = float(getattr(detail, "price_per_portion", 0) or 0)

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

            revision_price = float(revision_price or 0)

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

    return lines


def _generate_invoice_number(invoice_date):
    from app.models.finance import Invoice

    prefix = f"INV-{invoice_date.strftime('%Y%m%d')}"
    counter = Invoice.query.filter(Invoice.invoice_number.like(f"{prefix}-%")).count() + 1

    while True:
        invoice_number = f"{prefix}-{counter:03d}"
        existing = Invoice.query.filter_by(invoice_number=invoice_number).first()

        if not existing:
            return invoice_number

        counter += 1


@finance_bp.route("/invoices/generate-order")
@role_required("OWNER", "ADMIN", "FINANCE")
def generate_order_invoices():
    from app.models.operational import DailyOrder
    from app.models.finance import Invoice

    locked_orders = DailyOrder.query.filter_by(
        branch_id=current_user.branch_id,
        status="LOCKED"
    ).order_by(
        DailyOrder.order_date.desc(),
        DailyOrder.id.desc()
    ).all()

    groups = []

    for order in locked_orders:
        mandor_ids = []

        for detail in order.details:
            if detail.mandor_id not in mandor_ids:
                mandor_ids.append(detail.mandor_id)

        for mandor_id in mandor_ids:
            lines = _build_catering_invoice_lines(order, mandor_id)
            total_amount = sum(line["subtotal"] for line in lines)

            if total_amount <= 0:
                continue

            existing_invoice = Invoice.query.filter_by(
                branch_id=current_user.branch_id,
                source_type="DAILY_ORDER",
                source_order_id=order.id,
                mandor_id=mandor_id
            ).first()

            mandor_obj = None
            mandor_name = "-"
            client_name = "-"
            client_ready = False
            client_error = "Mandor/PIC lapangan belum terhubung ke client/perusahaan."

            for detail in order.details:
                if detail.mandor_id == mandor_id:
                    mandor_obj = getattr(detail, "mandor", None)
                    mandor_name = finance_safe_label(mandor_obj)
                    break

            client, client_error_result = get_client_for_mandor_invoice(mandor_obj)
            client_pics = []
            client_code = ""

            if client:
                client_name = finance_safe_label(client)
                client_code = getattr(client, "client_code", "") or ""
                client_pics = get_active_client_pics(client.id)
                client_ready = bool(client_pics)
                client_error = None if client_ready else "Client belum punya PIC resmi aktif."
            elif client_error_result:
                client_error = client_error_result

            groups.append({
                "order": order,
                "mandor_id": mandor_id,
                "mandor_name": mandor_name,
                "client_name": client_name,
                "client_code": client_code,
                "client_pics": client_pics,
                "client_ready": client_ready,
                "client_error": client_error,
                "line_count": len(lines),
                "total_amount": total_amount,
                "existing_invoice": existing_invoice
            })

    return render_template(
        "finance/invoice_generate_order.html",
        groups=groups
    )


@finance_bp.route("/invoices/generate-order/<int:order_id>/<int:mandor_id>", methods=["POST"])
@role_required("OWNER", "ADMIN", "FINANCE")
def generate_order_invoice(order_id, mandor_id):
    from datetime import date, timedelta
    from app.extensions import db
    from app.models.operational import DailyOrder
    from app.models.finance import Invoice, InvoiceItem

    order = DailyOrder.query.get_or_404(order_id)

    if order.branch_id != current_user.branch_id:
        flash("Data order tidak sesuai cabang user.", "danger")
        return redirect(url_for("finance.generate_order_invoices"))

    if order.status != "LOCKED":
        flash("Invoice hanya bisa dibuat dari order yang sudah LOCKED.", "warning")
        return redirect(url_for("finance.generate_order_invoices"))

    mandor = Mandor.query.get(mandor_id)

    if not mandor or int(getattr(mandor, "branch_id", 0) or 0) != int(current_user.branch_id):
        flash("Mandor/PIC lapangan tidak valid untuk cabang user.", "danger")
        return redirect(url_for("finance.generate_order_invoices"))

    client, client_error = get_client_for_mandor_invoice(mandor)

    if client_error:
        flash(client_error, "danger")
        return redirect(url_for("finance.generate_order_invoices"))

    from app.services.credit_control_service import invoice_billing_terms
    from app.services.invoice_identity_service import invoice_contact_snapshot

    invoice_date = date.today()
    # Aturan yang sama dengan invoice periode: termin dari akun kredit atau
    # kontrak; mandor yang ditagih langsung ditagih atas namanya sendiri dan
    # menjadi kontak invoice, tanpa mewajibkan PIC client.
    billing = invoice_billing_terms(invoice_date, current_user.branch_id, client, mandor)
    contact, client_pic_error = invoice_contact_snapshot(
        client, mandor, request.form.get("client_pic_id", type=int), billing["bill_to_type"]
    )
    if client_pic_error:
        flash(client_pic_error, "warning")
        return redirect(url_for("finance.generate_order_invoices"))

    existing_invoice = Invoice.query.filter_by(
        branch_id=current_user.branch_id,
        source_type="DAILY_ORDER",
        source_order_id=order.id,
        mandor_id=mandor_id
    ).first()

    if existing_invoice:
        flash("Invoice untuk order dan mandor ini sudah pernah dibuat.", "warning")
        return redirect(url_for("finance.invoice_detail", invoice_id=existing_invoice.id))

    lines = _build_catering_invoice_lines(order, mandor_id)
    total_amount = sum(line["subtotal"] for line in lines)

    if not lines or total_amount <= 0:
        flash("Tidak ada item invoice yang valid untuk order dan mandor ini.", "warning")
        return redirect(url_for("finance.generate_order_invoices"))

    due_date = billing["due_date"]

    invoice = Invoice(
        branch_id=current_user.branch_id,
        invoice_number=_generate_invoice_number(invoice_date),
        invoice_date=invoice_date,
        due_date=due_date,
        period_start=order.order_date,
        period_end=order.order_date,
        bill_to_type=billing["bill_to_type"],
        client_id=client.id,
        mandor_id=mandor_id,
        **contact,
        **build_company_bank_snapshot(current_user.branch_id),
        client_name_snapshot=billing["bill_to_name"],
        client_code_snapshot=getattr(client, "client_code", None),
        expected_payment_percent=100,
        total_amount=total_amount,
        paid_amount=0,
        remaining_amount=total_amount,
        status="DRAFT",
        notes=(
            f"Invoice catering resmi ke {billing['bill_to_name']}. "
            f"PIC lapangan: {mandor.name}. "
            f"Sumber order locked {order.order_number} + revisi AFTER_LOCK INCREASE. "
            f"Belum termasuk warung."
        ),
        source_type="DAILY_ORDER",
        source_order_id=order.id,
        input_source=INPUT_SOURCE_REALTIME,
        created_by=current_user.id
    )

    try:
        with atomic_business_action(
            module="FINANCE",
            action="ORDER_INVOICE_CREATE",
            description=f"Create invoice order locked {order.order_number} secara atomic.",
            reference_type="invoices",
            user_id=current_user.id,
            branch_id=current_user.branch_id,
            metadata={"source_order_id": order.id, "source_type": "DAILY_ORDER", "input_source": INPUT_SOURCE_REALTIME, "item_count": len(lines)},
        ):
            db.session.add(invoice)
            db.session.flush()

            for line in lines:
                item = InvoiceItem(
                    invoice_id=invoice.id,
                    item_type=line["item_type"],
                    description=line["description"],
                    qty=line["qty"],
                    unit_price=line["unit_price"],
                    subtotal=line["subtotal"],
                    source_type=line.get("source_type"),
                    source_id=line.get("source_id"),
                    input_source=INPUT_SOURCE_REALTIME,
                )

                db.session.add(item)

            # PRODUCTION: invoice order harian harus posting ke 4002 Pendapatan Catering Harian.
            db.session.flush()

            from app.services.accounting_service import create_invoice_journal_for_invoice
            create_invoice_journal_for_invoice(
                invoice=invoice,
                created_by=current_user.id,
                commit=False
            )

        record_audit_log(
            module="FINANCE",
            event_type="INVOICE_CREATED",
            action="CREATE",
            table_name="invoices",
            record_id=invoice.id,
            description=f"Invoice dibuat dari order locked: {invoice.invoice_number}.",
            metadata={"invoice_number": invoice.invoice_number, "source_type": invoice.source_type, "input_source": invoice.input_source, "total_amount": invoice.total_amount},
        )
        flash("Invoice catering harian resmi berhasil dibuat dan jurnal otomatis dicatat ke 4002.", "success")
        return redirect(url_for("finance.invoice_detail", invoice_id=invoice.id))

    except Exception as error:
        logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:901")
        flash(f"Gagal membuat invoice: {error}", "danger")
        return redirect(url_for("finance.generate_order_invoices"))



# === PATCH_PERIOD_INVOICE_PREVIEW ===
