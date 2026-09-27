# Split from app.routes.finance_routes. Keep root imports/helpers as shared context.
from app.routes.finance_routes import *  # noqa: F401,F403

@finance_bp.route("/invoices")
@role_required("OWNER", "ADMIN", "FINANCE")
def invoices():
    from flask_login import current_user
    from flask import render_template
    from app.models.finance import Invoice
    from app.services.pricing_service import PATH_FILTER_CHOICES, invoice_path_breakdown, requested_path

    all_invoices = Invoice.query.filter_by(
        branch_id=current_user.branch_id
    ).order_by(
        Invoice.id.desc()
    ).all()
    # Ringkasan per jalur selalu dari semua invoice; daftar & kartu mengikuti filter.
    path_breakdown = invoice_path_breakdown(all_invoices)
    selected_path = requested_path(request.args.get("path"))
    invoices = [invoice for invoice in all_invoices if not selected_path or invoice.customer_path == selected_path]

    invoices_data = []
    for invoice in invoices:
        invoices_data.append({
            "invoice": invoice,
            "bill_to": get_invoice_bill_to(invoice),
            "input_source": build_input_source_context(getattr(invoice, "input_source", None)),
        })

    # HYGIENE5C_ACTIVE_INVOICE_SUMMARY
    cancelled_statuses = ["CANCELLED", "CANCELED"]
    active_invoices = [
        invoice for invoice in invoices
        if str(invoice.status or "").upper() not in cancelled_statuses
    ]

    total_invoice = sum(float(invoice.total_amount or 0) for invoice in active_invoices)
    total_paid = sum(float(invoice.paid_amount or 0) for invoice in active_invoices)
    total_remaining = sum(float(invoice.remaining_amount or 0) for invoice in active_invoices)

    draft_count = len([invoice for invoice in active_invoices if invoice.status == "DRAFT"])
    paid_count = len([invoice for invoice in active_invoices if invoice.status == "PAID" or float(invoice.remaining_amount or 0) <= 0])
    unpaid_count = len([invoice for invoice in active_invoices if float(invoice.remaining_amount or 0) > 0])

    return render_template(
        "finance/invoice_index.html",
        invoices=invoices_data,
        total_invoice=total_invoice,
        total_paid=total_paid,
        total_remaining=total_remaining,
        draft_count=draft_count,
        paid_count=paid_count,
        unpaid_count=unpaid_count,
        # HYGIENE7A_CANCELLED_COUNT_SUMMARY
        active_invoice_count=len(active_invoices),
        cancelled_count=len(invoices) - len(active_invoices),
        path_breakdown=path_breakdown,
        selected_path=selected_path,
        path_choices=PATH_FILTER_CHOICES,
        path_filter_endpoint="finance.invoices",
    )





# === PRODUCTION_FINANCE_CSV_EXPORT_ROUTES ===
