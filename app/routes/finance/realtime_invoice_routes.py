# Split from app.routes.finance_routes. Keep root imports/helpers as shared context.
from app.routes.finance_routes import *  # noqa: F401,F403
from app.services.mandor_invoice_helper_service import finance_safe_label, get_client_for_mandor_invoice
from app.services.order_invoice_service import (
    OrderInvoiceError,
    build_order_invoice_lines,
    create_order_invoice,
    find_order_invoice,
    generate_invoice_number,
)
from app.utils.terms import T

# Pembuat baris invoice dan nomor invoice pindah ke app/services/order_invoice_service.py.
_build_catering_invoice_lines = build_order_invoice_lines
_generate_invoice_number = generate_invoice_number


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
            client_error = f"{T.sub_client}/PIC lapangan belum terhubung ke {T.client_lower}."

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
                client_error = None if client_ready else f"{T.client} belum punya PIC resmi aktif."
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
    from app.models.operational import DailyOrder

    order = DailyOrder.query.get_or_404(order_id)

    if order.branch_id != current_user.branch_id:
        flash("Data order tidak sesuai cabang user.", "danger")
        return redirect(url_for("finance.generate_order_invoices"))

    existing_invoice = find_order_invoice(current_user.branch_id, order.id, mandor_id)
    if existing_invoice:
        flash(f"Invoice untuk order dan {T.sub_client_lower} ini sudah pernah dibuat.", "warning")
        return redirect(url_for("finance.invoice_detail", invoice_id=existing_invoice.id))

    try:
        with atomic_business_action(
            module="FINANCE",
            action="ORDER_INVOICE_CREATE",
            description=f"Create invoice order locked {order.order_number} secara atomic.",
            reference_type="invoices",
            user_id=current_user.id,
            branch_id=current_user.branch_id,
            metadata={"source_order_id": order.id, "source_type": "DAILY_ORDER", "input_source": INPUT_SOURCE_REALTIME},
        ):
            invoice = create_order_invoice(
                order,
                Mandor.query.get(mandor_id),
                created_by=current_user.id,
                client_pic_id=request.form.get("client_pic_id", type=int),
            )
    except OrderInvoiceError as error:
        flash(str(error), "warning")
        return redirect(url_for("finance.generate_order_invoices"))
    except Exception as error:
        logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:901")
        flash(f"Gagal membuat invoice: {error}", "danger")
        return redirect(url_for("finance.generate_order_invoices"))

    record_audit_log(
        module="FINANCE",
        event_type="INVOICE_CREATED",
        action="CREATE",
        table_name="invoices",
        record_id=invoice.id,
        description=f"Invoice dibuat dari order locked: {invoice.invoice_number}.",
        metadata={"invoice_number": invoice.invoice_number, "source_type": invoice.source_type, "input_source": invoice.input_source, "total_amount": invoice.total_amount},
    )
    flash("Invoice catering resmi berhasil dibuat; jurnal otomatis dicatat ke 4001 (kontrak) atau 4002 (umum).", "success")
    return redirect(url_for("finance.invoice_detail", invoice_id=invoice.id))



# === PATCH_PERIOD_INVOICE_PREVIEW ===
